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
Unit tests for judging a Field Rule before it is stored, the Type changes that would break one, the scope / rule
boundary and the reach of an editor or a user group (``rule_judge``, ``rule_reach``, ``rule_shape``)

Pinned: a rule on listed Types sets only fields each of them carries, at the top level, of one kind, never a location
field, with a value fitting the field (the value stored cast); a rule on every Type needs one carrier; its triggers name
carried fields and stored classes; an active rule may not set a field another active rule sets on an overlapping Type
set, nor one a stored scope compares there; a Type change removing, retyping or sectioning a field an active rule sets
is refused; an editor may only make a rule set fields they may write (a ``system`` one excepted); a group's rules are
those whose ``when`` names a field the group may write
"""
from typing import Any

import pytest

from cmdb.framework.access_engine import build_grants
from cmdb.framework.field_rules import (
    FieldRuleMessage,
    RuleToken,
    ScopeComparison,
    group_may_trigger,
    judge_field_rule,
    reach_problems,
    rule_set_fields,
    type_change_rule_problems,
    types_overlap,
)
from cmdb.framework.scope_compiler import ScopeField
# -------------------------------------------------------------------------------------------------------------------- #

SERVER, CLIENT, OTHER = 11, 12, 13
GROUP_ID, ROLE_ID, ASSIGNMENT_ID = 7, 2, 1
SERVER_DOC: dict[str, Any] = {
    'public_id': SERVER,
    'fields': [{'name': 'status', 'type': 'text'},
               {'name': 'level', 'type': 'select', 'options': [{'name': 'low'}, {'name': 'high'}]},
               {'name': 'reviewed', 'type': 'date'},
               {'name': 'reviewer', 'type': 'person', 'selectable': ['PERSON']},
               {'name': 'place', 'type': 'location'},
               {'name': 'secret', 'type': 'text', 'protection': 'compliance'},
               {'name': 'stamp', 'type': 'text', 'protection': 'system'},
               {'name': 'row_note', 'type': 'text'}],
    'render_meta': {'sections': [{'type': 'multi-data-section', 'name': 'rows', 'fields': ['row_note']}]},
}
CLIENT_DOC: dict[str, Any] = {'public_id': CLIENT, 'fields': [{'name': 'status', 'type': 'number'}],
                              'render_meta': {'sections': []}}
CLASSES: set[str] = {'system', 'compliance'}


def _rule(values: dict[str, Any], types: Any = None, **extra: Any) -> dict[str, Any]:
    """A rule as it would be stored"""
    return {'public_id': 5, 'name': 'stamp-review', 'active': True, 'types': [SERVER] if types is None else types,
            'when': {'changed': ['status']}, 'set': values, **extra}


def _judge(rule: dict[str, Any], documents: list[dict[str, Any]] | None = None, others: list[dict[str, Any]] = (),
           comparisons: list[ScopeComparison] = ()) -> tuple[Any, list[str]]:
    """Judges against the server Type alone by default"""
    return judge_field_rule(rule, [SERVER_DOC] if documents is None else documents, CLASSES, others, comparisons)


class TestJudging:
    """A rule as it would be stored"""

    def test_a_valid_rule_is_stored_cast(self) -> None:
        """Every value cast to its field's kind; tokens and null kept"""
        cast, problems = _judge(_rule({'level': 'high', 'reviewed': '2026-01-02', 'reviewer': RuleToken.USER_PERSON.value,
                                       'status': None, 'stamp': RuleToken.NOW.value}))

        assert problems == []
        assert cast == {'level': 'high', 'reviewed': '2026-01-02', 'reviewer': RuleToken.USER_PERSON.value,
                        'status': None, 'stamp': RuleToken.NOW.value}

    def test_the_shape_is_judged_first(self) -> None:
        """A bad trigger refuses the rule before anything is resolved"""
        _, problems = _judge(_rule({'status': 'x'}, when={'changed': []}))

        assert problems == [FieldRuleMessage.BAD_TRIGGER.value.format(key='when')]

    @pytest.mark.parametrize(('values', 'expected'), [
        ({'gone': 'x'}, FieldRuleMessage.FIELD_NOT_ON_TYPE.value.format(field='gone', type_id=SERVER)),
        ({'row_note': 'x'}, FieldRuleMessage.FIELD_IN_SECTION.value.format(field='row_note')),
        ({'place': 1}, FieldRuleMessage.FORBIDDEN_FIELD.value.format(field='place')),
        ({'reviewed': RuleToken.USER_PERSON.value}, FieldRuleMessage.TOKEN_NOT_FOR_FIELD.value.format(
            token=RuleToken.USER_PERSON.value, field='reviewed', kind='date')),
    ])
    def test_a_field_it_may_not_set(self, values: dict[str, Any], expected: str) -> None:
        """Missing, sectioned, a location, a token the kind does not take"""
        assert expected in _judge(_rule(values))[1]

    def test_a_value_that_does_not_fit(self) -> None:
        """An option the select does not offer"""
        problems: list[str] = _judge(_rule({'level': 'nope'}))[1]

        assert len(problems) == 1 and "'level'" in problems[0]

    def test_kinds_must_agree_across_the_types(self) -> None:
        """A field one Type holds as text and another as number"""
        problems: list[str] = _judge(_rule({'status': 'x'}, [SERVER, CLIENT]), [SERVER_DOC, CLIENT_DOC])[1]

        assert FieldRuleMessage.FIELD_KINDS_DIFFER.value.format(field='status') in problems

    def test_every_type_needs_one_carrier(self) -> None:
        """A rule on every Type skips the Types without the field, but one must carry it"""
        assert _judge(_rule({'reviewed': '2026-01-02'}, '*'), [SERVER_DOC, CLIENT_DOC])[1] == []
        assert _judge(_rule({'gone': 'x'}, '*'))[1] == [FieldRuleMessage.NO_CARRIER.value.format(field='gone')]

    def test_the_triggers_name_carried_fields_and_stored_classes(self) -> None:
        """An unknown field in ``changed``, an unknown class in ``changed_any``"""
        problems: list[str] = _judge(_rule({'status': 'x'}, when={'changed': ['nowhere']},
                                           unless={'changed_any': {'class': 'unknown'}}))[1]

        assert problems == [FieldRuleMessage.UNKNOWN_TRIGGER_FIELD.value.format(field='nowhere'),
                            FieldRuleMessage.UNKNOWN_CLASS.value.format(name='unknown')]

    def test_an_overlapping_active_rule_setting_the_field(self) -> None:
        """Refused while both are active and their Types overlap"""
        other: dict[str, Any] = {'public_id': 9, 'active': True, 'types': '*', 'set': {'status': 'y'}}

        assert _judge(_rule({'status': 'x'}), others=[other])[1] == [
            FieldRuleMessage.OVERLAP.value.format(field='status', rule_id=9)]
        assert _judge(_rule({'status': 'x'}), others=[{**other, 'active': False}])[1] == []
        assert _judge(_rule({'status': 'x'}, active=False), others=[other])[1] == []
        assert _judge(_rule({'status': 'x'}), others=[{**other, 'types': [OTHER]}])[1] == []

    def test_a_field_a_scope_compares(self) -> None:
        """Refused on an overlapping Type set, naming the assignments"""
        comparison: ScopeComparison = ScopeComparison(ASSIGNMENT_ID, [SERVER], frozenset({'status'}))

        assert _judge(_rule({'status': 'x'}), comparisons=[comparison])[1] == [
            FieldRuleMessage.SCOPE_FIELD.value.format(field='status', assignment_ids=[ASSIGNMENT_ID])]
        assert _judge(_rule({'status': 'x'}), comparisons=[ScopeComparison(ASSIGNMENT_ID, [OTHER],
                                                                           frozenset({'status'}))])[1] == []


