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
Implementation of XmlExportFormat
"""
from logging import Logger, getLogger
from typing import Any
import xml.dom.minidom
import xml.etree.ElementTree as ET

from cmdb.models.object_model.cmdb_object_key_enum import CmdbObjectKey
from cmdb.models.type_model.field_key_enum import FieldKey
from cmdb.framework.exporter.format.base_exporter_format import (
    BaseExporterFormat,
    TYPE_INFO_LABEL_KEY,
    OBJECT_INFO_ID_KEY,
)
from cmdb.framework.exporter.config.exporter_config_type_enum import ExporterConfigType
from cmdb.framework.exporter.exporter_constants import ExporterMetadataKey
from cmdb.framework.rendering.render_result import RenderResult
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# Default identity columns emitted for each object (public_id + active flag + the type's label)
DEFAULT_HEADER: list[str] = [CmdbObjectKey.PUBLIC_ID.value, CmdbObjectKey.ACTIVE.value, TYPE_INFO_LABEL_KEY]

# XML tag names of the exported document (output contract - values must stay stable for consumers)
XML_ROOT_TAG: str = 'objects'
XML_OBJECT_TAG: str = 'object'
XML_META_TAG: str = 'meta'
XML_FIELDS_TAG: str = 'fields'
XML_FIELD_TAG: str = 'field'
XML_TYPE_TAG: str = 'type'  # the <type> meta element emitted for the 'type_label' header entry

# -------------------------------------------------------------------------------------------------------------------- #
#                                                XmlExportFormat - CLASS                                               #
# -------------------------------------------------------------------------------------------------------------------- #
class XmlExportFormat(BaseExporterFormat):
    """
    The XML export format class for exporting data as XML (.xml) files

    Extends: BaseExporterFormat
    """
    FILE_EXTENSION = "xml"
    MIME_TYPE = "text/xml"
    LABEL = "XML"
    MULTITYPE_SUPPORT = True
    ICON = "file-alt"
    DESCRIPTION = "Export as XML"
    ACTIVE = True


    def export(self, data: list[RenderResult], *args) -> str:
        """
        Exports the given objects as a formatted XML string

        The document is `<objects>` with one `<object>` per entry, each holding a `<meta>` block (the
        identity/header columns) and a `<fields>` block. In the RENDER view a supplied `metadata`
        override selects the header/columns; otherwise the header is the default identity columns and
        the columns are the union of every object's field names. An empty object list yields `<objects/>`.

        Args:
            data (list[RenderResult]): The objects to be exported
            *args: Optional export parameters dict (`view`, `metadata`)

        Returns:
            str: XML file content as a formatted (pretty-printed) string
        """
        header, columns, view = self._get_export_settings(args, data)
        cmdb_object_list = self._create_xml_structure(data, header, columns, view)

        xml_string = xml.dom.minidom.parseString(
            ET.tostring(cmdb_object_list, encoding='unicode', method='xml')
        ).toprettyxml()

        return xml_string


    def _get_export_settings(self, args: tuple, data: list[RenderResult]) -> tuple[list[str], list[str], str]:
        """
        Resolves the header, columns and view for the export from the request args

        The default header is the identity columns and the default columns are the union of the field
        names across all objects (so a multi-type export keeps every type's fields). A render-view
        `metadata` override replaces both; without such an override the export is forced to the NATIVE
        view (a render view is only honoured when it explicitly selects the columns).

        Args:
            args (tuple): The positional export args; `args[0]` (if present) is the options dict
            data (list[RenderResult]): The list of objects to be exported

        Returns:
            tuple[list[str], list[str], str]:
                - header (list[str]): Metadata/identity field names to include per object
                - columns (list[str]): Data field names to include per object
                - view (str): The resolved view type (`'native'` or `'render'`)
        """
        header: list[str] = list(DEFAULT_HEADER)
        columns: list[str] = self._collect_field_names(data)

        view, metadata = BaseExporterFormat.resolve_export_view(args)

        if metadata:
            header = metadata.get(ExporterMetadataKey.HEADER.value, header)
            columns = metadata.get(ExporterMetadataKey.COLUMNS.value, columns)
        else:
            # XML renders in the render view only when metadata explicitly selects the columns
            view = ExporterConfigType.NATIVE.value

        return header, columns, view


    @staticmethod
    def _collect_field_names(data: list[RenderResult]) -> list[str]:
        """
        Collects the ordered union of field names across all objects

        Preserving first-seen order and de-duplicating keeps a multi-type export (XML supports multiple
        types) from dropping the field names contributed by types other than the first object's.

        Args:
            data (list[RenderResult]): The objects to be exported

        Returns:
            list[str]: The de-duplicated field names in first-seen order
        """
        names: list[str] = []
        seen: set[str] = set()

        for obj in data:
            for field in obj.fields:
                name = field.get(FieldKey.NAME.value)
                if name not in seen:
                    seen.add(name)
                    names.append(name)

        return names


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
        cmdb_object_list = ET.Element(XML_ROOT_TAG)

        for obj in data:
            obj_fields_dict = self._extract_object_fields(obj, view)
            cmdb_object = ET.SubElement(cmdb_object_list, XML_OBJECT_TAG)
            self._add_meta_data(cmdb_object, obj, header)
            self._add_field_data(cmdb_object, obj_fields_dict, columns)

        return cmdb_object_list


    def _extract_object_fields(self, obj: RenderResult, view: str) -> dict[str, Any]:
        """
        Extracts the object's fields as a dictionary

        Args:
            obj (RenderResult): The object to extract fields from
            view (str): The view type for rendering

        Returns:
            dict[str, Any]: A dictionary of field names and their rendered values
        """
        return {
            field.get(FieldKey.NAME.value): BaseExporterFormat.summary_renderer(obj, field, view)
            for field in obj.fields
        }


    def _add_meta_data(self, cmdb_object: ET.Element, obj: RenderResult, header: list[str]) -> None:
        """
        Adds metadata elements to the XML structure

        `public_id` is emitted from the object information's object id, `type_label` as a `<type>`
        element from the type information, and every other header entry from the object information.

        Args:
            cmdb_object (ET.Element): The parent XML element
            obj (RenderResult): The object containing metadata
            header (list[str]): List of metadata fields
        """
        cmdb_object_meta = ET.SubElement(cmdb_object, XML_META_TAG)

        for head in header:
            if head == CmdbObjectKey.PUBLIC_ID.value:
                cmdb_object_meta_id = ET.SubElement(cmdb_object_meta, head)
                cmdb_object_meta_id.text = str(obj.object_information.get(OBJECT_INFO_ID_KEY, ''))
            elif head == TYPE_INFO_LABEL_KEY:
                cmdb_object_meta_type = ET.SubElement(cmdb_object_meta, XML_TYPE_TAG)
                cmdb_object_meta_type.text = obj.type_information.get(TYPE_INFO_LABEL_KEY, '')
            else:
                cmdb_object_meta_id = ET.SubElement(cmdb_object_meta, head)
                cmdb_object_meta_id.text = str(obj.object_information.get(head, ''))


    def _add_field_data(self, cmdb_object: ET.Element, obj_fields_dict: dict, columns: list[str]) -> None:
        """
        Adds field elements to the XML structure

        Args:
            cmdb_object (ET.Element): The parent XML element
            obj_fields_dict (dict): Dictionary of object fields and their values
            columns (list[str]): List of field names to be included
        """
        cmdb_object_fields = ET.SubElement(cmdb_object, XML_FIELDS_TAG)

        for field in columns:
            field_attribs: dict[str, str] = {
                FieldKey.NAME.value: str(field),
                FieldKey.VALUE.value: str(obj_fields_dict.get(field, ''))
            }
            ET.SubElement(cmdb_object_fields, XML_FIELD_TAG, field_attribs)
