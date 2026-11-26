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
Unit tests for applying the Field Rules to one object write (``rule_engine``, ``rule_triggers``, ``rule_values``)

Pinned: a rule runs when its ``when`` fires on the user's change and its ``unless`` does not; a create counts every
filled field; the rules run in public_id order, once each, never on what another rule set; ``${now}`` is the write's day
on a date field and its instant on a text field, ``${user.person}`` the writer's person (a list on a multiple selector,
none without a person); a value its field refuses - a broken pattern, an emptied required field - refuses the write
naming the rule; a field the Type lacks or holds in a section is skipped; a value equal to the stored one is no change
"""
from datetime import datetime, timezone
from typing import Any

import pytest

from cmdb.framework.field_rules import (
    FieldRuleMessage,
    RuleToken,
    apply_rules,
    resolve_rule_value,
    rule_runs,
    rules_on_type,
)
from cmdb.framework.scope_compiler import MULTIPLE_PERSON_KIND
# -------------------------------------------------------------------------------------------------------------------- #

SERVER, OTHER = 11, 12
PERSON_ID = 501
NOW: datetime = datetime(2026, 11, 26, 13, 45, tzinfo=timezone.utc)
MIDNIGHT: datetime = datetime(2026, 11, 26, tzinfo=timezone.utc)
FIELDS: list[dict[str, Any]] = [
    {'name': 'status', 'type': 'text'},
    {'name': 'iso', 'type': 'checkbox', 'audit_relevant': True},
    {'name': 'secret', 'type': 'text', 'protection': 'compliance'},
    {'name': 'reviewed', 'type': 'date'},
    {'name': 'reviewed_text', 'type': 'text'},
    {'name': 'reviewer', 'type': 'person', 'selectable': ['PERSON']},
    {'name': 'code', 'type': 'text', 'regex': '^[A-Z]+$'},
    {'name': 'owner', 'type': 'text', 'required': True},
    {'name': 'row_note', 'type': 'text'},
]
MDS_NAMES: list[str] = ['row_note']


def _rule(public_id: int, when: dict[str, Any], values: dict[str, Any], **extra: Any) -> dict[str, Any]:
    """A stored rule on the server Type"""
    return {'public_id': public_id, 'name': f'rule-{public_id}', 'types': [SERVER], 'when': when, 'set': values,
            **extra}


def _object(**values: Any) -> dict[str, Any]:
    """An object of the server Type carrying the given values"""
    return {'type_id': SERVER, 'fields': [{'name': name, 'value': value, 'type': 'text'}
                                          for name, value in values.items()]}


def _value(document: dict[str, Any], name: str) -> Any:
    """One field's value in a state"""
    return next(entry['value'] for entry in document['fields'] if entry['name'] == name)


class TestTriggers:
    """When a rule runs"""

    @pytest.mark.parametrize(('when', 'changed', 'runs'), [
        ({'changed': ['status']}, ['status'], True),
        ({'changed': ['status']}, ['code'], False),
        ({'changed_any': {'flag': 'audit_relevant'}}, ['iso'], True),
        ({'changed_any': {'flag': 'audit_relevant'}}, ['status'], False),
        ({'changed_any': {'class': 'compliance'}}, ['secret'], True),
        ({'changed_any': {'class': 'compliance'}}, ['iso'], False),
    ])
    def test_the_when(self, when: dict[str, Any], changed: list[str], runs: bool) -> None:
        """Each trigger kind fires on its own fields only"""
        assert rule_runs(_rule(1, when, {'code': 'A'}), changed, FIELDS) is runs

    def test_the_unless_holds_it_back(self) -> None:
        """A firing ``unless`` stops a firing ``when``"""
        rule: dict[str, Any] = _rule(1, {'changed': ['status']}, {'code': 'A'}, unless={'changed': ['code']})

        assert rule_runs(rule, ['status'], FIELDS) is True
        assert rule_runs(rule, ['status', 'code'], FIELDS) is False

    def test_the_rules_on_a_type(self) -> None:
        """Every-Type rules and the Type's own, ascending by public_id"""
        rules: list[dict[str, Any]] = [_rule(3, {}, {}), {**_rule(1, {}, {}), 'types': '*'},
                                       {**_rule(2, {}, {}), 'types': [OTHER]}]

        assert [rule['public_id'] for rule in rules_on_type(rules, SERVER)] == [1, 3]


class TestValues:
    """What a stored value writes"""

    def test_now(self) -> None:
        """The day on a date field, the instant on a text field"""
        assert resolve_rule_value(RuleToken.NOW.value, 'date', NOW, None) == MIDNIGHT
        assert resolve_rule_value(RuleToken.NOW.value, 'text', NOW, None) == NOW.isoformat()

    def test_the_user_s_person(self) -> None:
        """One id, a list on a multiple selector, none without a person"""
        assert resolve_rule_value(RuleToken.USER_PERSON.value, 'person', NOW, PERSON_ID) == PERSON_ID
        assert resolve_rule_value(RuleToken.USER_PERSON.value, MULTIPLE_PERSON_KIND, NOW, PERSON_ID) == [PERSON_ID]
        assert resolve_rule_value(RuleToken.USER_PERSON.value, MULTIPLE_PERSON_KIND, NOW, None) == []
        assert resolve_rule_value(RuleToken.USER_PERSON.value, 'person', NOW, None) is None

    def test_a_literal(self) -> None:
        """A date text becomes a date, anything else stays"""
        assert resolve_rule_value('2026-01-02', 'date', NOW, None) == datetime(2026, 1, 2, tzinfo=timezone.utc)
        assert resolve_rule_value('x', 'text', NOW, None) == 'x'


