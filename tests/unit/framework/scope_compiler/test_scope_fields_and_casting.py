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
Unit tests for scope_compiler.scope_fields and scope_casting - a field resolved across the role's Types and each value
cast to it (phase 9 step 3)

Pinned: the views of a Type (kind, a multi-value person selector, select options, multi-data-section fields; from a
CmdbType's lists and from a stored document); the carriers rule (none, disagreeing kinds, options united); the casting
per kind and operator - operators a kind does not take, password / location / ref-section / MDS refused, numeric and
id texts read, booleans never numbers, dates and relative dates, options, the between order - every problem named
"""
from typing import Any

import pytest

from cmdb.framework.scope_compiler import (
    MULTIPLE_PERSON_KIND,
    ScopeField,
    ScopeMessage,
    cast_scope,
    field_views,
    field_views_of_document,
    resolve_scope_fields,
)
# -------------------------------------------------------------------------------------------------------------------- #

FIELDS: list[dict[str, Any]] = [
    {'name': 'host', 'type': 'text'},
    {'name': 'state', 'type': 'select', 'options': [{'name': 'on', 'label': 'On'}, {'name': 'off', 'label': 'Off'}]},
    {'name': 'owner', 'type': 'person', 'multiple': False},
    {'name': 'team', 'type': 'person', 'multiple': True},
    {'name': 'port', 'type': 'text'},
    'junk',
    {'name': 7, 'type': 'text'},
]
TEXT: ScopeField = ScopeField('text')
NUMBER: ScopeField = ScopeField('number')
DATE: ScopeField = ScopeField('date')
SELECT: ScopeField = ScopeField('select', frozenset({'on', 'off'}))


def _cast(field: ScopeField, op: str, value: Any = None, has_value: bool = True) -> tuple[list[dict[str, Any]],
                                                                                     list[str]]:
    """Casts one condition on the field 'f'"""
    block: dict[str, Any] = {'field': 'f', 'op': op, **({'value': value} if has_value else {})}

    return cast_scope([block], {'f': field})


class TestFieldViews:
    """A Type's fields as a condition sees them"""

    def test_the_views_of_a_types_lists(self) -> None:
        """Kinds, the multi-value person kind, options, the MDS mark; junk entries left out"""
        views = field_views(FIELDS, ['port'])

        assert views == {
            'host': ScopeField('text'), 'state': ScopeField('select', frozenset({'on', 'off'})),
            'owner': ScopeField('person'), 'team': ScopeField(MULTIPLE_PERSON_KIND),
            'port': ScopeField('text', in_mds=True),
        }

    def test_the_views_of_a_stored_document(self) -> None:
        """The multi-data sections read from render_meta"""
        document = {'fields': FIELDS[:1] + FIELDS[4:5], 'render_meta': {'sections': [
            {'type': 'section', 'name': 'a', 'fields': ['host']},
            {'type': 'multi-data-section', 'name': 'b', 'fields': ['port']}]}}

        assert field_views_of_document(document) == {'host': TEXT, 'port': ScopeField('text', in_mds=True)}


class TestResolveScopeFields:
    """The carriers must agree"""

    def test_the_carriers_resolve_and_options_unite(self) -> None:
        """A Type without the field is fine"""
        fields, problems = resolve_scope_fields(['state'], [
            {'state': ScopeField('select', frozenset({'on'}))}, {}, {'state': ScopeField('select', frozenset({'x'}))}])

        assert (fields, problems) == ({'state': ScopeField('select', frozenset({'on', 'x'}))}, [])

    def test_no_carrier_and_disagreeing_kinds_are_named(self) -> None:
        """Both left out of the resolved fields"""
        fields, problems = resolve_scope_fields(['gone', 'mixed', 'gone'], [{'mixed': TEXT}, {'mixed': NUMBER}])

        assert not fields
        assert problems == [ScopeMessage.NO_CARRIER.value.format(field='gone'),
                            ScopeMessage.KINDS_DISAGREE.value.format(field='mixed', kinds=['number', 'text'])]

    def test_one_carrier_in_a_multi_data_section_marks_it(self) -> None:
        """Refused by the casting"""
        fields, _ = resolve_scope_fields(['f'], [{'f': TEXT}, {'f': ScopeField('text', in_mds=True)}])

        assert fields['f'].in_mds


class TestCastScope:
    """Each value to its field's stored type"""

    @pytest.mark.parametrize('field, op, value, cast', [
        (TEXT, 'equals', 'x', 'x'),
        (TEXT, 'starts_with', 'ab', 'ab'),
        (NUMBER, 'gt', '12', 12),
        (NUMBER, 'lte', '1.5', 1.5),
        (NUMBER, 'between', [1, '3'], [1, 3]),
        (ScopeField('ref'), 'in', ['4', 2], [4, 2]),
        (ScopeField('checkbox'), 'equals', True, True),
        (DATE, 'lt', {'days_ago': 90}, {'days_ago': 90}),
        (DATE, 'between', ['2026-01-01', '2026-02-01'], ['2026-01-01', '2026-02-01']),
        (SELECT, 'not_in', ['on'], ['on']),
        (ScopeField(MULTIPLE_PERSON_KIND), 'contains', '9', 9),
    ], ids=['text', 'prefix', 'number-text', 'decimal-text', 'between', 'ids', 'checkbox', 'relative-date', 'dates',
            'option', 'person-member'])
    def test_values_are_cast(self, field: ScopeField, op: str, value: Any, cast: Any) -> None:
        """No problem; the value as it will be compiled"""
        blocks, problems = _cast(field, op, value)

        assert (problems, blocks[0]['value']) == ([], cast)

    @pytest.mark.parametrize('field, op, value, expected', [
        (ScopeField('password'), 'equals', 'x', ScopeMessage.NOT_COMPARABLE.value.format(field='f', kind='password')),
        (ScopeField('location'), 'equals', 1, ScopeMessage.NOT_COMPARABLE.value.format(field='f', kind='location')),
        (ScopeField('ref-section-field'), 'exists', None,
         ScopeMessage.NOT_COMPARABLE.value.format(field='f', kind='ref-section-field')),
        (ScopeField('text', in_mds=True), 'equals', 'x', ScopeMessage.IN_MULTI_DATA_SECTION.value.format(field='f')),
        (NUMBER, 'contains', 1, ScopeMessage.OPERATOR_NOT_FOR_KIND.value.format(field='f', kind='number',
                                                                               op='contains')),
        (ScopeField(MULTIPLE_PERSON_KIND), 'equals', 1,
         ScopeMessage.OPERATOR_NOT_FOR_KIND.value.format(field='f', kind=MULTIPLE_PERSON_KIND, op='equals')),
        (NUMBER, 'equals', True, ScopeMessage.VALUE_MISFIT.value.format(value='true', field='f',
                                                                        expected='a number')),
        (NUMBER, 'equals', 'ten', ScopeMessage.VALUE_MISFIT.value.format(value='"ten"', field='f',
                                                                         expected='a number')),
        (ScopeField('ref'), 'equals', -1, ScopeMessage.VALUE_MISFIT.value.format(value='-1', field='f',
                                                                                 expected='a whole number (an id)')),
        (TEXT, 'equals', 3, ScopeMessage.VALUE_MISFIT.value.format(value='3', field='f', expected='a text')),
        (TEXT, 'equals', {'days_ago': 1}, ScopeMessage.VALUE_MISFIT.value.format(value='{"days_ago": 1}', field='f',
                                                                                 expected='a text')),
        (ScopeField('checkbox'), 'equals', 'true', ScopeMessage.VALUE_MISFIT.value.format(
            value='"true"', field='f', expected='true or false')),
        (DATE, 'gt', '01.02.2026', ScopeMessage.VALUE_MISFIT.value.format(
            value='"01.02.2026"', field='f', expected='a date (YYYY-MM-DD) or {days_ago: n}')),
        (SELECT, 'equals', 'maybe', ScopeMessage.NOT_AN_OPTION.value.format(value='maybe', field='f')),
        (NUMBER, 'between', [5, 1], ScopeMessage.BETWEEN_ORDER.value.format(field='f')),
    ], ids=['password', 'location', 'ref-section', 'mds', 'number-contains', 'multi-person-equals', 'boolean-number',
            'word-number', 'negative-id', 'number-as-text', 'relative-on-text', 'text-boolean', 'german-date',
            'not-an-option', 'between-order'])
    def test_problems_are_named(self, field: ScopeField, op: str, value: Any, expected: str) -> None:
        """The condition comes back as sent"""
        blocks, problems = _cast(field, op, value, has_value=op != 'exists')

        assert problems == [expected]
        assert blocks[0].get('value') == (value if op != 'exists' else None)

    def test_a_relative_between_is_not_ordered_on_save(self) -> None:
        """Resolved when evaluated"""
        assert _cast(DATE, 'between', [{'days_ago': 1}, '2020-01-01'])[1] == []

    def test_a_field_the_resolution_refused_is_skipped(self) -> None:
        """Its problem is the resolution's"""
        blocks, problems = cast_scope([{'field': 'gone', 'op': 'exists'}], {})

        assert (blocks, problems) == ([{'field': 'gone', 'op': 'exists'}], [])

    def test_every_value_problem_of_a_list_once(self) -> None:
        """Two misfits named, the option check skipped for them"""
        _blocks, problems = _cast(SELECT, 'in', ['on', 'maybe', 'nope'])

        assert problems == [ScopeMessage.NOT_AN_OPTION.value.format(value='maybe', field='f'),
                            ScopeMessage.NOT_AN_OPTION.value.format(value='nope', field='f')]
