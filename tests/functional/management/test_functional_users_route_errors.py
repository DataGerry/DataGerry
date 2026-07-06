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
Functional coverage for the /users routes' error paths and route-layer fixes

Complements test_functional_users_route.py (happy paths) by driving the branches the smoke suite
does not: the manager-error -> 400 / 404 / 500 mappings on every verb, the created-but-unretrievable
404 on create, the admin-delete guard surfaced through the route, and the route-layer fixes -
public_id is pinned from the URL on update, a registration_time payload is accepted, and a
password-change with no password body is rejected with 400.
"""
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.users_manager import UsersManager
from cmdb.models.user_model import CmdbUser
from cmdb.errors.manager.users_manager import (
    UsersManagerGetError,
    UsersManagerInsertError,
    UsersManagerUpdateError,
    UsersManagerDeleteError,
    UsersManagerIterationError,
)
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_URL: str = '/users'
ADMIN_USER_ID: int = 1
DEFAULT_GROUP_ID: int = 1
OTHER_GROUP_ID: int = 2

USER_ID: int = 96901
OTHER_USER_ID: int = 96902
MISSING_USER_ID: int = 96999

ALL_USER_IDS: list[int] = [USER_ID, OTHER_USER_ID]


def _payload(public_id: int = USER_ID, first_name: str = 'Original') -> dict[str, Any]:
    """Builds a CmdbUser-shaped payload accepted by POST /users/ and PUT /users/<id>."""
    return {
        'public_id': public_id,
        'user_name': f'user-{public_id}',
        'active': True,
        'group_id': DEFAULT_GROUP_ID,
        'first_name': first_name,
        'password': 'a-password',
    }


@pytest.fixture(autouse=True)
def _cleanup(database_manager: MongoDatabaseManager, database_name: str):
    """Removes any test users seeded by a test, before and after each test."""
    def _purge() -> None:
        database_manager.get_collection(CmdbUser.COLLECTION, database_name)\
            .delete_many({'public_id': {'$in': ALL_USER_IDS}})

    _purge()
    yield
    _purge()


def _seed(database_manager: MongoDatabaseManager, database_name: str, public_id: int) -> None:
    """Inserts a complete CmdbUser doc directly, bypassing POST schema validation."""
    doc = _payload(public_id)
    doc['registration_time'] = datetime.now(timezone.utc)
    database_manager.get_collection(CmdbUser.COLLECTION, database_name).insert_one(doc)


def _raiser(exc: Exception):
    """Returns a function that ignores its args and raises the given exception."""
    def _fail(*_args, **_kwargs):
        raise exc
    return _fail


def _patch_target_get_user(monkeypatch, target_id: int, *, exc: Exception | None = None, result: Any = 'unset'):
    """
    Patches UsersManager.get_user to raise / return a canned value ONLY for target_id.

    Any other public_id (notably the auth user resolved by insert_request_user) falls through to the
    real implementation, so authentication still works while the route's own get_user(target_id) is
    driven into the branch under test.
    """
    original = UsersManager.get_user

    def _fn(self, public_id: int):
        if public_id == target_id:
            if exc is not None:
                raise exc
            return result
        return original(self, public_id)

    monkeypatch.setattr(UsersManager, 'get_user', _fn)


class TestRouteFixes:
    """The route-layer fixes: public_id pinning, registration_time acceptance, password-body guard."""

    def test_update_pins_public_id_from_url(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """A body public_id different from the URL cannot rewrite the document's identity."""
        _seed(database_manager, database_name, USER_ID)
        payload = _payload(public_id=OTHER_USER_ID, first_name='Renamed')  # forged id in the body

        response = rest_api.put(f'{ROUTE_URL}/{USER_ID}', json=payload)  # URL says USER_ID

        assert response.status_code == HTTPStatus.ACCEPTED
        assert rest_api.get(f'{ROUTE_URL}/{USER_ID}').get_json()['result']['public_id'] == USER_ID
        assert rest_api.get(f'{ROUTE_URL}/{OTHER_USER_ID}').status_code == HTTPStatus.NOT_FOUND

    def test_update_accepts_registration_time_string(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """A PUT carrying a registration_time ISO string is coerced and accepted (no 500)."""
        _seed(database_manager, database_name, USER_ID)
        payload = _payload()
        # BSON $date wrapper - the shape the schema (registration_time: dict) accepts
        payload['registration_time'] = {'$date': '2024-01-02T03:04:05Z'}

        assert rest_api.put(f'{ROUTE_URL}/{USER_ID}', json=payload).status_code == HTTPStatus.ACCEPTED

    def test_password_change_without_body_returns_400(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """A password change with no password in the body is rejected with 400."""
        _seed(database_manager, database_name, USER_ID)

        assert rest_api.patch(f'{ROUTE_URL}/{USER_ID}/password', json={}).status_code == HTTPStatus.BAD_REQUEST

    def test_password_change_missing_user_returns_404(self, rest_api) -> None:
        """A password change for a missing user returns 404."""
        assert rest_api.patch(f'{ROUTE_URL}/{MISSING_USER_ID}/password',
                              json={'password': 'x'}).status_code == HTTPStatus.NOT_FOUND


class TestDeleteGuards:
    """DELETE guards: missing id 404 and the admin-protection surfaced through the route."""

    def test_delete_missing_returns_404(self, rest_api) -> None:
        """Deleting a missing user returns 404."""
        assert rest_api.delete(f'{ROUTE_URL}/{MISSING_USER_ID}').status_code == HTTPStatus.NOT_FOUND

    def test_delete_admin_is_refused(self, rest_api) -> None:
        """Deleting the bootstrap admin is refused (manager guard -> 400) and the admin survives."""
        response = rest_api.delete(f'{ROUTE_URL}/{ADMIN_USER_ID}')

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert rest_api.get(f'{ROUTE_URL}/{ADMIN_USER_ID}').status_code == HTTPStatus.OK


class TestErrorMapping:
    """The routes map manager failures to the documented HTTP statuses."""

    def test_insert_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A UsersManagerInsertError on create surfaces as 400."""
        monkeypatch.setattr(UsersManager, 'insert_user', _raiser(UsersManagerInsertError('boom')))

        assert rest_api.post(f'{ROUTE_URL}/', json=_payload()).status_code == HTTPStatus.BAD_REQUEST

    def test_insert_created_not_retrievable_returns_404(self, rest_api, monkeypatch) -> None:
        """When the created user cannot be re-read, the route returns 404."""
        monkeypatch.setattr(UsersManager, 'insert_user', lambda *_a, **_k: USER_ID)
        _patch_target_get_user(monkeypatch, USER_ID, result=None)

        assert rest_api.post(f'{ROUTE_URL}/', json=_payload()).status_code == HTTPStatus.NOT_FOUND

    def test_insert_get_error_returns_500(self, rest_api, monkeypatch) -> None:
        """A UsersManagerGetError re-reading the created user surfaces as 500."""
        monkeypatch.setattr(UsersManager, 'insert_user', lambda *_a, **_k: USER_ID)
        _patch_target_get_user(monkeypatch, USER_ID, exc=UsersManagerGetError('boom'))

        assert rest_api.post(f'{ROUTE_URL}/', json=_payload()).status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_insert_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error on create surfaces as 500."""
        monkeypatch.setattr(UsersManager, 'insert_user', _raiser(RuntimeError('boom')))

        assert rest_api.post(f'{ROUTE_URL}/', json=_payload()).status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_list_iteration_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A UsersManagerIterationError on list surfaces as 400."""
        monkeypatch.setattr(UsersManager, 'iterate', _raiser(UsersManagerIterationError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/').status_code == HTTPStatus.BAD_REQUEST

    def test_list_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error on list surfaces as 500."""
        monkeypatch.setattr(UsersManager, 'iterate', _raiser(RuntimeError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/').status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_get_single_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A UsersManagerGetError on get-single surfaces as 400."""
        _patch_target_get_user(monkeypatch, USER_ID, exc=UsersManagerGetError('boom'))

        assert rest_api.get(f'{ROUTE_URL}/{USER_ID}').status_code == HTTPStatus.BAD_REQUEST

    def test_get_single_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error on get-single surfaces as 500."""
        _patch_target_get_user(monkeypatch, USER_ID, exc=RuntimeError('boom'))

        assert rest_api.get(f'{ROUTE_URL}/{USER_ID}').status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_update_error_returns_400(
        self, rest_api, monkeypatch, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """A UsersManagerUpdateError (user present) surfaces as 400."""
        _seed(database_manager, database_name, USER_ID)
        monkeypatch.setattr(UsersManager, 'update_user', _raiser(UsersManagerUpdateError('boom')))

        assert rest_api.put(f'{ROUTE_URL}/{USER_ID}', json=_payload()).status_code == HTTPStatus.BAD_REQUEST

    def test_update_missing_returns_404(self, rest_api) -> None:
        """A PUT on a missing user returns 404."""
        assert rest_api.put(f'{ROUTE_URL}/{MISSING_USER_ID}', json=_payload(MISSING_USER_ID)).status_code \
            == HTTPStatus.NOT_FOUND

    def test_update_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error while loading the user on update surfaces as 500."""
        _patch_target_get_user(monkeypatch, USER_ID, exc=RuntimeError('boom'))

        assert rest_api.put(f'{ROUTE_URL}/{USER_ID}', json=_payload()).status_code \
            == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_password_update_error_returns_400(
        self, rest_api, monkeypatch, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """A UsersManagerUpdateError on password change surfaces as 400."""
        _seed(database_manager, database_name, USER_ID)
        monkeypatch.setattr(UsersManager, 'update_user', _raiser(UsersManagerUpdateError('boom')))

        assert rest_api.patch(f'{ROUTE_URL}/{USER_ID}/password',
                              json={'password': 'x'}).status_code == HTTPStatus.BAD_REQUEST

    def test_password_get_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A UsersManagerGetError on the password-change existence check surfaces as 400."""
        _patch_target_get_user(monkeypatch, USER_ID, exc=UsersManagerGetError('boom'))

        assert rest_api.patch(f'{ROUTE_URL}/{USER_ID}/password',
                              json={'password': 'x'}).status_code == HTTPStatus.BAD_REQUEST

    def test_password_unexpected_error_returns_500(
        self, rest_api, monkeypatch, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """An unexpected error on password change surfaces as 500."""
        _seed(database_manager, database_name, USER_ID)
        monkeypatch.setattr(UsersManager, 'update_user', _raiser(RuntimeError('boom')))

        assert rest_api.patch(f'{ROUTE_URL}/{USER_ID}/password',
                              json={'password': 'x'}).status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_delete_error_returns_400(
        self, rest_api, monkeypatch, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """A UsersManagerDeleteError surfaces as 400."""
        _seed(database_manager, database_name, USER_ID)
        monkeypatch.setattr(UsersManager, 'delete_user', _raiser(UsersManagerDeleteError('boom')))

        assert rest_api.delete(f'{ROUTE_URL}/{USER_ID}').status_code == HTTPStatus.BAD_REQUEST

    def test_delete_get_error_returns_404(self, rest_api, monkeypatch) -> None:
        """A UsersManagerGetError on the delete existence check surfaces as 404."""
        _patch_target_get_user(monkeypatch, USER_ID, exc=UsersManagerGetError('boom'))

        assert rest_api.delete(f'{ROUTE_URL}/{USER_ID}').status_code == HTTPStatus.NOT_FOUND

    def test_delete_unexpected_error_returns_500(
        self, rest_api, monkeypatch, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """An unexpected error on delete surfaces as 500."""
        _seed(database_manager, database_name, USER_ID)
        monkeypatch.setattr(UsersManager, 'delete_user', _raiser(RuntimeError('boom')))

        assert rest_api.delete(f'{ROUTE_URL}/{USER_ID}').status_code == HTTPStatus.INTERNAL_SERVER_ERROR
