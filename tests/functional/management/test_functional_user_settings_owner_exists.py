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
Functional tests: a user setting is written only for a user that exists, through the real REST app

As the administrator (who holds ``base.user-management.user.edit``): POST and PUT for a user id no user carries answer
the 404 the user routes answer and store nothing - also a PUT whose setting is already stored under the missing id,
and a POST for the next id the user counter will hand out, so the next created user starts without settings. A
failed user read answers its own 400. For a user that exists, the writes work as before. The reads and the delete
stay open for any id: the list of a missing user is empty, and a setting left without its user can be deleted
"""
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.errors.manager.users_manager import UsersManagerGetError
from cmdb.manager.users_manager import UsersManager
from cmdb.models.group_model.group_constants import USER_GROUP_ID
from cmdb.models.settings_model import CmdbUserSetting
from cmdb.models.user_model import CmdbUser
from cmdb.interface.rest_api.routes.user_management_routes.users_constants import USER_NOT_FOUND_MESSAGE
from cmdb.interface.rest_api.routes.user_management_routes.user_settings_constants import UserSettingMessage
# -------------------------------------------------------------------------------------------------------------------- #

EXISTING_ID: int = 88931
MISSING_ID: int = 88932
ORPHAN_ID: int = 88933
RESOURCE: str = 'owner-exists-table'
NEW_USER_NAME: str = 'settings-next-user'
PAYLOADS: list[dict[str, Any]] = [{'id': 'objects-table', 'page_size': 25}]
CHANGED_PAYLOADS: list[dict[str, Any]] = [{'id': 'objects-table', 'page_size': 50}]


def _body(user_id: int, payloads: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """A whole setting, as POST / PUT take it"""
    return {'resource': RESOURCE, 'user_id': user_id, 'payloads': payloads or PAYLOADS, 'setting_type': 'GLOBAL'}


@pytest.fixture(name='settings')
def fixture_settings(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[Any]:
    """An existing user, and a setting stored under an id no user carries; removed afterwards"""
    users = database_manager.get_collection(CmdbUser.COLLECTION, database_name)
    settings = database_manager.get_collection(CmdbUserSetting.COLLECTION, database_name)

    def _purge() -> None:
        users.delete_many({'$or': [{'public_id': EXISTING_ID}, {'user_name': NEW_USER_NAME}]})
        settings.delete_many({'resource': RESOURCE})

    _purge()
    users.insert_one({'public_id': EXISTING_ID, 'user_name': f'settings-{EXISTING_ID}', 'active': True,
                      'group_id': USER_GROUP_ID, 'registration_time': datetime.now(timezone.utc)})
    settings.insert_one({**_body(ORPHAN_ID), 'public_id': 889301})

    yield settings

    _purge()


def _stored(settings: Any, user_id: int) -> list[dict[str, Any]]:
    """The test's settings stored under the user id"""
    return list(settings.find({'resource': RESOURCE, 'user_id': user_id}, {'_id': 0}))


def _not_found(response: Any, user_id: int) -> bool:
    """The user routes' 404"""
    return (response.status_code, response.get_json()['message']) == (
        HTTPStatus.NOT_FOUND, USER_NOT_FOUND_MESSAGE.format(public_id=user_id))


