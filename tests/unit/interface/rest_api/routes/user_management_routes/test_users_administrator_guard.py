# DATAGERRY - OpenSource Enterprise CMDB
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
Unit tests for the administrator rule of cmdb.interface.rest_api.routes.user_management_routes.users_helper

Pure tests: users are built in memory, the users manager is a MagicMock. Pinned: who is an administrator, what a
non-administrator is refused (403) on a create and an update, what passes - an administrator's own writes, a
non-administrator's writes on ordinary users, the profile fields of an administrator - and the last-administrator
guard (400), which asks the database only for a write that could remove an administrator.
"""
from http import HTTPStatus
from typing import Any
from unittest.mock import MagicMock

import pytest
from werkzeug.exceptions import HTTPException

from cmdb.interface.rest_api.routes.user_management_routes.users_helper import (
    abort_unless_administrator,
    guard_administrator_create,
    guard_administrator_update,
    guard_last_administrator,
    is_administrator,
)
from cmdb.models.group_model import ADMIN_GROUP_ID, USER_GROUP_ID
from cmdb.models.user_model import CmdbUser
# -------------------------------------------------------------------------------------------------------------------- #

ADMIN_ID: int = 41
DELEGATE_ID: int = 42
TARGET_ID: int = 43
DELEGATE_GROUP_ID: int = 77


def _cmdb_user(public_id: int, group_id: int, active: bool = True) -> CmdbUser:
    """An in-memory user"""
    return CmdbUser(public_id=public_id, user_name=f'user-{public_id}', active=active, group_id=group_id,
                    first_name='First')


ADMIN: CmdbUser = _cmdb_user(ADMIN_ID, ADMIN_GROUP_ID)
DELEGATE: CmdbUser = _cmdb_user(DELEGATE_ID, DELEGATE_GROUP_ID)


def _body(user: CmdbUser, **changes: Any) -> dict[str, Any]:
    """The user as stored, with the given changes - what the edit screen sends back"""
    return {**CmdbUser.to_json(user), **changes}


def _refused(call: Any) -> HTTPException:
    """The HTTPException a call aborts with"""
    with pytest.raises(HTTPException) as refused:
        call()

    return refused.value


class TestWhoIsAnAdministrator:
    """Membership of the administrator group, nothing else."""

    @pytest.mark.parametrize('group_id, expected', [(ADMIN_GROUP_ID, True), (USER_GROUP_ID, False),
                                                    (DELEGATE_GROUP_ID, False)], ids=['admin', 'user', 'delegate'])
    def test_only_the_admin_group_counts(self, group_id: int, expected: bool) -> None:
        """A group holding every user right is still no administrator"""
        assert is_administrator(_cmdb_user(TARGET_ID, group_id)) is expected

    def test_an_administrator_passes(self) -> None:
        """No refusal"""
        abort_unless_administrator(ADMIN, 'do it')

    def test_anyone_else_is_refused_with_403_naming_the_action(self) -> None:
        """An authorisation refusal, not a payload error"""
        refusal = _refused(lambda: abort_unless_administrator(DELEGATE, 'do it'))

        assert (refusal.code, refusal.description) == (HTTPStatus.FORBIDDEN, 'Only an administrator may do it!')


class TestGuardAdministratorCreate:
    """Only an administrator creates an administrator."""

    def test_a_non_administrator_naming_the_admin_group_is_refused(self) -> None:
        """403"""
        refusal = _refused(lambda: guard_administrator_create(DELEGATE, {'group_id': ADMIN_GROUP_ID}))

        assert refusal.code == HTTPStatus.FORBIDDEN

    @pytest.mark.parametrize('caller, group_id', [(DELEGATE, USER_GROUP_ID), (ADMIN, ADMIN_GROUP_ID)],
                             ids=['ordinary user', 'administrator'])
    def test_everything_else_passes(self, caller: CmdbUser, group_id: int) -> None:
        """An ordinary user by anyone, an administrator by an administrator"""
        guard_administrator_create(caller, {'group_id': group_id})


class TestGuardAdministratorUpdate:
    """A non-administrator may not move anyone into the admin group, nor change an administrator's admin fields."""

    def test_an_administrator_may_change_anything(self) -> None:
        """Promotion, demotion, deactivation - no refusal"""
        target = _cmdb_user(TARGET_ID, ADMIN_GROUP_ID)

        guard_administrator_update(ADMIN, target, _body(target, group_id=USER_GROUP_ID, active=False))

    def test_promoting_an_ordinary_user_is_refused(self) -> None:
        """403"""
        target = _cmdb_user(TARGET_ID, USER_GROUP_ID)

        refusal = _refused(lambda: guard_administrator_update(DELEGATE, target, _body(target, group_id=ADMIN_GROUP_ID)))

        assert refusal.code == HTTPStatus.FORBIDDEN

    def test_regrouping_an_ordinary_user_elsewhere_passes(self) -> None:
        """Any group but the administrators'"""
        target = _cmdb_user(TARGET_ID, USER_GROUP_ID)

        guard_administrator_update(DELEGATE, target, _body(target, group_id=DELEGATE_GROUP_ID, active=False))

    @pytest.mark.parametrize('field, value', [('active', False), ('group_id', USER_GROUP_ID),
                                              ('user_name', 'renamed'), ('api_level', 3)])
    def test_an_administrators_administrative_field_is_refused(self, field: str, value: Any) -> None:
        """403 naming the field"""
        target = _cmdb_user(TARGET_ID, ADMIN_GROUP_ID)

        refusal = _refused(lambda: guard_administrator_update(DELEGATE, target, _body(target, **{field: value})))

        assert refusal.code == HTTPStatus.FORBIDDEN
        assert refusal.description == f"Only an administrator may change the field '{field}' of an administrator!"

    def test_an_administrators_profile_fields_pass_and_absent_admin_fields_are_pinned(self) -> None:
        """The name may change; an administrative field the body leaves out is copied from the stored one"""
        target = _cmdb_user(TARGET_ID, ADMIN_GROUP_ID)
        data: dict[str, Any] = {'first_name': 'Renamed'}

        guard_administrator_update(DELEGATE, target, data)

        assert (data['group_id'], data['active'], data['first_name']) == (ADMIN_GROUP_ID, True, 'Renamed')


