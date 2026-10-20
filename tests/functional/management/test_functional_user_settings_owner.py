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
Functional tests for who may use a user's settings, and for the two races the unique index decides

A user's settings are their own: every route asks for ``base.user-management.user.edit`` with the owner
carve-out. Pinned on all five routes, with members of the seeded ``user`` group:

  - another user is refused 403 naming the right, and nothing is read, written or deleted
  - the owner reaches their own settings without any right
  - a group holding ``base.user-management.user.edit`` reaches anyone's settings

And the races: a create that loses to a concurrent one answers the "already exists" 400, an update-or-create
whose insert loses updates the setting instead.
"""
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.user_settings_manager import UserSettingsManager
from cmdb.models.group_model import CmdbUserGroup
from cmdb.models.group_model.group_constants import USER_GROUP_ID
from cmdb.models.settings_model import CmdbUserSetting
from cmdb.models.user_model import CmdbUser
from cmdb.interface.rest_api.routes.user_management_routes.user_settings_constants import (
    USER_SETTINGS_RIGHT,
    UserSettingMessage,
)
# -------------------------------------------------------------------------------------------------------------------- #

RIGHT_REFUSAL: str = 'User has not the required right {right}'

# What the routes answer on success: create 201, reads 200, update / delete 202
SUCCESS: tuple[HTTPStatus, ...] = (HTTPStatus.OK, HTTPStatus.CREATED, HTTPStatus.ACCEPTED)

OWNER_ID: int = 88901
STRANGER_ID: int = 88902
EDITOR_ID: int = 88903
EDITOR_GROUP_ID: int = 88911
ALL_USER_IDS: list[int] = [OWNER_ID, STRANGER_ID, EDITOR_ID]

STORED: str = 'stored-resource'
NEW: str = 'new-resource'
STORED_PAYLOADS: list[dict[str, Any]] = [{'id': 'objects-table', 'page_size': 25}]
NEW_PAYLOADS: list[dict[str, Any]] = [{'id': 'objects-table', 'page_size': 50}]


def _body(resource: str, payloads: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """A whole setting, as POST / PUT take it"""
    return {'resource': resource, 'user_id': OWNER_ID, 'payloads': payloads or [], 'setting_type': 'GLOBAL'}


def _url(suffix: str = '/') -> str:
    """A path under the owner's settings"""
    return f'/users/{OWNER_ID}/settings{suffix}'


# (label, method, path under the owner's settings, body) - one per route
ROUTES: list[tuple[str, str, str, dict[str, Any] | None]] = [
    ('create', 'post', '/', _body(NEW)),
    ('list', 'get', '/', None),
    ('read', 'get', f'/{STORED}', None),
    ('update', 'put', f'/{STORED}', _body(STORED, NEW_PAYLOADS)),
    ('delete', 'delete', f'/{STORED}', None),
]
ROUTE_IDS: list[str] = [route[0] for route in ROUTES]


def _user(user_id: int, group_id: int) -> CmdbUser:
    """The model the test client sends as"""
    return CmdbUser(public_id=user_id, user_name=f'settings-{user_id}', active=True, group_id=group_id)


@pytest.fixture(name='users')
def fixture_users(database_manager: MongoDatabaseManager, database_name: str):
    """The owner and a stranger in the seeded user group, an editor holding user.edit; the owner's one setting"""
    groups = database_manager.get_collection(CmdbUserGroup.COLLECTION, database_name)
    users = database_manager.get_collection(CmdbUser.COLLECTION, database_name)
    settings = database_manager.get_collection(CmdbUserSetting.COLLECTION, database_name)

    def _purge() -> None:
        groups.delete_many({'public_id': EDITOR_GROUP_ID})
        users.delete_many({'public_id': {'$in': ALL_USER_IDS}})
        settings.delete_many({'user_id': {'$in': ALL_USER_IDS}})

    _purge()
    groups.insert_one({'public_id': EDITOR_GROUP_ID, 'name': 'settings-editors', 'label': 'Editors',
                       'rights': [USER_SETTINGS_RIGHT]})
    users.insert_many([{'public_id': user_id, 'user_name': f'settings-{user_id}', 'active': True, 'group_id': group,
                        'registration_time': datetime.now(timezone.utc)}
                       for user_id, group in ((OWNER_ID, USER_GROUP_ID), (STRANGER_ID, USER_GROUP_ID),
                                              (EDITOR_ID, EDITOR_GROUP_ID))])
    settings.insert_one({**_body(STORED, STORED_PAYLOADS), 'public_id': 889001})
    yield {
        'owner': _user(OWNER_ID, USER_GROUP_ID),
        'stranger': _user(STRANGER_ID, USER_GROUP_ID),
        'editor': _user(EDITOR_ID, EDITOR_GROUP_ID),
        'settings': settings,
    }
    _purge()