class TestApplying:
    """One write"""

    def test_a_triggered_rule_writes_and_is_recorded(self) -> None:
        """The values land in the state; each change names rule, field, before and after"""
        before: dict[str, Any] = _object(status='old', code='OLD')
        after: dict[str, Any] = _object(status='new', code='OLD')
        rule: dict[str, Any] = _rule(4, {'changed': ['status']}, {'code': 'NEW', 'reviewed': RuleToken.NOW.value,
                                                                  'reviewer': RuleToken.USER_PERSON.value})

        application = apply_rules([rule], before, after, FIELDS, MDS_NAMES, NOW, PERSON_ID)

        assert application.problems == []
        assert (_value(after, 'code'), _value(after, 'reviewed'), _value(after, 'reviewer')) == (
            'NEW', MIDNIGHT, PERSON_ID)
        assert application.changes[0] == {'rule_id': 4, 'rule_name': 'rule-4', 'field': 'code', 'before': 'OLD',
                                          'after': 'NEW'}
        assert [change['field'] for change in application.changes] == ['code', 'reviewed', 'reviewer']

    def test_an_appended_entry_is_a_full_triple(self) -> None:
        """A field the state does not carry is appended with the Type's kind"""
        after: dict[str, Any] = _object(status='new')

        apply_rules([_rule(1, {'changed': ['status']}, {'reviewed': '2026-01-02'})], None, after, FIELDS, MDS_NAMES,
                    NOW, None)

        assert after['fields'][-1] == {'name': 'reviewed', 'value': datetime(2026, 1, 2, tzinfo=timezone.utc),
                                       'type': 'date'}

    def test_a_create_counts_every_filled_field(self) -> None:
        """No stored state: a filled trigger field fires"""
        after: dict[str, Any] = _object(status='x')

        assert apply_rules([_rule(1, {'changed': ['status']}, {'code': 'A'})], None, after, FIELDS, MDS_NAMES, NOW,
                           None).changes

    def test_no_chaining(self) -> None:
        """A rule triggered by another rule's value does not run"""
        after: dict[str, Any] = _object(status='new')
        first: dict[str, Any] = _rule(1, {'changed': ['status']}, {'code': 'A'})
        second: dict[str, Any] = _rule(2, {'changed': ['code']}, {'reviewed_text': 'chained'})

        application = apply_rules([second, first], _object(status='old'), after, FIELDS, MDS_NAMES, NOW, None)

        assert [change['rule_id'] for change in application.changes] == [1]

    def test_an_untriggered_rule_and_another_type_s_rule_do_nothing(self) -> None:
        """Nothing changed, nothing recorded"""
        after: dict[str, Any] = _object(status='same')
        rules: list[dict[str, Any]] = [_rule(1, {'changed': ['status']}, {'code': 'A'}),
                                       {**_rule(2, {'changed': ['status']}, {'code': 'B'}), 'types': [OTHER]}]

        assert apply_rules(rules, _object(status='same'), after, FIELDS, MDS_NAMES, NOW, None).changes == []
        assert after == _object(status='same')

    def test_an_unchanged_value_is_not_recorded(self) -> None:
        """The value the object already holds"""
        after: dict[str, Any] = _object(status='new', code='A')

        assert apply_rules([_rule(1, {'changed': ['status']}, {'code': 'A'})], _object(status='old', code='A'), after,
                           FIELDS, MDS_NAMES, NOW, None).changes == []

    def test_a_missing_or_sectioned_field_is_skipped(self) -> None:
        """A field the Type lacks, or one in a multi-data section, is never written"""
        after: dict[str, Any] = _object(status='new')
        rule: dict[str, Any] = _rule(1, {'changed': ['status']}, {'gone': 'x', 'row_note': 'x'})

        assert apply_rules([rule], None, after, FIELDS, MDS_NAMES, NOW, None).changes == []
        assert [entry['name'] for entry in after['fields']] == ['status']

    @pytest.mark.parametrize(('values', 'part'), [
        ({'code': 'lower'}, 'code'),
        ({'owner': None}, FieldRuleMessage.REQUIRED_EMPTIED.value.format(field='owner')),
    ])
    def test_an_invalid_value_refuses_the_write_naming_the_rule(self, values: dict[str, Any], part: str) -> None:
        """A broken pattern or an emptied required field"""
        application = apply_rules([_rule(7, {'changed': ['status']}, values)], None, _object(status='x'), FIELDS,
                                  MDS_NAMES, NOW, None)

        assert len(application.problems) == 1
        assert "'rule-7'" in application.problems[0] and part in application.problems[0]
