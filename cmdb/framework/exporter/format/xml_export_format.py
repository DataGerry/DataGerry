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
import re
from typing import Any
from xml.dom.minidom import Document, Element

from cmdb.models.object_model.cmdb_object_key_enum import (
    CmdbObjectKey,
    CmdbObjectMdsKey,
    CmdbObjectMdsRowKey,
)
from cmdb.models.type_model.field_key_enum import FieldKey
from cmdb.framework.exporter.format.base_exporter_format import (
    BaseExporterFormat,
    TYPE_INFO_LABEL_KEY,
    OBJECT_INFO_ID_KEY,
    to_export_cell,
)
from cmdb.framework.exporter.config.exporter_config_type_enum import ExporterConfigType
from cmdb.framework.rendering.render_result import RenderResult

from cmdb.errors.exporter import ExporterCharacterError, ExporterMetadataError
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

# Multi-data-section tags: <multi_data_sections> -> <section> -> <row> -> <field> (row data reuses
# the <field name= value=/> element from the regular fields block)
XML_MDS_TAG: str = 'multi_data_sections'
XML_SECTION_TAG: str = 'section'
XML_ROW_TAG: str = 'row'

# Every identity header entry becomes the tag of a <meta> child, so it has to be an XML element name. The
# names are kept to ASCII letters, digits, `_`, `.` and `-`, not starting with a digit, `.` or `-`; a colon
# is left out because it would name an undeclared namespace prefix
XML_ELEMENT_NAME_PATTERN: re.Pattern[str] = re.compile(r'[A-Za-z_][A-Za-z0-9_.\-]*')

# Characters XML 1.0 cannot carry at all - the C0 controls other than tab, line feed and carriage return,
# the two non-characters U+FFFE / U+FFFF and lone surrogates
XML_ILLEGAL_CHARACTER_PATTERN: re.Pattern[str] = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]')

