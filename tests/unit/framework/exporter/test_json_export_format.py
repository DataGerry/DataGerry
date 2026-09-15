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
Unit tests for cmdb.framework.exporter.format.json_export_format
"""
import json
from types import SimpleNamespace

from cmdb.framework.exporter.format.json_export_format import JsonExportFormat
# -------------------------------------------------------------------------------------------------------------------- #


def _obj(object_id: int, type_id: int = 5, value: str = 'host-1', mds=None) -> SimpleNamespace:
    """A stand-in RenderResult with one text field and optional multi-data sections."""
    return SimpleNamespace(
        fields=[{'name': 'dg-name', 'type': 'text', 'value': value}],
        object_information={'object_id': object_id, 'active': True},
        type_information={'type_id': type_id, 'type_label': 'Server'},
        multi_data_sections=mds,
    )


def _export(data, *args) -> list:
    """Runs the JSON export and parses the resulting string back into Python."""
    return json.loads(JsonExportFormat().export(data, *args))


class TestJsonExport:
    """JsonExportFormat.export serializes rendered objects into a JSON string."""

    def test_native_export(self) -> None:
        """The default header identity fields + all object fields are emitted."""
        out = _export([_obj(10)])

        assert len(out) == 1
        assert out[0]['public_id'] == 10
        assert out[0]['active'] is True
        assert out[0]['type_label'] == 'Server'
        assert out[0]['fields'] == [{'name': 'dg-name', 'value': 'host-1'}]

    def test_empty_export_is_empty_list(self) -> None:
        """An empty object list serializes to an empty JSON array."""
        assert _export([]) == []

    def test_render_metadata_selects_header_and_columns(self) -> None:
        """A render-view metadata override restricts the header identity fields and the columns."""
        metadata = json.dumps({'header': ['public_id'], 'columns': ['dg-name']})
        out = _export([_obj(10)], {'view': 'render', 'metadata': metadata})

        assert set(out[0]) == {'public_id', 'fields'}
        assert out[0]['fields'] == [{'name': 'dg-name', 'value': 'host-1'}]

    def test_render_metadata_multiple_objects_does_not_crash(self) -> None:
        """Regression: a multi-object render export with metadata must not re-parse metadata per object."""
        metadata = json.dumps({'header': ['public_id'], 'columns': ['dg-name']})
        out = _export([_obj(10), _obj(11)], {'view': 'render', 'metadata': metadata})

        assert [entry['public_id'] for entry in out] == [10, 11]

    def test_multi_data_sections_serialized(self) -> None:
        """Multi-data sections are serialized with their rows and data entries."""
        mds = [{
            'section_id': 's1',
            'highest_id': 2,
            'values': [{'multi_data_id': 1, 'data': [{'name': 'f', 'value': 'v', 'type': 'text'}]}],
        }]
        out = _export([_obj(10, mds=mds)])

        assert out[0]['multi_data_sections'] == [{
            'section_id': 's1',
            'highest_id': 2,
            'values': [{'multi_data_id': 1, 'data': [{'name': 'f', 'value': 'v'}]}],
        }]

    def test_declares_json_mime_type(self) -> None:
        """JSON declares the standard application/json mime type."""
        assert JsonExportFormat.MIME_TYPE == 'application/json'
