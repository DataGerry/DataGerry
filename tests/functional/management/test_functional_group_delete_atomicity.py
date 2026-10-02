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
Functional tests: a user-group delete with a member redistribution is all-or-nothing

``DELETE /groups/<id>?action=MOVE|DELETE`` writes the members (moved, or deleted with their settings) and then
deletes the group. MongoDB runs standalone, so the route records every write in a WriteLedger first and undoes
them when a later one fails. These tests break each write in turn - failing outright, and applying then reporting
a failure - and compare the groups, the users and the settings with the snapshot taken before the request.
"""
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any, Callable

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import GroupsManager, UsersManager
from cmdb.interface.rest_api.routes.user_management_routes.cmdb_groups.groups_constants import (
    GROUP_ADMIN_MEMBER_MSG,
    GROUP_DELETE_UNDO_INCOMPLETE_MSG,
)
from cmdb.models.group_model import CmdbUserGroup, GroupDeleteMode, MASTER_RIGHT_NAME
from cmdb.models.settings_model import CmdbUserSetting
from cmdb.models.user_model import CmdbUser
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_URL: str = '/groups'

GROUP_ID: int = 9971
TARGET_GROUP_ID: int = 9972
MEMBER_ID: int = 9981
OTHER_MEMBER_ID: int = 9982
OUTSIDER_ID: int = 9983
SETTING_ID: int = 9991
ALL_GROUP_IDS: list[int] = [GROUP_ID, TARGET_GROUP_ID]
ALL_USER_IDS: list[int] = [MEMBER_ID, OTHER_MEMBER_ID, OUTSIDER_ID]
MOVE: dict[str, Any] = {'action': GroupDeleteMode.MOVE.value, 'group_id': TARGET_GROUP_ID}
DELETE: dict[str, Any] = {'action': GroupDeleteMode.DELETE.value}
RESIDUE_PREFIX: str = GROUP_DELETE_UNDO_INCOMPLETE_MSG.split('{', maxsplit=1)[0]


def _group_doc(public_id: int) -> dict[str, Any]:
    """A plain user group."""
    return {'public_id': public_id, 'name': f'atomic-delete-{public_id}', 'label': 'Atomic delete', 'rights': []}


def _user_doc(public_id: int, group_id: int) -> dict[str, Any]:
    """A user of the given group."""
    return {'public_id': public_id, 'user_name': f'atomic-delete-{public_id}', 'active': True,
            'group_id': group_id, 'registration_time': datetime(2026, 1, 1, tzinfo=timezone.utc),
            'password': 'hashed-stub'}


@pytest.fixture(name='collections', autouse=True)
def fixture_collections(database_manager: MongoDatabaseManager, database_name: str):
    """Two members of the group (one with two settings rows, one of them without a public_id) and an outsider."""
    groups = database_manager.get_collection(CmdbUserGroup.COLLECTION, database_name)
    users = database_manager.get_collection(CmdbUser.COLLECTION, database_name)
    settings = database_manager.get_collection(CmdbUserSetting.COLLECTION, database_name)

    def _purge() -> None:
        groups.delete_many({'public_id': {'$in': ALL_GROUP_IDS}})
        users.delete_many({'public_id': {'$in': ALL_USER_IDS}})
        settings.delete_many({'user_id': {'$in': ALL_USER_IDS}})

    _purge()
    groups.insert_many([_group_doc(GROUP_ID), _group_doc(TARGET_GROUP_ID)])
    users.insert_many([_user_doc(MEMBER_ID, GROUP_ID), _user_doc(OTHER_MEMBER_ID, GROUP_ID),
                       _user_doc(OUTSIDER_ID, TARGET_GROUP_ID)])
    settings.insert_many([
        {'public_id': SETTING_ID, 'resource': 'atomic-a', 'user_id': MEMBER_ID, 'payloads': [],
         'setting_type': 'APPLICATION'},
        {'resource': 'atomic-b', 'user_id': MEMBER_ID, 'payloads': [], 'setting_type': 'APPLICATION'},
    ])
    yield {'groups': groups, 'users': users, 'settings': settings}
    _purge()


def _snapshot(collections: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """
    Every test document. Users and settings with their `_id`: a batch delete is undone under the old identity. A
    group re-inserted by the single-document undo gets a fresh `_id`, which nothing references
    """
    return {
        'groups': sorted(({k: v for k, v in doc.items() if k != '_id'}
                          for doc in collections['groups'].find({'public_id': {'$in': ALL_GROUP_IDS}})),
                         key=lambda doc: doc['public_id']),
        'users': sorted(collections['users'].find({'public_id': {'$in': ALL_USER_IDS}}),
                        key=lambda doc: doc['public_id']),
        'settings': sorted(collections['settings'].find({'user_id': {'$in': ALL_USER_IDS}}),
                           key=lambda doc: doc['resource']),
    }


def _raiser(error: Exception) -> Callable[..., Any]:
    """A replacement that always raises the given error."""
    def _raise(*_args: Any, **_kwargs: Any) -> None:
        raise error

    return _raise


def _applied_once_then_raising(real: Callable[..., Any]) -> Callable[..., Any]:
    """The first call lands and reports a failure (a partial write, a lost acknowledgement); later calls work."""
    calls: dict[str, int] = {'count': 0}

    def _write(*args: Any, **kwargs: Any) -> Any:
        calls['count'] += 1
        result = real(*args, **kwargs)
        if calls['count'] == 1:
            raise RuntimeError('acknowledgement lost')
        return result

    return _write


def _delete(rest_api, query: dict[str, Any]):
    """DELETE the test group with the given redistribution."""
    return rest_api.delete(f'{ROUTE_URL}/{GROUP_ID}', query_string=query)


class TestMoveIsAllOrNothing:
    """action=MOVE: the members come back into the group whenever the group is not gone."""

    def test_the_ordinary_move_still_works(self, rest_api, collections) -> None:
        """The baseline: members moved, group gone, the outsider untouched."""
        response = _delete(rest_api, MOVE)

        assert response.status_code == HTTPStatus.ACCEPTED
        assert collections['groups'].find_one({'public_id': GROUP_ID}) is None
        assert {doc['group_id'] for doc in collections['users'].find({'public_id': {'$in': ALL_USER_IDS}})} \
            == {TARGET_GROUP_ID}

    def test_a_failed_group_delete_moves_the_members_back(self, rest_api, monkeypatch, collections) -> None:
        """The members were moved; the group would not go: they are back in it, and the answer is a 500."""
        before = _snapshot(collections)
        monkeypatch.setattr(GroupsManager, 'delete_group', _raiser(RuntimeError('down')))

        response = _delete(rest_api, MOVE)

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert _snapshot(collections) == before

    def test_an_applied_move_that_reported_failure_is_moved_back(self, rest_api, monkeypatch, collections) -> None:
        """The move landed and raised: the recorded inverse moves exactly those members back."""
        before = _snapshot(collections)
        monkeypatch.setattr(UsersManager, 'move_users', _applied_once_then_raising(UsersManager.move_users))

        response = _delete(rest_api, MOVE)

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert _snapshot(collections) == before

    def test_an_applied_group_delete_that_reported_failure_is_re_inserted(self, rest_api, monkeypatch,
                                                                          collections) -> None:
        """The group did go: it is back under its old id, with the members back in it."""
        before = _snapshot(collections)
        monkeypatch.setattr(GroupsManager, 'delete_group', _applied_once_then_raising(GroupsManager.delete_group))

        response = _delete(rest_api, MOVE)

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert _snapshot(collections) == before

    def test_a_move_back_that_fails_is_named(self, rest_api, monkeypatch, collections) -> None:
        """The group delete fails and so does the move back: the 500 names the moved users."""
        real_move = UsersManager.move_users
        calls: dict[str, int] = {'count': 0}

        def _move_once(*args: Any, **kwargs: Any) -> None:
            calls['count'] += 1
            if calls['count'] > 1:
                raise RuntimeError('move back failed')
            real_move(*args, **kwargs)

        monkeypatch.setattr(GroupsManager, 'delete_group', _raiser(RuntimeError('down')))
        monkeypatch.setattr(UsersManager, 'move_users', _move_once)

        response = _delete(rest_api, MOVE)
        message: str = response.get_json()['message']

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert message.startswith(RESIDUE_PREFIX)
        assert CmdbUser.COLLECTION in message
        assert str(MEMBER_ID) in message


class TestDeleteIsAllOrNothing:
    """action=DELETE: the members and their settings come back whenever the group is not gone."""

    def test_the_ordinary_delete_still_works(self, rest_api, collections) -> None:
        """The baseline: members and their settings gone, the outsider untouched."""
        response = _delete(rest_api, DELETE)

        assert response.status_code == HTTPStatus.ACCEPTED
        assert [doc['public_id'] for doc in collections['users'].find({'public_id': {'$in': ALL_USER_IDS}})] \
            == [OUTSIDER_ID]
        assert collections['settings'].count_documents({'user_id': {'$in': ALL_USER_IDS}}) == 0

    def test_a_failed_group_delete_restores_users_and_settings(self, rest_api, monkeypatch, collections) -> None:
        """Both batches were deleted; the group would not go: users and settings are back under their _ids."""
        before = _snapshot(collections)
        monkeypatch.setattr(GroupsManager, 'delete_group', _raiser(RuntimeError('down')))

        response = _delete(rest_api, DELETE)

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert _snapshot(collections) == before

    def test_a_failed_settings_delete_restores_the_users(self, rest_api, monkeypatch, collections) -> None:
        """The users were already deleted when their settings would not go: the users are back."""
        before = _snapshot(collections)
        monkeypatch.setattr(UsersManager, '_delete_user_settings', _raiser(RuntimeError('down')))

        response = _delete(rest_api, DELETE)

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert _snapshot(collections) == before

    def test_an_applied_settings_delete_restores_the_row_without_public_id(self, rest_api, monkeypatch,
                                                                           collections) -> None:
        """The settings did go: both rows are back, including the one no public_id identifies."""
        before = _snapshot(collections)
        monkeypatch.setattr(UsersManager, '_delete_user_settings',
                            _applied_once_then_raising(UsersManager._delete_user_settings))

        response = _delete(rest_api, DELETE)

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert _snapshot(collections) == before

    def test_a_user_re_insert_that_fails_is_named(self, rest_api, monkeypatch, collections) -> None:
        """The group delete fails and the users cannot be put back: the 500 names the deleted users."""
        monkeypatch.setattr(GroupsManager, 'delete_group', _raiser(RuntimeError('down')))
        monkeypatch.setattr(UsersManager, 'insert_many', _raiser(RuntimeError('re-insert failed')))

        response = _delete(rest_api, DELETE)
        message: str = response.get_json()['message']

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert message.startswith(RESIDUE_PREFIX)
        assert CmdbUser.COLLECTION in message
        assert str(MEMBER_ID) in message
        assert collections['groups'].find_one({'public_id': GROUP_ID}) is not None


class TestTheAdminRefusal:
    """The admin user among the members refuses a DELETE before anything is written."""

    def test_refused_before_any_write(self, rest_api, monkeypatch, collections) -> None:
        """400 with its own message; no member delete is even attempted."""
        users = collections['users']
        admin_group = users.find_one({'public_id': CmdbUser.ADMIN_PUBLIC_ID})['group_id']
        attempted: list[Any] = []
        monkeypatch.setattr(UsersManager, 'delete_users', lambda *args, **_kwargs: attempted.append(args))
        # The request is made as the admin, so the group keeps them authorised while they are in it
        collections['groups'].update_one({'public_id': GROUP_ID}, {'$set': {'rights': [MASTER_RIGHT_NAME]}})
        users.update_one({'public_id': CmdbUser.ADMIN_PUBLIC_ID}, {'$set': {'group_id': GROUP_ID}})

        try:
            before = _snapshot(collections)
            response = _delete(rest_api, DELETE)
            after = _snapshot(collections)
        finally:
            users.update_one({'public_id': CmdbUser.ADMIN_PUBLIC_ID}, {'$set': {'group_id': admin_group}})

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'] == GROUP_ADMIN_MEMBER_MSG
        assert not attempted
        assert after == before
