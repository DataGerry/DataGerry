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
Unit tests for cmdb.framework.exporter.format.xml_export_format
"""
import json
import xml.etree.ElementTree as ET
from types import SimpleNamespace

import pytest

from cmdb.framework.exporter.format.xml_export_format import XmlExportFormat, keep_whitespace_references
from cmdb.errors.exporter import ExporterCharacterError, ExporterMetadataError
# -------------------------------------------------------------------------------------------------------------------- #

SHARED_FIELD: str = 'name'
SERVER_FIELD: str = 'rack-unit'
ROUTER_FIELD: str = 'ip'

# The pinned document text: the declaration, tab indentation, every empty element self-closing
SINGLE_TYPE_DOCUMENT: str = (
    '<?xml version="1.0" ?>\n'
    '<objects>\n'
    '\t<object>\n'
    '\t\t<meta>\n'
    '\t\t\t<public_id>10</public_id>\n'
    '\t\t\t<active>True</active>\n'
    '\t\t\t<type>Server</type>\n'
    '\t\t</meta>\n'
    '\t\t<fields>\n'
    '\t\t\t<field name="name" value="q&quot;&lt;&amp;&gt;"/>\n'
    '\t\t\t<field name="rack-unit" value=""/>\n'
    '\t\t</fields>\n'
    '\t</object>\n'
    '</objects>\n'
)
# A header entry the stand-in object information carries no value for
ABSENT_HEAD: str = 'author_id'
EMPTY_DOCUMENT: str = '<?xml version="1.0" ?>\n<objects/>\n'


def _obj(object_id: int, type_id: int = 5, type_label: str = 'Server', fields=None, mds=None,
         sections=None) -> SimpleNamespace:
    """A stand-in RenderResult with the given fields (defaulting to one text field), optional MDS and sections."""
    return SimpleNamespace(
        fields=fields if fields is not None else [{'name': 'dg-name', 'type': 'text', 'value': 'host-1'}],
        multi_data_sections=mds or [],
        sections=sections or [],
        object_information={'object_id': object_id, 'active': True},
        type_information={'type_id': type_id, 'type_label': type_label},
    )


def _field(name: str, value) -> dict:
    """A rendered text field."""
    return {'name': name, 'type': 'text', 'value': value}


def _field_pairs(obj_element: ET.Element) -> list[tuple[str, str]]:
    """The (name, value) pairs of an exported <object>'s <fields> block, in document order."""
    return [(field.attrib['name'], field.attrib['value']) for field in obj_element.find('fields')]


def _export(data, *args) -> ET.Element:
    """Runs the XML export and parses the resulting string back into an ElementTree root."""
    return ET.fromstring(XmlExportFormat().export(data, *args))


