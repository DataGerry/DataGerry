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
Implementation of XmlExportFormat
"""
from logging import Logger, getLogger
import json
import xml.dom.minidom
import xml.etree.ElementTree as ET

from cmdb.framework.exporter.format.base_exporter_format import BaseExporterFormat
from cmdb.framework.exporter.config.exporter_config_type_enum import ExporterConfigType
from cmdb.framework.rendering.render_result import RenderResult
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                XmlExportFormat - CLASS                                               #
# -------------------------------------------------------------------------------------------------------------------- #
class XmlExportFormat(BaseExporterFormat):
    """
    The XML export format class for exporting data as XML (.xml) files
    """
    FILE_EXTENSION = "xml"
    LABEL = "XML"
    MULTITYPE_SUPPORT = True
    ICON = "file-alt"
    DESCRIPTION = "Export as XML"
    ACTIVE = True


    def export(self, data: list[RenderResult], *args) -> str:
        """Exports object_list as .xml file

        Args:
            data (list[RenderResult]): The objects to be exported
            *args: Additional arguments that may contain metadata

        Returns:
            str: XML file content as a formatted string
        """
        header, columns, view = self._get_export_settings(args, data)
        cmdb_object_list = self._create_xml_structure(data, header, columns, view)

        xml_string = xml.dom.minidom.parseString(
            ET.tostring(cmdb_object_list, encoding='unicode', method='xml')
        ).toprettyxml()

        return xml_string


    def _get_export_settings(self, args: tuple, data: list[RenderResult]) -> tuple[list[str], list[str], str]:
        """Extracts export settings from arguments.

        Args:
            args (tuple): Additional arguments that may contain metadata
            data (list[RenderResult]): The list of objects to be exported

        Returns:
            tuple[list[str], list[str], str]:
                - header (list[str]): List of metadata field names to be included in the export
                - columns (list[str]): List of data field names to be included in the export
                - view (str): The view type for rendering the export
        """
        header = ['public_id', 'active', 'type_label']
        columns = [] if not data else [x['name'] for x in data[0].fields]
        view = 'native'

        if args and args[0].get("metadata", False) and \
           args[0].get('view', 'native').upper() == ExporterConfigType.RENDER.name:
            _meta = json.loads(args[0].get("metadata", ""))
            view = args[0].get('view', 'native')
            header = _meta['header']
            columns = _meta['columns']

        return header, columns, view


    def _create_xml_structure(
            self,
            data: list[RenderResult],
            header: list[str],
            columns: list[str],
            view: str) -> ET.Element:
        """
        Creates the XML structure for export

        Args:
            data (list[RenderResult]): The list of objects to be exported
            header (list[str]): List of metadata field names to be included in the export
            columns (list[str]): List of data field names to be included in the export
            view (str): The view type for rendering the export

        Returns:
            xml.etree.ElementTree.Element: The root XML element containing all exported objects
        """
        cmdb_object_list = ET.Element('objects')

        for obj in data:
            obj_fields_dict = self._extract_object_fields(obj, view)
            cmdb_object = ET.SubElement(cmdb_object_list, 'object')
            self._add_meta_data(cmdb_object, obj, header)
            self._add_field_data(cmdb_object, obj_fields_dict, columns)

        return cmdb_object_list


    def _extract_object_fields(self, obj: RenderResult, view: str) -> dict:
        """
        Extracts the object's fields as a dictionary

        Args:
            obj (RenderResult): The object to extract fields from.
            view (str): The view type for rendering.

        Returns:
            dict: A dictionary of field names and their rendered values.
        """
        return {field.get('name'): BaseExporterFormat.summary_renderer(obj, field, view) for field in obj.fields}


    def _add_meta_data(self, cmdb_object: ET.Element, obj: RenderResult, header: list[str]) -> None:
        """
        Adds metadata elements to the XML structure

        Args:
            cmdb_object (ET.Element): The parent XML element
            obj (RenderResult): The object containing metadata
            header (list[str]): List of metadata fields
        """
        cmdb_object_meta = ET.SubElement(cmdb_object, 'meta')
        for head in header:
            if head == 'public_id':
                cmdb_object_meta_id = ET.SubElement(cmdb_object_meta, head)
                cmdb_object_meta_id.text = str(obj.object_information.get('object_id', ''))
            elif head == 'type_label':
                cmdb_object_meta_type = ET.SubElement(cmdb_object_meta, 'type')
                cmdb_object_meta_type.text = obj.type_information.get('type_label', '')
            else:
                cmdb_object_meta_id = ET.SubElement(cmdb_object_meta, head)
                cmdb_object_meta_id.text = str(obj.object_information.get(head, ''))


    def _add_field_data(self, cmdb_object: ET.Element, obj_fields_dict: dict, columns: list[str]) -> None:
        """Adds field elements to the XML structure.

        Args:
            cmdb_object (ET.Element): The parent XML element
            obj_fields_dict (dict): Dictionary of object fields and their values
            columns (list[str]): List of field names to be included
        """
        cmdb_object_fields = ET.SubElement(cmdb_object, 'fields')

        for field in columns:
            field_attribs: dict[str, str] = {
                'name': str(field),
                'value': str(obj_fields_dict.get(field, ''))
            }
            ET.SubElement(cmdb_object_fields, "field", field_attribs)
