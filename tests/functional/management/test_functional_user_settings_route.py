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
Functional smoke for the ``/users/<user_id>/settings`` REST routes

Covers CRUD, the GET envelopes, the 404s, the manager-error -> 400 / -> 500 mappings, and the
route-layer fixes: the owning user_id is pinned from the URL on create/update (a mismatched body
cannot store under another user), the update existence-check + resource are keyed on the URL, the
PUT upsert (create-if-absent), and the duplicate-create -> 400 mapping. UserSettings are keyed by a
unique (resource, user_id) pair (no public_id).
"""
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.user_settings_manager import UserSettingsManager
from cmdb.models.settings_model import CmdbUserSetting
from cmdb.errors.manager.user_settings_manager import (
    UserSettingsManagerInsertError,
    UserSettingsManagerGetError,
    UserSettingsManagerUpdateError,
    UserSettingsManagerDeleteError,
    UserSettingsManagerIterationError,
)
# -------------------------------------------------------------------------------------------------------------------- #

USER_ID: int = 96601
OTHER_USER_ID: int = 96602

RESOURCE_A: str = 'dashboard'
RESOURCE_B: str = 'sidebar'
MISSING_RESOURCE: str = 'does-not-exist'

ALL_USER_IDS: list[int] = [USER_ID, OTHER_USER_ID]


def _settings_url(user_id: int = USER_ID) -> str:
    """Base URL for a user's settings collection."""
    return f'/users/{user_id}/settings'


def _setting_payload(resource: str, user_id: int = USER_ID, setting_type: str = 'GLOBAL') -> dict[str, Any]:
    """Builds a CmdbUserSetting body accepted by POST / PUT (all required schema fields present)."""
    return {'resource': resource, 'user_id': user_id, 'payloads': [], 'setting_type': setting_type}


@pytest.fixture(autouse=True)
def _cleanup(database_manager: MongoDatabaseManager, database_name: str):
    """Removes any user settings seeded by a test, before and after each test."""
    def _purge() -> None:
        database_manager.get_collection(CmdbUserSetting.COLLECTION, database_name)\
            .delete_many({'user_id': {'$in': ALL_USER_IDS}})

    _purge()
    yield
    _purge()


class TestPostUserSetting:
    """POST /users/<user_id>/settings/ creates a setting."""

    def test_creates_setting(self, rest_api) -> None:
        """A POST with a valid body succeeds and the setting becomes retrievable."""
        response = rest_api.post(f'{_settings_url()}/', json=_setting_payload(RESOURCE_A))

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.CREATED)
        assert rest_api.get(f'{_settings_url()}/{RESOURCE_A}').status_code == HTTPStatus.OK

    def test_missing_required_field_returns_400(self, rest_api) -> None:
        """A POST missing the required setting_type fails schema validation with 400."""
        payload = _setting_payload(RESOURCE_A)
        payload.pop('setting_type')

        assert rest_api.post(f'{_settings_url()}/', json=payload).status_code == HTTPStatus.BAD_REQUEST

    def test_duplicate_returns_400(self, rest_api) -> None:
        """Creating a second setting for the same (resource, user_id) is rejected with 400."""
        assert rest_api.post(f'{_settings_url()}/', json=_setting_payload(RESOURCE_A)).status_code \
            in (HTTPStatus.OK, HTTPStatus.CREATED)

        assert rest_api.post(f'{_settings_url()}/', json=_setting_payload(RESOURCE_A)).status_code \
            == HTTPStatus.BAD_REQUEST

    def test_pins_user_id_from_url(self, rest_api) -> None:
        """A body user_id different from the URL is overridden by the URL user_id."""
        payload = _setting_payload(RESOURCE_A, user_id=OTHER_USER_ID)

        assert rest_api.post(f'{_settings_url(USER_ID)}/', json=payload).status_code \
            in (HTTPStatus.OK, HTTPStatus.CREATED)

        stored = rest_api.get(f'{_settings_url(USER_ID)}/{RESOURCE_A}').get_json()['result']
        assert stored['user_id'] == USER_ID
        # the setting is not visible under the body's user_id
        assert rest_api.get(f'{_settings_url(OTHER_USER_ID)}/{RESOURCE_A}').status_code == HTTPStatus.NOT_FOUND


class TestGetUserSetting:
    """GET single + GET list."""

    def test_get_list_returns_results_envelope(self, rest_api) -> None:
        """GET /users/<id>/settings/ returns a results envelope containing the created settings."""
        rest_api.post(f'{_settings_url()}/', json=_setting_payload(RESOURCE_A))

        response = rest_api.get(f'{_settings_url()}/')

        assert response.status_code == HTTPStatus.OK
        resources = [item['resource'] for item in response.get_json()['results']]
        assert RESOURCE_A in resources

    def test_get_single_missing_returns_404(self, rest_api) -> None:
        """A missing resource returns 404."""
        assert rest_api.get(f'{_settings_url()}/{MISSING_RESOURCE}').status_code == HTTPStatus.NOT_FOUND


