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
Unit tests for the object-list search stages

The shape is the contract here: an empty term adds nothing and queries nothing; a term becomes the T42
reference rule (`search_reference_match.build_text_term_stages`) with two conditions - the referenced
objects by their field values, the listed object by its public_id, timestamps and field values - every value
compared as a string, the term escaped. What these stages match against real documents is the functional
and integration tiers' question
"""
import re
from typing import Any

import pytest

from cmdb.framework.search import object_list_search
from cmdb.framework.search.object_list_search import (
    build_field_values_expression,
    build_object_search_stages,
    build_own_values_expression,
    build_term_condition,
)
from cmdb.framework.search.search_constants import SEARCH_REGEX_FLAGS
from cmdb.framework.search.search_pattern import escape_search_term
from cmdb.framework.search.search_reference_match import build_reference_rows_condition
# -------------------------------------------------------------------------------------------------------------------- #

TERM: str = 'needle'
ACL_STAGES: list[dict[str, Any]] = [{'$match': {'type_id': {'$nin': [21]}}}]
REFERENCED_IDS: list[int] = [31, 32]


class _StubObjectsManager:
    """Answers the configured ids as public_id documents and records every pipeline it ran."""

    def __init__(self, public_ids: list[int] | None = None) -> None:
        self.public_ids = public_ids or []
        self.pipelines: list[list[dict[str, Any]]] = []

    def aggregate_objects(self, pipeline: list[dict[str, Any]]) -> list[dict[str, int]]:
        """Records the pipeline and answers the ids."""
        self.pipelines.append(pipeline)

        return [{'public_id': public_id} for public_id in self.public_ids]


def _regex_match(condition: dict[str, Any]) -> dict[str, Any]:
    """The `$regexMatch` of a term condition."""
    return condition['$expr']['$anyElementTrue'][0]['$map']['in']['$regexMatch']


def _values(condition: dict[str, Any]) -> dict[str, Any]:
    """The values expression a term condition matches."""
    return condition['$expr']['$anyElementTrue'][0]['$map']['input']

# ---------------------------------------------------- no term ------------------------------------------------------- #

# An empty list is the contract for "no search", so this asserts the exact value rather than
# falsiness - a None slipping through would break the caller that splices the result
# pylint: disable=use-implicit-booleaness-not-comparison
@pytest.mark.parametrize('term', [None, '', '   ', '\t'], ids=repr)
def test_no_term_adds_no_stages_and_runs_no_query(term) -> None:
    """Blank means unsearched: nothing is added and the database is not asked."""
    manager = _StubObjectsManager(REFERENCED_IDS)

    assert build_object_search_stages(term, manager, ACL_STAGES) == []
    assert not manager.pipelines

# ---------------------------------------------------- the rule ------------------------------------------------------ #

def test_the_referenced_objects_are_collected_by_their_field_values_and_the_acl() -> None:
    """One query: the term on a referenced object's field values, then the caller's ACL stages."""
    manager = _StubObjectsManager()

    build_object_search_stages(TERM, manager, ACL_STAGES)

    assert len(manager.pipelines) == 1
    assert manager.pipelines[0][0] == {'$match': build_term_condition(build_field_values_expression(), TERM)}
    assert manager.pipelines[0][1:1 + len(ACL_STAGES)] == ACL_STAGES


def test_no_referenced_match_matches_the_own_values_only() -> None:
    """Nothing referenced matched: one $match on the listed object's own values."""
    stages = build_object_search_stages(TERM, _StubObjectsManager(), ACL_STAGES)

    assert stages == [{'$match': build_term_condition(build_own_values_expression(), TERM)}]


def test_a_referenced_match_is_followed_through_reference_rows_only() -> None:
    """Own values OR a reference row (by stored kind) carrying a matched id - no $lookup, no number-as-reference."""
    stages = build_object_search_stages(TERM, _StubObjectsManager(REFERENCED_IDS), ACL_STAGES)

    assert stages == [{'$match': {'$or': [
        build_term_condition(build_own_values_expression(), TERM),
        build_reference_rows_condition(REFERENCED_IDS),
    ]}}]
    assert '$lookup' not in str(stages)


def test_past_the_cap_the_rule_runs_as_the_join(monkeypatch: pytest.MonkeyPatch) -> None:
    """Too many referenced matches for an id list: the database-side join, with the same two conditions."""
    monkeypatch.setattr('cmdb.framework.search.search_reference_match.MAX_REFERENCED_MATCH_IDS', 1)

    stages = build_object_search_stages(TERM, _StubObjectsManager(REFERENCED_IDS), ACL_STAGES)
    sub_pipeline: list[dict[str, Any]] = stages[0]['$lookup']['pipeline']

    assert {'$match': build_term_condition(build_field_values_expression(), TERM)} in sub_pipeline
    assert all(stage in sub_pipeline for stage in ACL_STAGES)
    assert stages[1]['$match']['$or'][0] == build_term_condition(build_own_values_expression(), TERM)

# ------------------------------------------------- the conditions --------------------------------------------------- #

def test_the_term_is_escaped_case_insensitive_and_trimmed() -> None:
    """A literal: `C++ (EU)` is escaped, the options are the search flags, surrounding blanks go."""
    stages = build_object_search_stages('  C++ (EU)  ', _StubObjectsManager(), [])
    regex_match: dict[str, Any] = _regex_match(stages[0]['$match'])

    assert regex_match['regex'] == escape_search_term('C++ (EU)')
    assert regex_match['options'] == SEARCH_REGEX_FLAGS
    assert re.search(regex_match['regex'], 'C++ (EU)')


def test_the_listed_object_is_searched_by_id_timestamps_and_field_values() -> None:
    """The decided set, each converted to a string - and not the summary line."""
    collected: str = str(build_own_values_expression())

    for path in ['$public_id', '$creation_time', '$last_edit_time', '$fields']:
        assert path in collected
    assert 'summary_line' not in collected
    assert collected.count("'to': 'string'") == 4


def test_a_referenced_object_is_searched_by_its_field_values_only() -> None:
    """Not its public_id or its timestamps - what a user sees of it is its values."""
    collected: str = str(build_field_values_expression())

    assert '$fields' in collected
    for path in ['$public_id', '$creation_time', '$last_edit_time']:
        assert path not in collected


def test_every_field_value_is_converted_to_a_string_and_null_safe() -> None:
    """A number or date value matches as text; an object without fields is an empty list, not null."""
    expression: dict[str, Any] = build_field_values_expression()

    assert expression['$map']['input'] == {'$ifNull': ['$fields', []]}
    assert expression['$map']['in']['$convert']['to'] == 'string'


def test_the_condition_matches_computed_strings_through_expr() -> None:
    """An `$expr` over the given values - a plain `$regex` on fields.value would miss non-strings."""
    values: dict[str, Any] = build_field_values_expression()
    condition: dict[str, Any] = build_term_condition(values, TERM)

    assert set(condition) == {'$expr'}
    assert _values(condition) == values
    assert _regex_match(condition)['input'] == '$$value'


def test_the_module_exports_its_builders() -> None:
    """Consumers import from the module path."""
    assert set(object_list_search.__all__) == {
        'build_field_values_expression', 'build_object_search_stages', 'build_own_values_expression',
        'build_term_condition',
    }
