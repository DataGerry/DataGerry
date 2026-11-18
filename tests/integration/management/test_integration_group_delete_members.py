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
Integration tests for the member side of a user-group delete, against a real MongoDB

``UsersManager.has_group_members`` is the question the delete route asks before it lets a group go
without an action, so it is checked on real documents. And the DELETE mode removes exactly the members
it read: a user who joins the group between the read and the delete is not deleted with them - which is
what keeps an account and its settings together. The sole members - whose only group it is - are told apart from the
members in other groups too, on real lists: only the sole ones are moved or deleted, the others lose the group, and
taking it out never empties a list
"""
from datetime import datetime, timezone
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.users_manager import UsersManager
from cmdb.models.group_model import GroupDeleteMode
from cmdb.models.settings_model import CmdbUserSetting
from cmdb.models.user_model import CmdbUser
# -------------------------------------------------------------------------------------------------------------------- #

GROUP_ID: int = 9921
EMPTY_GROUP_ID: int = 9922
KEPT_GROUP_ID: int = 9923
TARGET_GROUP_ID: int = 9924
MEMBER_ID: int = 9931
LATE_JOINER_ID: int = 9932
SHARED_MEMBER_ID: int = 9933
ALL_USER_IDS: list[int] = [MEMBER_ID, LATE_JOINER_ID, SHARED_MEMBER_ID]


def _user_doc(public_id: int, group_id: int) -> dict[str, Any]:
    """A user of the given group."""
    return {'public_id': public_id, 'user_name': f'group-delete-{public_id}', 'active': True,
            'group_ids': [group_id], 'registration_time': datetime.now(timezone.utc), 'password': 'hashed-stub'}


@pytest.fixture(name='users_manager')
def fixture_users_manager(rest_api, database_manager: MongoDatabaseManager, database_name: str):
    """A real UsersManager; the test users and their settings are removed around each test."""
    users = database_manager.get_collection(CmdbUser.COLLECTION, database_name)
    settings = database_manager.get_collection(CmdbUserSetting.COLLECTION, database_name)

    def _purge() -> None:
        users.delete_many({'public_id': {'$in': ALL_USER_IDS}})
        settings.delete_many({'user_id': {'$in': ALL_USER_IDS}})

    _purge()
    with rest_api.application.app_context():
        yield UsersManager(database_manager)
    _purge()


def _users(database_manager: MongoDatabaseManager, database_name: str):
    """The users collection."""
    return database_manager.get_collection(CmdbUser.COLLECTION, database_name)


class TestHasGroupMembers:
    """The route's pre-delete question."""

    def test_a_group_with_a_member(self, users_manager: UsersManager, database_manager: MongoDatabaseManager,
                                   database_name: str) -> None:
        """One stored user is enough"""
        _users(database_manager, database_name).insert_one(_user_doc(MEMBER_ID, GROUP_ID))

        assert users_manager.has_group_members(GROUP_ID) is True

    def test_an_empty_group(self, users_manager: UsersManager) -> None:
        """No user holds the id"""
        assert users_manager.has_group_members(EMPTY_GROUP_ID) is False


class TestDeleteRemovesTheMembersItRead:
    """DELETE mode against a group that gains a member between the read and the delete."""

    def test_a_late_joiner_keeps_account_and_settings(
        self, users_manager: UsersManager, database_manager: MongoDatabaseManager, database_name: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The read saw one member; the user added right after it is neither deleted nor orphaned"""
        users = _users(database_manager, database_name)
        settings = database_manager.get_collection(CmdbUserSetting.COLLECTION, database_name)
        users.insert_one(_user_doc(MEMBER_ID, GROUP_ID))
        settings.insert_many([{'user_id': user_id, 'resource': 'table', 'payloads': []}
                              for user_id in (MEMBER_ID, LATE_JOINER_ID)])
        original_find = users_manager.find

        def _find_then_a_user_joins(*args: Any, **kwargs: Any):
            members = list(original_find(*args, **kwargs))

            # Once, right after the first read - the member read; the sole-member read that follows already sees them
            if users.count_documents({'public_id': LATE_JOINER_ID}) == 0:
                users.insert_one(_user_doc(LATE_JOINER_ID, GROUP_ID))

            return members

        monkeypatch.setattr(users_manager, 'find', _find_then_a_user_joins)

        users_manager.handle_users_on_group_delete(GROUP_ID, GroupDeleteMode.DELETE, None)

        assert users.find_one({'public_id': MEMBER_ID}) is None
        assert users.find_one({'public_id': LATE_JOINER_ID}) is not None
        assert {row['user_id'] for row in settings.find({'user_id': {'$in': ALL_USER_IDS}})} == {LATE_JOINER_ID}


class TestSoleAndSharedMembers:
    """Who is moved or deleted, and who only loses the group."""

    @staticmethod
    def _seed(database_manager: MongoDatabaseManager, database_name: str) -> Any:
        """A sole member, and a member in a second group too"""
        users = _users(database_manager, database_name)
        users.insert_many([_user_doc(MEMBER_ID, GROUP_ID),
                           {**_user_doc(SHARED_MEMBER_ID, GROUP_ID), 'group_ids': [GROUP_ID, KEPT_GROUP_ID]}])

        return users

    def test_the_sole_members_are_read_apart(self, users_manager: UsersManager,
                                             database_manager: MongoDatabaseManager, database_name: str) -> None:
        """Both are members; only the one without another group is sole"""
        self._seed(database_manager, database_name)

        assert users_manager.read_group_members(GROUP_ID) == ([MEMBER_ID, SHARED_MEMBER_ID], [MEMBER_ID])
        assert users_manager.has_sole_members(GROUP_ID) is True
        assert users_manager.has_sole_members(KEPT_GROUP_ID) is False

    def test_a_move_moves_the_sole_member_only(self, users_manager: UsersManager,
                                               database_manager: MongoDatabaseManager, database_name: str) -> None:
        """The sole member is in the target; the shared one keeps only its other group"""
        users = self._seed(database_manager, database_name)

        users_manager.handle_users_on_group_delete(GROUP_ID, GroupDeleteMode.MOVE, TARGET_GROUP_ID)

        assert users.find_one({'public_id': MEMBER_ID})['group_ids'] == [TARGET_GROUP_ID]
        assert users.find_one({'public_id': SHARED_MEMBER_ID})['group_ids'] == [KEPT_GROUP_ID]

    def test_a_delete_deletes_the_sole_member_only(self, users_manager: UsersManager,
                                                   database_manager: MongoDatabaseManager, database_name: str) -> None:
        """The shared member stays, without the group"""
        users = self._seed(database_manager, database_name)

        users_manager.handle_users_on_group_delete(GROUP_ID, GroupDeleteMode.DELETE, None)

        assert users.find_one({'public_id': MEMBER_ID}) is None
        assert users.find_one({'public_id': SHARED_MEMBER_ID})['group_ids'] == [KEPT_GROUP_ID]

    def test_taking_the_group_out_never_empties_a_list(self, users_manager: UsersManager,
                                                       database_manager: MongoDatabaseManager,
                                                       database_name: str) -> None:
        """A user named as shared whose other group went in the meantime keeps this one"""
        users = self._seed(database_manager, database_name)

        users_manager.remove_group_from_users([MEMBER_ID, SHARED_MEMBER_ID], GROUP_ID)

        assert users.find_one({'public_id': MEMBER_ID})['group_ids'] == [GROUP_ID]
        assert users.find_one({'public_id': SHARED_MEMBER_ID})['group_ids'] == [KEPT_GROUP_ID]
