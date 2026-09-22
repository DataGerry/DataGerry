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
Functional smoke for the ``/users`` REST routes

Covers the route-layer concerns that the UsersManager integration suite cannot:
HTTP status codes, schema validation, the 404 on a missing id, the JSON envelope
returned by GET-list, the PUT round-trip, the password-change PATCH, and the
DELETE 200 + follow-up 404. The CRUD behavior itself is asserted at the manager
layer; these tests only verify the route wraps it correctly
"""
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.user_model import CmdbUser
from cmdb.security.auth.providers.ldap_auth_provider import LdapAuthenticationProvider
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_URL: str = '/users'

ADMIN_USER_ID: int = 1
DEFAULT_GROUP_ID: int = 1

USER_ID_FOR_CREATE: int = 9710
USER_ID_FOR_GET: int = 9711
USER_ID_FOR_UPDATE: int = 9712
USER_ID_FOR_DELETE: int = 9713
USER_ID_FOR_PASSWORD: int = 9714
# A user whose credentials an external directory owns - the password route must refuse it
USER_ID_LDAP_AUTHENTICATED: int = 9718
MISSING_USER_ID: int = 9799

ALL_USER_IDS: list[int] = [
    USER_ID_FOR_CREATE,
    USER_ID_FOR_GET,
    USER_ID_FOR_UPDATE,
    USER_ID_FOR_DELETE,
    USER_ID_FOR_PASSWORD,
    USER_ID_LDAP_AUTHENTICATED,
]

ORIGINAL_FIRST_NAME: str = 'Original'
UPDATED_FIRST_NAME: str = 'Updated'
INITIAL_PASSWORD: str = 'initial-pass'
NEW_PASSWORD: str = 'new-pass'


def _user_payload(public_id: int, first_name: str = ORIGINAL_FIRST_NAME) -> dict[str, Any]:
    """Builds a CmdbUser-shaped payload acceptable to POST /users/ and PUT /users/<id>."""
    return {
        'public_id': public_id,
        'user_name': f'user-{public_id}',
        'active': True,
        'group_id': DEFAULT_GROUP_ID,
        'first_name': first_name,
        'password': INITIAL_PASSWORD,
    }


def _user_doc(public_id: int, first_name: str = ORIGINAL_FIRST_NAME) -> dict[str, Any]:
    """Builds a complete CmdbUser doc for direct DB insertion (bypasses POST schema validation)."""
    doc = _user_payload(public_id, first_name)
    doc['registration_time'] = datetime.now(timezone.utc)
    return doc


@pytest.fixture(scope='module', autouse=True)
def _cleanup_users_after_module(database_manager: MongoDatabaseManager, database_name: str):
    """Removes any leftover test users after the module's tests have run."""
    yield
    database_manager.get_collection(CmdbUser.COLLECTION, database_name)\
        .delete_many({'public_id': {'$in': ALL_USER_IDS}})


def _drop_user(database_manager: MongoDatabaseManager, database_name: str, public_id: int) -> None:
    """Removes a single CmdbUser doc directly via the collection, for per-test cleanup."""
    database_manager.get_collection(CmdbUser.COLLECTION, database_name).delete_one({'public_id': public_id})


