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
Unit tests for the write rules of the access rules

Pure where the rule is pure (the name change, the unknown ids and names, the canonical scope); the rules that read
are driven past MagicMock managers: which read each asks, that it reads nothing when there is nothing to judge, and
the message each problem carries. What the reads match is the integration tier's question
"""
from typing import Any
from unittest.mock import MagicMock

import pytest

from cmdb.framework.access_rules import (
    AccessRuleMessage,
    assignment_reference_problems,
    assignment_taken,
    canonical_scope,
    clashes,
    field_class_name_change,
    field_class_name_taken,
    scope_role_name_taken,
    scope_role_reference_problems,
    unknown_field_classes,
    unknown_type_ids,
)
from cmdb.framework.access_rules.access_rule_reads import CLASH_COUNT_LIMIT
from cmdb.models.user_model import CmdbUser
from cmdb.security.acl.permission import AccessControlPermission
# -------------------------------------------------------------------------------------------------------------------- #

CLASS_ID: int = 11
CLASS_NAME: str = 'compliance'
CALLER: CmdbUser = CmdbUser(public_id=51, user_name='role-editor', active=True, group_ids=[21])
# A member of the administrator group (1), beside another group
ADMINISTRATOR: CmdbUser = CmdbUser(public_id=52, user_name='admin-editor', active=True, group_ids=[21, 1])
ROLE_ID: int = 21
GROUP_ID: int = 4
STORED_CLASS: dict[str, Any] = {'public_id': CLASS_ID, 'name': CLASS_NAME, 'label': 'Compliance'}
ASSIGNMENT: dict[str, Any] = {'group_id': GROUP_ID, 'role_id': ROLE_ID, 'scope': '*'}


def _counting(count: int) -> MagicMock:
    """A manager whose count answers ``count``"""
    manager = MagicMock()
    manager.count_documents.return_value = count

    return manager


class TestClashes:
    """One count stopped at the first match, the updated document left out."""

    def test_a_create_counts_the_criteria(self) -> None:
        """No own id: the criteria as given"""
        manager = _counting(1)

        assert clashes(manager, {'name': 'x'}) is True
        manager.count_documents.assert_called_once_with({'name': 'x'}, limit=CLASH_COUNT_LIMIT)

    def test_an_update_leaves_itself_out(self) -> None:
        """public_id $ne the own id; the caller's criteria not changed"""
        manager = _counting(0)
        criteria: dict[str, Any] = {'name': 'x'}

        assert clashes(manager, criteria, own_id=ROLE_ID) is False
        manager.count_documents.assert_called_once_with({'name': 'x', 'public_id': {'$ne': ROLE_ID}},
                                                        limit=CLASH_COUNT_LIMIT)
        assert criteria == {'name': 'x'}


class TestFieldClassRules:
    """The name is fixed once stored and unique."""

    @pytest.mark.parametrize('body', [{}, {'name': CLASS_NAME, 'label': 'Other'}], ids=['left-out', 'same'])
    def test_the_name_may_stay(self, body: dict[str, Any]) -> None:
        """Left out or the stored one"""
        assert field_class_name_change(STORED_CLASS, body) is None

    def test_a_rename_is_refused_naming_the_stored_name(self) -> None:
        """The class and its name"""
        assert field_class_name_change(STORED_CLASS, {'name': 'audit'}) == \
            AccessRuleMessage.FIELD_CLASS_NAME_FIXED.value.format(public_id=CLASS_ID, stored=CLASS_NAME)

    @pytest.mark.parametrize('count, expected', [
        (1, AccessRuleMessage.FIELD_CLASS_NAME_TAKEN.value.format(name=CLASS_NAME)),
        (0, None),
    ], ids=['taken', 'free'])
    def test_a_taken_name(self, count: int, expected: str | None) -> None:
        """Counted by name"""
        manager = _counting(count)

        assert field_class_name_taken(manager, CLASS_NAME) == expected
        manager.count_documents.assert_called_once_with({'name': CLASS_NAME}, limit=CLASH_COUNT_LIMIT)


