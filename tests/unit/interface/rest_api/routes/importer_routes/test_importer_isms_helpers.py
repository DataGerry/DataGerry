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
Unit tests for the pure importer helpers of importer_isms_routes

Covers ``parse_list_of_strings`` and ``parse_bool`` (no I/O) and ``read_csv_file`` (in-memory
FileStorage): delimiter detection for comma / semicolon files and the missing-header abort.
"""
import io

import pytest
from werkzeug.datastructures import FileStorage
from werkzeug.exceptions import HTTPException

from cmdb.interface.rest_api.routes.importer_routes.importer_isms_routes import (
    parse_list_of_strings,
    parse_bool,
    read_csv_file,
)
# -------------------------------------------------------------------------------------------------------------------- #

HEADERS: set[str] = {'name', 'value'}


def _csv_file(content: str) -> FileStorage:
    """Wraps CSV text in a FileStorage as the route would receive it."""
    return FileStorage(stream=io.BytesIO(content.encode('utf-8')), filename='import.csv')


class TestParseListOfStrings:
    """parse_list_of_strings splits a comma-separated CSV cell into a trimmed list."""

    def test_splits_and_trims(self) -> None:
        """Comma-separated values are split and stripped."""
        assert parse_list_of_strings('field', {'field': 'a, b ,c'}) == ['a', 'b', 'c']

    def test_drops_empty_items(self) -> None:
        """Empty segments between commas are dropped."""
        assert parse_list_of_strings('field', {'field': 'a,,  ,b'}) == ['a', 'b']

    def test_missing_or_empty_field_returns_empty_list(self) -> None:
        """A missing or empty field yields an empty list."""
        assert parse_list_of_strings('field', {}) == []
        assert parse_list_of_strings('field', {'field': ''}) == []


class TestParseBool:
    """parse_bool maps common truthy / falsy strings, defaulting unknown / None to False."""

    @pytest.mark.parametrize('value', ['true', 'YES', '1', ' True '])
    def test_truthy_values(self, value: str) -> None:
        """Recognised truthy strings (case/space-insensitive) return True."""
        assert parse_bool(value) is True

    @pytest.mark.parametrize('value', ['false', 'No', '0', 'maybe', '', None])
    def test_falsy_and_unknown_values(self, value: str) -> None:
        """Falsy strings, unknown strings and None all return False."""
        assert parse_bool(value) is False

    def test_bool_passthrough(self) -> None:
        """An actual bool is returned unchanged."""
        assert parse_bool(True) is True


class TestReadCsvFile:
    """read_csv_file detects the delimiter and validates the required headers."""

    def test_reads_comma_delimited(self) -> None:
        """A comma-delimited file is parsed into rows."""
        reader = read_csv_file(_csv_file('name,value\nfoo,1\nbar,2\n'), HEADERS)
        rows = list(reader)

        assert [row['name'] for row in rows] == ['foo', 'bar']

    def test_reads_semicolon_delimited(self) -> None:
        """A semicolon-delimited file is parsed into rows."""
        reader = read_csv_file(_csv_file('name;value\nfoo;1\n'), HEADERS)
        rows = list(reader)

        assert rows[0]['value'] == '1'

    def test_missing_header_aborts_400(self) -> None:
        """A file missing a required header aborts with 400."""
        with pytest.raises(HTTPException) as exc_info:
            read_csv_file(_csv_file('name\nfoo\n'), HEADERS)

        assert exc_info.value.code == 400
