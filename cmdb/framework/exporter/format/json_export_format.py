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
Implementation of JsonExportFormat
"""
import logging
import json

from cmdb.database.database_utils import default
from cmdb.framework.exporter.format.base_exporter_format import BaseExporterFormat
from cmdb.framework.exporter.config.exporter_config_type_enum import ExporterConfigType
from cmdb.framework.rendering.render_result import RenderResult
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER = logging.getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                               JsonExportFormat - CLASS                                               #
# -------------------------------------------------------------------------------------------------------------------- #
class JsonExportFormat(BaseExporterFormat):
    """
    The JSON export format for exporting data as a .json file

    Extends: BaseExporterFormat
    """
    FILE_EXTENSION = "json"
    LABEL = "JSON"
    MULTITYPE_SUPPORT = True
    ICON = "file-code"
    DESCRIPTION = "Export as JSON"
    ACTIVE = True


    def export(self, data: list[RenderResult], *args) -> str:
        """
        Exports a list of RenderResult objects as a JSON-formatted string

        Args:
            data (List[RenderResult]): List of `RenderResult` objects to export
            *args: arguments including:
                - 'metadata' (dict or str): Customizes the export (e.g., columns, header)
                - 'view' (str): Specifies the view format. Defaults to 'native'.
                                Affects data processing if set to 'RENDER'.

        Returns:
            str: A JSON-formatted string representing the exported data with fields, MDS, and metadata
        """
        metadata = None
        view = 'native'

        if args:
            metadata = args[0].get("metadata")
            view = args[0].get("view", 'native')

        header = ['public_id', 'active', 'type_label']
        output = []

        for obj in data:
            # Initialize columns and multi_data_sections
            columns = obj.fields
            multi_data_sections = obj.multi_data_sections if obj.multi_data_sections else []

            # If metadata is provided, adjust columns and header
            if metadata and view.upper() == ExporterConfigType.RENDER.name:
                metadata = json.loads(metadata)
                header = metadata.get('header', header)
                columns = [field for field in columns if field['name'] in metadata.get('columns', [])]

            # Prepare the base output element
            output_element = self._create_output_element(obj, header)

            # Add fields to the output element
            output_element['fields'] = self._get_fields(obj, columns, view)

            # Add multi-data sections if available
            if multi_data_sections:
                output_element['multi_data_sections'] = self._get_multi_data_sections(multi_data_sections)

            output.append(output_element)

        return json.dumps(output, default=default, ensure_ascii=False, indent=2)


    def _create_output_element(self, obj: RenderResult, header: list[str]) -> dict:
        """
        Creates the basic structure of an output element based on the header

        Args:
            obj (RenderResult): The RenderResult object containing the data to be exported
            header (list[str]): A list of field names to include in the output element

        Returns:
            dict: A dictionary representing the output element with the specified header fields
        """
        output_element = {}
        for head in header:
            if head == 'public_id':
                output_element[head] = obj.object_information.get('object_id')
            elif head == 'type_label':
                output_element[head] = obj.type_information.get(head)
            else:
                output_element[head] = obj.object_information.get(head)

        return output_element


    def _get_fields(self, obj: RenderResult, columns: list[dict], view: str) -> list[dict]:
        """
        Retrieves the fields data for the object based on the view format

        Args:
            obj (RenderResult): The RenderResult object containing the fields to be retrieved
            columns (list[dict]): A list of field definitions for the object
            view (str): The view format that determines how the field data is processed

        Returns:
            list[dict]: A list of dictionaries representing the field names and their corresponding values
        """
        fields = []

        for field in columns:
            fields.append({
                'name': field.get('name'),
                'value': BaseExporterFormat.summary_renderer(obj, field, view)
            })

        return fields


    def _get_multi_data_sections(self, multi_data_sections: list[dict]) -> list[dict]:
        """
        Processes the multi-data sections for the object

        Args:
            multi_data_sections (list[dict]): A list of multi-data sections to be processed

        Returns:
            list[dict]: A list of dictionaries representing the multi-data sections and their values
        """
        sections = []

        for mds in multi_data_sections:
            section = {
                'section_id': mds.get('section_id'),
                'highest_id': mds.get('highest_id'),
                'values': self._get_multi_data_values(mds.get('values', []))
            }
            sections.append(section)

        return sections


    def _get_multi_data_values(self, values: list[dict]) -> list[dict]:
        """
        Processes the values within each multi-data section

        Args:
            values (list[dict]): A list of values within a multi-data section

        Returns:
            list[dict]: A list of dictionaries representing the values and their data
                        within the multi-data sections
        """
        value_list = []

        for value in values:
            value_data = {
                'multi_data_id': value.get('multi_data_id'),
                'data': self._get_data(value.get('data', []))
            }
            value_list.append(value_data)

        return value_list


    def _get_data(self, data: list[dict]) -> list[dict]:
        """
        Processes the individual data elements within each multi-data value

        Args:
            data (list[dict]): A list of data elements to be processed

        Returns:
            list[dict]: A list of dictionaries representing the data elements
                        with their names and values
        """
        return [{'name': data_set.get('name'), 'value': data_set.get('value')} for data_set in data]
