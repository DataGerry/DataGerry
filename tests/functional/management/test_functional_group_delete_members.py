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

A delete never leaves a member holding a group id that resolves to nothing. Every member loses the group; a member in
other groups too keeps them and nothing else happens to it, whatever the action. The ``action`` is about the sole
members, whose only group it is: without one the delete is refused while there are any, and a ``MOVE`` into the group
being deleted is refused too - both before anything is written. A group without sole members deletes without an
action, ``MOVE`` puts the sole members into the target, and ``DELETE`` removes them together with their settings
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
KEPT_GROUP_ID: int = 9873
MEMBER_ID: int = 9881
OTHER_MEMBER_ID: int = 9882
OUTSIDER_ID: int = 9883
ALL_GROUP_IDS: list[int] = [GROUP_ID, OTHER_GROUP_ID, KEPT_GROUP_ID]
ALL_USER_IDS: list[int] = [MEMBER_ID, OTHER_MEMBER_ID, OUTSIDER_ID]


def _group_doc(public_id: int) -> dict[str, Any]:
    """A plain user group."""
    return {'public_id': public_id, 'name': f'delete-members-{public_id}', 'label': 'Delete members', 'rights': []}


def _user_doc(public_id: int, group_id: int) -> dict[str, Any]:
    """A user of the given group."""
    return {'public_id': public_id, 'user_name': f'delete-members-{public_id}', 'active': True,
            'group_ids': [group_id], 'registration_time': datetime.now(timezone.utc), 'password': 'hashed-stub'}


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
        """The members would keep a group id that resolves to nothing"""
        groups, users, _ = collections
        groups.insert_one(_group_doc(GROUP_ID))
        users.insert_one(_user_doc(MEMBER_ID, GROUP_ID))

        response = rest_api.delete(f'{ROUTE_URL}/{GROUP_ID}')

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'] == GROUP_MEMBERS_NEED_ACTION_MSG.format(public_id=GROUP_ID)
        assert groups.find_one({'public_id': GROUP_ID}) is not None
        assert users.find_one({'public_id': MEMBER_ID})['group_ids'] == [GROUP_ID]

    def test_a_group_whose_members_all_have_other_groups_is_deleted(self, rest_api, collections) -> None:
        """Nobody is left without a group: each member only loses this one"""
        groups, users, _ = collections
        groups.insert_many([_group_doc(GROUP_ID), _group_doc(KEPT_GROUP_ID)])
        users.insert_one({**_user_doc(MEMBER_ID, GROUP_ID), 'group_ids': [GROUP_ID, KEPT_GROUP_ID]})

        assert rest_api.delete(f'{ROUTE_URL}/{GROUP_ID}').status_code == HTTPStatus.ACCEPTED
        assert groups.find_one({'public_id': GROUP_ID}) is None
        assert users.find_one({'public_id': MEMBER_ID})['group_ids'] == [KEPT_GROUP_ID]

    def test_one_sole_member_is_enough_to_refuse(self, rest_api, collections) -> None:
        """A shared member beside a sole one: refused, nothing written"""
        groups, users, _ = collections
        groups.insert_many([_group_doc(GROUP_ID), _group_doc(KEPT_GROUP_ID)])
        users.insert_many([{**_user_doc(MEMBER_ID, GROUP_ID), 'group_ids': [GROUP_ID, KEPT_GROUP_ID]},
                           _user_doc(OTHER_MEMBER_ID, GROUP_ID)])

        assert rest_api.delete(f'{ROUTE_URL}/{GROUP_ID}').status_code == HTTPStatus.BAD_REQUEST
        assert users.find_one({'public_id': MEMBER_ID})['group_ids'] == [GROUP_ID, KEPT_GROUP_ID]

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
        assert users.find_one({'public_id': MEMBER_ID})['group_ids'] == [GROUP_ID]

    def test_moving_into_another_group_still_works(self, rest_api, collections) -> None:
        """The control"""
        groups, users, _ = collections
        groups.insert_many([_group_doc(GROUP_ID), _group_doc(OTHER_GROUP_ID)])
        users.insert_one(_user_doc(MEMBER_ID, GROUP_ID))

        response = rest_api.delete(f'{ROUTE_URL}/{GROUP_ID}',
                                   query_string={'action': GroupDeleteMode.MOVE.value, 'group_id': OTHER_GROUP_ID})

        assert response.status_code == HTTPStatus.ACCEPTED
        assert users.find_one({'public_id': MEMBER_ID})['group_ids'] == [OTHER_GROUP_ID]

    def test_only_the_sole_members_are_moved(self, rest_api, collections) -> None:
        """A member in other groups only loses the deleted one - it is not put into the target"""
        groups, users, _ = collections
        groups.insert_many([_group_doc(GROUP_ID), _group_doc(OTHER_GROUP_ID), _group_doc(KEPT_GROUP_ID)])
        users.insert_many([
            {**_user_doc(MEMBER_ID, GROUP_ID), 'group_ids': [GROUP_ID, KEPT_GROUP_ID]},
            _user_doc(OTHER_MEMBER_ID, GROUP_ID),
        ])

        response = rest_api.delete(f'{ROUTE_URL}/{GROUP_ID}',
                                   query_string={'action': GroupDeleteMode.MOVE.value, 'group_id': OTHER_GROUP_ID})

        assert response.status_code == HTTPStatus.ACCEPTED
        assert users.find_one({'public_id': MEMBER_ID})['group_ids'] == [KEPT_GROUP_ID]
        assert users.find_one({'public_id': OTHER_MEMBER_ID})['group_ids'] == [OTHER_GROUP_ID]


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

    def test_a_member_in_other_groups_is_kept_with_its_settings(self, rest_api, collections) -> None:
        """Only the sole member is deleted; the shared one loses the group and keeps everything else"""
        groups, users, settings = collections
        groups.insert_many([_group_doc(GROUP_ID), _group_doc(KEPT_GROUP_ID)])
        users.insert_many([{**_user_doc(MEMBER_ID, GROUP_ID), 'group_ids': [GROUP_ID, KEPT_GROUP_ID]},
                           _user_doc(OTHER_MEMBER_ID, GROUP_ID)])
        settings.insert_many([{'user_id': user_id, 'resource': 'table', 'payloads': []}
                              for user_id in (MEMBER_ID, OTHER_MEMBER_ID)])

        response = rest_api.delete(f'{ROUTE_URL}/{GROUP_ID}', query_string={'action': GroupDeleteMode.DELETE.value})

        assert response.status_code == HTTPStatus.ACCEPTED
        assert users.find_one({'public_id': MEMBER_ID})['group_ids'] == [KEPT_GROUP_ID]
        assert users.find_one({'public_id': OTHER_MEMBER_ID}) is None
        assert {row['user_id'] for row in settings.find({'user_id': {'$in': ALL_USER_IDS}})} == {MEMBER_ID}
