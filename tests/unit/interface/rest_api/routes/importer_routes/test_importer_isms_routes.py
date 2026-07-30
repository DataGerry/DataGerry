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
Unit tests for the helpers of cmdb.interface.rest_api.routes.importer_routes.importer_isms_routes

DB-free: the managers are MagicMocks and the CSV files are in-memory FileStorage objects. Covers the
cell reader (short rows), the CSV reader (delimiters, BOM, encoding, headers), the risk-type rule
table, the batched reference resolution (ONE query per collection, inserts only for genuinely new
names) and the batched duplicate check with its whole-row equality rule.

Supersedes the former test_importer_isms_helpers.py: its parse_list_of_strings / read_csv_file cases are
carried over here, and its parse_bool cases went with that function (the module now uses the shared
strict cmdb.utils.helpers.parse_import_bool).

The route-level behaviour lives in tests/functional/isms/test_functional_isms_importer_route.py.
"""
from io import BytesIO
from typing import Any
from unittest.mock import MagicMock

import pytest
from werkzeug.datastructures import FileStorage
from werkzeug.exceptions import HTTPException

from cmdb.models.extendable_option_model import OptionType
from cmdb.models.isms_model import RiskType
from cmdb.interface.rest_api.routes.importer_routes.importer_isms_routes import (
    RESULT_CREATED,
    RESULT_EXISTING,
    RESULT_IMPORTED,
    RESULT_INVALID,
    RESULT_TOTAL_ROWS,
    THREAT_HEADERS,
    build_import_result,
    insert_new_items,
    parse_list_of_strings,
    read_csv_file,
    resolve_extendable_options,
    resolve_named_items,
    risk_row_is_valid,
    stripped_cell,
)
# -------------------------------------------------------------------------------------------------------------------- #

THREAT_HEADER_LINE: str = 'name,source,identifier,description'


def _csv_file(text: str, encoding: str = 'utf-8') -> FileStorage:
    """Wraps CSV text in a FileStorage the way the route receives it."""
    return FileStorage(stream=BytesIO(text.encode(encoding)), filename='import.csv')


def _manager(found: list[dict[str, Any]] | None = None, insert_ids: list[int] | None = None) -> MagicMock:
    """A manager whose find returns the given documents and whose insert_item hands out the given ids."""
    manager = MagicMock()
    manager.find.return_value = found or []
    manager.insert_item.side_effect = insert_ids or [901, 902, 903, 904]

    return manager


# -------------------------------------------------------------------------------------------------------------------- #
#                                                   stripped_cell                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
class TestStrippedCell:
    """Reading one cell of a possibly short row."""

    def test_strips_a_value(self) -> None:
        """Surrounding whitespace is removed."""
        assert stripped_cell({'name': '  Threat  '}, 'name') == 'Threat'

    @pytest.mark.parametrize('row', [{}, {'name': None}, {'name': ''}, {'name': '   '}])
    def test_absent_or_empty_is_none(self, row: dict) -> None:
        """A missing key, a None (short row) and an empty cell all read as None."""
        assert stripped_cell(row, 'name') is None

    def test_a_short_row_does_not_raise(self) -> None:
        """The None DictReader fills a short row with used to raise AttributeError."""
        assert stripped_cell({'name': 'R1', 'consequences': None}, 'consequences') is None


# -------------------------------------------------------------------------------------------------------------------- #
#                                                 parse_list_of_strings                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class TestParseListOfStrings:
    """The comma-separated multi-value cells."""

    def test_splits_and_strips(self) -> None:
        """Values are split on commas and trimmed."""
        assert parse_list_of_strings('threats', {'threats': ' A , B '}) == ['A', 'B']

    @pytest.mark.parametrize('raw', [None, '', '  ', ',,,'])
    def test_empty_yields_an_empty_list(self, raw: Any) -> None:
        """Nothing usable in the cell means no values."""
        assert parse_list_of_strings('threats', {'threats': raw}) == []

    def test_drops_empty_segments_between_values(self) -> None:
        """Empty segments between commas are dropped, the real values survive."""
        assert parse_list_of_strings('threats', {'threats': 'a,,  ,b'}) == ['a', 'b']


# -------------------------------------------------------------------------------------------------------------------- #
#                                                    read_csv_file                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
class TestReadCsvFile:
    """Decoding, delimiter detection and the header contract."""

    def test_reads_a_comma_separated_file(self) -> None:
        """The common case - every row is parsed, in order."""
        reader = read_csv_file(_csv_file(f'{THREAT_HEADER_LINE}\nT1,S,ID,D\nT2,,,\n'), THREAT_HEADERS)

        assert [row['name'] for row in reader] == ['T1', 'T2']

    def test_reads_a_semicolon_separated_file(self) -> None:
        """The German-Excel case."""
        reader = read_csv_file(_csv_file('name;source;identifier;description\nT1;S;ID;D\n'), THREAT_HEADERS)

        assert next(reader)['name'] == 'T1'

    def test_accepts_a_utf8_bom(self) -> None:
        """A file saved by Excel keeps a usable first header (it used to become '\\ufeffname')."""
        reader = read_csv_file(_csv_file(f'{THREAT_HEADER_LINE}\nT1,S,ID,D\n', 'utf-8-sig'), THREAT_HEADERS)

        assert next(reader)['name'] == 'T1'

    def test_a_non_utf8_file_aborts_400(self) -> None:
        """A latin-1 file is the caller's problem, not a server error."""
        latin1 = FileStorage(stream=BytesIO('name,source,identifier,description\nCafé,,,\n'.encode('latin-1')),
                             filename='import.csv')

        with pytest.raises(HTTPException) as err:
            read_csv_file(latin1, THREAT_HEADERS)

        assert err.value.code == 400

    def test_missing_headers_abort_400_naming_them(self) -> None:
        """A readable table that lacks a required column names it (a one-column file trips the
        delimiter check first, see the test below)."""
        with pytest.raises(HTTPException) as err:
            read_csv_file(_csv_file('name,identifier\nT1,ID\n'), THREAT_HEADERS)

        assert err.value.code == 400
        assert 'source' in err.value.description

    def test_an_undeterminable_delimiter_aborts_400(self) -> None:
        """A single-column file with neither delimiter cannot be read as a table."""
        with pytest.raises(HTTPException) as err:
            read_csv_file(_csv_file('justonecolumn\nvalue\n'), THREAT_HEADERS)

        assert err.value.code == 400


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  risk_row_is_valid                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
class TestRiskRowIsValid:
    """The per-RiskType rule table."""

    def test_unknown_risk_type_is_invalid(self) -> None:
        """Anything outside the RiskType enum is rejected."""
        assert risk_row_is_valid('BANANA', None, None, [], []) is False

    @pytest.mark.parametrize('consequences, description, threats, vulnerabilities, expected', [
        (None, None, ['T'], ['V'], True),      # the happy shape
        ('c', None, ['T'], ['V'], False),      # consequences do not belong here
        (None, None, [], ['V'], False),        # threats required
        (None, None, ['T'], [], False),        # vulnerabilities required
    ])
    def test_threat_x_vulnerability(self, consequences, description, threats, vulnerabilities, expected) -> None:
        """THREAT_X_VULNERABILITY needs both sides and no consequences."""
        assert risk_row_is_valid(
            RiskType.THREAT_X_VULNERABILITY, consequences, description, threats, vulnerabilities,
        ) is expected

    @pytest.mark.parametrize('consequences, threats, vulnerabilities, expected', [
        (None, ['T'], [], True),
        ('c', ['T'], [], False),
        (None, [], [], False),
        (None, ['T'], ['V'], False),
    ])
    def test_threat(self, consequences, threats, vulnerabilities, expected) -> None:
        """THREAT needs threats only."""
        assert risk_row_is_valid(RiskType.THREAT, consequences, None, threats, vulnerabilities) is expected

    @pytest.mark.parametrize('consequences, description, threats, vulnerabilities, expected', [
        ('c', 'd', [], [], True),
        (None, 'd', [], [], False),
        ('c', None, [], [], False),
        ('c', 'd', ['T'], [], False),
        ('c', 'd', [], ['V'], False),
    ])
    def test_event(self, consequences, description, threats, vulnerabilities, expected) -> None:
        """EVENT needs consequences + description and neither threats nor vulnerabilities."""
        assert risk_row_is_valid(RiskType.EVENT, consequences, description, threats, vulnerabilities) is expected


