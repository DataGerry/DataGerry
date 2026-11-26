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
Unit tests for scope_compiler.scope_grammar - the shape of a scope (phase 9 step 1) and its canonical form

Pinned: '*' and well-formed lists pass; every shape problem is named (not a list, empty, over the cap, not a block,
unknown keys, no field, unknown operator, a value where none is taken / missing, list and pair arity, a document or
non-finite number as a value, a text over the cap, a bad relative date); the canonical form sorts the conditions and
the in / not_in values (each once) and keeps a between pair in order
"""
from typing import Any

import pytest

from cmdb.framework.scope_compiler import (
    MAX_LIST_VALUES,
    MAX_SCOPE_BLOCKS,
    MAX_TEXT_LENGTH,
    ScopeMessage,
    canonical_blocks,
    is_relative_date,
    scope_shape_problems,
)
# -------------------------------------------------------------------------------------------------------------------- #

BLOCK: dict[str, Any] = {'field': 'status', 'op': 'equals', 'value': 'active'}


@pytest.mark.parametrize('scope', [
    '*',
    [BLOCK],
    [{'field': 'f', 'op': 'exists'}, {'field': 'f', 'op': 'in', 'value': ['a', 1, 2.5, True]}],
    [{'field': 'd', 'op': 'between', 'value': [{'days_ago': 30}, '2026-01-01']}],
    [BLOCK] * MAX_SCOPE_BLOCKS,
], ids=['every-object', 'one', 'no-value-and-list', 'relative-pair', 'at-the-cap'])
def test_well_formed_scopes_pass(scope: Any) -> None:
    """No problem"""
    assert not scope_shape_problems(scope)


@pytest.mark.parametrize('scope, expected', [
    ({'field': 'f'}, [ScopeMessage.NOT_A_LIST.value]),
    ('all', [ScopeMessage.NOT_A_LIST.value]),
    ([], [ScopeMessage.EMPTY.value]),
    ([BLOCK] * (MAX_SCOPE_BLOCKS + 1),
     [ScopeMessage.TOO_MANY_BLOCKS.value.format(limit=MAX_SCOPE_BLOCKS, count=MAX_SCOPE_BLOCKS + 1)]),
], ids=['a-document', 'a-word', 'empty', 'over-the-cap'])
def test_the_scope_itself(scope: Any, expected: list[str]) -> None:
    """'*' or a list of 1 to 50"""
    assert scope_shape_problems(scope) == expected


@pytest.mark.parametrize('block, expected', [
    ('x', ScopeMessage.NOT_A_BLOCK.value.format(position=1)),
    ({**BLOCK, '$where': 'x'}, ScopeMessage.UNKNOWN_KEYS.value.format(position=1, keys=['$where'])),
    ({'op': 'exists'}, ScopeMessage.BAD_FIELD.value.format(position=1, limit=255)),
    ({'field': '  ', 'op': 'exists'}, ScopeMessage.BAD_FIELD.value.format(position=1, limit=255)),
    ({'field': {'$ne': 1}, 'op': 'exists'}, ScopeMessage.BAD_FIELD.value.format(position=1, limit=255)),
    ({'field': 'f', 'op': 'regex', 'value': '.*'}, ScopeMessage.UNKNOWN_OPERATOR.value.format(position=1, op='regex')),
    ({'field': 'f', 'op': 'exists', 'value': 1}, ScopeMessage.VALUE_NOT_ALLOWED.value.format(position=1, op='exists')),
    ({'field': 'f', 'op': 'equals'}, ScopeMessage.VALUE_MISSING.value.format(position=1, op='equals')),
    ({'field': 'f', 'op': 'in', 'value': []},
     ScopeMessage.NOT_A_LIST_VALUE.value.format(position=1, op='in', limit=MAX_LIST_VALUES)),
    ({'field': 'f', 'op': 'in', 'value': 'a'},
     ScopeMessage.NOT_A_LIST_VALUE.value.format(position=1, op='in', limit=MAX_LIST_VALUES)),
    ({'field': 'f', 'op': 'between', 'value': [1]}, ScopeMessage.NOT_A_PAIR.value.format(position=1)),
    ({'field': 'f', 'op': 'equals', 'value': {'$gt': ''}},
     ScopeMessage.NOT_A_SCALAR.value.format(position=1, value='{"$gt": ""}')),
    ({'field': 'f', 'op': 'equals', 'value': None}, ScopeMessage.NOT_A_SCALAR.value.format(position=1, value='null')),
    ({'field': 'f', 'op': 'equals', 'value': float('nan')},
     ScopeMessage.NOT_A_SCALAR.value.format(position=1, value=float('nan'))),
    ({'field': 'f', 'op': 'equals', 'value': 'x' * (MAX_TEXT_LENGTH + 1)},
     ScopeMessage.TEXT_TOO_LONG.value.format(position=1, limit=MAX_TEXT_LENGTH)),
    ({'field': 'f', 'op': 'lt', 'value': {'days_ago': -1}},
     ScopeMessage.BAD_RELATIVE_DATE.value.format(position=1, limit=36500)),
    ({'field': 'f', 'op': 'lt', 'value': {'days_ago': True}},
     ScopeMessage.BAD_RELATIVE_DATE.value.format(position=1, limit=36500)),
], ids=['not-a-block', 'unknown-key', 'no-field', 'blank-field', 'field-document', 'unknown-op', 'value-not-taken',
        'value-missing', 'empty-list', 'not-a-list', 'not-a-pair', 'operator-document', 'null', 'nan', 'long-text',
        'negative-days', 'boolean-days'])
def test_each_condition_problem(block: Any, expected: str) -> None:
    """Named with its position"""
    assert scope_shape_problems([block]) == [expected]


def test_every_condition_is_judged_and_named_by_position() -> None:
    """Not only the first"""
    problems = scope_shape_problems([BLOCK, {'field': 'f', 'op': 'nope'}, {'field': 'f', 'op': 'equals'}])

    assert problems == [ScopeMessage.UNKNOWN_OPERATOR.value.format(position=2, op='nope'),
                        ScopeMessage.VALUE_MISSING.value.format(position=3, op='equals')]


def test_a_list_value_problem_is_named_once() -> None:
    """Three bad values, one message"""
    assert len(scope_shape_problems([{'field': 'f', 'op': 'in', 'value': [None, None, {}]}])) == 2


class TestCanonicalBlocks:
    """One spelling per scope"""

    def test_conditions_and_in_values_are_sorted_each_once(self) -> None:
        """Key order and value order do not matter"""
        one = canonical_blocks([{'value': [3, 1, 3], 'op': 'in', 'field': 'n'}, {'op': 'exists', 'field': 'a'}])
        other = canonical_blocks([{'field': 'a', 'op': 'exists'}, {'field': 'n', 'op': 'in', 'value': [1, 3]}])

        assert one == other == [{'field': 'a', 'op': 'exists'}, {'field': 'n', 'op': 'in', 'value': [1, 3]}]

    def test_a_between_pair_keeps_its_order(self) -> None:
        """Lower first, as sent"""
        assert canonical_blocks([{'field': 'n', 'op': 'between', 'value': [5, 1]}])[0]['value'] == [5, 1]

    def test_values_of_different_kinds_stay_apart(self) -> None:
        """1 and '1' are two values"""
        assert len(canonical_blocks([{'field': 'f', 'op': 'not_in', 'value': [1, '1', 1]}])[0]['value']) == 2

    def test_numbers_sort_by_value_and_one_value_is_kept_once(self) -> None:
        """16 after 4 (not by spelling); 4 and 4.0 are one value - the first spelling kept; texts by spelling"""
        assert canonical_blocks([{'field': 'f', 'op': 'in', 'value': [16, 'b', 4, 4.0, 'a', 10]}])[0]['value'] == [
            4, 10, 16, 'a', 'b']


@pytest.mark.parametrize('value, expected', [({'days_ago': 3}, True), ('2026-01-01', False), (3, False)])
def test_is_relative_date(value: Any, expected: bool) -> None:
    """Only the relative form"""
    assert is_relative_date(value) is expected
