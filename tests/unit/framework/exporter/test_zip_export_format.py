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
Unit tests for cmdb.framework.exporter.format.zip_export_format
"""
import json
import zipfile
from types import SimpleNamespace

import pytest

from cmdb.framework.exporter.format.csv_export_format import CsvExportFormat
from cmdb.framework.exporter.format.xml_export_format import XmlExportFormat
from cmdb.framework.exporter.format.zip_export_format import ZipExportFormat
# -------------------------------------------------------------------------------------------------------------------- #

CSV_FORMAT: str = 'CsvExportFormat'
JSON_FORMAT: str = 'JsonExportFormat'
XML_FORMAT: str = 'XmlExportFormat'

SHARED_FIELD: str = 'dg-name'
SERVER_FIELD: str = 'rack-unit'

# A ZIP64 threshold every packed file exceeds, to show the archive no longer refuses a large entry
TINY_ZIP64_LIMIT: int = 8


def _obj(object_id: int, type_id: int, type_name: str, value: str = 'host-1') -> SimpleNamespace:
    """A stand-in RenderResult with one text field."""
    return SimpleNamespace(
        fields=[{'name': 'dg-name', 'type': 'text', 'value': value}],
        sections=[],
        multi_data_sections=[],
        object_information={'object_id': object_id, 'active': True},
        type_information={'type_id': type_id, 'type_name': type_name, 'type_label': type_name.title()},
    )


def _members(data, options: dict) -> dict[str, bytes]:
    """Runs the ZIP export and returns each archive entry's content by name."""
    with zipfile.ZipFile(ZipExportFormat().export(data, options)) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def _two_field_obj(object_id: int, type_id: int, type_name: str) -> SimpleNamespace:
    """A stand-in RenderResult with two labelled text fields."""
    obj = _obj(object_id, type_id, type_name)
    obj.fields = [{'name': SHARED_FIELD, 'label': 'Name', 'type': 'text', 'value': 'host-1'},
                  {'name': SERVER_FIELD, 'label': 'Rack unit', 'type': 'text', 'value': '12'}]
    return obj


def _entries(data, classname: str = 'JsonExportFormat') -> list[str]:
    """Runs the ZIP export and returns the archive's entry names."""
    with zipfile.ZipFile(ZipExportFormat().export(data, {'classname': classname})) as archive:
        return archive.namelist()


class TestZipExport:
    """ZipExportFormat.export packs one inner-format file per type into a ZIP archive."""

    def test_single_type_yields_one_entry(self) -> None:
        """Objects of one type produce a single archive entry named after the type."""
        entries = _entries([_obj(10, 5, 'server'), _obj(11, 5, 'server')])

        assert entries == ['server_ID_5.json']

    def test_multi_type_yields_one_entry_per_type(self) -> None:
        """Objects of several types produce one archive entry per type (sorted by type id)."""
        entries = _entries([_obj(12, 6, 'router'), _obj(10, 5, 'server')])

        assert entries == ['server_ID_5.json', 'router_ID_6.json']

    def test_empty_data_yields_valid_empty_archive(self) -> None:
        """An empty object list produces a valid, empty ZIP archive (no crash)."""
        assert _entries([]) == []

    def test_input_list_is_not_mutated(self) -> None:
        """The export groups by type without mutating the caller's object list."""
        data = [_obj(10, 5, 'server'), _obj(12, 6, 'router')]
        ZipExportFormat().export(data, {'classname': 'JsonExportFormat'})

        assert len(data) == 2

    def test_delegates_to_inner_format_extension(self) -> None:
        """The archive entry extension follows the inner format (CSV here)."""
        entries = _entries([_obj(10, 5, 'server')], classname='CsvExportFormat')

        assert entries == ['server_ID_5.csv']

    def test_declares_zip_mime_type(self) -> None:
        """ZIP declares the standard application/zip mime type."""
        assert ZipExportFormat.MIME_TYPE == 'application/zip'


