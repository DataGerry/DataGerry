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
Unit tests for user_management_routes.group_membership_guard

Pure: the managers, the grants and the caller's rights are stand-ins. Pinned: only added groups count; a group is
beyond the caller by a right not held and by a role reaching beyond, each part once; an administrator and an empty
addition read nothing; the refusal names each group beyond, the others pass silently
"""
from http import HTTPStatus
from typing import Any
from unittest.mock import MagicMock

import pytest
from werkzeug.exceptions import HTTPException

from cmdb.models.group_model import CmdbUserGroup
from cmdb.models.right_model.all_rights import ALL_RIGHTS_FLAT
from cmdb.models.user_model import CmdbUser
from cmdb.interface.rest_api.routes.user_management_routes import group_membership_guard as guard
from cmdb.interface.rest_api.routes.user_management_routes.group_membership_guard import (
    abort_if_adding_groups_beyond,
    added_group_ids,
    group_beyond_caller,
)
from cmdb.interface.rest_api.routes.user_management_routes.users_constants import (
    MEMBERSHIP_BEYOND_MSG,
    MEMBERSHIP_GROUP_PART,
    MEMBERSHIP_RIGHTS_PART,
)
# -------------------------------------------------------------------------------------------------------------------- #

CALLER: CmdbUser = CmdbUser(public_id=61, user_name='member-editor', active=True, group_ids=[21])
ADMINISTRATOR: CmdbUser = CmdbUser(public_id=62, user_name='admin', active=True, group_ids=[1])
HELD_RIGHT: str = 'base.framework.object.view'
UNHELD_RIGHT: str = 'base.framework.type.edit'
STRONG_GROUP_ID: int = 31
WEAK_GROUP_ID: int = 32
ROLE: dict[str, Any] = {'public_id': 41, 'types': [5], 'operations': ['edit']}
REACH_PART: str = 'edit on Types [5]'


def _held(*names: str) -> MagicMock:
    """The caller's rights: exactly the names given"""
    held = MagicMock()
    held.grants.side_effect = lambda name: name in names

    return held


class TestAddedGroupIds:
    """What a write adds"""

    @pytest.mark.parametrize('before, after, expected', [
        ([], [3, 1], [1, 3]), ([1, 2], [2, 1], []), ([1, 2], [2], []), ([1], [1, 4, 3], [3, 4]),
    ], ids=['create', 'reordered', 'removal', 'two-added'])
    def test_after_minus_before_ascending(self, before: list[int], after: list[int], expected: list[int]) -> None:
        """A kept group and a removal add nothing"""
        assert added_group_ids(before, after) == expected


class TestGroupBeyondCaller:
    """What one group holds beyond the caller"""

    def test_nothing_beyond(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Held rights, a role within reach"""
        monkeypatch.setattr(guard, 'beyond_reach', MagicMock(return_value=[]))

        assert not group_beyond_caller(_held(HELD_RIGHT), MagicMock(), [HELD_RIGHT], [ROLE])

    def test_the_rights_part_then_each_reach_part_once(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Two roles reaching the same way name it once"""
        monkeypatch.setattr(guard, 'beyond_reach', MagicMock(return_value=[REACH_PART]))

        assert group_beyond_caller(_held(HELD_RIGHT), MagicMock(), [HELD_RIGHT, UNHELD_RIGHT], [ROLE, ROLE]) == [
            MEMBERSHIP_RIGHTS_PART.format(names=[UNHELD_RIGHT]), REACH_PART]

    def test_no_grants_judges_no_role(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A group without assignments - the grants were not read"""
        reach = MagicMock(return_value=[REACH_PART])
        monkeypatch.setattr(guard, 'beyond_reach', reach)

        assert not group_beyond_caller(_held(HELD_RIGHT), None, [HELD_RIGHT], [ROLE])
        reach.assert_not_called()


@pytest.fixture(name='reads')
def fixture_reads(monkeypatch: pytest.MonkeyPatch) -> dict[str, MagicMock]:
    """A strong group (an unheld right + a role reaching beyond) and a weak one (a held right, no assignment)"""
    groups_manager, assignments_manager, roles_manager = MagicMock(), MagicMock(), MagicMock()
    rights = {right.name: right for right in ALL_RIGHTS_FLAT}
    groups_manager.get_groups.return_value = [
        CmdbUserGroup(public_id=STRONG_GROUP_ID, name='strong', label='S', rights=[rights[UNHELD_RIGHT]]),
        CmdbUserGroup(public_id=WEAK_GROUP_ID, name='weak', label='W', rights=[rights[HELD_RIGHT]]),
    ]
    assignments_manager.assignments_of_groups.return_value = [
        {'public_id': 51, 'group_id': STRONG_GROUP_ID, 'role_id': ROLE['public_id'], 'scope': '*'}]
    roles_manager.roles_by_ids.return_value = [ROLE]
    managers = {'GROUPS': groups_manager, 'ACCESS_ASSIGNMENTS': assignments_manager, 'SCOPE_ROLES': roles_manager}
    provider = MagicMock()
    provider.get_manager.side_effect = lambda manager_type, _user: managers[manager_type.name]
    load = MagicMock(return_value='grants')
    reach = MagicMock(return_value=[REACH_PART])
    monkeypatch.setattr(guard, 'ManagerProvider', provider)
    monkeypatch.setattr(guard, 'load_grants', load)
    monkeypatch.setattr(guard, 'beyond_reach', reach)
    monkeypatch.setattr(guard, 'request_groups', MagicMock(return_value=_held(HELD_RIGHT)))

    return {'provider': provider, 'load': load, 'reach': reach, 'roles': roles_manager}


class TestAbortIfAddingGroupsBeyond:
    """The refusal of the three writes"""

    def test_the_strong_group_is_named_with_both_parts(self, reads: dict[str, MagicMock]) -> None:
        """The weak group passes silently"""
        with pytest.raises(HTTPException) as raised:
            abort_if_adding_groups_beyond(CALLER, [WEAK_GROUP_ID, STRONG_GROUP_ID])

        part: str = MEMBERSHIP_GROUP_PART.format(
            group_id=STRONG_GROUP_ID, beyond=f"{MEMBERSHIP_RIGHTS_PART.format(names=[UNHELD_RIGHT])}, {REACH_PART}")
        assert raised.value.code == HTTPStatus.FORBIDDEN
        assert raised.value.description == MEMBERSHIP_BEYOND_MSG.format(details=part)
        reads['roles'].roles_by_ids.assert_called_once_with([ROLE['public_id']])
        reads['reach'].assert_called_once_with('grants', ROLE)

    @pytest.mark.parametrize('caller, group_ids', [(ADMINISTRATOR, [STRONG_GROUP_ID]), (CALLER, [])],
                             ids=['administrator', 'nothing-added'])
    def test_reads_nothing(self, reads: dict[str, MagicMock], caller: CmdbUser, group_ids: list[int]) -> None:
        """Exempt, or nothing to judge"""
        abort_if_adding_groups_beyond(caller, group_ids)

        reads['provider'].get_manager.assert_not_called()
        reads['load'].assert_not_called()

    def test_no_assignment_reads_no_grants_and_no_roles(self, reads: dict[str, MagicMock]) -> None:
        """Only the rights are judged - the weak group passes"""
        reads['provider'].get_manager.side_effect = None
        manager = MagicMock()
        manager.get_groups.return_value = []
        manager.assignments_of_groups.return_value = []
        reads['provider'].get_manager.return_value = manager

        abort_if_adding_groups_beyond(CALLER, [WEAK_GROUP_ID])

        reads['load'].assert_not_called()
        manager.roles_by_ids.assert_not_called()
