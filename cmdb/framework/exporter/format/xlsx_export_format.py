# DataGerry - OpenSource Enterprise CMDB
# Copyright (C) 2026 becon GmbH
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.
"""
Implementation of XlsxExportFormat
"""
from logging import Logger, getLogger
from io import BytesIO
import re
from openpyxl import Workbook
from openpyxl.worksheet.worksheet import Worksheet

from cmdb.models.object_model.cmdb_object_key_enum import CmdbObjectKey
from cmdb.models.type_model.field_key_enum import FieldKey
from cmdb.framework.exporter.format.base_exporter_format import (
    BaseExporterFormat,
    TYPE_INFO_ID_KEY,
    TYPE_INFO_LABEL_KEY,
    OBJECT_INFO_ID_KEY,
)
from cmdb.framework.exporter.config.exporter_config_type_enum import ExporterConfigType
from cmdb.framework.exporter.exporter_constants import ExporterMetadataKey
from cmdb.framework.rendering.render_result import RenderResult
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# Default identity columns emitted for each object (public_id + active flag)
DEFAULT_HEADER: list[str] = [CmdbObjectKey.PUBLIC_ID.value, CmdbObjectKey.ACTIVE.value]

# Characters not allowed in an Excel sheet title, plus Excel's hard 31-character title limit
INVALID_SHEET_TITLE_CHARS: str = r'[\\*?:/\[\]]'
MAX_SHEET_TITLE_LENGTH: int = 31