class TestXmlExport:
    """XmlExportFormat.export serializes rendered objects into an XML string."""

    def test_native_export(self) -> None:
        """One <object> with the default meta block and its field is emitted."""
        root = _export([_obj(10)])

        assert root.tag == 'objects'
        objects = root.findall('object')
        assert len(objects) == 1

        meta = objects[0].find('meta')
        assert meta.find('public_id').text == '10'
        assert meta.find('active').text == 'True'
        assert meta.find('type').text == 'Server'

        fields = objects[0].find('fields').findall('field')
        assert len(fields) == 1
        assert fields[0].attrib == {'name': 'dg-name', 'value': 'host-1'}

    def test_empty_export_yields_empty_root(self) -> None:
        """An empty object list yields a valid, childless <objects/> root (no crash / 500)."""
        root = _export([])

        assert root.tag == 'objects'
        assert not list(root)

    def test_render_metadata_selects_header_and_columns(self) -> None:
        """A render-view metadata override restricts the meta header and the field columns."""
        metadata = json.dumps({'header': ['public_id'], 'columns': ['dg-name']})
        root = _export([_obj(10)], {'view': 'render', 'metadata': metadata})

        meta = root.find('object/meta')
        assert [child.tag for child in meta] == ['public_id']

        fields = root.findall('object/fields/field')
        assert [f.attrib['name'] for f in fields] == ['dg-name']

    def test_multitype_export_carries_each_types_own_fields(self) -> None:
        """Each object lists the fields of its own type only, never a field another type declares."""
        obj_a = _obj(10, type_id=5, fields=[{'name': 'dg-name', 'type': 'text', 'value': 'host-1'}])
        obj_b = _obj(11, type_id=6, fields=[{'name': 'ip', 'type': 'text', 'value': '10.0.0.1'}])

        first, second = _export([obj_a, obj_b]).findall('object')

        assert _field_pairs(first) == [('dg-name', 'host-1')]
        assert _field_pairs(second) == [('ip', '10.0.0.1')]

    def test_multitype_export_keeps_each_types_field_order(self) -> None:
        """A type sharing a field name with an earlier type keeps its own field order."""
        server = _obj(10, type_id=5, fields=[_field(SHARED_FIELD, 'x')])
        router = _obj(11, type_id=6, fields=[_field(ROUTER_FIELD, '1'), _field(SHARED_FIELD, 'y')])

        _, second = _export([server, router]).findall('object')

        assert _field_pairs(second) == [(ROUTER_FIELD, '1'), (SHARED_FIELD, 'y')]

    def test_an_own_empty_field_stays_an_empty_value(self) -> None:
        """A field the type declares but the object leaves empty is still listed, with an empty value."""
        root = _export([_obj(10, fields=[_field(SHARED_FIELD, None)])])

        assert _field_pairs(root.find('object')) == [(SHARED_FIELD, '')]

    def test_render_selection_is_narrowed_to_each_types_fields(self) -> None:
        """A column selection spanning types gives each object the selected fields its type owns, in selection order."""
        server = _obj(10, type_id=5, fields=[_field(SHARED_FIELD, 'x'), _field(SERVER_FIELD, 's')])
        router = _obj(11, type_id=6, fields=[_field(ROUTER_FIELD, '1'), _field(SHARED_FIELD, 'y')])
        metadata = json.dumps({'header': ['public_id'], 'columns': [ROUTER_FIELD, SERVER_FIELD, SHARED_FIELD]})

        first, second = _export([server, router], {'view': 'render', 'metadata': metadata}).findall('object')

        assert _field_pairs(first) == [(SERVER_FIELD, 's'), (SHARED_FIELD, 'x')]
        assert _field_pairs(second) == [(ROUTER_FIELD, '1'), (SHARED_FIELD, 'y')]

    def test_render_metadata_without_columns_keeps_every_own_field(self) -> None:
        """A metadata override leaving `columns` out selects the default columns, not none at all."""
        obj = _obj(10, fields=[_field(SHARED_FIELD, 'x'), _field(SERVER_FIELD, 's')])
        metadata = json.dumps({'header': ['public_id']})

        root = _export([obj], {'view': 'render', 'metadata': metadata})

        assert [child.tag for child in root.find('object/meta')] == ['public_id']
        assert _field_pairs(root.find('object')) == [(SHARED_FIELD, 'x'), (SERVER_FIELD, 's')]

    def test_render_metadata_with_empty_columns_exports_no_field(self) -> None:
        """An empty `columns` list is a selection of its own: no field at all."""
        metadata = json.dumps({'header': ['public_id'], 'columns': []})

        root = _export([_obj(10)], {'view': 'render', 'metadata': metadata})

        assert not root.findall('object/fields/field')

    @pytest.mark.parametrize('head', ['bad name', '1st', 'a:b', '-dash', '', 'a/><b', 'a b="1"', 7])
    def test_header_entry_that_is_no_element_name_is_refused(self, head) -> None:
        """A header entry becomes a tag, so one that is no XML element name is refused instead of crashing."""
        metadata = json.dumps({'header': ['public_id', head], 'columns': []})

        with pytest.raises(ExporterMetadataError):
            XmlExportFormat().export([_obj(10)], {'view': 'render', 'metadata': metadata})

    @pytest.mark.parametrize('head', ['public_id', 'type_label', 'creation_time', 'object_information.x', '_a-1'])
    def test_header_entry_that_is_an_element_name_is_accepted(self, head) -> None:
        """Element names - the frontend's identity columns among them - pass the header check."""
        metadata = json.dumps({'header': [head], 'columns': []})

        root = _export([_obj(10)], {'view': 'render', 'metadata': metadata})

        assert len(list(root.find('object/meta'))) == 1

    def test_header_is_checked_also_without_any_object(self) -> None:
        """The header is refused before any object is serialized, so an empty selection is refused too."""
        metadata = json.dumps({'header': ['bad name'], 'columns': []})

        with pytest.raises(ExporterMetadataError):
            XmlExportFormat().export([], {'view': 'render', 'metadata': metadata})

    @pytest.mark.parametrize('value', ['nul\x00', 'vertical\x0btab', 'escape\x1b', 'lone\ud800', 'non\ufffe'])
    def test_value_xml_cannot_carry_is_refused(self, value: str) -> None:
        """A field value holding a character XML 1.0 has no spelling for is refused, naming the character."""
        with pytest.raises(ExporterCharacterError, match=r'U\+[0-9A-F]{4}'):
            XmlExportFormat().export([_obj(10, fields=[_field(SHARED_FIELD, value)])])

    def test_meta_text_xml_cannot_carry_is_refused(self) -> None:
        """The check covers element text too, not only attribute values."""
        obj = _obj(10, type_label='bad\x07label')

        with pytest.raises(ExporterCharacterError):
            XmlExportFormat().export([obj])

    @pytest.mark.parametrize('value', [
        'line1\nline2', 'tab\there', 'crlf\r\nnext', 'cr\ronly', ' lead and trail ', 'q"<&>\'', 'ü€😀',
    ])
    def test_value_xml_can_carry_reads_back_as_exported(self, value: str) -> None:
        """Whitespace, markup characters and non-ASCII text are exported - and an XML reader gets them back"""
        root = _export([_obj(10, fields=[_field(SHARED_FIELD, value)])])

        assert root.find('object/fields/field').attrib['value'] == value

    def test_a_line_break_is_a_character_reference_in_the_file(self) -> None:
        """The bytes: `&#10;` / `&#13;` / `&#9;` inside the attribute, never the raw character"""
        document = XmlExportFormat().export([_obj(10, fields=[_field(SHARED_FIELD, 'a\r\nb\tc')])])

        assert 'value="a&#13;&#10;b&#9;c"' in document

    def test_an_mds_row_value_reads_back_as_exported(self) -> None:
        """Row values are attributes too"""
        mds = [{'section_id': 's1', 'highest_id': 1, 'values': [
            {'multi_data_id': 1, 'data': [{'name': 'note', 'value': 'r1\nr2\tr3'}]},
        ]}]

        field = _export([_obj(10, mds=mds)]).find('object/multi_data_sections/section/row/field')

        assert field.attrib['value'] == 'r1\nr2\tr3'

    def test_a_carriage_return_in_meta_text_reads_back(self) -> None:
        """Element text keeps a line feed and a tab anyway; a carriage return only as a reference"""
        root = _export([_obj(10, type_label='a\r\nb\tc')])

        assert root.find('object/meta/type').text == 'a\r\nb\tc'

    def test_a_refusal_names_the_object_and_the_field(self) -> None:
        """In an export of thousands of objects the reader has to find the value"""
        with pytest.raises(ExporterCharacterError, match=r"Object 10, field 'name'.*U\+0007"):
            XmlExportFormat().export([_obj(10, fields=[_field(SHARED_FIELD, 'bell\x07')])])

    def test_a_refusal_in_an_mds_row_names_its_section(self) -> None:
        """Field and multi-data section"""
        mds = [{'section_id': 'ports', 'highest_id': 1, 'values': [
            {'multi_data_id': 1, 'data': [{'name': 'port', 'value': 'eth\x00'}]},
        ]}]

        with pytest.raises(ExporterCharacterError, match=r"Object 12, field 'port' of multi-data section 'ports'"):
            XmlExportFormat().export([_obj(12, mds=mds)])

    def test_a_refusal_in_the_meta_block_names_the_entry(self) -> None:
        """The header entry the text was written for"""
        with pytest.raises(ExporterCharacterError, match=r"Object 10, field 'type_label'"):
            XmlExportFormat().export([_obj(10, type_label='bad\x07label')])

    def test_single_type_document_bytes(self) -> None:
        """The exact document text of a single-type export: declaration, tab indentation, self-closing fields."""
        obj = _obj(10, fields=[_field(SHARED_FIELD, 'q"<&>'), _field(SERVER_FIELD, None)])

        assert XmlExportFormat().export([obj]) == SINGLE_TYPE_DOCUMENT

    def test_an_empty_meta_value_is_a_self_closing_element(self) -> None:
        """A header entry the object has no value for is written `<entry/>`, not `<entry></entry>`."""
        metadata = json.dumps({'header': ['public_id', ABSENT_HEAD], 'columns': []})

        document = XmlExportFormat().export([_obj(10)], {'view': 'render', 'metadata': metadata})

        assert f'\t\t\t<{ABSENT_HEAD}/>\n' in document

    def test_empty_document_bytes(self) -> None:
        """An empty export is the declaration and a self-closing root."""
        assert XmlExportFormat().export([]) == EMPTY_DOCUMENT

    def test_no_mds_block_when_object_has_no_mds(self) -> None:
        """An object without MDS gets no <multi_data_sections> element."""
        root = _export([_obj(10)])

        assert root.find('object/multi_data_sections') is None

    def test_mds_exported_as_nested_elements(self) -> None:
        """An object with MDS gets a nested <multi_data_sections>/<section>/<row>/<field> block."""
        mds = [{
            'section_id': 's1',
            'highest_id': 2,
            'values': [
                {'multi_data_id': 1, 'data': [{'name': 'f', 'value': 'v', 'type': 'text'}]},
                {'multi_data_id': 2, 'data': [{'name': 'f', 'value': 'w', 'type': 'text'}]},
            ],
        }]

        section = _export([_obj(10, mds=mds)]).find('object/multi_data_sections/section')

        assert section.attrib == {'section_id': 's1', 'highest_id': '2'}
        rows = section.findall('row')
        assert [row.attrib['multi_data_id'] for row in rows] == ['1', '2']
        # Row data reuses the <field name= value=/> element (field type dropped, re-derived on read)
        assert rows[0].find('field').attrib == {'name': 'f', 'value': 'v'}
        assert rows[1].find('field').attrib == {'name': 'f', 'value': 'w'}

    # ---------------------------------------- an MDS field is written once ---------------------------------------- #

    MDS_SECTIONS: list[dict] = [
        {'type': 'section', 'name': 'main', 'fields': ['dg-name']},
        {'type': 'multi-data-section', 'name': 's1', 'fields': ['port', 'speed']},
    ]
    MDS_ROWS: list[dict] = [{'section_id': 's1', 'highest_id': 2, 'values': [
        {'multi_data_id': 1, 'data': [{'name': 'port', 'value': 'p1'}, {'name': 'speed', 'value': '1G'}]},
        {'multi_data_id': 2, 'data': [{'name': 'port', 'value': 'p2'}, {'name': 'speed', 'value': '10G'}]},
    ]}]

    def _mds_object(self, object_id: int = 10, type_id: int = 5) -> SimpleNamespace:
        """An object whose flat list carries its MDS fields with values no row holds - as the renderer gives it"""
        return _obj(object_id, type_id=type_id, mds=self.MDS_ROWS, sections=self.MDS_SECTIONS, fields=[
            _field('dg-name', 'host-1'), _field('port', 'DEFAULT'), _field('speed', 'flat-speed'),
        ])

    def test_an_mds_field_is_not_repeated_under_fields(self) -> None:
        """<fields> holds the regular fields; the flat value no row holds is nowhere in the document"""
        document_root = _export([self._mds_object()])
        obj = document_root.find('object')

        assert _field_pairs(obj) == [('dg-name', 'host-1')]
        assert 'DEFAULT' not in ET.tostring(document_root, encoding='unicode')
        assert 'flat-speed' not in ET.tostring(document_root, encoding='unicode')

    def test_each_mds_field_is_written_once_per_row(self) -> None:
        """Under <multi_data_sections>, with the row's own values"""
        obj = _export([self._mds_object()]).find('object')

        names = [field.attrib['name'] for field in obj.iter('field')]
        assert names.count('port') == 2 and names.count('speed') == 2
        rows = obj.findall('multi_data_sections/section/row')
        assert [(f.attrib['name'], f.attrib['value']) for f in rows[1].findall('field')] == [
            ('port', 'p2'), ('speed', '10G'),
        ]

    def test_a_selected_mds_field_is_still_written_in_its_rows_only(self) -> None:
        """A render-view selection naming an MDS field does not bring the flat copy back"""
        metadata = {'header': ['public_id'], 'columns': ['port', 'dg-name']}

        obj = _export([self._mds_object()], {'view': 'render', 'metadata': metadata}).find('object')

        assert _field_pairs(obj) == [('dg-name', 'host-1')]

    def test_a_multitype_export_reads_each_objects_own_layout(self) -> None:
        """An object of a type without that MDS section keeps a field of the same name under <fields>"""
        plain = _obj(11, type_id=6, fields=[_field('dg-name', 'host-2'), _field('port', 'kept')])

        objects = _export([self._mds_object(), plain]).findall('object')

        assert _field_pairs(objects[0]) == [('dg-name', 'host-1')]
        assert _field_pairs(objects[1]) == [('dg-name', 'host-2'), ('port', 'kept')]

    def test_declares_xml_mime_type(self) -> None:
        """XML declares the text/xml mime type (matching the previous writer text/<ext> fallback)."""
        assert XmlExportFormat.MIME_TYPE == 'text/xml'


class TestKeepWhitespaceReferences:
    """keep_whitespace_references - the pass over the serialized document."""

    def test_attribute_whitespace_becomes_references(self) -> None:
        """Line feed, carriage return and tab, inside an attribute value"""
        assert keep_whitespace_references('<f v="a\nb\rc\td"/>') == '<f v="a&#10;b&#13;c&#9;d"/>'

    def test_the_indentation_between_elements_is_left_alone(self) -> None:
        """Pretty-printing's line feeds and tabs are outside every attribute"""
        document = '<a>\n\t<f v="x"/>\n</a>\n'

        assert keep_whitespace_references(document) == document

    def test_a_carriage_return_in_text_becomes_a_reference(self) -> None:
        """Text keeps its line feed and tab - they read back as they are"""
        assert keep_whitespace_references('<t>a\r\nb\tc</t>') == '<t>a&#13;\nb\tc</t>'

    def test_an_already_escaped_document_is_unchanged(self) -> None:
        """A minidom that writes the references itself leaves nothing raw - the output is the same"""
        document = '<?xml version="1.0" ?>\n<f v="a&#10;b&#9;c&#13;"/>\n'

        assert keep_whitespace_references(document) == document
