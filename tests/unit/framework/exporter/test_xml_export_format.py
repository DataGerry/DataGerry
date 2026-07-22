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

from cmdb.framework.exporter.format.xml_export_format import XmlExportFormat
# -------------------------------------------------------------------------------------------------------------------- #


def _obj(object_id: int, type_id: int = 5, type_label: str = 'Server', fields=None) -> SimpleNamespace:
    """A stand-in RenderResult with the given fields (defaulting to one text field)."""
    return SimpleNamespace(
        fields=fields if fields is not None else [{'name': 'dg-name', 'type': 'text', 'value': 'host-1'}],
        object_information={'object_id': object_id, 'active': True},
        type_information={'type_id': type_id, 'type_label': type_label},
    )


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

    def test_multitype_export_keeps_all_types_fields(self) -> None:
        """B1: a multi-type export keeps the field names contributed by every object, not just the first."""
        obj_a = _obj(10, type_id=5, fields=[{'name': 'dg-name', 'type': 'text', 'value': 'host-1'}])
        obj_b = _obj(11, type_id=6, fields=[{'name': 'ip', 'type': 'text', 'value': '10.0.0.1'}])

        root = _export([obj_a, obj_b])

        # Column union is applied to every object; each object only fills in the fields it owns
        first_fields = {f.attrib['name']: f.attrib['value'] for f in root.findall('object')[0].find('fields')}
        second_fields = {f.attrib['name']: f.attrib['value'] for f in root.findall('object')[1].find('fields')}

        assert first_fields == {'dg-name': 'host-1', 'ip': ''}
        assert second_fields == {'dg-name': '', 'ip': '10.0.0.1'}

    def test_declares_xml_mime_type(self) -> None:
        """XML declares the text/xml mime type (matching the previous writer text/<ext> fallback)."""
        assert XmlExportFormat.MIME_TYPE == 'text/xml'

    def test_collect_field_names_dedupes_in_first_seen_order(self) -> None:
        """The column union preserves first-seen order and de-duplicates shared field names."""
        # pylint: disable=protected-access
        obj_a = _obj(10, fields=[{'name': 'a', 'type': 'text', 'value': '1'},
                                 {'name': 'b', 'type': 'text', 'value': '2'}])
        obj_b = _obj(11, fields=[{'name': 'b', 'type': 'text', 'value': '3'},
                                 {'name': 'c', 'type': 'text', 'value': '4'}])

        assert XmlExportFormat._collect_field_names([obj_a, obj_b]) == ['a', 'b', 'c']
