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
Functional tests for the uniqueness of a CmdbUser's user_name and a CmdbUserGroup's name

Both are held by a unique index; each write route pre-checks the name so the ordinary clash is answered with
a message naming it, and the index's own refusal - what a concurrent write runs into - is answered with the
same message. Anything else the write raises is a 500: an outage is never reported as a taken name.

The names are compared EXACTLY as sent, the way the index compares them: another case or surrounding blanks
is a different name here (folding them is backlog T253 / T252), and a stored near-twin never blocks a write.

The indexes are built by the fixture: the test database never goes through CollectionValidator, so without
them a duplicate write would simply succeed and the race tests would prove nothing.
"""
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import GroupsManager, UsersManager
from cmdb.models.group_model import CmdbUserGroup, GroupKey
from cmdb.models.user_model import CmdbUser, CmdbUserKey
from cmdb.errors.database import DocumentNetworkError
from cmdb.interface.rest_api.routes.user_management_routes import users_routes
from cmdb.interface.rest_api.routes.user_management_routes.cmdb_groups import groups_routes
from cmdb.interface.rest_api.routes.user_management_routes.users_constants import USER_NAME_TAKEN_MESSAGE
from cmdb.interface.rest_api.routes.user_management_routes.cmdb_groups.groups_constants import (
    GROUP_NAME_TAKEN_MSG,
)
# -------------------------------------------------------------------------------------------------------------------- #

USERS_URL: str = '/users'
GROUPS_URL: str = '/groups'
DEFAULT_GROUP_ID: int = 1

TAKEN_USER_NAME: str = 'names-taken-user'
FREE_USER_NAME: str = 'names-free-user'
TAKEN_GROUP_NAME: str = 'names-taken-group'
FREE_GROUP_NAME: str = 'names-free-group'

# The spellings the index treats as different names, and so does the pre-check
NEAR_TWINS: dict[str, str] = {'other-case': 'Names-Taken-{kind}', 'padded': ' names-taken-{kind}'}

USER_NAMES: list[str] = [TAKEN_USER_NAME, FREE_USER_NAME] + [t.format(kind='User') for t in NEAR_TWINS.values()]
GROUP_NAMES: list[str] = [TAKEN_GROUP_NAME, FREE_GROUP_NAME] + [t.format(kind='Group') for t in NEAR_TWINS.values()]


def _user_payload(user_name: str) -> dict[str, Any]:
    """A CmdbUser body accepted by POST /users/ (the password only goes in on create)."""
    return {'user_name': user_name, 'active': True, 'group_id': DEFAULT_GROUP_ID, 'password': 'a-password'}


def _group_payload(name: str) -> dict[str, Any]:
    """A CmdbUserGroup body accepted by POST /groups/ and PUT /groups/<id>."""
    return {'name': name, 'label': name, 'rights': []}


@pytest.fixture(name='collections', autouse=True)
def fixture_collections(database_manager: MongoDatabaseManager, database_name: str):
    """Builds both unique indexes and removes every user and group these tests name, before and after."""
    users = database_manager.get_collection(CmdbUser.COLLECTION, database_name)
    groups = database_manager.get_collection(CmdbUserGroup.COLLECTION, database_name)

    database_manager.create_indexes(CmdbUser.COLLECTION, database_name, CmdbUser.get_index_keys())
    database_manager.create_indexes(CmdbUserGroup.COLLECTION, database_name, CmdbUserGroup.get_index_keys())

    def _purge() -> None:
        users.delete_many({CmdbUserKey.USER_NAME.value: {'$in': USER_NAMES}})
        groups.delete_many({GroupKey.NAME.value: {'$in': GROUP_NAMES}})

    _purge()
    yield users, groups
    _purge()


def _create_user(rest_api, user_name: str):
    """POSTs a user."""
    return rest_api.post(f'{USERS_URL}/', json=_user_payload(user_name))


def _create_group(rest_api, name: str):
    """POSTs a group."""
    return rest_api.post(f'{GROUPS_URL}/', json=_group_payload(name))


def _stored_user(rest_api, user_name: str) -> dict[str, Any]:
    """Creates a user and reads its stored document back through GET, ready to be PUT."""
    new_id: int = _create_user(rest_api, user_name).get_json()['result_id']
    document: dict[str, Any] = rest_api.get(f'{USERS_URL}/{new_id}').get_json()['result']

    return {key: value for key, value in document.items() if key != 'password'}


def _created_id(response) -> int:
    """The public_id of an InsertSingleResponse."""
    return response.get_json()['result_id']


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       USERS                                                          #
# -------------------------------------------------------------------------------------------------------------------- #
class TestUserName:
    """POST /users/ and PUT /users/<id>"""

    def test_a_taken_user_name_is_refused_by_name(self, rest_api) -> None:
        """The pre-check: the message names the clash - it used to be "Failed to create the User in database!"."""
        assert _create_user(rest_api, TAKEN_USER_NAME).status_code in (HTTPStatus.OK, HTTPStatus.CREATED)

        response = _create_user(rest_api, TAKEN_USER_NAME)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'] == USER_NAME_TAKEN_MESSAGE.format(user_name=TAKEN_USER_NAME)

    def test_the_pre_check_refuses_before_any_write(self, rest_api, monkeypatch) -> None:
        """The readable refusal is the read's, not the index's: the insert is never attempted."""
        _create_user(rest_api, TAKEN_USER_NAME)
        attempts: list[Any] = []
        monkeypatch.setattr(UsersManager, 'insert_user', lambda _self, data: attempts.append(data))

        assert _create_user(rest_api, TAKEN_USER_NAME).status_code == HTTPStatus.BAD_REQUEST
        assert not attempts

    def test_a_rename_onto_a_taken_user_name_is_refused_by_name(self, rest_api, collections) -> None:
        """The path no frontend validator covers: the edit form has none, only the add form does."""
        _create_user(rest_api, TAKEN_USER_NAME)
        renamed: dict[str, Any] = _stored_user(rest_api, FREE_USER_NAME)
        renamed[CmdbUserKey.USER_NAME.value] = TAKEN_USER_NAME

        response = rest_api.put(f'{USERS_URL}/{renamed["public_id"]}', json=renamed)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'] == USER_NAME_TAKEN_MESSAGE.format(user_name=TAKEN_USER_NAME)
        assert collections[0].find_one({'public_id': renamed['public_id']})[CmdbUserKey.USER_NAME.value] \
            == FREE_USER_NAME

    def test_an_update_that_keeps_its_own_user_name_passes(self, rest_api) -> None:
        """The pre-check excludes the user being updated - its own name is no clash."""
        stored: dict[str, Any] = _stored_user(rest_api, TAKEN_USER_NAME)
        stored['first_name'] = 'Changed'

        assert rest_api.put(f'{USERS_URL}/{stored["public_id"]}', json=stored).status_code \
            in (HTTPStatus.OK, HTTPStatus.ACCEPTED)

    @pytest.mark.parametrize('twin', list(NEAR_TWINS.values()), ids=list(NEAR_TWINS))
    def test_a_near_twin_is_a_different_user_name(self, rest_api, twin: str) -> None:
        """Compared as sent, like the index: another case or padding is not refused here (T253 / T252)."""
        _create_user(rest_api, TAKEN_USER_NAME)

        assert _create_user(rest_api, twin.format(kind='User')).status_code in (HTTPStatus.OK, HTTPStatus.CREATED)

    def test_a_create_only_the_index_catches_is_the_same_400(self, rest_api, monkeypatch, collections) -> None:
        """
        The race the index exists for: the pre-check passes, the write is refused anyway

        Switching the pre-check off reproduces a concurrent create without threads: the second insert reaches
        the database, the unique index refuses it, and the typed refusal travels the manager chain.
        """
        _create_user(rest_api, TAKEN_USER_NAME)
        monkeypatch.setattr(users_routes, 'abort_if_taken', lambda *_a, **_k: None)

        response = _create_user(rest_api, TAKEN_USER_NAME)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'] == USER_NAME_TAKEN_MESSAGE.format(user_name=TAKEN_USER_NAME)
        assert collections[0].count_documents({CmdbUserKey.USER_NAME.value: TAKEN_USER_NAME}) == 1

    def test_a_rename_only_the_index_catches_is_the_same_400(self, rest_api, monkeypatch) -> None:
        """The update half of the race."""
        _create_user(rest_api, TAKEN_USER_NAME)
        renamed: dict[str, Any] = _stored_user(rest_api, FREE_USER_NAME)
        renamed[CmdbUserKey.USER_NAME.value] = TAKEN_USER_NAME
        monkeypatch.setattr(users_routes, 'abort_if_taken', lambda *_a, **_k: None)

        response = rest_api.put(f'{USERS_URL}/{renamed["public_id"]}', json=renamed)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'] == USER_NAME_TAKEN_MESSAGE.format(user_name=TAKEN_USER_NAME)

    def test_an_outage_on_create_is_a_500_never_a_taken_name(self, rest_api, monkeypatch) -> None:
        """
        The database write is failed for real, below every manager

        UsersManager.insert_user lets the transient error through, so it reaches Flask's catch-all - hence
        exception propagation off, as production runs.
        """
        monkeypatch.setitem(rest_api.application.config, 'PROPAGATE_EXCEPTIONS', False)
        monkeypatch.setattr(MongoDatabaseManager, 'insert', _raiser(DocumentNetworkError('connection lost')))

        response = _create_user(rest_api, FREE_USER_NAME)

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert 'already exists' not in response.get_json()['message']


# -------------------------------------------------------------------------------------------------------------------- #
#                                                      GROUPS                                                          #
# -------------------------------------------------------------------------------------------------------------------- #
class TestGroupName:
    """POST /groups/ and PUT /groups/<id> - no frontend validator covers either"""

    def test_a_taken_group_name_is_refused_by_name(self, rest_api) -> None:
        """It used to be "Failed to insert the new UserGroup in the database!"."""
        _create_group(rest_api, TAKEN_GROUP_NAME)

        response = _create_group(rest_api, TAKEN_GROUP_NAME)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'] == GROUP_NAME_TAKEN_MSG.format(name=TAKEN_GROUP_NAME)

    def test_the_pre_check_refuses_before_any_write(self, rest_api, monkeypatch) -> None:
        """The readable refusal is the read's, not the index's: the insert is never attempted."""
        _create_group(rest_api, TAKEN_GROUP_NAME)
        attempts: list[Any] = []
        monkeypatch.setattr(GroupsManager, 'insert_group', lambda _self, data: attempts.append(data))

        assert _create_group(rest_api, TAKEN_GROUP_NAME).status_code == HTTPStatus.BAD_REQUEST
        assert not attempts

    def test_a_rename_onto_a_taken_group_name_is_refused_by_name(self, rest_api, collections) -> None:
        """It used to be "User group with public_id:n could not be updated!"."""
        _create_group(rest_api, TAKEN_GROUP_NAME)
        renamed_id: int = _created_id(_create_group(rest_api, FREE_GROUP_NAME))

        response = rest_api.put(f'{GROUPS_URL}/{renamed_id}', json=_group_payload(TAKEN_GROUP_NAME))

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'] == GROUP_NAME_TAKEN_MSG.format(name=TAKEN_GROUP_NAME)
        assert collections[1].find_one({'public_id': renamed_id})[GroupKey.NAME.value] == FREE_GROUP_NAME

    def test_an_update_that_keeps_its_own_group_name_passes(self, rest_api) -> None:
        """The pre-check excludes the group being updated."""
        group_id: int = _created_id(_create_group(rest_api, TAKEN_GROUP_NAME))

        assert rest_api.put(f'{GROUPS_URL}/{group_id}', json=_group_payload(TAKEN_GROUP_NAME)).status_code \
            in (HTTPStatus.OK, HTTPStatus.ACCEPTED)

    @pytest.mark.parametrize('twin', list(NEAR_TWINS.values()), ids=list(NEAR_TWINS))
    def test_a_near_twin_is_a_different_group_name(self, rest_api, twin: str) -> None:
        """Compared as sent, like the index."""
        _create_group(rest_api, TAKEN_GROUP_NAME)

        assert _create_group(rest_api, twin.format(kind='Group')).status_code in (HTTPStatus.OK, HTTPStatus.CREATED)

    def test_a_create_only_the_index_catches_is_the_same_400(self, rest_api, monkeypatch, collections) -> None:
        """The race, through the real index."""
        _create_group(rest_api, TAKEN_GROUP_NAME)
        monkeypatch.setattr(groups_routes, 'abort_if_taken', lambda *_a, **_k: None)

        response = _create_group(rest_api, TAKEN_GROUP_NAME)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'] == GROUP_NAME_TAKEN_MSG.format(name=TAKEN_GROUP_NAME)
        assert collections[1].count_documents({GroupKey.NAME.value: TAKEN_GROUP_NAME}) == 1

    def test_a_rename_only_the_index_catches_is_the_same_400(self, rest_api, monkeypatch) -> None:
        """The update half of the race."""
        _create_group(rest_api, TAKEN_GROUP_NAME)
        renamed_id: int = _created_id(_create_group(rest_api, FREE_GROUP_NAME))
        monkeypatch.setattr(groups_routes, 'abort_if_taken', lambda *_a, **_k: None)

        response = rest_api.put(f'{GROUPS_URL}/{renamed_id}', json=_group_payload(TAKEN_GROUP_NAME))

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'] == GROUP_NAME_TAKEN_MSG.format(name=TAKEN_GROUP_NAME)

    def test_an_outage_on_create_is_a_500_never_a_taken_name(self, rest_api, monkeypatch) -> None:
        """GroupsManager.insert_group lets the transient error through to Flask's catch-all."""
        monkeypatch.setitem(rest_api.application.config, 'PROPAGATE_EXCEPTIONS', False)
        monkeypatch.setattr(MongoDatabaseManager, 'insert', _raiser(DocumentNetworkError('connection lost')))

        response = _create_group(rest_api, FREE_GROUP_NAME)

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert 'already exists' not in response.get_json()['message']


def _raiser(error: Exception):
    """A replacement that always raises the given error."""
    def _raise(*_args: Any, **_kwargs: Any) -> None:
        raise error

    return _raise
