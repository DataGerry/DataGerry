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
Functional coverage of what a user-group delete may do to the group's members

A delete never leaves a member holding a group_id that resolves to nothing: without an ``action`` it is
refused while the group has members, and a ``MOVE`` into the group being deleted is refused too - both
before anything is written. An empty group still deletes without an action, and ``DELETE`` removes the
members together with their settings
"""
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.interface.rest_api.routes.user_management_routes.cmdb_groups.groups_constants import (
    GROUP_MEMBERS_NEED_ACTION_MSG,
    GROUP_MOVE_TARGET_IS_SOURCE_MSG,
)
from cmdb.models.group_model import CmdbUserGroup, GroupDeleteMode
from cmdb.models.settings_model import CmdbUserSetting
from cmdb.models.user_model import CmdbUser
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_URL: str = '/groups'

GROUP_ID: int = 9871
OTHER_GROUP_ID: int = 9872
MEMBER_ID: int = 9881
OTHER_MEMBER_ID: int = 9882
OUTSIDER_ID: int = 9883
ALL_GROUP_IDS: list[int] = [GROUP_ID, OTHER_GROUP_ID]
ALL_USER_IDS: list[int] = [MEMBER_ID, OTHER_MEMBER_ID, OUTSIDER_ID]


def _group_doc(public_id: int) -> dict[str, Any]:
    """A plain user group."""
    return {'public_id': public_id, 'name': f'delete-members-{public_id}', 'label': 'Delete members', 'rights': []}


def _user_doc(public_id: int, group_id: int) -> dict[str, Any]:
    """A user of the given group."""
    return {'public_id': public_id, 'user_name': f'delete-members-{public_id}', 'active': True,
            'group_id': group_id, 'registration_time': datetime.now(timezone.utc), 'password': 'hashed-stub'}


@pytest.fixture(name='collections')
def fixture_collections(database_manager: MongoDatabaseManager, database_name: str):
    """The groups, users and settings collections, cleaned around each test."""
    groups = database_manager.get_collection(CmdbUserGroup.COLLECTION, database_name)
    users = database_manager.get_collection(CmdbUser.COLLECTION, database_name)
    settings = database_manager.get_collection(CmdbUserSetting.COLLECTION, database_name)

    def _purge() -> None:
        groups.delete_many({'public_id': {'$in': ALL_GROUP_IDS}})
        users.delete_many({'public_id': {'$in': ALL_USER_IDS}})
        settings.delete_many({'user_id': {'$in': ALL_USER_IDS}})

    _purge()
    yield groups, users, settings
    _purge()


class TestNoAction:
    """DELETE /groups/<id> without an action."""

    def test_a_group_with_members_is_refused_and_nothing_changes(self, rest_api, collections) -> None:
        """The members would keep a group_id that resolves to nothing"""
        groups, users, _ = collections
        groups.insert_one(_group_doc(GROUP_ID))
        users.insert_one(_user_doc(MEMBER_ID, GROUP_ID))

        response = rest_api.delete(f'{ROUTE_URL}/{GROUP_ID}')

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'] == GROUP_MEMBERS_NEED_ACTION_MSG.format(public_id=GROUP_ID)
        assert groups.find_one({'public_id': GROUP_ID}) is not None
        assert users.find_one({'public_id': MEMBER_ID})['group_id'] == GROUP_ID

    def test_an_empty_group_is_deleted(self, rest_api, collections) -> None:
        """Nobody to strand, so no action is needed"""
        groups, _, _ = collections
        groups.insert_one(_group_doc(GROUP_ID))

        assert rest_api.delete(f'{ROUTE_URL}/{GROUP_ID}').status_code == HTTPStatus.ACCEPTED
        assert groups.find_one({'public_id': GROUP_ID}) is None


class TestMove:
    """action=MOVE."""

    def test_moving_into_the_group_being_deleted_is_refused(self, rest_api, collections) -> None:
        """Refused before anything is written: the group and its member stay as they were"""
        groups, users, _ = collections
        groups.insert_one(_group_doc(GROUP_ID))
        users.insert_one(_user_doc(MEMBER_ID, GROUP_ID))

        response = rest_api.delete(f'{ROUTE_URL}/{GROUP_ID}',
                                   query_string={'action': GroupDeleteMode.MOVE.value, 'group_id': GROUP_ID})

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'] == GROUP_MOVE_TARGET_IS_SOURCE_MSG.format(public_id=GROUP_ID)
        assert groups.find_one({'public_id': GROUP_ID}) is not None
        assert users.find_one({'public_id': MEMBER_ID})['group_id'] == GROUP_ID

    def test_moving_into_another_group_still_works(self, rest_api, collections) -> None:
        """The control"""
        groups, users, _ = collections
        groups.insert_many([_group_doc(GROUP_ID), _group_doc(OTHER_GROUP_ID)])
        users.insert_one(_user_doc(MEMBER_ID, GROUP_ID))

        response = rest_api.delete(f'{ROUTE_URL}/{GROUP_ID}',
                                   query_string={'action': GroupDeleteMode.MOVE.value, 'group_id': OTHER_GROUP_ID})

        assert response.status_code == HTTPStatus.ACCEPTED
        assert users.find_one({'public_id': MEMBER_ID})['group_id'] == OTHER_GROUP_ID


class TestDelete:
    """action=DELETE."""

    def test_the_members_go_with_their_settings_and_nobody_else(self, rest_api, collections) -> None:
        """Exactly the members; a user of another group and their settings are untouched"""
        groups, users, settings = collections
        groups.insert_many([_group_doc(GROUP_ID), _group_doc(OTHER_GROUP_ID)])
        users.insert_many([_user_doc(MEMBER_ID, GROUP_ID), _user_doc(OTHER_MEMBER_ID, GROUP_ID),
                           _user_doc(OUTSIDER_ID, OTHER_GROUP_ID)])
        settings.insert_many([{'user_id': user_id, 'resource': 'table', 'payloads': []} for user_id in ALL_USER_IDS])

        response = rest_api.delete(f'{ROUTE_URL}/{GROUP_ID}', query_string={'action': GroupDeleteMode.DELETE.value})

        assert response.status_code == HTTPStatus.ACCEPTED
        assert {user['public_id'] for user in users.find({'public_id': {'$in': ALL_USER_IDS}})} == {OUTSIDER_ID}
        assert {row['user_id'] for row in settings.find({'user_id': {'$in': ALL_USER_IDS}})} == {OUTSIDER_ID}
