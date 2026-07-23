# DATAGERRY - OpenSource Enterprise CMDB
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
Unit tests for the concrete object parsers (JsonObjectParser / CsvObjectParser)

Filesystem-only (no DB): each test writes a small file to a tmp_path and parses it. Focus: the
parsed response shape, auto-casting + index-pairing of CSV rows, honouring the header/delimiter
config, and the shared ParserRuntimeError failure contract (both parsers wrap read/parse errors;
the CSV 'No content data!' guard is not re-wrapped by the broad handler).
"""
from pathlib import Path

import pytest

from cmdb.framework.importer.parser.json_object_parser import JsonObjectParser
from cmdb.framework.importer.parser.csv_object_parser import CsvObjectParser
from cmdb.framework.importer.responses.json_object_parser_response import JsonObjectParserResponse
from cmdb.framework.importer.responses.csv_object_parser_response import CsvObjectParserResponse
from cmdb.errors.importer import ParserRuntimeError
# -------------------------------------------------------------------------------------------------------------------- #


def _write(tmp_path: Path, name: str, content: str) -> str:
    """Write content to a temp file and return its path as a string."""
    file_path = tmp_path / name
    file_path.write_text(content, encoding='utf-8')
    return str(file_path)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                 JsonObjectParser                                                    #
# -------------------------------------------------------------------------------------------------------------------- #

class TestJsonObjectParser:
    """Parsing JSON import files."""

    def test_parses_a_list_of_objects(self, tmp_path: Path) -> None:
        """A JSON array yields a response whose count matches the number of objects."""
        path = _write(tmp_path, 'objects.json', '[{"x": 1}, {"x": 2}, {"x": 3}]')

        result = JsonObjectParser().parse(path)

        assert isinstance(result, JsonObjectParserResponse)
        assert result.count == 3
        assert result.entries == [{'x': 1}, {'x': 2}, {'x': 3}]

    def test_invalid_json_raises_parser_runtime_error(self, tmp_path: Path) -> None:
        """Malformed JSON is wrapped in ParserRuntimeError (B1 — symmetry with CSV)."""
        path = _write(tmp_path, 'bad.json', '{not valid json')

        with pytest.raises(ParserRuntimeError):
            JsonObjectParser().parse(path)

    def test_missing_file_raises_parser_runtime_error(self, tmp_path: Path) -> None:
        """A missing file is wrapped in ParserRuntimeError rather than a raw OSError."""
        with pytest.raises(ParserRuntimeError):
            JsonObjectParser().parse(str(tmp_path / 'does_not_exist.json'))

    def test_default_config_keys(self) -> None:
        """The default config exposes the FE-facing indent/encoding keys."""
        assert JsonObjectParser().get_config() == {'indent': 2, 'encoding': 'UTF-8'}


# -------------------------------------------------------------------------------------------------------------------- #
#                                                 CsvObjectParser                                                     #
# -------------------------------------------------------------------------------------------------------------------- #

class TestCsvObjectParser:
    """Parsing CSV import files."""

    def test_parses_rows_with_header(self, tmp_path: Path) -> None:
        """With header=True the first row is the header and rows become index->value dicts."""
        path = _write(tmp_path, 'data.csv', 'id,name\n1,alice\n2,bob\n')

        result = CsvObjectParser().parse(path)

        assert isinstance(result, CsvObjectParserResponse)
        assert result.count == 2
        assert result.get_header_list() == ['id', 'name']
        assert result.get_entry_length() == 2
        assert result.entries == [{0: 1, 1: 'alice'}, {0: 2, 1: 'bob'}]

    def test_values_are_auto_cast(self, tmp_path: Path) -> None:
        """Cell values are auto-cast (ints stay ints, text stays str)."""
        path = _write(tmp_path, 'cast.csv', 'a,b\n42,hello\n')

        entry = CsvObjectParser().parse(path).entries[0]

        assert entry[0] == 42
        assert entry[1] == 'hello'

    def test_header_disabled_keeps_all_rows(self, tmp_path: Path) -> None:
        """With header=False no row is consumed as a header."""
        path = _write(tmp_path, 'noheader.csv', '1,alice\n2,bob\n')

        result = CsvObjectParser({'header': False}).parse(path)

        assert result.get_header_list() == []
        assert result.count == 2

    def test_custom_delimiter(self, tmp_path: Path) -> None:
        """A semicolon-delimited file parses when the delimiter is configured."""
        path = _write(tmp_path, 'semi.csv', 'id;name\n1;alice\n')

        result = CsvObjectParser({'delimiter': ';'}).parse(path)

        assert result.entries == [{0: 1, 1: 'alice'}]

    def test_empty_file_raises_clean_no_content_error(self, tmp_path: Path) -> None:
        """A header-only file raises the 'No content data!' error, not a re-wrapped one (B2)."""
        path = _write(tmp_path, 'empty.csv', 'id,name\n')

        with pytest.raises(ParserRuntimeError) as exc_info:
            CsvObjectParser().parse(path)

        message = str(exc_info.value)
        assert 'No content data!' in message
        assert 'An error occurred' not in message

    def test_missing_file_raises_parser_runtime_error(self, tmp_path: Path) -> None:
        """A missing file is wrapped in ParserRuntimeError."""
        with pytest.raises(ParserRuntimeError):
            CsvObjectParser().parse(str(tmp_path / 'nope.csv'))

    def test_default_config_keys(self) -> None:
        """The default config exposes the full FE-facing CSV parser contract."""
        assert CsvObjectParser().get_config() == {
            'delimiter': ',',
            'newline': '',
            'quoteChar': '"',
            'escapeChar': None,
            'header': True,
            'encoding': 'utf-8',
        }

    def test_generate_index_pair(self) -> None:
        """The row helper maps column indices to values."""
        # pylint: disable=protected-access
        assert CsvObjectParser._generate_index_pair(['a', 'b', 'c']) == {0: 'a', 1: 'b', 2: 'c'}