class TestGuardLastAdministrator:
    """The administrator group keeps an active member; only a write that could remove one asks the database."""

    @staticmethod
    def _manager(other_active: bool) -> MagicMock:
        """A users manager answering whether another active administrator exists"""
        manager = MagicMock(name='users_manager')
        manager.has_other_active_member.return_value = other_active

        return manager

    @pytest.mark.parametrize('data, change', [
        ({'group_id': USER_GROUP_ID, 'active': True}, 'moved out of the administrator group'),
        ({'group_id': ADMIN_GROUP_ID, 'active': False}, 'deactivated'),
        (None, 'deleted'),
    ], ids=['demote', 'deactivate', 'delete'])
    def test_removing_the_last_administrator_is_refused(self, data: dict[str, Any] | None, change: str) -> None:
        """400 naming the user and the change"""
        manager = self._manager(other_active=False)
        target = _cmdb_user(TARGET_ID, ADMIN_GROUP_ID)

        refusal = _refused(lambda: guard_last_administrator(manager, target, data))

        assert refusal.code == HTTPStatus.BAD_REQUEST
        assert refusal.description == (
            f'The User with ID: {TARGET_ID} is the last active administrator and cannot be {change}!')
        manager.has_other_active_member.assert_called_once_with(ADMIN_GROUP_ID, TARGET_ID)

    def test_another_active_administrator_lets_it_pass(self) -> None:
        """The demotion goes ahead"""
        guard_last_administrator(self._manager(other_active=True), _cmdb_user(TARGET_ID, ADMIN_GROUP_ID), None)

    @pytest.mark.parametrize('target, data', [
        (_cmdb_user(TARGET_ID, USER_GROUP_ID), None),
        (_cmdb_user(TARGET_ID, ADMIN_GROUP_ID, active=False), None),
        (_cmdb_user(TARGET_ID, ADMIN_GROUP_ID), {'group_id': ADMIN_GROUP_ID, 'active': True}),
    ], ids=['not an administrator', 'already inactive', 'stays an active administrator'])
    def test_a_write_that_cannot_remove_an_administrator_reads_nothing(self, target: CmdbUser,
                                                                       data: dict[str, Any] | None) -> None:
        """No count at all"""
        manager = self._manager(other_active=False)

        guard_last_administrator(manager, target, data)

        manager.has_other_active_member.assert_not_called()