class TestUnknownReferences:
    """The pure differences."""

    @pytest.mark.parametrize('types, existing, expected', [
        ('*', set(), []),
        ([], set(), []),
        ([7, 3, 9], {3}, [7, 9]),
        ([3], {3}, []),
    ], ids=['all-types', 'none', 'two-unknown', 'all-known'])
    def test_unknown_type_ids(self, types: Any, existing: set[int], expected: list[int]) -> None:
        """Ascending; never any for '*'"""
        assert unknown_type_ids(types, existing) == expected

    def test_unknown_field_classes(self) -> None:
        """Sorted"""
        assert unknown_field_classes(['z', CLASS_NAME, 'a'], {CLASS_NAME}) == ['a', 'z']


class TestScopeRoleReferences:
    """One read per kind, none when there is nothing to judge."""

    def test_every_problem_together(self) -> None:
        """An unknown Type, a Type the caller may not read and an unknown class, all named - the hidden Type like the
        unknown one"""
        types_manager, classes_manager = MagicMock(), MagicMock()
        types_manager.get_existing_type_ids.return_value = {3, 5}
        types_manager.get_denied_type_ids.return_value = [5, 99]
        classes_manager.find_existing_names.return_value = set()

        problems = scope_role_reference_problems({'types': [3, 5, 8], 'field_classes': [CLASS_NAME]}, types_manager,
                                                 classes_manager, CALLER)

        assert problems == [AccessRuleMessage.UNKNOWN_TYPES.value.format(ids=[5, 8]),
                            AccessRuleMessage.UNKNOWN_FIELD_CLASSES.value.format(names=[CLASS_NAME])]
        types_manager.get_existing_type_ids.assert_called_once_with([3, 5, 8])
        types_manager.get_denied_type_ids.assert_called_once_with(CALLER, AccessControlPermission.READ)
        classes_manager.find_existing_names.assert_called_once_with([CLASS_NAME])

    def test_an_administrator_names_a_hidden_type(self) -> None:
        """Only a missing Type is refused - the denied ones are not read, so administrators can re-grant themselves"""
        types_manager, classes_manager = MagicMock(), MagicMock()
        types_manager.get_existing_type_ids.return_value = {3, 5}

        problems = scope_role_reference_problems({'types': [3, 5, 8]}, types_manager, classes_manager, ADMINISTRATOR)

        assert problems == [AccessRuleMessage.UNKNOWN_TYPES.value.format(ids=[8])]
        types_manager.get_denied_type_ids.assert_not_called()

    @pytest.mark.parametrize('role', [{'types': '*'}, {'types': [], 'field_classes': []}, {'description': 'x'}],
                             ids=['all-types', 'empty', 'not-sent'])
    def test_nothing_to_judge_reads_nothing(self, role: dict[str, Any]) -> None:
        """Every Type, no Type, no class, or an update not sending them"""
        types_manager, classes_manager = MagicMock(), MagicMock()

        assert not scope_role_reference_problems(role, types_manager, classes_manager, CALLER)
        types_manager.get_existing_type_ids.assert_not_called()
        types_manager.get_denied_type_ids.assert_not_called()
        classes_manager.find_existing_names.assert_not_called()

    @pytest.mark.parametrize('own_id, criteria', [
        (None, {'name': 'Operator'}),
        (ROLE_ID, {'name': 'Operator', 'public_id': {'$ne': ROLE_ID}}),
    ], ids=['create', 'update'])
    def test_a_taken_role_name(self, own_id: int | None, criteria: dict[str, Any]) -> None:
        """Counted by name, the updated role left out"""
        manager = _counting(1)

        assert scope_role_name_taken(manager, 'Operator', own_id) == \
            AccessRuleMessage.SCOPE_ROLE_NAME_TAKEN.value.format(name='Operator')
        manager.count_documents.assert_called_once_with(criteria, limit=CLASH_COUNT_LIMIT)


