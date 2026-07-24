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
from cmdb.framework.exporter.format.base_exporter_format import BaseExporterFormat, TYPE_INFO_ID_KEY
from cmdb.framework.exporter.config.exporter_config_type_enum import ExporterConfigType
from cmdb.framework.exporter.exporter_constants import ExporterMetadataKey, ExporterOptionKey
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

        The header is `public_id, active` plus the type's regular field names, followed by one column
        per multi-data-section (MDS) field (see `BaseExporterFormat.build_object_rows` for the row
        layout). In the RENDER view a supplied `metadata` override selects the identity header + regular
        columns instead. All objects must share one type (CSV has no multi-type support). An empty object
        list yields a valid CSV with only the header row.

        Args:
            data (list[RenderResult]): The objects to export
            *args: Optional export parameters dict (`view`, `metadata`)

        Returns:
            StringIO: A file-like object containing the CSV data

        Raises:
            ExporterCSVTypeError: If objects of different types are detected
            ExporterColumnError: If two fields resolve to the same CSV column name
        """
        options = args[0] if args else {}
        human_readable = self.is_human_readable(options)
        location_names = options.get(ExporterOptionKey.LOCATION_NAMES.value) or {}

        header, regular_columns, mds_layout, mds_columns, view = self._resolve_columns(data, args)

        full_header: list[str] = [*header, *regular_columns, *mds_columns]
        # The duplicate guard runs on the unique field NAMES, before any human-readable relabel
        self.assert_unique_columns(full_header)

        current_type_id = data[0].type_information[TYPE_INFO_ID_KEY] if data else None
        rows: list[list[str]] = []

        for obj in data:
            # CSV can only hold a single type, so reject a mixed-type selection
            if current_type_id != obj.type_information[TYPE_INFO_ID_KEY]:
                raise ExporterCSVTypeError('CSV can export only Objects of the same Type')

            rows.extend(
                self.build_object_rows(obj, header, regular_columns, mds_layout, view, human_readable, location_names)
            )

        # Human-readable: relabel the finished header (names -> labels) as the last step
        if human_readable:
            full_header = self.relabel_header(full_header, data)

        return self.csv_writer(full_header, rows)


    def _resolve_columns(
            self,
            data: list[RenderResult],
            args: tuple) -> tuple[list[str], list[str], list[tuple[str, list[str]]], list[str], str]:
        """
        Resolves the identity header, regular columns, MDS layout/columns and view for the export

        Args:
            data (list[RenderResult]): The objects to export
            args (tuple): The positional export args; `args[0]` (if present) is the options dict

        Returns:
            tuple: `(header, regular_columns, mds_layout, mds_columns, view)` where `mds_layout` is the
                   `(section_id, field_names)` list and `mds_columns` the flattened MDS field names
        """
        header: list[str] = list(DEFAULT_HEADER)

        # The MDS layout is derived from the (single, shared) type's rendered sections
        mds_layout = self.extract_mds_layout(data[0].sections) if data else []
        mds_columns: list[str] = [name for _, field_names in mds_layout for name in field_names]

        view, metadata = BaseExporterFormat.resolve_export_view(args)
        if metadata:
            header = metadata.get(ExporterMetadataKey.HEADER.value, header)
            regular_columns = metadata.get(ExporterMetadataKey.COLUMNS.value, [])
        else:
            # CSV renders in the render view only when metadata explicitly selects the columns
            view = ExporterConfigType.NATIVE.value
            regular_columns = [field[FieldKey.NAME.value] for field in data[0].fields] if data else []

        # MDS fields also appear (default-valued) in the flat field list; keep them out of the regular
        # columns so each one is emitted exactly once, as its row-expanded MDS column
        mds_column_set: set[str] = set(mds_columns)
        regular_columns = [name for name in regular_columns if name not in mds_column_set]

        return header, regular_columns, mds_layout, mds_columns, view


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
