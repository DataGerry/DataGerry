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
Unit tests for cmdb.framework.access_engine.access_grants

A Type no assigned role names allows everything to everyone; a Type an assigned role names - any group's - is
restricted and allows an operation only through the user's own assignments, which add up over the groups. A role
naming every Type restricts every Type. An empty-operations role restricts and grants nothing; no groups grant
nothing. Regular fields are written only through a role granting the very operation. Assignments of other groups,
with a role not read or a scope condition grant nothing. Distinct ids per document, so a swapped key fails a test
"""
from typing import Any

import pytest

from cmdb.framework.access_engine import (
    AccessGrants,
    GrantEntry,
    TypeSet,
    build_grants,
    grant_entries,
    restricted_types,
    role_operations,
)
from cmdb.models.access_model import ScopeOperation
# -------------------------------------------------------------------------------------------------------------------- #

SERVER_TYPE_ID: int = 11
ROUTER_TYPE_ID: int = 12
FREE_TYPE_ID: int = 13
ORPHAN_TYPE_ID: int = 999
USER_GROUP_ID: int = 21
SECOND_USER_GROUP_ID: int = 22
OTHER_GROUP_ID: int = 23
VIEW_ROLE_ID: int = 31
EDIT_ROLE_ID: int = 32
EMPTY_ROLE_ID: int = 33
EVERY_TYPE_ROLE_ID: int = 34
VIEW = ScopeOperation.VIEW
CREATE = ScopeOperation.CREATE
EDIT = ScopeOperation.EDIT
DELETE = ScopeOperation.DELETE


def _role(public_id: int, types: Any, operations: list[str], write_regular_fields: bool = True) -> dict[str, Any]:
    """A stored scope role"""
    return {'public_id': public_id, 'name': f'role-{public_id}', 'description': '', 'types': types,
            'operations': operations, 'write_regular_fields': write_regular_fields, 'field_classes': []}


def _assignment(public_id: int, group_id: int, role_id: int, scope: Any = '*') -> dict[str, Any]:
    """A stored assignment"""
    return {'public_id': public_id, 'group_id': group_id, 'role_id': role_id, 'scope': scope, 'description': ''}


VIEW_ROLE: dict[str, Any] = _role(VIEW_ROLE_ID, [SERVER_TYPE_ID], ['view'], write_regular_fields=True)
EDIT_ROLE: dict[str, Any] = _role(EDIT_ROLE_ID, [SERVER_TYPE_ID, ROUTER_TYPE_ID], ['edit', 'delete'],
                                  write_regular_fields=False)
EMPTY_ROLE: dict[str, Any] = _role(EMPTY_ROLE_ID, [ROUTER_TYPE_ID], [])
EVERY_TYPE_ROLE: dict[str, Any] = _role(EVERY_TYPE_ROLE_ID, '*', ['view', 'create'])


def _grants(user_assignments: list[dict[str, Any]], roles: list[dict[str, Any]],
            group_ids: list[int] | None = None) -> AccessGrants:
    """The grants of a user in the given groups (default: the user group)"""
    return build_grants(user_assignments, roles, [USER_GROUP_ID] if group_ids is None else group_ids)


class TestRoleOperations:
    """role_operations"""

    def test_the_listed_operations(self) -> None:
        """Each as its enum member"""
        assert role_operations(EDIT_ROLE) == frozenset({EDIT, DELETE})

    def test_an_unknown_value_is_passed_over(self) -> None:
        """'read' is no operation"""
        assert role_operations(_role(VIEW_ROLE_ID, [SERVER_TYPE_ID], ['read', 'create'])) == frozenset({CREATE})

    @pytest.mark.parametrize('stored', [None, 'view', {'view': True}], ids=['none', 'string', 'dict'])
    def test_a_value_that_is_no_list_grants_nothing(self, stored: Any) -> None:
        """Fail closed"""
        assert role_operations({'operations': stored}) == frozenset()


class TestRestrictedTypes:
    """restricted_types"""

    def test_no_assigned_role_restricts_nothing(self) -> None:
        """Every Type is free"""
        assert restricted_types([]).is_empty()

    def test_the_named_types_together(self) -> None:
        """Every assigned role's Types, an empty-operations role's too"""
        assert restricted_types([VIEW_ROLE, EMPTY_ROLE]) == TypeSet.of([SERVER_TYPE_ID, ROUTER_TYPE_ID])

    def test_a_role_on_every_type_restricts_every_type(self) -> None:
        """E1"""
        assert restricted_types([VIEW_ROLE, EVERY_TYPE_ROLE]) == TypeSet.everything()

    def test_a_role_with_no_type_restricts_nothing(self) -> None:
        """types: [] - left by a Type delete"""
        assert restricted_types([_role(VIEW_ROLE_ID, [], ['view'])]).is_empty()


class TestGrantEntries:
    """grant_entries"""

    def test_an_entry_carries_its_assignment_and_role(self) -> None:
        """Every key read from its own document"""
        entries = grant_entries([_assignment(41, USER_GROUP_ID, EDIT_ROLE_ID)], {EDIT_ROLE_ID: EDIT_ROLE},
                                [USER_GROUP_ID])

        assert entries == (GrantEntry(assignment_id=41, role_id=EDIT_ROLE_ID,
                                      types=TypeSet.of([SERVER_TYPE_ID, ROUTER_TYPE_ID]),
                                      operations=frozenset({EDIT, DELETE}), write_regular_fields=False),)

    @pytest.mark.parametrize('assignment', [
        _assignment(41, OTHER_GROUP_ID, VIEW_ROLE_ID),
        _assignment(41, USER_GROUP_ID, EDIT_ROLE_ID),
        _assignment(41, USER_GROUP_ID, VIEW_ROLE_ID, scope={'location': {'within': 3}}),
    ], ids=['other-group', 'role-not-read', 'scope-condition'])
    def test_an_assignment_that_cannot_grant_is_passed_over(self, assignment: dict[str, Any]) -> None:
        """Fail closed"""
        assert not grant_entries([assignment], {VIEW_ROLE_ID: VIEW_ROLE}, [USER_GROUP_ID])

    def test_entries_are_ordered_by_assignment_id(self) -> None:
        """Ascending, whatever the read order"""
        assignments: list[dict[str, Any]] = [_assignment(45, USER_GROUP_ID, VIEW_ROLE_ID),
                                             _assignment(42, USER_GROUP_ID, EDIT_ROLE_ID)]
        entries = grant_entries(assignments, {VIEW_ROLE_ID: VIEW_ROLE, EDIT_ROLE_ID: EDIT_ROLE}, [USER_GROUP_ID])

        assert [entry.assignment_id for entry in entries] == [42, 45]

    def test_only_true_writes_regular_fields(self) -> None:
        """A truthy non-bool is no permission"""
        role: dict[str, Any] = {**VIEW_ROLE, 'write_regular_fields': 1}

        assert not grant_entries([_assignment(41, USER_GROUP_ID, VIEW_ROLE_ID)], {VIEW_ROLE_ID: role},
                                 [USER_GROUP_ID])[0].write_regular_fields


class TestAllows:
    """AccessGrants.allows"""

    def test_an_unrestricted_type_allows_everything_to_everyone(self) -> None:
        """No groups, no assignments, a Type no role names"""
        grants: AccessGrants = _grants([], [VIEW_ROLE], group_ids=[])

        assert all(grants.allows(operation, FREE_TYPE_ID) for operation in ScopeOperation)

    def test_a_restricted_type_allows_only_what_is_granted(self) -> None:
        """View on the server Type, nothing else"""
        grants: AccessGrants = _grants([_assignment(41, USER_GROUP_ID, VIEW_ROLE_ID)], [VIEW_ROLE])

        assert grants.allows(VIEW, SERVER_TYPE_ID)
        assert not grants.allows(EDIT, SERVER_TYPE_ID)

    def test_another_groups_assignment_restricts_but_grants_nothing(self) -> None:
        """The role is assigned - to someone else"""
        grants: AccessGrants = _grants([_assignment(41, OTHER_GROUP_ID, VIEW_ROLE_ID)], [VIEW_ROLE])

        assert grants.is_restricted(SERVER_TYPE_ID)
        assert not grants.allows(VIEW, SERVER_TYPE_ID)

    def test_the_groups_add_up(self) -> None:
        """View through one group, edit through the other"""
        grants: AccessGrants = _grants(
            [_assignment(41, USER_GROUP_ID, VIEW_ROLE_ID), _assignment(42, SECOND_USER_GROUP_ID, EDIT_ROLE_ID)],
            [VIEW_ROLE, EDIT_ROLE], group_ids=[USER_GROUP_ID, SECOND_USER_GROUP_ID])

        assert grants.allows(VIEW, SERVER_TYPE_ID) and grants.allows(EDIT, SERVER_TYPE_ID)
        assert not grants.allows(VIEW, ROUTER_TYPE_ID)

    def test_an_empty_operations_role_restricts_and_grants_nothing(self) -> None:
        """A15 - even to the group holding it"""
        grants: AccessGrants = _grants([_assignment(41, USER_GROUP_ID, EMPTY_ROLE_ID)], [EMPTY_ROLE])

        assert not any(grants.allows(operation, ROUTER_TYPE_ID) for operation in ScopeOperation)

    def test_no_groups_are_denied_a_restricted_type(self) -> None:
        """Fail closed - the assignment of the user's former group no longer counts"""
        grants: AccessGrants = _grants([_assignment(41, USER_GROUP_ID, VIEW_ROLE_ID)], [VIEW_ROLE], group_ids=[])

        assert not grants.allows(VIEW, SERVER_TYPE_ID)

    def test_a_role_on_every_type_elsewhere_denies_every_type(self) -> None:
        """E1 + E5: also a Type no role lists and an id no Type carries"""
        grants: AccessGrants = _grants([_assignment(41, OTHER_GROUP_ID, EVERY_TYPE_ROLE_ID)], [EVERY_TYPE_ROLE])

        assert not grants.allows(VIEW, FREE_TYPE_ID)
        assert not grants.allows(VIEW, ORPHAN_TYPE_ID)

    def test_a_role_on_every_type_held_grants_every_type(self) -> None:
        """Its operations only"""
        grants: AccessGrants = _grants([_assignment(41, USER_GROUP_ID, EVERY_TYPE_ROLE_ID)],
                                       [EVERY_TYPE_ROLE, VIEW_ROLE])

        assert grants.allows(CREATE, FREE_TYPE_ID) and grants.allows(VIEW, SERVER_TYPE_ID)
        assert not grants.allows(DELETE, FREE_TYPE_ID)