class TestPutUserSetting:
    """PUT /users/<user_id>/settings/<resource> upserts a setting."""

    def test_creates_when_absent(self, rest_api) -> None:
        """PUT on a non-existent resource creates it."""
        response = rest_api.put(f'{_settings_url()}/{RESOURCE_A}', json=_setting_payload(RESOURCE_A))

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
        assert rest_api.get(f'{_settings_url()}/{RESOURCE_A}').status_code == HTTPStatus.OK

    def test_updates_when_present(self, rest_api) -> None:
        """PUT on an existing resource updates it (setting_type GLOBAL -> SERVER)."""
        rest_api.post(f'{_settings_url()}/', json=_setting_payload(RESOURCE_A, setting_type='GLOBAL'))

        response = rest_api.put(f'{_settings_url()}/{RESOURCE_A}',
                                json=_setting_payload(RESOURCE_A, setting_type='SERVER'))

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
        assert rest_api.get(f'{_settings_url()}/{RESOURCE_A}').get_json()['result']['setting_type'] == 'SERVER'

    def test_pins_resource_from_url(self, rest_api) -> None:
        """A body resource different from the URL is overridden by the URL resource."""
        payload = _setting_payload(RESOURCE_B)  # body says RESOURCE_B ...

        response = rest_api.put(f'{_settings_url()}/{RESOURCE_A}', json=payload)  # ... URL says RESOURCE_A

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
        assert rest_api.get(f'{_settings_url()}/{RESOURCE_A}').status_code == HTTPStatus.OK
        assert rest_api.get(f'{_settings_url()}/{RESOURCE_B}').status_code == HTTPStatus.NOT_FOUND


class TestDeleteUserSetting:
    """DELETE /users/<user_id>/settings/<resource>."""

    def test_delete_removes_setting(self, rest_api) -> None:
        """A DELETE succeeds and a subsequent GET returns 404."""
        rest_api.post(f'{_settings_url()}/', json=_setting_payload(RESOURCE_A))

        response = rest_api.delete(f'{_settings_url()}/{RESOURCE_A}')

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
        assert rest_api.get(f'{_settings_url()}/{RESOURCE_A}').status_code == HTTPStatus.NOT_FOUND

    def test_delete_missing_returns_404(self, rest_api) -> None:
        """Deleting a non-existent resource returns 404."""
        assert rest_api.delete(f'{_settings_url()}/{MISSING_RESOURCE}').status_code == HTTPStatus.NOT_FOUND


def _raiser(exc: Exception):
    """Returns a function that ignores its args and raises the given exception."""
    def _fail(*_args, **_kwargs):
        raise exc
    return _fail


