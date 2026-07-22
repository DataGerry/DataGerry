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
from cmdb.errors.exporter import ExporterCSVTypeError
# -------------------------------------------------------------------------------------------------------------------- #


def _obj(object_id: int, type_id: int = 5, value: str = 'host-1') -> SimpleNamespace:
    """A stand-in RenderResult with one text field."""
    return SimpleNamespace(
        fields=[{'name': 'dg-name', 'type': 'text', 'value': value}],
        object_information={'object_id': object_id, 'active': True},
        type_information={'type_id': type_id, 'type_label': 'Server'},
    )


def _read(stream: StringIO) -> list[list[str]]:
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


class TestCsvWriter:
    """csv_writer renders a header + rows into a rewound StringIO."""

    def test_writes_header_and_rows(self) -> None:
        """The writer emits the header then each row, and rewinds the buffer."""
        result = CsvExportFormat().csv_writer(['a', 'b'], [['1', '2'], ['3', '4']])

        assert result.tell() == 0
        assert list(csv.reader(StringIO(result.getvalue()))) == [['a', 'b'], ['1', '2'], ['3', '4']]