class TestWritesRegularFields:
    """AccessGrants.writes_regular_fields"""

    def test_only_a_role_granting_the_operation_counts(self) -> None:
        """The view role writes fields, the edit role does not - editing writes no field"""
        grants: AccessGrants = _grants(
            [_assignment(41, USER_GROUP_ID, VIEW_ROLE_ID), _assignment(42, USER_GROUP_ID, EDIT_ROLE_ID)],
            [VIEW_ROLE, EDIT_ROLE])

        assert grants.allows(EDIT, SERVER_TYPE_ID)
        assert not grants.writes_regular_fields(EDIT, SERVER_TYPE_ID)
        assert grants.writes_regular_fields(VIEW, SERVER_TYPE_ID)

    def test_an_unrestricted_type_writes_every_regular_field(self) -> None:
        """Nobody restricts it"""
        assert _grants([], [VIEW_ROLE], group_ids=[]).writes_regular_fields(EDIT, FREE_TYPE_ID)


class TestGrantingAssignmentIds:
    """AccessGrants.granting_assignment_ids"""

    def test_the_granting_assignments_ascending(self) -> None:
        """View through the view role (41) and the every-Type role (44), delete through the edit role (42) alone"""
        grants: AccessGrants = _grants(
            [_assignment(44, USER_GROUP_ID, EVERY_TYPE_ROLE_ID), _assignment(41, USER_GROUP_ID, VIEW_ROLE_ID),
             _assignment(42, USER_GROUP_ID, EDIT_ROLE_ID)],
            [VIEW_ROLE, EDIT_ROLE, EVERY_TYPE_ROLE])

        assert grants.granting_assignment_ids(VIEW, SERVER_TYPE_ID) == [41, 44]
        assert grants.granting_assignment_ids(DELETE, SERVER_TYPE_ID) == [42]
        assert grants.granting_assignment_ids(DELETE, FREE_TYPE_ID) == []


def test_the_grant_maps_are_read_only() -> None:
    """A caller cannot widen a user's grants"""
    grants: AccessGrants = _grants([], [])

    with pytest.raises(TypeError):
        grants.granted[VIEW] = TypeSet.everything()  # type: ignore[index]
