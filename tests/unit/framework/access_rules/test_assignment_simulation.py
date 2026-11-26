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
Unit tests for the pure half of the assignment simulation (phase 11): the filter combinators, the role clause, the one
aggregation's shape, reading its facets, and every warning; ``newly_restricted`` of the Type states
"""
from typing import Any

import pytest

from cmdb.framework.access_rules import TypeAccessState, newly_restricted
from cmdb.framework.access_rules.assignment_simulation import (
    all_of,
    any_of,
    condition_warnings,
    count_warnings,
    facet_by_type,
    facet_count,
    facet_sample_ids,
    member_facet,
    role_clause,
    simulation_pipeline,
)
from cmdb.framework.access_rules.assignment_simulation_constants import SAMPLE_LIMIT
from cmdb.framework.scope_compiler import ScopeField
# -------------------------------------------------------------------------------------------------------------------- #

NOTHING: dict[str, Any] = {'type_id': {'$in': []}}
A: dict[str, Any] = {'a': 1}
B: dict[str, Any] = {'b': 2}
FIELDS: dict[str, ScopeField] = {'host': ScopeField('text'), 'note': ScopeField('textarea'),
                                 'size': ScopeField('number'), 'owner': ScopeField('person')}


def test_all_of() -> None:
    """Empty parts left out; one part itself; none matches everything"""
    assert (all_of(), all_of({}, A), all_of(A, {}, B)) == ({}, A, {'$and': [A, B]})


def test_any_of() -> None:
    """No part matches nothing; an empty part matches everything; one part itself"""
    assert (any_of([]), any_of([A, {}]), any_of([A]), any_of([A, B])) == (NOTHING, {}, A, {'$or': [A, B]})


@pytest.mark.parametrize('role, expected', [
    ({'types': '*'}, {}), ({'types': [3, 1]}, {'type_id': {'$in': [1, 3]}}), ({}, {'type_id': {'$in': []}}),
], ids=['every-type', 'listed', 'none'])
def test_role_clause(role: dict[str, Any], expected: dict[str, Any]) -> None:
    """Every Type matches every object"""
    assert role_clause(role) == expected


def test_the_pipeline_without_a_change() -> None:
    """The view and the role in front; by Type, samples, role total; one facet per member"""
    stages = simulation_pipeline(A, [{'type_id': {'$in': [1]}}], B, None, {7: B})

    assert stages[0] == {'$match': {'$and': [A, {'type_id': {'$in': [1]}}]}}
    facets = stages[1]['$facet']
    assert sorted(facets) == ['by_type', member_facet(7), 'role_total', 'samples']
    assert facets['samples'][2] == {'$limit': SAMPLE_LIMIT}
    assert facets[member_facet(7)] == [{'$match': B}, {'$count': 'count'}]


def test_the_pipeline_of_a_change() -> None:
    """Gained = new and not old, lost = old and not new; both roles' Types read"""
    stages = simulation_pipeline({}, [A, B], {'n': 1}, {'o': 1}, {})

    assert stages[0] == {'$match': {'$or': [A, B]}}
    facets = stages[1]['$facet']
    assert facets['gained'][0] == {'$match': {'$and': [{'n': 1}, {'$nor': [{'o': 1}]}]}}
    assert facets['lost'][0] == {'$match': {'$and': [{'o': 1}, {'$nor': [{'n': 1}]}]}}


def test_reading_the_facets() -> None:
    """A count facet without a document is 0; the Types ascending"""
    result = {'by_type': [{'_id': 9, 'count': 2}, {'_id': 3, 'count': 5}], 'gained': [{'count': 4}], 'lost': [],
              'samples': [{'public_id': 1, 'type_id': 3}]}

    assert (facet_count(result, 'gained'), facet_count(result, 'lost'), facet_count(result, 'gone')) == (4, 0, 0)
    assert facet_by_type(result) == [{'type_id': 3, 'count': 5}, {'type_id': 9, 'count': 2}]
    assert facet_sample_ids(result, 'samples') == [{'public_id': 1, 'type_id': 3}]


def test_the_condition_warnings() -> None:
    """contains on a text kind; negations and emptiness; contains on a person is indexed"""
    scope = [{'field': 'host', 'op': 'contains', 'value': 'x'}, {'field': 'note', 'op': 'contains', 'value': 'y'},
             {'field': 'owner', 'op': 'contains', 'value': 3}, {'field': 'size', 'op': 'not_in', 'value': [1]},
             {'field': 'host', 'op': 'is_empty'}, {'within': 4}]

    warnings = condition_warnings(scope, FIELDS)

    assert [warning['code'] for warning in warnings] == ['unindexed_contains', 'poorly_indexed']
    assert "['host', 'note']" in warnings[0]['message'] and "['host', 'size']" in warnings[1]['message']
    assert not condition_warnings('*', FIELDS)


@pytest.mark.parametrize('scope, total, role_total, codes', [
    (A, 0, 5, ['empty']), ([A], 5, 5, ['every_object']), ('*', 5, 5, []), ([A], 3, 5, []),
], ids=['empty', 'every-object', 'star-is-meant-to', 'some'])
def test_the_count_warnings(scope: Any, total: int, role_total: int, codes: list[str]) -> None:
    """Empty, or every object without '*'"""
    assert [warning['code'] for warning in count_warnings(scope, total, role_total, [], [])] == codes


def test_the_member_and_type_warnings() -> None:
    """Named, ascending"""
    warnings = count_warnings([A], 1, 5, [9, 3], [7])

    assert [warning['code'] for warning in warnings] == ['unresolved_token', 'newly_restricted']
    assert '[3, 9]' in warnings[0]['message'] and '[7]' in warnings[1]['message']


def test_newly_restricted() -> None:
    """Open before, restricted after - viewable or locked"""
    before = {1: TypeAccessState.OPEN, 2: TypeAccessState.OPEN, 3: TypeAccessState.VIEWABLE, 4: TypeAccessState.OPEN}
    after = {1: TypeAccessState.VIEWABLE, 2: TypeAccessState.OPEN, 3: TypeAccessState.LOCKED,
             4: TypeAccessState.LOCKED}

    assert newly_restricted(before, after) == [1, 4]
