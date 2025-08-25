# DataGerry - OpenSource Enterprise CMDB
# Copyright (C)  becon GmbH
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
import json

from cmdb.framework.exporter.format.base_exporter_format import BaseExporterFormat
from cmdb.framework.exporter.config.exporter_config_type_enum import ExporterConfigType
from cmdb.framework.rendering.render_result import RenderResult

from cmdb.errors.exporter import ExporterCSVTypeError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                CsvExportFormat - CLASS                                               #
# -------------------------------------------------------------------------------------------------------------------- #
class CsvExportFormat(BaseExporterFormat):
    """
    The csv export format class

    Extends: BaseExporterFormat
    """
    FILE_EXTENSION = "csv"
    LABEL = "CSV"
    MULTITYPE_SUPPORT = False
    ICON = "file-csv"
    DESCRIPTION = "Export as CSV (only of the same type)"
    ACTIVE = True


    def export(self, data: list[RenderResult], *args) -> StringIO:
        """ 
        Exports data as a CSV file
        
        Args:
            data (List[RenderResult]): The objects to be exported
            *args (Dict[str, Any]): Additional export parameters
        
        Returns:
            StringIO: A file-like object containing the CSV data
        
        Raises:
            ExporterCSVTypeError: If objects of different types are detected
        """
        if not data:
            raise ValueError("No data provided for CSV export")

        header: list[str] = ['public_id', 'active']
        columns: list = [x['name'] for x in data[0].fields] if data else []
        rows: list = []
        view = 'native'
        current_type_id: int = data[0].type_information['type_id']

        # Export only the shown fields chosen by the user
        if args and args[0].get("metadata") and\
           args[0].get("view", "native").upper() == ExporterConfigType.RENDER.name:
            metadata = json.loads(args[0]["metadata"])
            view = args[0]["view"]
            header = metadata.get("header", header)
            columns = metadata.get("columns", columns)

        for obj in data:
            # get type from first object and setup csv header
            if current_type_id is None:
                current_type_id = obj.type_information['type_id']

            # throw Exception if objects of different type are detected
            if current_type_id != obj.type_information['type_id']:
                raise ExporterCSVTypeError('CSV can export only Objects of the same Type')

            # get object fields as dict:
            obj_fields_dict = {}

            for field in obj.fields:
                obj_field_name: str = field.get('name')
                obj_fields_dict[obj_field_name] = BaseExporterFormat.summary_renderer(obj, field, view)

            # define output row
            row = []

            for head in header:
                head = 'object_id' if head == 'public_id' else head
                row.append(str(obj.object_information[head]))

            for name in columns:
                row.append(str(obj_fields_dict.get(name, None)))

            rows.append(row)

        return self.csv_writer([*header, *columns], rows)


    def csv_writer(self, header: list, rows: list, dialect=csv.excel) -> StringIO:
        """
        Generates a CSV file in memory

        Args:
            header (list): A list representing the CSV header row
            rows (list): A list of lists, where each inner list represents a row of data
            dialect (str, optional): The CSV dialect to use. Defaults to `csv.excel`

        Returns:
            StringIO: A file-like object containing the CSV data
        """
        csv_file = StringIO()
        writer = csv.writer(csv_file, dialect=dialect)
        writer.writerow(header)
        writer.writerows(rows)
        csv_file.seek(0) # Reset pointer to the beginning of the file

        return csv_file
