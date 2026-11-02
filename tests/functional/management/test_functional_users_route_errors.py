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

An unreadable stored user - its read failed, or the model refuses the stored document - is the read's 400 with one
message on all four routes that name a user (GET, PUT, PATCH /password, DELETE), never the delete's old 404 nor the
update's old 500; a missing user stays the 404 on all four.

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
from cmdb.interface.rest_api.routes.user_management_routes.users_constants import (
    USER_CREATED_NOT_READABLE_MESSAGE,
    USER_NOT_FOUND_MESSAGE,
    USER_NOT_READABLE_MESSAGE,
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


def _update_payload(public_id: int = USER_ID, first_name: str = 'Original') -> dict[str, Any]:
    """The same user as a PUT body: no password, which only changes through PATCH /users/<id>/password."""
    payload = _payload(public_id, first_name)
    payload.pop('password')
    return payload


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
        payload = _update_payload(public_id=OTHER_USER_ID, first_name='Renamed')  # forged id in the body

        response = rest_api.put(f'{ROUTE_URL}/{USER_ID}', json=payload)  # URL says USER_ID

        assert response.status_code == HTTPStatus.ACCEPTED
        assert rest_api.get(f'{ROUTE_URL}/{USER_ID}').get_json()['result']['public_id'] == USER_ID
        assert rest_api.get(f'{ROUTE_URL}/{OTHER_USER_ID}').status_code == HTTPStatus.NOT_FOUND

    def test_update_accepts_registration_time_string(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """A PUT carrying a registration_time ISO string is coerced and accepted (no 500)."""
        _seed(database_manager, database_name, USER_ID)
        payload = _update_payload()
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

    def test_an_insert_error_that_is_no_duplicate_returns_500(self, rest_api, monkeypatch) -> None:
        """
        A UsersManagerInsertError alone is no taken name: only a typed refusal in its chain is

        It used to be the generic "Failed to create the User in database!" 400 a duplicate name answered too.
        """
        monkeypatch.setattr(UsersManager, 'insert_user', _raiser(UsersManagerInsertError('boom')))

        assert rest_api.post(f'{ROUTE_URL}/', json=_payload()).status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_insert_created_not_retrievable_returns_500(self, rest_api, monkeypatch) -> None:
        """The insert worked but the read-back found nothing: the server lost its own write, not a 404."""
        monkeypatch.setattr(UsersManager, 'insert_user', lambda *_a, **_k: USER_ID)
        _patch_target_get_user(monkeypatch, USER_ID, result=None)

        response = rest_api.post(f'{ROUTE_URL}/', json=_payload())

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert response.get_json()['message'] == USER_CREATED_NOT_READABLE_MESSAGE

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

    def test_an_update_error_that_is_no_duplicate_returns_500(
        self, rest_api, monkeypatch, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """A UsersManagerUpdateError (user present) alone says nothing about the request - a 500, not the old 400."""
        _seed(database_manager, database_name, USER_ID)
        monkeypatch.setattr(UsersManager, 'update_user', _raiser(UsersManagerUpdateError('boom')))

        assert rest_api.put(f'{ROUTE_URL}/{USER_ID}', json=_update_payload()).status_code \
            == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_update_missing_returns_404(self, rest_api) -> None:
        """A PUT on a missing user returns 404."""
        assert rest_api.put(f'{ROUTE_URL}/{MISSING_USER_ID}', json=_update_payload(MISSING_USER_ID)).status_code \
            == HTTPStatus.NOT_FOUND

    def test_update_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error while loading the user on update surfaces as 500."""
        _patch_target_get_user(monkeypatch, USER_ID, exc=RuntimeError('boom'))

        assert rest_api.put(f'{ROUTE_URL}/{USER_ID}', json=_update_payload()).status_code \
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

    def test_delete_get_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A UsersManagerGetError on the delete existence check is the read's 400 - never "not found"."""
        _patch_target_get_user(monkeypatch, USER_ID, exc=UsersManagerGetError('boom'))

        response = rest_api.delete(f'{ROUTE_URL}/{USER_ID}')

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'] == USER_NOT_READABLE_MESSAGE.format(public_id=USER_ID)

    def test_delete_unexpected_error_returns_500(
        self, rest_api, monkeypatch, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """An unexpected error on delete surfaces as 500."""
        _seed(database_manager, database_name, USER_ID)
        monkeypatch.setattr(UsersManager, 'delete_user', _raiser(RuntimeError('boom')))

        assert rest_api.delete(f'{ROUTE_URL}/{USER_ID}').status_code == HTTPStatus.INTERNAL_SERVER_ERROR


# The four routes naming one user, each with a body it accepts
USER_ROUTES: list[tuple[str, str, dict[str, Any] | None]] = [
    ('get', '', None),
    ('put', '', None),
    ('patch', '/password', {'password': 'a-new-password'}),
    ('delete', '', None),
]
USER_ROUTE_IDS: list[str] = ['get', 'put', 'patch-password', 'delete']


def _call(rest_api, method: str, suffix: str, body: dict[str, Any] | None, public_id: int) -> Any:
    """Calls one of the four routes on `public_id` - the PUT with the user's own update body"""
    if method == 'put':
        body = _update_payload(public_id)

    return getattr(rest_api, method)(f'{ROUTE_URL}/{public_id}{suffix}', **({'json': body} if body else {}))


class TestUnreadableStoredUser:
    """One answer on every route: the read's 400, the stored document untouched"""

    @pytest.mark.parametrize('method, suffix, body', USER_ROUTES, ids=USER_ROUTE_IDS)
    def test_a_failed_read_is_the_same_400(self, rest_api, monkeypatch, method: str, suffix: str,
                                           body: dict[str, Any] | None) -> None:
        """A UsersManagerGetError on the route's read of the user"""
        _patch_target_get_user(monkeypatch, USER_ID, exc=UsersManagerGetError('boom'))

        response = _call(rest_api, method, suffix, body, USER_ID)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'] == USER_NOT_READABLE_MESSAGE.format(public_id=USER_ID)

    @pytest.mark.parametrize('method, suffix, body', USER_ROUTES, ids=USER_ROUTE_IDS)
    def test_a_stored_document_the_model_refuses(self, rest_api, database_manager: MongoDatabaseManager,
                                                 database_name: str, method: str, suffix: str,
                                                 body: dict[str, Any] | None) -> None:
        """A real stored user without its user_name: the same 400, nothing written or deleted"""
        _seed(database_manager, database_name, USER_ID)
        users = database_manager.get_collection(CmdbUser.COLLECTION, database_name)
        users.update_one({'public_id': USER_ID}, {'$unset': {'user_name': 1}})
        stored_before = users.find_one({'public_id': USER_ID})

        response = _call(rest_api, method, suffix, body, USER_ID)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'] == USER_NOT_READABLE_MESSAGE.format(public_id=USER_ID)
        assert users.find_one({'public_id': USER_ID}) == stored_before

    @pytest.mark.parametrize('method, suffix, body', USER_ROUTES, ids=USER_ROUTE_IDS)
    def test_a_missing_user_stays_the_404(self, rest_api, method: str, suffix: str,
                                          body: dict[str, Any] | None) -> None:
        """404 means the user is not there - never that it could not be read"""
        response = _call(rest_api, method, suffix, body, MISSING_USER_ID)

        assert response.status_code == HTTPStatus.NOT_FOUND
        assert response.get_json()['message'] == USER_NOT_FOUND_MESSAGE.format(public_id=MISSING_USER_ID)

    def test_the_deletes_administrator_count_shares_the_400(
            self, rest_api, monkeypatch, database_manager: MongoDatabaseManager, database_name: str) -> None:
        """The last-administrator rule's read of the other administrators fails: the read's 400, the user kept"""
        _seed(database_manager, database_name, USER_ID)
        monkeypatch.setattr(
            'cmdb.interface.rest_api.routes.user_management_routes.users_routes.guard_last_administrator',
            _raiser(UsersManagerGetError('boom')),
        )

        response = rest_api.delete(f'{ROUTE_URL}/{USER_ID}')

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'] == USER_NOT_READABLE_MESSAGE.format(public_id=USER_ID)
        assert database_manager.get_collection(CmdbUser.COLLECTION, database_name).find_one({'public_id': USER_ID})
