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
Implementation of the CsvExportFormat
"""
from logging import Logger, getLogger
import csv
from io import StringIO

from cmdb.models.object_model.cmdb_object_key_enum import CmdbObjectKey
from cmdb.models.type_model.field_key_enum import FieldKey
from cmdb.framework.exporter.format.base_exporter_format import (
    BaseExporterFormat,
    TYPE_INFO_ID_KEY,
    OBJECT_INFO_ID_KEY,
)
from cmdb.framework.exporter.config.exporter_config_type_enum import ExporterConfigType
from cmdb.framework.exporter.exporter_constants import ExporterMetadataKey
from cmdb.framework.rendering.render_result import RenderResult

from cmdb.errors.exporter import ExporterCSVTypeError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# Default CSV identity columns (object public_id + active flag)
DEFAULT_HEADER: list[str] = [CmdbObjectKey.PUBLIC_ID.value, CmdbObjectKey.ACTIVE.value]

# -------------------------------------------------------------------------------------------------------------------- #
#                                                CsvExportFormat - CLASS                                               #
# -------------------------------------------------------------------------------------------------------------------- #
class CsvExportFormat(BaseExporterFormat):
    """
    The csv export format class

    Extends: BaseExporterFormat
    """
    FILE_EXTENSION = "csv"
    MIME_TYPE = "text/csv"
    LABEL = "CSV"
    MULTITYPE_SUPPORT = False
    ICON = "file-csv"
    DESCRIPTION = "Export as CSV (only of the same type)"
    ACTIVE = True


    def export(self, data: list[RenderResult], *args) -> StringIO:
        """
        Exports the objects as a CSV file

        The header is `public_id, active` plus the type's field names; in the RENDER view a supplied
        `metadata` override selects the header/columns instead. All objects must share one type (CSV has
        no multi-type support). An empty object list yields a valid CSV with only the header row.

        Args:
            data (list[RenderResult]): The objects to export
            *args: Optional export parameters dict (`view`, `metadata`)

        Returns:
            StringIO: A file-like object containing the CSV data

        Raises:
            ExporterCSVTypeError: If objects of different types are detected
        """
        header: list[str] = list(DEFAULT_HEADER)
        columns: list[str] = [field[FieldKey.NAME.value] for field in data[0].fields] if data else []

        view, metadata = BaseExporterFormat.resolve_export_view(args)
        if metadata:
            header = metadata.get(ExporterMetadataKey.HEADER.value, header)
            columns = metadata.get(ExporterMetadataKey.COLUMNS.value, columns)
        else:
            # CSV renders in the render view only when metadata explicitly selects the columns
            view = ExporterConfigType.NATIVE.value

        current_type_id = data[0].type_information[TYPE_INFO_ID_KEY] if data else None
        rows: list[list[str]] = []

        for obj in data:
            # CSV can only hold a single type, so reject a mixed-type selection
            if current_type_id != obj.type_information[TYPE_INFO_ID_KEY]:
                raise ExporterCSVTypeError('CSV can export only Objects of the same Type')

            rows.append(self._build_row(obj, header, columns, view))

        return self.csv_writer([*header, *columns], rows)


    def _build_row(self, obj: RenderResult, header: list[str], columns: list[str], view: str) -> list[str]:
        """
        Builds a single CSV row for one object

        Args:
            obj (RenderResult): The object to serialize
            header (list[str]): The identity columns (from object_information; `public_id` -> `object_id`)
            columns (list[str]): The field names to serialize (from the type / metadata override)
            view (str): The export view passed to the field summary renderer

        Returns:
            list[str]: The stringified cell values, in `header` then `columns` order
        """
        obj_fields: dict = {
            field[FieldKey.NAME.value]: BaseExporterFormat.summary_renderer(obj, field, view)
            for field in obj.fields
        }

        row: list[str] = []

        for head in header:
            info_key = OBJECT_INFO_ID_KEY if head == CmdbObjectKey.PUBLIC_ID.value else head
            row.append(str(obj.object_information[info_key]))

        for name in columns:
            row.append(str(obj_fields.get(name)))

        return row


    def csv_writer(self, header: list[str], rows: list[list], dialect=csv.excel) -> StringIO:
        """
        Generates a CSV file in memory

        Args:
            header (list[str]): A list representing the CSV header row
            rows (list[list]): A list of lists, where each inner list represents a row of data
            dialect (type[csv.Dialect]): The CSV dialect to use. Defaults to `csv.excel`

        Returns:
            StringIO: A file-like object containing the CSV data
        """
        csv_file = StringIO()
        writer = csv.writer(csv_file, dialect=dialect)
        writer.writerow(header)
        writer.writerows(rows)
        csv_file.seek(0)  # Reset pointer to the beginning of the file

        return csv_file
