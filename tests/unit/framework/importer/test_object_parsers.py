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
parsed response shape, auto-casting + index-pairing of CSV rows, the resolution of a header column to
its identifier (a plain export header and a decorated import-template header both work, decided per
column), honouring the header/delimiter
config, and the shared ParserRuntimeError failure contract (both parsers wrap read/parse errors;
the CSV 'No content data!' guard is not re-wrapped by the broad handler).
"""
from pathlib import Path

import pytest

from cmdb.framework.importer.parser.json_object_parser import JsonObjectParser
from cmdb.framework.importer.parser.csv_object_parser import (
    CsvObjectParser,
    extract_column_identifier,
    normalize_csv_header,
)
from cmdb.framework.importer.responses.json_object_parser_response import JsonObjectParserResponse
from cmdb.framework.importer.responses.csv_object_parser_response import CsvObjectParserResponse
from cmdb.errors.importer import ParserNoContentError, ParserRuntimeError
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

    def test_an_empty_list_raises_the_no_content_error(self, tmp_path: Path) -> None:
        """An empty top-level list holds nothing to import - reported exactly like a header-only CSV,
        so both formats answer the same 400 instead of JSON silently importing zero objects."""
        path = _write(tmp_path, 'empty.json', '[]')

        with pytest.raises(ParserNoContentError) as exc_info:
            JsonObjectParser().parse(path)

        assert 'No content data!' in str(exc_info.value)

    def test_non_list_top_level_raises_parser_runtime_error(self, tmp_path: Path) -> None:
        """A top-level JSON object (not a list) is rejected so count stays the object count."""
        path = _write(tmp_path, 'dict.json', '{"x": 1}')

        with pytest.raises(ParserRuntimeError):
            JsonObjectParser().parse(path)

    def test_missing_file_raises_parser_runtime_error(self, tmp_path: Path) -> None:
        """A missing file is wrapped in ParserRuntimeError rather than a raw OSError."""
        with pytest.raises(ParserRuntimeError):
            JsonObjectParser().parse(str(tmp_path / 'does_not_exist.json'))

    def test_default_config_keys(self) -> None:
        """The default config exposes the FE-facing indent/encoding keys."""
        assert JsonObjectParser().get_config() == {'encoding': 'UTF-8'}


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
        """A header-only file raises the precise no-content error, not a re-wrapped one (B2).

        The type matters: the routes answer it with 'the file has no data rows' instead of blaming the
        parser configuration, so it must stay distinguishable from a plain ParserRuntimeError.
        """
        path = _write(tmp_path, 'empty.csv', 'id,name\n')

        with pytest.raises(ParserNoContentError) as exc_info:
            CsvObjectParser().parse(path)

        message = str(exc_info.value)
        assert 'No content data!' in message
        assert 'An error occurred' not in message

    def test_an_undecodable_file_is_a_plain_parser_error(self, tmp_path: Path) -> None:
        """A real parsing failure (here: the wrong encoding) stays a plain ParserRuntimeError.

        That is the case the generic 'could not parse with the given configuration' answer is for, so it
        must NOT be reported as an empty file.
        """
        path = tmp_path / 'latin1.csv'
        path.write_bytes(b'id,name\n1,caf\xe9\n')

        with pytest.raises(ParserRuntimeError) as exc_info:
            CsvObjectParser().parse(str(path))

        assert not isinstance(exc_info.value, ParserNoContentError)
        assert 'An error occurred' in str(exc_info.value)

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


# -------------------------------------------------------------------------------------------------------------------- #
#                                        CSV header identifier resolution                                             #
# -------------------------------------------------------------------------------------------------------------------- #

class TestExtractColumnIdentifier:
    """One header column resolves to the identifier the import maps it by."""

    @pytest.mark.parametrize('header_cell,expected', [
        ('public_id', 'public_id'),
        ('dg-name', 'dg-name'),
        ('Public ID [public_id]', 'public_id'),
        ('Hostname [hostname]', 'hostname'),
        ('Port [MDS-Network Interfaces] [port]', 'port'),
        ('[port]', 'port'),
        ('Padded [ port ]', 'port'),
        ('Trailing [port]   ', 'port'),
    ], ids=['plain', 'plain-dashed', 'identity', 'labelled', 'mds', 'bare-brackets', 'padded', 'trailing-space'])
    def test_resolves_both_notations(self, header_cell: str, expected: str) -> None:
        """A trailing bracketed group is the identifier; anything else already is one."""
        assert extract_column_identifier(header_cell) == expected

    @pytest.mark.parametrize('header_cell', [
        'Label []',
        'Weird [x] label',
        '',
        'ends with bracket]',
    ], ids=['empty-group', 'group-not-at-end', 'empty-cell', 'unbalanced'])
    def test_keeps_a_cell_that_names_nothing(self, header_cell: str) -> None:
        """A cell with no usable trailing group stands as it is - never an empty column key."""
        assert extract_column_identifier(header_cell) == header_cell

    def test_a_non_string_cell_is_returned_untouched(self) -> None:
        """A malformed header entry does not raise on the way through."""
        assert extract_column_identifier(None) is None


class TestNormalizeCsvHeader:
    """The whole header row resolves column for column, order preserved."""

    def test_resolves_every_column_in_order(self) -> None:
        """A mixed header (some columns decorated, some not) resolves entry by entry."""
        header = ['public_id', 'Active [active]', 'Port [MDS-Ifaces] [port]']

        assert normalize_csv_header(header) == ['public_id', 'active', 'port']

    @pytest.mark.parametrize('header', [None, []], ids=['none', 'empty'])
    def test_no_header_yields_an_empty_list(self, header: list | None) -> None:
        """A file parsed without a header row resolves to nothing."""
        assert normalize_csv_header(header) == []


class TestCsvObjectParserHeaderNotations:
    """The parser hands on resolved identifiers plus the file's original header line."""

    def test_a_plain_header_is_unchanged_and_mirrored_as_raw(self, tmp_path: Path) -> None:
        """An export-style file behaves exactly as before: header == raw_header == the file's names."""
        path = _write(tmp_path, 'plain.csv', 'public_id,dg-name\n1,alice\n')

        result = CsvObjectParser().parse(path)

        assert result.get_header_list() == ['public_id', 'dg-name']
        assert result.get_raw_header_list() == ['public_id', 'dg-name']

    def test_a_template_header_resolves_to_the_identifiers(self, tmp_path: Path) -> None:
        """A decorated (import-template) header is handed on as the plain field names."""
        path = _write(
            tmp_path,
            'template.csv',
            'Public ID [public_id],Name [dg-name],Port [MDS-Ifaces] [port]\n1,alice,80\n',
        )

        result = CsvObjectParser().parse(path)

        assert result.get_header_list() == ['public_id', 'dg-name', 'port']

    def test_a_template_header_keeps_its_labels_in_raw_header(self, tmp_path: Path) -> None:
        """The labels survive for display, so a client can show them next to the preview."""
        path = _write(tmp_path, 'template.csv', 'Public ID [public_id],Name [dg-name]\n1,alice\n')

        result = CsvObjectParser().parse(path)

        assert result.get_raw_header_list() == ['Public ID [public_id]', 'Name [dg-name]']

    def test_the_rows_are_untouched_by_the_resolution(self, tmp_path: Path) -> None:
        """Only the header is resolved - the rows stay index-keyed and auto-cast as before."""
        path = _write(tmp_path, 'template.csv', 'Public ID [public_id],Name [dg-name]\n1,alice\n')

        result = CsvObjectParser().parse(path)

        assert result.entries == [{0: 1, 1: 'alice'}]

    def test_without_a_header_row_both_lists_stay_empty(self, tmp_path: Path) -> None:
        """header=False consumes no row, so there is nothing to resolve."""
        result = CsvObjectParser({'header': False}).parse(_write(tmp_path, 'n.csv', '1,alice\n'))

        assert result.get_header_list() == []
        assert result.get_raw_header_list() == []