def _insert_user_doc(database_manager: MongoDatabaseManager, database_name: str, public_id: int) -> None:
    """Inserts a CmdbUser doc directly via the collection, bypassing the POST route validation."""
    database_manager.get_collection(CmdbUser.COLLECTION, database_name).insert_one(_user_doc(public_id))


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       CREATE                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class TestPostUser:
    """POST /users/ creates a new CmdbUser; the password is HMAC'd before persistence."""

    def test_creates_new_user(
        self,
        rest_api,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """A POST with a fresh public_id succeeds; the user is then queryable."""
        try:
            response = rest_api.post(f'{ROUTE_URL}/', json=_user_payload(USER_ID_FOR_CREATE))

            assert response.status_code in (HTTPStatus.OK, HTTPStatus.CREATED)
            # `public_id` is server-owned: the payload's id is purged, so the route names the real one
            created_id = response.get_json()['result_id']
            follow_up = rest_api.get(f'{ROUTE_URL}/{created_id}')
            assert follow_up.status_code == HTTPStatus.OK
        finally:
            _drop_user(database_manager, database_name, USER_ID_FOR_CREATE)
            _drop_user(database_manager, database_name, created_id)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       READ                                                           #
# -------------------------------------------------------------------------------------------------------------------- #
class TestGetUser:
    """GET /users/<id> and GET /users/ return the expected envelopes."""

    @pytest.fixture(autouse=True)
    def _seed(self, database_manager: MongoDatabaseManager, database_name: str):
        """Inserts one user directly via the DB before each test and removes it after."""
        _insert_user_doc(database_manager, database_name, USER_ID_FOR_GET)
        yield
        _drop_user(database_manager, database_name, USER_ID_FOR_GET)

    def test_get_single_returns_user(self, rest_api) -> None:
        """A GET /users/<id> for a seeded user returns 200 and a parseable payload."""
        response = rest_api.get(f'{ROUTE_URL}/{USER_ID_FOR_GET}')

        assert response.status_code == HTTPStatus.OK
        parsed = CmdbUser.from_data(response.get_json()['result'])
        assert parsed.public_id == USER_ID_FOR_GET

    def test_get_single_missing_returns_404(self, rest_api) -> None:
        """A GET /users/<id> for a missing id returns 404."""
        response = rest_api.get(f'{ROUTE_URL}/{MISSING_USER_ID}')

        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_get_list_returns_results_envelope(self, rest_api) -> None:
        """A GET /users/ returns a JSON envelope whose results length matches X-Total-Count."""
        response = rest_api.get(f'{ROUTE_URL}/')

        assert response.status_code == HTTPStatus.OK
        body = response.get_json()
        assert 'results' in body
        assert len(body['results']) == int(response.headers['X-Total-Count'])


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       UPDATE                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class TestPutUser:
    """PUT /users/<id> writes the new payload over the existing CmdbUser."""

    def test_update_persists_new_first_name(
        self,
        rest_api,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """After PUT, GET reflects the updated first_name."""
        _insert_user_doc(database_manager, database_name, USER_ID_FOR_UPDATE)
        try:
            response = rest_api.put(
                f'{ROUTE_URL}/{USER_ID_FOR_UPDATE}',
                json=_user_payload(USER_ID_FOR_UPDATE, UPDATED_FIRST_NAME),
            )

            assert response.status_code == HTTPStatus.ACCEPTED
            follow_up = rest_api.get(f'{ROUTE_URL}/{USER_ID_FOR_UPDATE}')
            assert follow_up.get_json()['result']['first_name'] == UPDATED_FIRST_NAME
        finally:
            _drop_user(database_manager, database_name, USER_ID_FOR_UPDATE)

    def test_password_patch_succeeds_for_existing_user(
        self,
        rest_api,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """PATCH /users/<id>/password against an existing user returns 202 (or 200)."""
        _insert_user_doc(database_manager, database_name, USER_ID_FOR_PASSWORD)
        try:
            response = rest_api.patch(
                f'{ROUTE_URL}/{USER_ID_FOR_PASSWORD}/password',
                json={'password': NEW_PASSWORD},
            )

            assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
        finally:
            _drop_user(database_manager, database_name, USER_ID_FOR_PASSWORD)


class TestPasswordChangeRespectsWhoOwnsThePassword:
    """
    A password may only be set for a user whose password DataGerry owns

    The LDAP provider never reads a stored digest - its bind IS the check - so writing one would not
    change that user's login. Worse, it would CREATE a second one: the local provider refuses a user
    that carries no password, and that refusal is the only thing keeping a directory-managed account
    out of `AuthModule.authenticate_with_any_provider`, which tries every active provider after the
    primary one fails.
    """

    def test_a_directory_authenticated_user_is_refused(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """400, naming the provider - not a silent 202 that changes nothing the user logs in with."""
        users = database_manager.get_collection(CmdbUser.COLLECTION, database_name)
        doc = _user_doc(USER_ID_LDAP_AUTHENTICATED)
        doc['authenticator'] = LdapAuthenticationProvider.get_name()
        doc.pop('password', None)
        users.insert_one(doc)

        try:
            response = rest_api.patch(
                f'{ROUTE_URL}/{USER_ID_LDAP_AUTHENTICATED}/password',
                json={'password': NEW_PASSWORD},
            )

            assert response.status_code == HTTPStatus.BAD_REQUEST
            assert LdapAuthenticationProvider.get_name() in response.get_json()['message']
        finally:
            _drop_user(database_manager, database_name, USER_ID_LDAP_AUTHENTICATED)

    def test_the_refusal_leaves_the_user_without_a_local_password(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """The point of the refusal: no digest is stored, so the local provider still refuses the user."""
        users = database_manager.get_collection(CmdbUser.COLLECTION, database_name)
        doc = _user_doc(USER_ID_LDAP_AUTHENTICATED)
        doc['authenticator'] = LdapAuthenticationProvider.get_name()
        doc.pop('password', None)
        users.insert_one(doc)

        try:
            rest_api.patch(f'{ROUTE_URL}/{USER_ID_LDAP_AUTHENTICATED}/password', json={'password': NEW_PASSWORD})

            assert not users.find_one({'public_id': USER_ID_LDAP_AUTHENTICATED}).get('password')
        finally:
            _drop_user(database_manager, database_name, USER_ID_LDAP_AUTHENTICATED)

    def test_a_locally_authenticated_user_is_still_changed(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """The guard is about WHO owns the password, so the ordinary case must stay untouched."""
        _insert_user_doc(database_manager, database_name, USER_ID_FOR_PASSWORD)

        try:
            response = rest_api.patch(
                f'{ROUTE_URL}/{USER_ID_FOR_PASSWORD}/password',
                json={'password': NEW_PASSWORD},
            )

            assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
            stored = database_manager.get_collection(CmdbUser.COLLECTION, database_name)\
                .find_one({'public_id': USER_ID_FOR_PASSWORD})
            assert stored['password'] != INITIAL_PASSWORD
        finally:
            _drop_user(database_manager, database_name, USER_ID_FOR_PASSWORD)

    def test_a_user_whose_provider_is_unknown_may_still_be_given_one(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """
        An unknown provider cannot authenticate the user at all

        The local password is then the only way to reach the account, so refusing to set one would
        take away the repair rather than protect anything.
        """
        users = database_manager.get_collection(CmdbUser.COLLECTION, database_name)
        doc = _user_doc(USER_ID_LDAP_AUTHENTICATED)
        doc['authenticator'] = 'NoSuchAuthenticationProvider'
        users.insert_one(doc)

        try:
            response = rest_api.patch(
                f'{ROUTE_URL}/{USER_ID_LDAP_AUTHENTICATED}/password',
                json={'password': NEW_PASSWORD},
            )

            assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
        finally:
            _drop_user(database_manager, database_name, USER_ID_LDAP_AUTHENTICATED)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       DELETE                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class TestDeleteUser:
    """DELETE /users/<id> removes the doc; the admin id remains protected at the manager layer."""

    def test_delete_removes_user(
        self,
        rest_api,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """A DELETE succeeds, and a subsequent GET for the same id returns 404."""
        _insert_user_doc(database_manager, database_name, USER_ID_FOR_DELETE)
        try:
            response = rest_api.delete(f'{ROUTE_URL}/{USER_ID_FOR_DELETE}')

            assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
            follow_up = rest_api.get(f'{ROUTE_URL}/{USER_ID_FOR_DELETE}')
            assert follow_up.status_code == HTTPStatus.NOT_FOUND
        finally:
            _drop_user(database_manager, database_name, USER_ID_FOR_DELETE)
