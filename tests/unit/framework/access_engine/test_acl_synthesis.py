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
Unit tests for cmdb.framework.access_engine.acl_synthesis and its answer form synthesised_acl_values

The block a Type answers with is the one the access rules decide: off for an unrestricted Type, on and listing each
group's permissions for a restricted one, a role on every Type counting for each. Fed the translation of a type ACL,
it grants exactly what that ACL granted
"""
from typing import Any

import pytest

from cmdb.framework.access_engine import access_filters
from cmdb.framework.access_engine import (
    assignment_documents,
    held_permission_values,
    group_entries,
    role_documents,
    synthesised_acl_values,
    synthesised_acls,
    translate_type_acls,
)
from cmdb.security.acl.access_control_list import AccessControlList
from cmdb.security.acl.acl_groups import group_permissions
from tests.utils.type_acl_scenarios import EXISTING_GROUP_IDS as SCENARIO_GROUP_IDS, scenario
# -------------------------------------------------------------------------------------------------------------------- #

SERVER_TYPE_ID: int = 11
ROUTER_TYPE_ID: int = 12
FREE_TYPE_ID: int = 13
OPERATORS_GROUP_ID: int = 21
AUDITORS_GROUP_ID: int = 22
VIEW_ROLE_ID: int = 31
EDIT_ROLE_ID: int = 32
EVERY_TYPE_ROLE_ID: int = 33
NO_OPERATION_ROLE_ID: int = 34
ADMIN_GROUP_ID: int = 1
SCENARIO_TYPE_IDS: list[int] = [9901, 9902, 9903, 9904, 9905]
SCENARIO_COUNT: int = 30


def _role(public_id: int, types: Any, operations: list[str]) -> dict[str, Any]:
    """A stored scope role"""
    return {'public_id': public_id, 'name': f'role-{public_id}', 'types': types, 'operations': operations,
            'write_regular_fields': True, 'field_classes': []}


def _assignment(public_id: int, group_id: int, role_id: int, scope: Any = '*') -> dict[str, Any]:
    """A stored assignment"""
    return {'public_id': public_id, 'group_id': group_id, 'role_id': role_id, 'scope': scope, 'description': ''}


ROLES: list[dict[str, Any]] = [
    _role(VIEW_ROLE_ID, [SERVER_TYPE_ID, ROUTER_TYPE_ID], ['view']),
    _role(EDIT_ROLE_ID, [SERVER_TYPE_ID], ['delete', 'edit']),
]
ASSIGNMENTS: list[dict[str, Any]] = [
    _assignment(41, OPERATORS_GROUP_ID, VIEW_ROLE_ID),
    _assignment(42, OPERATORS_GROUP_ID, EDIT_ROLE_ID),
    _assignment(43, AUDITORS_GROUP_ID, VIEW_ROLE_ID),
]


def _on(includes: dict[int, list[str]]) -> dict[str, Any]:
    """An activated block"""
    return {'activated': True, 'groups': {'includes': {str(group): values for group, values in includes.items()}}}


class TestSynthesisedAcls:
    """synthesised_acls"""

    def test_each_group_with_its_permissions_in_operation_order(self) -> None:
        """READ before UPDATE before DELETE, whatever the role lists"""
        blocks = synthesised_acls([SERVER_TYPE_ID, ROUTER_TYPE_ID], ASSIGNMENTS, ROLES)

        assert blocks == {
            SERVER_TYPE_ID: _on({OPERATORS_GROUP_ID: ['READ', 'UPDATE', 'DELETE'], AUDITORS_GROUP_ID: ['READ']}),
            ROUTER_TYPE_ID: _on({OPERATORS_GROUP_ID: ['READ'], AUDITORS_GROUP_ID: ['READ']}),
        }

    def test_an_unrestricted_type_answers_the_default(self) -> None:
        """Off, nobody listed"""
        assert synthesised_acls([FREE_TYPE_ID], ASSIGNMENTS, ROLES) == {FREE_TYPE_ID: AccessControlList.default_json()}

    def test_a_role_on_every_type_counts_for_each(self) -> None:
        """Every Type restricted; the auditors view all"""
        roles = [*ROLES, _role(EVERY_TYPE_ROLE_ID, '*', ['view'])]
        assignments = [*ASSIGNMENTS, _assignment(44, AUDITORS_GROUP_ID, EVERY_TYPE_ROLE_ID)]

        assert synthesised_acls([FREE_TYPE_ID], assignments, roles) == {
            FREE_TYPE_ID: _on({AUDITORS_GROUP_ID: ['READ']})}

    def test_a_restriction_granting_nobody_lists_nobody(self) -> None:
        """A role without operations - on, empty"""
        roles = [_role(NO_OPERATION_ROLE_ID, [FREE_TYPE_ID], [])]

        assert synthesised_acls([FREE_TYPE_ID], [_assignment(45, ADMIN_GROUP_ID, NO_OPERATION_ROLE_ID)], roles) == {
            FREE_TYPE_ID: _on({})}

    def test_a_conditional_assignment_grants_nothing(self) -> None:
        """It still restricts through its role; the group is not listed"""
        assignments = [_assignment(46, AUDITORS_GROUP_ID, EDIT_ROLE_ID, scope={'location': 1})]

        assert synthesised_acls([SERVER_TYPE_ID], assignments, [ROLES[1]]) == {SERVER_TYPE_ID: _on({})}

    @pytest.mark.parametrize('number', range(SCENARIO_COUNT))
    def test_a_translated_acl_comes_back_granting_the_same(self, number: int) -> None:
        """Each existing group holds the same permissions as in the activated ACL; a deactivated ACL is off"""
        types = scenario(number, SCENARIO_TYPE_IDS)
        translated = translate_type_acls(types, SCENARIO_GROUP_IDS, ADMIN_GROUP_ID)
        roles = role_documents(translated, 1)

        blocks = synthesised_acls(SCENARIO_TYPE_IDS, assignment_documents(translated, 1, 1), roles)

        for document in types:
            acl: Any = document.get('acl')
            activated: bool = isinstance(acl, dict) and acl.get('activated') is True
            expected: dict[str, set[str]] = {
                str(group): set(values) & {'CREATE', 'READ', 'UPDATE', 'DELETE'}
                for group, values in group_permissions(acl).items() if group in SCENARIO_GROUP_IDS} if activated else {}
            answered = blocks[document['public_id']]
            assert answered['activated'] is activated
            assert {group: set(values) for group, values in answered['groups']['includes'].items()} == {
                group: values for group, values in expected.items() if values}


class TestParts:
    """group_entries, held_permission_values"""

    def test_each_group_reads_its_own_assignments(self) -> None:
        """Ascending groups; the auditors only the view role"""
        entries = group_entries(ASSIGNMENTS, ROLES)

        assert list(entries) == [OPERATORS_GROUP_ID, AUDITORS_GROUP_ID]
        assert [entry.role_id for entry in entries[AUDITORS_GROUP_ID]] == [VIEW_ROLE_ID]

    def test_nothing_held_is_empty(self) -> None:
        """A Type the group's roles do not name"""
        assert held_permission_values(group_entries(ASSIGNMENTS, ROLES)[AUDITORS_GROUP_ID], FREE_TYPE_ID) == []


def test_the_answer_form_reads_the_rules_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """synthesised_acl_values: the user's tenant's rules, then the blocks"""
    calls: list[Any] = []

    def _load(user: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        calls.append(user)
        return ASSIGNMENTS, ROLES

    monkeypatch.setattr(access_filters, 'load_access_rules', _load)

    assert synthesised_acl_values('the-user', [ROUTER_TYPE_ID]) == {
        ROUTER_TYPE_ID: _on({OPERATORS_GROUP_ID: ['READ'], AUDITORS_GROUP_ID: ['READ']})}
    assert calls == ['the-user']