class TestAWriteNeedsTheUser:
    """POST and PUT refuse a user id no user carries."""

    def test_a_create_for_a_missing_user_is_a_404(self, rest_api, settings: Any) -> None:
        """Nothing stored"""
        response = rest_api.post(f'/users/{MISSING_ID}/settings/', json=_body(MISSING_ID))

        assert _not_found(response, MISSING_ID)
        assert not _stored(settings, MISSING_ID)

    def test_an_update_or_create_for_a_missing_user_is_a_404(self, rest_api, settings: Any) -> None:
        """The create branch of PUT: nothing stored"""
        response = rest_api.put(f'/users/{MISSING_ID}/settings/{RESOURCE}', json=_body(MISSING_ID))

        assert _not_found(response, MISSING_ID)
        assert not _stored(settings, MISSING_ID)

    def test_a_setting_left_without_its_user_is_not_updated(self, rest_api, settings: Any) -> None:
        """The check comes before PUT reads the setting, so its update branch is refused too"""
        response = rest_api.put(f'/users/{ORPHAN_ID}/settings/{RESOURCE}', json=_body(ORPHAN_ID, CHANGED_PAYLOADS))

        assert _not_found(response, ORPHAN_ID)
        assert _stored(settings, ORPHAN_ID)[0]['payloads'] == PAYLOADS

    def test_the_next_user_cannot_be_given_settings_ahead_of_time(
            self, rest_api, settings: Any, database_manager: MongoDatabaseManager, database_name: str) -> None:
        """The next id is predictable; a setting written for it would be the next user's - it is refused"""
        next_id: int = database_manager.get_next_public_id(CmdbUser.COLLECTION, database_name)

        refused = rest_api.post(f'/users/{next_id}/settings/', json=_body(next_id))
        created = rest_api.post('/users/', json={'user_name': NEW_USER_NAME, 'password': 'pw', 'active': True,
                                                 'group_id': USER_GROUP_ID})

        assert _not_found(refused, next_id)
        assert created.get_json()['result_id'] == next_id
        assert rest_api.get(f'/users/{next_id}/settings/').get_json()['results'] == []

    def test_a_failed_user_read_answers_its_own_400(self, rest_api, settings: Any,
                                                    monkeypatch: pytest.MonkeyPatch) -> None:
        """The check could not be made: refused, nothing stored, the message names the user check"""
        real = UsersManager.get_user

        def _failing_for_the_path_user(self: UsersManager, public_id: int) -> Any:
            if public_id == EXISTING_ID:
                raise UsersManagerGetError('users unavailable')
            return real(self, public_id)

        monkeypatch.setattr(UsersManager, 'get_user', _failing_for_the_path_user)

        response = rest_api.post(f'/users/{EXISTING_ID}/settings/', json=_body(EXISTING_ID))

        assert (response.status_code, response.get_json()['message']) == (
            HTTPStatus.BAD_REQUEST, UserSettingMessage.OWNER_CHECK_FAILED)
        assert not _stored(settings, EXISTING_ID)


class TestAnExistingUserIsWrittenAsBefore:
    """The check passes for a user that exists."""

    def test_a_create_for_another_existing_user(self, rest_api, settings: Any) -> None:
        """The editor writes another user's setting"""
        response = rest_api.post(f'/users/{EXISTING_ID}/settings/', json=_body(EXISTING_ID))

        assert response.status_code == HTTPStatus.CREATED
        assert _stored(settings, EXISTING_ID)

    def test_an_update_or_create_for_another_existing_user(self, rest_api, settings: Any) -> None:
        """Both PUT branches, the create then the update"""
        url: str = f'/users/{EXISTING_ID}/settings/{RESOURCE}'

        assert rest_api.put(url, json=_body(EXISTING_ID)).status_code == HTTPStatus.ACCEPTED
        assert rest_api.put(url, json=_body(EXISTING_ID, CHANGED_PAYLOADS)).status_code == HTTPStatus.ACCEPTED
        assert _stored(settings, EXISTING_ID)[0]['payloads'] == CHANGED_PAYLOADS


class TestReadsAndTheDeleteStayOpen:
    """They write nothing - and the delete is how a setting without its user is removed."""

    def test_the_list_of_a_missing_user_is_empty(self, rest_api, settings: Any) -> None:
        """200 and no setting, not a 404"""
        response = rest_api.get(f'/users/{MISSING_ID}/settings/')

        assert (response.status_code, response.get_json()['results']) == (HTTPStatus.OK, [])

    def test_a_setting_left_without_its_user_can_be_deleted(self, rest_api, settings: Any) -> None:
        """The cleanup path"""
        response = rest_api.delete(f'/users/{ORPHAN_ID}/settings/{RESOURCE}')

        assert response.status_code == HTTPStatus.ACCEPTED
        assert not _stored(settings, ORPHAN_ID)
