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
Unit tests for scope_compiler.field_comparisons - the MongoDB filter of a cast scope (phase 9 step 2)

The shapes per operator; whether MongoDB matches them as intended is pinned against real objects by
``tests/integration/framework/test_integration_scope_compiler.py``. Pinned here: an $and of one $elemMatch per
condition; empty handling (is_empty also a missing entry, exists, negations excluding empty values); contains by kind;
starts_with anchored and escaped; dates day-granular, a relative date counted back from the evaluation day (UTC), a
between pair ordered when resolved
"""
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from cmdb.framework.scope_compiler import (
    EMPTY_VALUES,
    MULTIPLE_PERSON_KIND,
    ScopeField,
    compile_condition,
    compile_scope,
    resolve_date,
)
# -------------------------------------------------------------------------------------------------------------------- #

NOW: datetime = datetime(2026, 11, 25, 15, 30, tzinfo=timezone.utc)
DAY: datetime = datetime(2026, 11, 1)
DAY_END: datetime = datetime(2026, 11, 1, 23, 59, 59, 999999)
TEXT: ScopeField = ScopeField('text')
NUMBER: ScopeField = ScopeField('number')
DATE: ScopeField = ScopeField('date')


def _match(value_fragment: dict[str, Any], name: str = 'f') -> dict[str, Any]:
    """The expected entry match"""
    return {'fields': {'$elemMatch': {'name': name, 'value': value_fragment}}}


def _compiled(field: ScopeField, op: str, value: Any = None) -> dict[str, Any]:
    """One condition on 'f', compiled"""
    block: dict[str, Any] = {'field': 'f', 'op': op, **({} if value is None else {'value': value})}

    return compile_condition(block, field, NOW)


@pytest.mark.parametrize('field, op, value, expected', [
    (TEXT, 'equals', 'x', _match({'$eq': 'x'})),
    (TEXT, 'not_equals', 'x', _match({'$nin': ['x', *EMPTY_VALUES], '$type': 'string'})),
    (NUMBER, 'in', [1, 2], _match({'$in': [1, 2]})),
    (NUMBER, 'not_in', [1], _match({'$nin': [1, *EMPTY_VALUES], '$type': 'number'})),
    (TEXT, 'contains', 'a.b', _match({'$regex': 'a\\.b'})),
    (ScopeField(MULTIPLE_PERSON_KIND), 'contains', 9, _match({'$eq': 9})),
    (TEXT, 'starts_with', 'a+', _match({'$regex': '^a\\+'})),
    (NUMBER, 'lt', 3, _match({'$lt': 3})),
    (NUMBER, 'gte', 3, _match({'$gte': 3})),
    (NUMBER, 'between', [1, 5], _match({'$gte': 1, '$lte': 5})),
    (TEXT, 'exists', None, _match({'$nin': EMPTY_VALUES})),
    (TEXT, 'is_empty', None, {'$or': [_match({'$in': EMPTY_VALUES}),
                                      {'fields': {'$not': {'$elemMatch': {'name': 'f'}}}}]}),
], ids=['equals', 'not-equals', 'in', 'not-in', 'contains-text', 'contains-member', 'starts-with', 'lt', 'gte',
        'between', 'exists', 'is-empty'])
def test_the_fragment_per_operator(field: ScopeField, op: str, value: Any, expected: dict[str, Any]) -> None:
    """One $elemMatch on the named entry - is_empty also reaches an object without it"""
    assert _compiled(field, op, value) == expected


@pytest.mark.parametrize('op, value, expected', [
    ('equals', '2026-11-01', {'$gte': DAY, '$lte': DAY_END}),
    ('not_equals', '2026-11-01', {'$not': {'$gte': DAY, '$lte': DAY_END}, '$type': 'date'}),
    ('lt', '2026-11-01', {'$lt': DAY}),
    ('lte', '2026-11-01', {'$lte': DAY_END}),
    ('gt', '2026-11-01', {'$gt': DAY_END}),
    ('gte', '2026-11-01', {'$gte': DAY}),
    ('lt', {'days_ago': 24}, {'$lt': DAY}),
    ('between', [{'days_ago': 0}, '2026-11-01'], {'$gte': DAY, '$lte': datetime(2026, 11, 25, 23, 59, 59, 999999)}),
], ids=['equals', 'not-equals', 'lt', 'lte', 'gt', 'gte', 'relative', 'between-ordered'])
def test_dates_are_day_granular(op: str, value: Any, expected: dict[str, Any]) -> None:
    """The whole day where the comparison needs it"""
    assert _compiled(DATE, op, value) == _match(expected)


def test_a_scope_is_the_and_of_its_conditions() -> None:
    """In order, each on its own field"""
    scope = [{'field': 'a', 'op': 'exists'}, {'field': 'b', 'op': 'equals', 'value': 1}]

    assert compile_scope(scope, {'a': TEXT, 'b': NUMBER}, NOW) == {
        '$and': [_match({'$nin': EMPTY_VALUES}, 'a'), _match({'$eq': 1}, 'b')]}


@pytest.mark.parametrize('value, expected', [
    ('2026-02-03', datetime(2026, 2, 3)),
    ({'days_ago': 0}, datetime(2026, 11, 25)),
    ({'days_ago': 30}, datetime(2026, 10, 26)),
], ids=['absolute', 'today', 'thirty-days'])
def test_resolve_date(value: Any, expected: datetime) -> None:
    """Naive UTC midnight"""
    assert resolve_date(value, NOW) == expected


def test_a_relative_date_counts_from_the_utc_day() -> None:
    """00:30 in Berlin is still the previous day in UTC"""
    berlin = timezone(timedelta(hours=1))

    assert resolve_date({'days_ago': 0}, datetime(2026, 11, 26, 0, 30, tzinfo=berlin)) == datetime(2026, 11, 25)
