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
Unit tests for cmdb.framework.access_rules.type_access_states

A Type no assigned role names is open; one an unconditional assignment's role views is viewable; else locked. A role
on every Type restricts every Type. A change newly locking a Type is refused; newly opening one only unconfirmed
"""
from typing import Any

import pytest

from cmdb.framework.access_engine import TypeSet
from cmdb.framework.access_rules import (
    AccessRuleMessage,
    TypeAccessState,
    access_change_problems,
    assigned_roles,
    changed_types,
    involved_types,
    type_states,
    viewable_types,
)
# -------------------------------------------------------------------------------------------------------------------- #

SERVER_TYPE_ID: int = 11
ROUTER_TYPE_ID: int = 12
FREE_TYPE_ID: int = 13
OPEN = TypeAccessState.OPEN
VIEWABLE = TypeAccessState.VIEWABLE
LOCKED = TypeAccessState.LOCKED


def _role(public_id: int, types: Any, operations: list[str]) -> dict[str, Any]:
    """A stored scope role"""
    return {'public_id': public_id, 'types': types, 'operations': operations}


def _assignment(public_id: int, role_id: int, scope: Any = '*') -> dict[str, Any]:
    """A stored assignment"""
    return {'public_id': public_id, 'group_id': 21, 'role_id': role_id, 'scope': scope}


VIEW_ROLE: dict[str, Any] = _role(31, [SERVER_TYPE_ID], ['view', 'edit'])
EDIT_ROLE: dict[str, Any] = _role(32, [ROUTER_TYPE_ID], ['edit'])
EVERY_TYPE_ROLE: dict[str, Any] = _role(33, '*', ['delete'])
ROLES: dict[int, dict[str, Any]] = {role['public_id']: role for role in (VIEW_ROLE, EDIT_ROLE, EVERY_TYPE_ROLE)}
TYPE_IDS: list[int] = [SERVER_TYPE_ID, ROUTER_TYPE_ID, FREE_TYPE_ID]


class TestStates:
    """assigned_roles, viewable_types, type_states"""

    def test_assigned_roles_each_once(self) -> None:
        """A role assigned twice; an assignment of a role not read"""
        roles = assigned_roles([_assignment(41, 31), _assignment(42, 31), _assignment(43, 99)], ROLES)

        assert roles == [VIEW_ROLE]

    def test_viewable_types_need_view_and_the_unconditional_scope(self) -> None:
        """The edit role views nothing; a scope condition grants nothing"""
        assert viewable_types([_assignment(41, 31), _assignment(42, 32)], ROLES) == TypeSet.of([SERVER_TYPE_ID])
        assert viewable_types([_assignment(41, 31, scope={'x': 1})], ROLES).is_empty()

    def test_open_viewable_locked(self) -> None:
        """Servers viewed, routers restricted without view, the free Type open"""
        assert type_states([_assignment(41, 31), _assignment(42, 32)], ROLES, TYPE_IDS) == {
            SERVER_TYPE_ID: VIEWABLE, ROUTER_TYPE_ID: LOCKED, FREE_TYPE_ID: OPEN}

    def test_a_role_on_every_type_restricts_every_type(self) -> None:
        """Delete everywhere, view only on servers"""
        assert type_states([_assignment(41, 31), _assignment(43, 33)], ROLES, TYPE_IDS) == {
            SERVER_TYPE_ID: VIEWABLE, ROUTER_TYPE_ID: LOCKED, FREE_TYPE_ID: LOCKED}

    def test_no_assignment_leaves_everything_open(self) -> None:
        """A fresh installation"""
        assert set(type_states([], ROLES, TYPE_IDS).values()) == {OPEN}


class TestChange:
    """changed_types + access_change_problems"""

    def test_newly_locked_and_newly_opened(self) -> None:
        """A Type staying locked or open is no change"""
        before = {11: VIEWABLE, 12: VIEWABLE, 13: LOCKED, 14: OPEN, 15: LOCKED}
        after = {11: LOCKED, 12: OPEN, 13: LOCKED, 14: OPEN, 15: OPEN}

        assert changed_types(before, after) == ([11], [12, 15])

    def test_opening_an_open_type_to_locked(self) -> None:
        """An assignment without view on a Type nobody restricted locks it"""
        assert changed_types({11: OPEN}, {11: LOCKED}) == ([11], [])

    @pytest.mark.parametrize('unrestrict', [False, True], ids=['unconfirmed', 'confirmed'])
    def test_a_lock_is_always_refused(self, unrestrict: bool) -> None:
        """Confirming does not help"""
        assert access_change_problems([11], [], unrestrict) == [AccessRuleMessage.TYPES_LOCKED.value.format(ids=[11])]

    def test_an_opening_needs_the_confirmation(self) -> None:
        """Refused, then passing"""
        assert access_change_problems([], [12], False) == [AccessRuleMessage.TYPES_OPENED.value.format(ids=[12])]
        assert not access_change_problems([], [12], True)


def test_involved_types() -> None:
    """The Types of every involved role; every Type with a role on every Type"""
    assert involved_types([VIEW_ROLE, EDIT_ROLE]) == TypeSet.of([SERVER_TYPE_ID, ROUTER_TYPE_ID])
    assert involved_types([VIEW_ROLE, EVERY_TYPE_ROLE]) == TypeSet.everything()