class TestZipForwardsTheOptions:
    """Each packed file is the inner format's export with the request's options."""

    def test_a_render_selection_reaches_the_packed_file(self) -> None:
        """The column selection is honoured inside the archive, as in a direct export."""
        options = {'classname': CSV_FORMAT, 'view': 'render',
                   'metadata': json.dumps({'header': ['public_id'], 'columns': [SERVER_FIELD]})}
        obj = _two_field_obj(10, 5, 'server')

        members = _members([obj], options)

        assert members['server_ID_5.csv'].decode() == CsvExportFormat().export([obj], options).getvalue()

    def test_the_human_readable_flag_reaches_the_packed_file(self) -> None:
        """The packed CSV carries the field labels, as a direct human-readable CSV does."""
        options = {'classname': CSV_FORMAT, 'human_readable': 'true'}

        header = _members([_two_field_obj(10, 5, 'server')], options)['server_ID_5.csv'].decode().splitlines()[0]

        assert header == 'Public ID,Active,Name,Rack unit'

    def test_each_packed_file_equals_the_direct_export_of_its_type(self) -> None:
        """Byte for byte, per type - also in a native export with no further options."""
        server, router = _two_field_obj(10, 5, 'server'), _obj(11, 6, 'router')
        options = {'classname': XML_FORMAT}

        members = _members([router, server], options)

        assert members['server_ID_5.xml'].decode() == XmlExportFormat().export([server], options)
        assert members['router_ID_6.xml'].decode() == XmlExportFormat().export([router], options)

    def test_the_frontends_call_shape_is_a_native_export(self) -> None:
        """The reference table's ZIP sends no view and the metadata text 'undefined': both stay without effect."""
        obj = _two_field_obj(10, 5, 'server')

        members = _members([obj], {'classname': CSV_FORMAT, 'zip': 'true', 'metadata': 'undefined'})

        assert members['server_ID_5.csv'].decode() == CsvExportFormat().export([obj]).getvalue()


class TestZipHonoursHumanReadable:
    """ZipExportFormat.honours_human_readable answers for the packed format."""

    @pytest.mark.parametrize(('classname', 'expected'), [(CSV_FORMAT, True), ('XlsxExportFormat', True),
                                                         (JSON_FORMAT, False), (XML_FORMAT, False)])
    def test_the_packed_format_decides(self, classname: str, expected: bool) -> None:
        """A flagged ZIP is a presentation export exactly when its inner format honours the flag."""
        assert ZipExportFormat().honours_human_readable({'classname': classname, 'human_readable': 'true'}) is expected

    def test_without_the_flag_it_is_never_human_readable(self) -> None:
        """No flag, no presentation export - whatever is packed."""
        assert ZipExportFormat().honours_human_readable({'classname': CSV_FORMAT}) is False


class TestZipEntryNames:
    """Entry names are sanitized like the archive's own filename."""
    # pylint: disable=protected-access

    def test_a_path_in_the_type_name_stays_inside_the_entry_name(self) -> None:
        """Separators and the path-climbing `..` cannot shape a path inside the archive."""
        name = ZipExportFormat._zip_entry_name('../evil/Type Name', 5, 'json')

        assert '/' not in name and '\\' not in name
        assert not name.startswith('.')
        assert name.endswith('_ID_5.json')

    def test_upper_case_and_spaces_are_reduced(self) -> None:
        """The same reduction as the download filename: lower case, a dash for every other run."""
        assert ZipExportFormat._zip_entry_name('My Router', 6, 'csv') == 'my-router_ID_6.csv'

    def test_a_name_with_nothing_usable_takes_the_fallback(self) -> None:
        """The type id still keeps such an entry apart."""
        assert ZipExportFormat._zip_entry_name('???', 7, 'xml') == 'type_ID_7.xml'


class TestZipLargeEntries:
    """The archive takes an entry beyond the ZIP64 threshold."""

    def test_an_entry_beyond_the_zip64_limit_is_written(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """With ZIP64 refused such an entry raised LargeZipFile - an export of that size answered 500."""
        monkeypatch.setattr(zipfile, 'ZIP64_LIMIT', TINY_ZIP64_LIMIT)

        assert _entries([_obj(10, 5, 'server')]) == ['server_ID_5.json']