# -------------------------------------------------------------------------------------------------------------------- #
#                                               XlsxExportFormat - CLASS                                               #
# -------------------------------------------------------------------------------------------------------------------- #
class XlsxExportFormat(BaseExporterFormat):
    """
    The XLSX export format class for exporting data to Excel (.xlsx) files

    Objects are grouped onto one worksheet per type (sorted by type id); each worksheet carries the
    identity header columns followed by that type's field columns.

    Extends: BaseExporterFormat
    """
    FILE_EXTENSION = "xlsx"
    MIME_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    LABEL = "XLSX"
    MULTITYPE_SUPPORT = True
    ICON = "file-excel"
    DESCRIPTION = "Export as XLSX"
    ACTIVE = True


    def export(self, data: list[RenderResult], *args) -> bytes:
        """
        Exports a list of RenderResult objects as an XLSX file

        Args:
            data (list[RenderResult]): The objects to be exported
            *args: Optional export parameters dict (`view`, `metadata`)

        Returns:
            bytes: The content of the XLSX file as a byte string
        """
        workbook: Workbook = self.create_xls_object(data, args)

        buffer = BytesIO()
        workbook.save(buffer)

        return buffer.getvalue()


    def create_xls_object(self, data: list[RenderResult], args: tuple) -> Workbook:
        """
        Creates an XLSX workbook with the provided data

        Objects are sorted by type id and written onto one worksheet per type. In the NATIVE view each
        worksheet's field columns are the field names of that type (so a multi-type export keeps every
        type's own fields); a render-view `metadata` override instead fixes the header/columns across all
        worksheets. An empty object list still yields one valid, visible header-only worksheet.

        Args:
            data (list[RenderResult]): The objects to be exported
            args (tuple): The positional export args; `args[0]` (if present) is the options dict

        Returns:
            Workbook: The created XLSX workbook
        """
        workbook = Workbook()
        workbook.remove(workbook.active)  # drop the empty default sheet openpyxl creates

        view, header, metadata_columns = self._resolve_settings(args)
        sorted_data = sorted(data, key=lambda obj: obj.type_information[TYPE_INFO_ID_KEY])

        current_type_id = None
        sheet: Worksheet | None = None
        columns: list[str] = []
        row_index = 1

        for obj in sorted_data:
            type_id = obj.type_information[TYPE_INFO_ID_KEY]

            # A new type starts a new worksheet with its own header row and (native view) its own columns
            if current_type_id != type_id:
                current_type_id = type_id
                columns = metadata_columns if metadata_columns is not None else self._field_names(obj)
                title = self._normalize_sheet_title(obj.type_information[TYPE_INFO_LABEL_KEY])
                sheet = workbook.create_sheet(title=title)
                self._write_header_row(sheet, header, columns)
                row_index = 2  # data rows start below the header

            self._write_object_row(sheet, obj, row_index, header, columns, view)
            row_index += 1

        # openpyxl refuses to save a workbook with no visible sheet, so an empty export gets a header-only one
        if not workbook.sheetnames:
            self._write_header_row(workbook.create_sheet(), header, [])

        return workbook


    def _resolve_settings(self, args: tuple) -> tuple[str, list[str], list[str] | None]:
        """
        Resolves the view, identity header and (optional) fixed column selection from the export args

        A render-view `metadata` override supplies the header and the fixed columns used for every
        worksheet; without such an override the export is forced to the NATIVE view and the columns are
        derived per worksheet from each type's fields (signalled by returning `None` for the columns).

        Args:
            args (tuple): The positional export args; `args[0]` (if present) is the options dict

        Returns:
            tuple[str, list[str], list[str] | None]:
                - view (str): The resolved view type (`'native'` or `'render'`)
                - header (list[str]): The identity columns to include per object
                - metadata_columns (list[str] | None): The fixed field columns, or None for per-type columns
        """
        view, metadata = BaseExporterFormat.resolve_export_view(args)

        header: list[str] = list(DEFAULT_HEADER)
        metadata_columns: list[str] | None = None

        if metadata:
            header = metadata.get(ExporterMetadataKey.HEADER.value, header)
            metadata_columns = metadata.get(ExporterMetadataKey.COLUMNS.value, [])
        else:
            # XLSX renders in the render view only when metadata explicitly selects the columns
            view = ExporterConfigType.NATIVE.value

        return view, header, metadata_columns


    @staticmethod
    def _field_names(obj: RenderResult) -> list[str]:
        """
        Returns the field names of a single object in definition order

        Args:
            obj (RenderResult): The object to read the field names from

        Returns:
            list[str]: The object's field names
        """
        return [field[FieldKey.NAME.value] for field in obj.fields]


    def _write_header_row(self, sheet: Worksheet, header: list[str], columns: list[str]) -> None:
        """
        Writes the header row (identity columns followed by field columns) into a worksheet

        Args:
            sheet (Worksheet): The worksheet to write into
            header (list[str]): The identity column titles
            columns (list[str]): The field column titles
        """
        for col_index, title in enumerate([*header, *columns], start=1):
            sheet.cell(row=1, column=col_index).value = title


    def _write_object_row(
            self,
            sheet: Worksheet,
            obj: RenderResult,
            row_index: int,
            header: list[str],
            columns: list[str],
            view: str) -> None:
        """
        Writes one object as a single worksheet row (identity cells followed by field cells)

        Args:
            sheet (Worksheet): The worksheet to write into
            obj (RenderResult): The object to serialize
            row_index (int): The 1-based row number to write the object on
            header (list[str]): The identity columns (from object_information; `public_id` -> `object_id`)
            columns (list[str]): The field names to serialize
            view (str): The export view passed to the field summary renderer
        """
        obj_fields: dict = {
            field[FieldKey.NAME.value]: BaseExporterFormat.summary_renderer(obj, field, view)
            for field in obj.fields
        }

        for col_index, head in enumerate(header, start=1):
            info_key = OBJECT_INFO_ID_KEY if head == CmdbObjectKey.PUBLIC_ID.value else head
            sheet.cell(row=row_index, column=col_index).value = str(obj.object_information.get(info_key, ""))

        for col_index, name in enumerate(columns, start=len(header) + 1):
            sheet.cell(row=row_index, column=col_index).value = str(obj_fields.get(name, ""))


    @staticmethod
    def _normalize_sheet_title(input_data: str) -> str:
        """
        Normalizes a sheet title by replacing invalid characters and enforcing Excel's length limit

        Args:
            input_data (str): The raw sheet title

        Returns:
            str: The normalized sheet title (invalid characters replaced, truncated to 31 characters)
        """
        normalized = re.sub(INVALID_SHEET_TITLE_CHARS, '_', input_data)

        return normalized[:MAX_SHEET_TITLE_LENGTH]
