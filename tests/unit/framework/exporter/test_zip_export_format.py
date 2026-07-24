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
import zipfile
from types import SimpleNamespace

from cmdb.framework.exporter.format.zip_export_format import ZipExportFormat
# -------------------------------------------------------------------------------------------------------------------- #


def _obj(object_id: int, type_id: int, type_name: str, value: str = 'host-1') -> SimpleNamespace:
    """A stand-in RenderResult with one text field."""
    return SimpleNamespace(
        fields=[{'name': 'dg-name', 'type': 'text', 'value': value}],
        sections=[],
        multi_data_sections=[],
        object_information={'object_id': object_id, 'active': True},
        type_information={'type_id': type_id, 'type_name': type_name, 'type_label': type_name.title()},
    )


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