class TestTypesOverlap:
    """Two Type sets"""

    @pytest.mark.parametrize(('first', 'second', 'overlap'), [
        ('*', '*', True), ('*', [SERVER], True), ([SERVER], '*', True), ('*', [], False),
        ([SERVER, CLIENT], [CLIENT], True), ([SERVER], [CLIENT], False),
    ])
    def test_overlap(self, first: Any, second: Any, overlap: bool) -> None:
        """Every Type overlaps any non-empty set"""
        assert types_overlap(first, second) is overlap


class TestStaleness:
    """A Type change and a stored rule"""

    RULE: dict[str, Any] = _rule({'level': 'high'})
    BEFORE: dict[str, ScopeField] = {'level': ScopeField('select', frozenset({'low', 'high'}))}

    def test_a_kept_field_passes(self) -> None:
        """The field stays with its option"""
        after: dict[str, ScopeField] = {'level': ScopeField('select', frozenset({'high'}))}

        assert type_change_rule_problems(SERVER, [self.RULE], self.BEFORE, after) == []

    @pytest.mark.parametrize('after', [
        {},
        {'level': ScopeField('text')},
        {'level': ScopeField('select', frozenset({'low'}))},
        {'level': ScopeField('select', frozenset({'high'}), in_mds=True)},
    ])
    def test_a_breaking_change(self, after: dict[str, ScopeField]) -> None:
        """Removed, retyped, its option gone, moved into a section"""
        problems: list[str] = type_change_rule_problems(SERVER, [self.RULE], self.BEFORE, after)

        assert len(problems) == 1 and "'stamp-review'" in problems[0] and "'level'" in problems[0]

    def test_an_inactive_rule_or_another_type_is_not_judged(self) -> None:
        """Only active rules covering the Type"""
        assert type_change_rule_problems(SERVER, [{**self.RULE, 'active': False}], self.BEFORE, {}) == []
        assert type_change_rule_problems(CLIENT, [self.RULE], self.BEFORE, {}) == []

    def test_a_rule_on_every_type_ignores_a_type_without_the_field(self) -> None:
        """The field may be missing - only a carrier is judged"""
        assert type_change_rule_problems(CLIENT, [{**self.RULE, 'types': '*'}], {}, {}) == []

    def test_the_fields_rules_set(self) -> None:
        """By field, the active rules setting it on an overlapping Type set"""
        rules: list[dict[str, Any]] = [self.RULE, {**self.RULE, 'public_id': 6, 'types': [OTHER]},
                                       {**self.RULE, 'public_id': 8, 'active': False}]

        assert rule_set_fields(rules, [SERVER]) == {'level': [5]}
        assert rule_set_fields(rules, '*') == {'level': [5, 6]}