class TestCanonicalScope:
    """Keys sorted at every depth, lists kept in order."""

    def test_the_unconditional_scope_is_itself(self) -> None:
        """'*' stays"""
        assert canonical_scope('*') == '*'

    def test_documents_are_sorted_at_every_depth(self) -> None:
        """Two spellings, one result; the list order kept"""
        first = canonical_scope({'b': 1, 'a': {'d': [{'z': 1, 'y': 2}, 3], 'c': 0}})
        second = canonical_scope({'a': {'c': 0, 'd': [{'y': 2, 'z': 1}, 3]}, 'b': 1})

        assert first == second
        assert list(first) == ['a', 'b'] and list(first['a']) == ['c', 'd'] and list(first['a']['d'][0]) == ['y', 'z']

    def test_the_input_is_not_changed(self) -> None:
        """New documents throughout"""
        scope: dict[str, Any] = {'b': [{'d': 1, 'c': 2}], 'a': 0}
        canonical_scope(scope)['b'][0]['e'] = 3

        assert scope == {'b': [{'d': 1, 'c': 2}], 'a': 0}

    def test_a_condition_list_has_one_spelling(self) -> None:
        """Conditions and in values sorted - two spellings meet the unique index as one (phase 9, R5)"""
        one = canonical_scope([{'op': 'in', 'field': 'n', 'value': [2, 1]}, {'field': 'a', 'op': 'exists'}])
        other = canonical_scope([{'field': 'a', 'op': 'exists'}, {'field': 'n', 'op': 'in', 'value': [1, 2]}])

        assert one == other

    def test_a_malformed_list_keeps_its_order(self) -> None:
        """The schema refuses it; nothing is reordered"""
        assert canonical_scope([{'b': 1, 'a': 2}, 'x']) == [{'a': 2, 'b': 1}, 'x']


class TestAssignmentRules:
    """The group and role are stored; one group, role and scope once."""

    @pytest.mark.parametrize('groups, roles, expected', [
        ({GROUP_ID}, {ROLE_ID}, []),
        (set(), {ROLE_ID}, [AccessRuleMessage.UNKNOWN_GROUP.value.format(group_id=GROUP_ID)]),
        (set(), set(), [AccessRuleMessage.UNKNOWN_GROUP.value.format(group_id=GROUP_ID),
                        AccessRuleMessage.UNKNOWN_ROLE.value.format(role_id=ROLE_ID)]),
    ], ids=['both', 'no-group', 'neither'])
    def test_the_references(self, groups: set[int], roles: set[int], expected: list[str]) -> None:
        """One read each, every problem together"""
        groups_manager, roles_manager = MagicMock(), MagicMock()
        groups_manager.find_existing_public_ids.return_value = groups
        roles_manager.find_existing_public_ids.return_value = roles

        assert assignment_reference_problems(ASSIGNMENT, groups_manager, roles_manager) == expected
        groups_manager.find_existing_public_ids.assert_called_once_with([GROUP_ID])
        roles_manager.find_existing_public_ids.assert_called_once_with([ROLE_ID])

    @pytest.mark.parametrize('sent, groups_read, roles_read', [
        ({'description': 'x'}, False, False),
        ({'role_id': ROLE_ID}, False, True),
        ({'group_id': GROUP_ID}, True, False),
    ], ids=['nothing', 'role-only', 'group-only'])
    def test_an_update_judges_only_what_it_sends(self, sent: dict[str, Any], groups_read: bool,
                                                 roles_read: bool) -> None:
        """A reference left out is not read"""
        groups_manager, roles_manager = MagicMock(), MagicMock()
        groups_manager.find_existing_public_ids.return_value = {GROUP_ID}
        roles_manager.find_existing_public_ids.return_value = {ROLE_ID}

        assert not assignment_reference_problems(sent, groups_manager, roles_manager)
        assert (groups_manager.find_existing_public_ids.called, roles_manager.find_existing_public_ids.called) == (
            groups_read, roles_read)

    @pytest.mark.parametrize('count, expected', [
        (1, AccessRuleMessage.ASSIGNMENT_TAKEN.value.format(group_id=GROUP_ID, role_id=ROLE_ID)),
        (0, None),
    ], ids=['taken', 'free'])
    def test_a_taken_assignment(self, count: int, expected: str | None) -> None:
        """Counted by group, role and scope"""
        manager = _counting(count)

        assert assignment_taken(manager, ASSIGNMENT) == expected
        manager.count_documents.assert_called_once_with(ASSIGNMENT, limit=CLASH_COUNT_LIMIT)