def _call(rest_api: Any, method: str, path: str, body: dict[str, Any] | None, user: CmdbUser) -> Any:
    """Sends one request as ``user``"""
    kwargs: dict[str, Any] = {'user': user}

    if body is not None:
        kwargs['json'] = body

    return getattr(rest_api, method)(_url(path), **kwargs)


def _owner_settings(users: dict[str, Any]) -> list[dict[str, Any]]:
    """The owner's stored settings, without storage keys"""
    return list(users['settings'].find({'user_id': OWNER_ID}, {'_id': 0, 'public_id': 0}).sort('resource', 1))


class TestAnotherUser:
    """A member of the seeded user group, on someone else's settings"""

    @pytest.mark.parametrize('label, method, path, body', ROUTES, ids=ROUTE_IDS)
    def test_is_refused_and_nothing_changes(self, rest_api, users: dict[str, Any], label: str, method: str,
                                            path: str, body: dict[str, Any] | None) -> None:
        """403 naming the right; the owner's settings are as they were and none leak into the body"""
        del label
        before = _owner_settings(users)

        response = _call(rest_api, method, path, body, users['stranger'])

        assert response.status_code == HTTPStatus.FORBIDDEN
        assert response.get_json()['message'] == RIGHT_REFUSAL.format(right=USER_SETTINGS_RIGHT)
        assert 'page_size' not in response.get_data(as_text=True)
        assert _owner_settings(users) == before


class TestTheOwner:
    """Their own settings, without any right"""

    @pytest.mark.parametrize('label, method, path, body', ROUTES, ids=ROUTE_IDS)
    def test_reaches_every_route(self, rest_api, users: dict[str, Any], label: str, method: str, path: str,
                                 body: dict[str, Any] | None) -> None:
        """What the frontend does for everyone"""
        del label

        assert _call(rest_api, method, path, body, users['owner']).status_code in SUCCESS


class TestTheUserEditRight:
    """base.user-management.user.edit reaches anyone's settings"""

    @pytest.mark.parametrize('label, method, path, body', ROUTES, ids=ROUTE_IDS)
    def test_reaches_every_route(self, rest_api, users: dict[str, Any], label: str, method: str, path: str,
                                 body: dict[str, Any] | None) -> None:
        """An administrator can repair a broken setting"""
        del label

        assert _call(rest_api, method, path, body, users['editor']).status_code in SUCCESS


class TestTheRaces:
    """The unique (resource, user_id) index decides what the pre-read missed"""

    @pytest.fixture(autouse=True)
    def _unique_index(self, database_manager: MongoDatabaseManager, database_name: str):
        """The test session does not run the collection validator, so the declared index is built here"""
        collection = database_manager.get_collection(CmdbUserSetting.COLLECTION, database_name)
        existing: set[str] = set(collection.index_information())
        built: list[str] = [name for name in collection.create_indexes(CmdbUserSetting.get_index_keys())
                            if name not in existing]
        yield
        for name in built:
            collection.drop_index(name)

    def test_a_create_that_loses_answers_already_exists(self, rest_api, monkeypatch, users: dict[str, Any]) -> None:
        """The pre-read saw nothing; the insert hits the stored setting"""
        monkeypatch.setattr(UserSettingsManager, 'get_user_setting', lambda *_args, **_kwargs: None)

        response = _call(rest_api, 'post', '/', _body(STORED), users['owner'])

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'] == UserSettingMessage.EXISTS.format(resource=STORED)

    def test_an_update_whose_insert_loses_updates_instead(self, rest_api, monkeypatch,
                                                          users: dict[str, Any]) -> None:
        """The setting appeared between the read and the insert - it is updated, not refused"""
        monkeypatch.setattr(UserSettingsManager, 'get_user_setting', lambda *_args, **_kwargs: None)

        response = _call(rest_api, 'put', f'/{STORED}', _body(STORED, NEW_PAYLOADS), users['owner'])

        assert response.status_code == HTTPStatus.ACCEPTED
        stored = users['settings'].find_one({'user_id': OWNER_ID, 'resource': STORED})
        assert stored['payloads'] == NEW_PAYLOADS
        assert users['settings'].count_documents({'user_id': OWNER_ID, 'resource': STORED}) == 1