# -------------------------------------------------------------------------------------------------------------------- #
#                                                XmlExportFormat - CLASS                                               #
# -------------------------------------------------------------------------------------------------------------------- #
class XmlExportFormat(BaseExporterFormat):
    """
    The XML export format class for exporting data as XML (.xml) files

    One document holds the whole selection, also when it spans several types: each `<object>` carries the
    fields of its own type only (as the JSON export does), so a field another type declares never appears on
    it, and a `<field value="">` always is a field of the object's type that holds nothing

    Extends: BaseExporterFormat
    """
    FILE_EXTENSION = "xml"
    MIME_TYPE = "text/xml"
    LABEL = "XML"
    MULTITYPE_SUPPORT = True
    ICON = "file-alt"
    DESCRIPTION = "Export as XML"
    ACTIVE = True


    def export(self, data: list[RenderResult], *args: Any) -> str:
        """
        Exports the given objects as a formatted XML string

        The document is `<objects>` with one `<object>` per entry, each holding a `<meta>` block (the
        identity/header columns) and a `<fields>` block with the object's own fields. In the RENDER view a
        supplied `metadata` override selects the header and the field columns; each object then carries the
        selected fields its type owns, in the order of the selection. An empty object list yields `<objects/>`.

        Args:
            data (list[RenderResult]): The objects to be exported
            *args: Optional export parameters dict (`view`, `metadata`)

        Raises:
            ExporterMetadataError: If the metadata header names an entry that is no XML element name
            ExporterCharacterError: If a value holds a character XML 1.0 cannot represent

        Returns:
            str: XML file content as a formatted (pretty-printed) string
        """
        header, selected_columns, view = self._get_export_settings(args)

        return self._create_xml_document(data, header, selected_columns, view).toprettyxml()


    def _get_export_settings(self, args: tuple[Any, ...]) -> tuple[list[str], list[str] | None, str]:
        """
        Resolves the header, the field-column selection and the view for the export from the request args

        A render-view `metadata` override selects the header and the columns, a key it leaves out keeping the
        default; without such an override the export is forced to the NATIVE view (a render view is only
        honoured when it explicitly selects the columns). The header entries are checked here, before any
        object is serialized, because each of them becomes an element name

        Args:
            args (tuple[Any, ...]): The positional export args; `args[0]` (if present) is the options dict

        Raises:
            ExporterMetadataError: If a header entry is no XML element name

        Returns:
            tuple[list[str], list[str] | None, str]:
                - header (list[str]): Metadata/identity field names to include per object
                - selected_columns (list[str] | None): The selected field names, None for every own field
                - view (str): The resolved view type (`'native'` or `'render'`)
        """
        view, metadata = BaseExporterFormat.resolve_export_view(args)
        header, selected_columns = BaseExporterFormat.resolve_metadata_selection(metadata, DEFAULT_HEADER)

        if not metadata:
            # XML renders in the render view only when metadata explicitly selects the columns
            view = ExporterConfigType.NATIVE.value

        self._assert_element_names(header)

        return header, selected_columns, view


    @staticmethod
    def _assert_element_names(header: list[str]) -> None:
        """
        Refuses a header entry that cannot be the tag of a `<meta>` child

        Args:
            header (list[str]): The identity header entries

        Raises:
            ExporterMetadataError: If an entry is not a string or no XML element name
        """
        for head in header:
            if not isinstance(head, str) or not XML_ELEMENT_NAME_PATTERN.fullmatch(head):
                raise ExporterMetadataError(
                    f"The export metadata header '{head}' is not usable as an XML element name!"
                )


    def _create_xml_document(
            self,
            data: list[RenderResult],
            header: list[str],
            selected_columns: list[str] | None,
            view: str) -> Document:
        """
        Creates the XML document for export

        Args:
            data (list[RenderResult]): The list of objects to be exported
            header (list[str]): List of metadata field names to be included in the export
            selected_columns (list[str] | None): The selected field names, None for every own field
            view (str): The view type for rendering the export

        Returns:
            Document: The document whose root `<objects>` element holds all exported objects
        """
        document = Document()
        cmdb_object_list = self._append_element(document, document, XML_ROOT_TAG)

        for obj in data:
            obj_fields_dict = self._extract_object_fields(obj, view)
            columns = BaseExporterFormat.select_owned_columns(selected_columns, list(obj_fields_dict))

            cmdb_object = self._append_element(document, cmdb_object_list, XML_OBJECT_TAG)
            self._add_meta_data(document, cmdb_object, obj, header)
            self._add_field_data(document, cmdb_object, obj_fields_dict, columns)
            self._add_multi_data_sections(document, cmdb_object, obj)

        return document


    @staticmethod
    def _append_element(
            document: Document,
            parent: Document | Element,
            tag: str,
            attributes: dict[str, str] | None = None,
            text: str | None = None) -> Element:
        """
        Appends one element with its attributes and its text to a parent node

        The attributes keep their given order. An empty or absent text adds no text node, so the element is
        written self-closing. Every attribute value and the text are checked for characters XML cannot carry

        Args:
            document (Document): The document creating the nodes
            parent (Document | Element): The node the element is appended to
            tag (str): The element's tag name
            attributes (dict[str, str] | None): The element's attributes, in output order
            text (str | None): The element's text content

        Raises:
            ExporterCharacterError: If an attribute value or the text holds a character XML cannot represent

        Returns:
            Element: The appended element
        """
        element = document.createElement(tag)

        for name, value in (attributes or {}).items():
            element.setAttribute(name, XmlExportFormat._checked_text(value))

        if text:
            element.appendChild(document.createTextNode(XmlExportFormat._checked_text(text)))

        parent.appendChild(element)

        return element


    @staticmethod
    def _checked_text(value: str) -> str:
        """
        Returns a value unchanged once it is known to hold only characters XML 1.0 can represent

        Args:
            value (str): The attribute value or element text

        Raises:
            ExporterCharacterError: If the value holds a character XML cannot represent

        Returns:
            str: The value
        """
        illegal = XML_ILLEGAL_CHARACTER_PATTERN.search(value)

        if illegal:
            raise ExporterCharacterError(
                f"The value '{value[:illegal.start()]}…' holds the character U+{ord(illegal.group()):04X}, "
                "which an XML document cannot carry!"
            )

        return value


    def _extract_object_fields(self, obj: RenderResult, view: str) -> dict[str, Any]:
        """
        Extracts the object's fields as a dictionary

        Args:
            obj (RenderResult): The object to extract fields from
            view (str): The view type for rendering

        Returns:
            dict[str, Any]: A dictionary of field names and their rendered values, in the type's field order
        """
        return {
            field.get(FieldKey.NAME.value): BaseExporterFormat.summary_renderer(obj, field, view)
            for field in obj.fields
        }


    def _add_meta_data(self, document: Document, cmdb_object: Element, obj: RenderResult, header: list[str]) -> None:
        """
        Adds metadata elements to the XML structure

        `public_id` is emitted from the object information's object id, `type_label` as a `<type>`
        element from the type information, and every other header entry from the object information.

        Args:
            document (Document): The document creating the nodes
            cmdb_object (Element): The parent XML element
            obj (RenderResult): The object containing metadata
            header (list[str]): List of metadata fields
        """
        cmdb_object_meta = self._append_element(document, cmdb_object, XML_META_TAG)

        for head in header:
            if head == CmdbObjectKey.PUBLIC_ID.value:
                text = str(obj.object_information.get(OBJECT_INFO_ID_KEY, ''))
                self._append_element(document, cmdb_object_meta, head, text=text)
            elif head == TYPE_INFO_LABEL_KEY:
                text = obj.type_information.get(TYPE_INFO_LABEL_KEY, '')
                self._append_element(document, cmdb_object_meta, XML_TYPE_TAG, text=text)
            else:
                text = str(obj.object_information.get(head, ''))
                self._append_element(document, cmdb_object_meta, head, text=text)


    def _add_field_data(
            self,
            document: Document,
            cmdb_object: Element,
            obj_fields_dict: dict[str, Any],
            columns: list[str]) -> None:
        """
        Adds field elements to the XML structure

        Args:
            document (Document): The document creating the nodes
            cmdb_object (Element): The parent XML element
            obj_fields_dict (dict[str, Any]): Dictionary of object fields and their values
            columns (list[str]): The field names to include, all of them fields of the object's type
        """
        cmdb_object_fields = self._append_element(document, cmdb_object, XML_FIELDS_TAG)

        for field in columns:
            self._append_element(document, cmdb_object_fields, XML_FIELD_TAG, {
                FieldKey.NAME.value: str(field),
                FieldKey.VALUE.value: to_export_cell(obj_fields_dict.get(field))
            })


    def _add_multi_data_sections(self, document: Document, cmdb_object: Element, obj: RenderResult) -> None:
        """
        Adds the object's multi-data sections as a nested `<multi_data_sections>` block

        The block is added only when the object actually has MDS. It is built from the shared
        `serialize_multi_data_sections` shape and rendered as `<section>` -> `<row>` -> `<field>`
        (each row's data reuses the same `<field name= value=/>` element as the regular fields block).

        Args:
            document (Document): The document creating the nodes
            cmdb_object (Element): The parent `<object>` element
            obj (RenderResult): The object whose multi-data sections are serialized
        """
        sections = BaseExporterFormat.serialize_multi_data_sections(obj.multi_data_sections)

        if not sections:
            return

        mds_element = self._append_element(document, cmdb_object, XML_MDS_TAG)

        for section in sections:
            section_element = self._append_element(document, mds_element, XML_SECTION_TAG, {
                CmdbObjectMdsKey.SECTION_ID.value: str(section.get(CmdbObjectMdsKey.SECTION_ID.value, '')),
                CmdbObjectMdsKey.HIGHEST_ID.value: str(section.get(CmdbObjectMdsKey.HIGHEST_ID.value, '')),
            })

            for row in section.get(CmdbObjectMdsKey.VALUES.value, []):
                row_element = self._append_element(document, section_element, XML_ROW_TAG, {
                    CmdbObjectMdsRowKey.MULTI_DATA_ID.value: str(row.get(CmdbObjectMdsRowKey.MULTI_DATA_ID.value, '')),
                })

                for entry in row.get(CmdbObjectMdsRowKey.DATA.value, []):
                    self._append_element(document, row_element, XML_FIELD_TAG, {
                        FieldKey.NAME.value: str(entry.get(FieldKey.NAME.value, '')),
                        FieldKey.VALUE.value: to_export_cell(entry.get(FieldKey.VALUE.value)),
                    })