class TestReach:
    """What an editor or a group reaches"""

    @staticmethod
    def _grants(classes: list[str], regular: bool = True) -> Any:
        """One unconditional assignment editing the server Type"""
        return build_grants([{'public_id': ASSIGNMENT_ID, 'group_id': GROUP_ID, 'role_id': ROLE_ID, 'scope': '*'}],
                            [{'public_id': ROLE_ID, 'types': [SERVER], 'operations': ['view', 'edit'],
                              'write_regular_fields': regular, 'field_classes': classes}], [GROUP_ID])

    def test_the_editor_writes_every_set_field(self) -> None:
        """A regular field, a class granted, a system field"""
        rule: dict[str, Any] = _rule({'status': 'x', 'secret': 'y', 'stamp': RuleToken.NOW.value})

        assert reach_problems(self._grants(['compliance']), rule, [SERVER_DOC]) == []

    def test_a_field_beyond_the_editor(self) -> None:
        """A class the editor does not hold"""
        rule: dict[str, Any] = _rule({'status': 'x', 'secret': 'y'})

        assert reach_problems(self._grants([]), rule, [SERVER_DOC]) == [
            FieldRuleMessage.BEYOND_REACH.value.format(fields=['secret'], type_id=SERVER)]

    def test_a_group_triggers_by_a_field_it_writes(self) -> None:
        """The ``when`` names a field the group may write"""
        assert group_may_trigger(self._grants([]), _rule({'stamp': 'x'}), [SERVER_DOC]) is True
        assert group_may_trigger(self._grants([], regular=False), _rule({'stamp': 'x'}), [SERVER_DOC]) is False
        assert group_may_trigger(self._grants(['compliance'], regular=False),
                                 _rule({'stamp': 'x'}, when={'changed_any': {'class': 'compliance'}}),
                                 [SERVER_DOC]) is True
