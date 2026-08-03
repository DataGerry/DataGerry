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
Unit tests for cmdb.framework.exporter.format.csv_export_format
"""
import csv
import json
from io import StringIO
from types import SimpleNamespace

import pytest

from cmdb.framework.exporter.format.csv_export_format import CsvExportFormat
from cmdb.errors.exporter import ExporterCSVTypeError, ExporterColumnError
# -------------------------------------------------------------------------------------------------------------------- #


def _obj(
        object_id: int,
        type_id: int = 5,
        value: str = 'host-1',
        mds=None,
        sections=None,
        fields=None) -> SimpleNamespace:
    """A stand-in RenderResult with one text field (plus optional multi-data sections / type sections)."""
    return SimpleNamespace(
        fields=fields if fields is not None else [{'name': 'dg-name', 'type': 'text', 'value': value}],
        sections=sections or [],
        multi_data_sections=mds or [],
        object_information={'object_id': object_id, 'active': True},
        type_information={'type_id': type_id, 'type_label': 'Server'},
    )


def _mds_section(section_id: str, field_names: list) -> dict:
    """Builds a rendered type-section dict describing a multi-data-section."""
    return {'type': 'multi-data-section', 'name': section_id, 'label': section_id, 'fields': field_names}


def _mds(section_id: str, entries: list) -> dict:
    """Builds an object's MDS section instance from a list of {field_name: value} entry dicts."""
    return {
        'section_id': section_id,
        'highest_id': len(entries),
        'values': [
            {'multi_data_id': idx, 'data': [{'name': name, 'value': val} for name, val in entry.items()]}
            for idx, entry in enumerate(entries)
        ],
    }


def _read(stream: StringIO) -> list:
    """Parses the CSV StringIO into a list of rows."""
    return list(csv.reader(StringIO(stream.getvalue())))


class TestCsvExport:
    """CsvExportFormat.export serializes single-type objects into CSV."""

    def test_native_export(self) -> None:
        """The header is public_id/active + field names; the row carries the object's values."""
        rows = _read(CsvExportFormat().export([_obj(10)]))

        assert rows[0] == ['public_id', 'active', 'dg-name']
        assert rows[1] == ['10', 'True', 'host-1']

    def test_empty_export_yields_header_only(self) -> None:
        """An empty object list produces a valid header-only CSV (no error)."""
        rows = _read(CsvExportFormat().export([]))

        assert rows == [['public_id', 'active']]

    def test_mixed_types_raise(self) -> None:
        """Objects of differing types are rejected (CSV is single-type)."""
        with pytest.raises(ExporterCSVTypeError):
            CsvExportFormat().export([_obj(10, type_id=5), _obj(11, type_id=6)])

    def test_render_view_metadata_selects_columns(self) -> None:
        """In the render view a metadata override drives the header + columns."""
        metadata = json.dumps({'header': ['public_id'], 'columns': ['dg-name']})
        rows = _read(CsvExportFormat().export([_obj(10)], {'view': 'render', 'metadata': metadata}))

        assert rows[0] == ['public_id', 'dg-name']
        assert rows[1] == ['10', 'host-1']

    def test_declares_csv_mime_type(self) -> None:
        """CSV declares its (correct) text/csv mime type."""
        assert CsvExportFormat.MIME_TYPE == 'text/csv'