class TestErrorMapping:
    """The routes map manager failures to the documented HTTP statuses."""

    def test_insert_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A UserSettingsManagerInsertError on create surfaces as 400."""
        monkeypatch.setattr(UserSettingsManager, 'insert_item',
                            _raiser(UserSettingsManagerInsertError('boom')))

        assert rest_api.post(f'{_settings_url()}/', json=_setting_payload(RESOURCE_A)).status_code \
            == HTTPStatus.BAD_REQUEST

    def test_insert_created_not_retrievable_returns_404(self, rest_api, monkeypatch) -> None:
        """When the created setting cannot be re-read, the route returns 404."""
        monkeypatch.setattr(UserSettingsManager, 'get_user_setting', lambda *_a, **_k: None)

        assert rest_api.post(f'{_settings_url()}/', json=_setting_payload(RESOURCE_A)).status_code \
            == HTTPStatus.NOT_FOUND

    def test_insert_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error on create surfaces as 500."""
        monkeypatch.setattr(UserSettingsManager, 'insert_item', _raiser(RuntimeError('boom')))

        assert rest_api.post(f'{_settings_url()}/', json=_setting_payload(RESOURCE_A)).status_code \
            == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_list_iteration_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A UserSettingsManagerIterationError on list surfaces as 400."""
        monkeypatch.setattr(UserSettingsManager, 'get_user_settings',
                            _raiser(UserSettingsManagerIterationError('boom')))

        assert rest_api.get(f'{_settings_url()}/').status_code == HTTPStatus.BAD_REQUEST

    def test_list_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error on list surfaces as 500."""
        monkeypatch.setattr(UserSettingsManager, 'get_user_settings', _raiser(RuntimeError('boom')))

        assert rest_api.get(f'{_settings_url()}/').status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_get_single_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A UserSettingsManagerGetError on get-single surfaces as 400."""
        monkeypatch.setattr(UserSettingsManager, 'get_user_setting',
                            _raiser(UserSettingsManagerGetError('boom')))

        assert rest_api.get(f'{_settings_url()}/{RESOURCE_A}').status_code == HTTPStatus.BAD_REQUEST

    def test_get_single_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error on get-single surfaces as 500."""
        monkeypatch.setattr(UserSettingsManager, 'get_user_setting', _raiser(RuntimeError('boom')))

        assert rest_api.get(f'{_settings_url()}/{RESOURCE_A}').status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_update_error_returns_400(self, rest_api, monkeypatch,
                                     database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A UserSettingsManagerUpdateError (setting present) surfaces as 400."""
        database_manager.get_collection(CmdbUserSetting.COLLECTION, database_name)\
            .insert_one(_setting_payload(RESOURCE_A))
        monkeypatch.setattr(UserSettingsManager, 'update_user_setting',
                            _raiser(UserSettingsManagerUpdateError('boom')))

        assert rest_api.put(f'{_settings_url()}/{RESOURCE_A}', json=_setting_payload(RESOURCE_A)).status_code \
            == HTTPStatus.BAD_REQUEST

    def test_update_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error on update surfaces as 500."""
        monkeypatch.setattr(UserSettingsManager, 'get_user_setting', _raiser(RuntimeError('boom')))

        assert rest_api.put(f'{_settings_url()}/{RESOURCE_A}', json=_setting_payload(RESOURCE_A)).status_code \
            == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_delete_error_returns_400(self, rest_api, monkeypatch,
                                     database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A UserSettingsManagerDeleteError (setting present) surfaces as 400."""
        database_manager.get_collection(CmdbUserSetting.COLLECTION, database_name)\
            .insert_one(_setting_payload(RESOURCE_A))
        monkeypatch.setattr(UserSettingsManager, 'delete_user_setting',
                            _raiser(UserSettingsManagerDeleteError('boom')))

        assert rest_api.delete(f'{_settings_url()}/{RESOURCE_A}').status_code == HTTPStatus.BAD_REQUEST

    def test_delete_unexpected_error_returns_500(self, rest_api, monkeypatch,
                                               database_manager: MongoDatabaseManager, database_name: str) -> None:
        """An unexpected error on delete surfaces as 500."""
        database_manager.get_collection(CmdbUserSetting.COLLECTION, database_name)\
            .insert_one(_setting_payload(RESOURCE_A))
        monkeypatch.setattr(UserSettingsManager, 'delete_user_setting', _raiser(RuntimeError('boom')))

        assert rest_api.delete(f'{_settings_url()}/{RESOURCE_A}').status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_insert_get_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A UserSettingsManagerGetError during the create's duplicate/re-read check surfaces as 400."""
        monkeypatch.setattr(UserSettingsManager, 'get_user_setting',
                            _raiser(UserSettingsManagerGetError('boom')))

        assert rest_api.post(f'{_settings_url()}/', json=_setting_payload(RESOURCE_A)).status_code \
            == HTTPStatus.BAD_REQUEST

    def test_update_get_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A UserSettingsManagerGetError on the update existence-check surfaces as 400."""
        monkeypatch.setattr(UserSettingsManager, 'get_user_setting',
                            _raiser(UserSettingsManagerGetError('boom')))

        assert rest_api.put(f'{_settings_url()}/{RESOURCE_A}', json=_setting_payload(RESOURCE_A)).status_code \
            == HTTPStatus.BAD_REQUEST

    def test_update_insert_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A UserSettingsManagerInsertError on the update create-path surfaces as 400."""
        monkeypatch.setattr(UserSettingsManager, 'get_user_setting', lambda *_a, **_k: None)
        monkeypatch.setattr(UserSettingsManager, 'insert_item',
                            _raiser(UserSettingsManagerInsertError('boom')))

        assert rest_api.put(f'{_settings_url()}/{RESOURCE_A}', json=_setting_payload(RESOURCE_A)).status_code \
            == HTTPStatus.BAD_REQUEST

    def test_delete_get_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A UserSettingsManagerGetError on the delete existence-check surfaces as 400."""
        monkeypatch.setattr(UserSettingsManager, 'get_user_setting',
                            _raiser(UserSettingsManagerGetError('boom')))

        assert rest_api.delete(f'{_settings_url()}/{RESOURCE_A}').status_code == HTTPStatus.BAD_REQUEST