# -------------------------------------------------------------------------------------------------------------------- #
#                                            resolve_extendable_options                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class TestResolveExtendableOptions:
    """Batched option resolution."""

    def test_no_values_reads_nothing(self) -> None:
        """An import referencing no option pays no query."""
        manager = _manager()

        assert resolve_extendable_options(set(), manager, OptionType.CONTROL_MEASURE) == {}
        manager.find.assert_not_called()

    def test_existing_options_are_reused_in_one_query(self) -> None:
        """All values are resolved with a single $in query and nothing is inserted."""
        manager = _manager(found=[{'value': 'A', 'public_id': 1}, {'value': 'B', 'public_id': 2}])

        result = resolve_extendable_options({'A', 'B'}, manager, OptionType.CONTROL_MEASURE)

        assert result == {'A': 1, 'B': 2}
        manager.find.assert_called_once()
        criteria = manager.find.call_args.kwargs['criteria']
        assert criteria['value']['$in'] == ['A', 'B']
        assert criteria['option_type'] == OptionType.CONTROL_MEASURE
        manager.insert_item.assert_not_called()

    def test_missing_options_are_created_once_each(self) -> None:
        """Only the unknown values cost an insert."""
        manager = _manager(found=[{'value': 'A', 'public_id': 1}], insert_ids=[7])

        result = resolve_extendable_options({'A', 'B'}, manager, OptionType.THREAT_VULNERABILITY)

        assert result == {'A': 1, 'B': 7}
        manager.insert_item.assert_called_once_with(
            {'value': 'B', 'option_type': OptionType.THREAT_VULNERABILITY, 'predefined': False},
        )