class TestCsvExportMds:
    """MDS fields become their own columns; entries are spread across consecutive rows."""

    def test_single_section_multiple_entries_spread_over_rows(self) -> None:
        """Each MDS field is a column; the first row holds regular fields + entry 1, next rows entry 2..N."""
        sections = [_mds_section('nics', ['nic_name', 'mac'])]
        mds = [_mds('nics', [{'nic_name': 'eth0', 'mac': 'm0'}, {'nic_name': 'eth1', 'mac': 'm1'}])]

        rows = _read(CsvExportFormat().export([_obj(10, mds=mds, sections=sections)]))

        assert rows[0] == ['public_id', 'active', 'dg-name', 'nic_name', 'mac']
        assert rows[1] == ['10', 'True', 'host-1', 'eth0', 'm0']
        # Continuation row: identity + regular columns empty, only the 2nd MDS entry present
        assert rows[2] == ['', '', '', 'eth1', 'm1']

    def test_two_sections_unequal_entry_counts(self) -> None:
        """A section that runs out of entries leaves its columns empty (like the regular fields)."""
        sections = [_mds_section('nics', ['nic_name', 'mac']), _mds_section('disks', ['disk_label', 'size_gb'])]
        mds = [
            _mds('nics', [{'nic_name': 'eth0', 'mac': 'm0'},
                          {'nic_name': 'eth1', 'mac': 'm1'},
                          {'nic_name': 'eth2', 'mac': 'm2'}]),
            _mds('disks', [{'disk_label': 'root', 'size_gb': 100},
                           {'disk_label': 'data', 'size_gb': 500}]),
        ]

        rows = _read(CsvExportFormat().export([_obj(10, mds=mds, sections=sections)]))

        assert rows[0] == ['public_id', 'active', 'dg-name', 'nic_name', 'mac', 'disk_label', 'size_gb']
        assert rows[1] == ['10', 'True', 'host-1', 'eth0', 'm0', 'root', '100']
        assert rows[2] == ['', '', '', 'eth1', 'm1', 'data', '500']
        # 3rd row: nics has a 3rd entry, disks does not -> disk columns empty
        assert rows[3] == ['', '', '', 'eth2', 'm2', '', '']

    def test_type_has_mds_but_object_has_no_entries(self) -> None:
        """A type with an MDS section but an object with no entries yields one row with empty MDS cells."""
        sections = [_mds_section('nics', ['nic_name', 'mac'])]

        rows = _read(CsvExportFormat().export([_obj(10, mds=[], sections=sections)]))

        assert rows[0] == ['public_id', 'active', 'dg-name', 'nic_name', 'mac']
        assert rows[1] == ['10', 'True', 'host-1', '', '']

    def test_mds_field_not_duplicated_from_flat_fields(self) -> None:
        """An MDS field also present (default-valued) in the flat fields is emitted once, with MDS values."""
        sections = [_mds_section('nics', ['nic_name'])]
        # The renderer includes MDS fields in the flat list with a default value; it must not win
        fields = [{'name': 'dg-name', 'type': 'text', 'value': 'host-1'},
                  {'name': 'nic_name', 'type': 'text', 'value': 'DEFAULT'}]
        mds = [_mds('nics', [{'nic_name': 'eth0'}])]

        rows = _read(CsvExportFormat().export([_obj(10, mds=mds, sections=sections, fields=fields)]))

        assert rows[0] == ['public_id', 'active', 'dg-name', 'nic_name']
        assert rows[0].count('nic_name') == 1
        assert rows[1] == ['10', 'True', 'host-1', 'eth0']

    def test_partial_entry_leaves_missing_field_empty(self) -> None:
        """A sparse entry (missing one of its section's fields) leaves that cell empty."""
        sections = [_mds_section('nics', ['nic_name', 'mac'])]
        mds = [_mds('nics', [{'nic_name': 'eth0', 'mac': 'm0'}, {'nic_name': 'eth1'}])]

        rows = _read(CsvExportFormat().export([_obj(10, mds=mds, sections=sections)]))

        assert rows[2] == ['', '', '', 'eth1', '']

    def test_multiple_objects_each_span_their_own_rows(self) -> None:
        """Each object contributes its own block of rows; continuation rows blank the identity."""
        sections = [_mds_section('nics', ['nic_name'])]
        obj_a = _obj(10, mds=[_mds('nics', [{'nic_name': 'a0'}, {'nic_name': 'a1'}])], sections=sections)
        obj_b = _obj(11, mds=[_mds('nics', [{'nic_name': 'b0'}])], sections=sections)

        rows = _read(CsvExportFormat().export([obj_a, obj_b]))

        assert rows[1] == ['10', 'True', 'host-1', 'a0']
        assert rows[2] == ['', '', '', 'a1']
        assert rows[3] == ['11', 'True', 'host-1', 'b0']

    def test_duplicate_column_name_raises(self) -> None:
        """Two fields resolving to the same column name refuse the export."""
        sections = [_mds_section('s1', ['dup']), _mds_section('s2', ['dup'])]

        with pytest.raises(ExporterColumnError):
            CsvExportFormat().export([_obj(10, sections=sections)])


class TestCsvExportHumanReadable:
    """The human_readable flag relabels headers and resolves reference / location values."""

    def test_headers_relabelled_and_values_resolved(self, human_readable_object) -> None:
        """Headers become labels (incl. identity); ref -> summary line; location -> tree name."""
        options = {'human_readable': 'true', 'location_names': {42: 'Berlin/Room-1'}}
        rows = _read(CsvExportFormat().export([human_readable_object], options))

        assert rows[0] == ['Public ID', 'Active', 'Hostname', 'Owner', 'Location']
        assert rows[1] == ['10', 'True', 'host-1', 'User #3 | alice', 'Berlin/Room-1']

    def test_without_flag_headers_are_names_and_values_raw(self, human_readable_object) -> None:
        """Without the flag the header stays field names and ref/location values stay raw ids."""
        rows = _read(CsvExportFormat().export([human_readable_object]))

        assert rows[0] == ['public_id', 'active', 'dg-name', 'owner', 'dg_location']
        assert rows[1] == ['10', 'True', 'host-1', '3', '42']


class TestCsvWriter:
    """csv_writer renders a header + rows into a rewound StringIO."""

    def test_writes_header_and_rows(self) -> None:
        """The writer emits the header then each row, and rewinds the buffer."""
        result = CsvExportFormat().csv_writer(['a', 'b'], [['1', '2'], ['3', '4']])

        assert result.tell() == 0
        assert list(csv.reader(StringIO(result.getvalue()))) == [['a', 'b'], ['1', '2'], ['3', '4']]