# -------------------------------------------------------------------------------------------------------------------- #
#                                              resolve_named_items                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
class TestResolveNamedItems:
    """Batched threat / vulnerability / protection-goal resolution."""

    def test_no_names_reads_nothing(self) -> None:
        """No references, no query."""
        manager = _manager()

        assert resolve_named_items(set(), manager, {}) == {}
        manager.find.assert_not_called()

    def test_existing_names_are_reused_in_one_query(self) -> None:
        """One $in query resolves the whole batch."""
        manager = _manager(found=[{'name': 'T1', 'public_id': 5}])

        assert resolve_named_items({'T1'}, manager, {}) == {'T1': 5}
        manager.find.assert_called_once_with(criteria={'name': {'$in': ['T1']}})
        manager.insert_item.assert_not_called()

    def test_missing_names_are_created_with_the_given_defaults(self) -> None:
        """A name nobody knows becomes a new entity carrying the caller's defaults."""
        manager = _manager(insert_ids=[11])

        result = resolve_named_items({'New'}, manager, {'predefined': False})

        assert result == {'New': 11}
        manager.insert_item.assert_called_once_with({'name': 'New', 'predefined': False})


# -------------------------------------------------------------------------------------------------------------------- #
#                                                insert_new_items                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
class TestInsertNewItems:
    """The batched duplicate check and its whole-row equality rule."""

    def test_no_candidates_writes_nothing(self) -> None:
        """An import whose every row was rejected performs no query at all."""
        manager = _manager()

        assert insert_new_items([], manager, 'name') == (0, 0)
        manager.find.assert_not_called()

    def test_a_new_candidate_is_inserted(self) -> None:
        """Nothing stored under that name means a create."""
        manager = _manager()

        assert insert_new_items([{'name': 'T1', 'source': None}], manager, 'name') == (1, 0)
        manager.insert_item.assert_called_once()

    def test_an_identical_candidate_counts_as_existing(self) -> None:
        """Every field the import writes matches, so the row is a duplicate."""
        manager = _manager(found=[{'public_id': 1, 'name': 'T1', 'source': None, 'description': None}])

        assert insert_new_items([{'name': 'T1', 'source': None, 'description': None}], manager, 'name') == (0, 1)
        manager.insert_item.assert_not_called()

    def test_a_row_differing_in_one_field_is_a_new_entity(self) -> None:
        """Whole-row equality is the intended duplicate rule (same name, other description = new)."""
        manager = _manager(found=[{'public_id': 1, 'name': 'T1', 'description': 'old'}])

        assert insert_new_items([{'name': 'T1', 'description': 'new'}], manager, 'name') == (1, 0)

    def test_the_identity_values_are_resolved_in_one_query(self) -> None:
        """One $in query pre-selects the comparison candidates for the whole batch."""
        manager = _manager()

        insert_new_items([{'name': 'A'}, {'name': 'B'}], manager, 'name')

        manager.find.assert_called_once_with(criteria={'name': {'$in': ['A', 'B']}})

    def test_the_identity_field_can_be_the_title(self) -> None:
        """Control measures are identified by 'title'."""
        manager = _manager()

        insert_new_items([{'title': 'C1'}], manager, 'title')

        manager.find.assert_called_once_with(criteria={'title': {'$in': ['C1']}})


# -------------------------------------------------------------------------------------------------------------------- #
#                                              build_import_result                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
class TestBuildImportResult:
    """The per-target result dict."""

    def test_reports_every_counter(self) -> None:
        """imported_objects is created + existing; total_rows counts everything that was read."""
        result = build_import_result(total_rows=5, created=2, existing=1, invalid=[{'name': None}])

        assert result == {
            RESULT_TOTAL_ROWS: 5,
            RESULT_IMPORTED: 3,
            RESULT_CREATED: 2,
            RESULT_EXISTING: 1,
            RESULT_INVALID: [{'name': None}],
        }
