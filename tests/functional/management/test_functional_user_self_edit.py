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
Functional coverage of what `PUT /users/<id>` lets each caller change

A user may edit their own record without ``base.user-management.user.edit`` (the ``excepted``
carve-out); that covers the profile - names, email, image - and nothing that decides what the user
may do. A holder of the right may also change the administrative fields; nobody changes the tenant
database, the ConfigItem limit or the password through this route.

The requests are the ones the frontend sends: the user as read from ``GET /users/<id>``, with the
edited fields merged in. The self-editor sits in the seeded "user" group, which does not hold the
edit right; the administrator is the default test client. The cloud test drives hosted cloud mode,
where the tenant database decides which data every later request reads
"""
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.user_model import CmdbUser, CmdbUserKey
from cmdb.models.object_model import CmdbObject
from cmdb.models.group_model.group_constants import ADMIN_GROUP_ID, USER_GROUP_ID

from tests.utils.cloud_mode import cloud_auth_header, enable_hosted_cloud_mode
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_URL: str = '/users'

SELF_EDITOR_ID: int = 9701
OTHER_USER_ID: int = 9702
USER_IDS: list[int] = [SELF_EDITOR_ID, OTHER_USER_ID]

STORED_DIGEST: str = 'digest-that-must-survive'
STORED_LIMIT: int = 50
OTHER_TENANT: str = 'self-edit-other-tenant'

# A value different from the stored one for every field a self-edit may not change
REFUSED_SELF_CHANGES: dict[CmdbUserKey, Any] = {
    CmdbUserKey.GROUP_ID: ADMIN_GROUP_ID,
    CmdbUserKey.ACTIVE: False,
    CmdbUserKey.AUTHENTICATOR: 'LdapAuthenticationProvider',
    CmdbUserKey.API_LEVEL: 3,
    CmdbUserKey.USER_NAME: 'renamed-self-editor',
    CmdbUserKey.DATABASE: OTHER_TENANT,
    CmdbUserKey.CONFIG_ITEMS_LIMIT: 999_999,
}


def _user_document(public_id: int, database: str) -> dict[str, Any]:
    """A stored local user in the "user" group, carrying a password digest and a limit."""
    return {
        'public_id': public_id,
        'user_name': f'self-edit-{public_id}',
        'active': True,
        'group_id': USER_GROUP_ID,
        'registration_time': datetime.now(timezone.utc),
        'authenticator': 'LocalAuthenticationProvider',
        'database': database,
        'api_level': 0,
        'config_items_limit': STORED_LIMIT,
        'password': STORED_DIGEST,
        'first_name': 'Original',
    }


@pytest.fixture(name='users')
def fixture_users(database_manager: MongoDatabaseManager, database_name: str):
    """Stores the self-editor and a second user; yields the collection and removes both afterwards."""
    collection = database_manager.get_collection(CmdbUser.COLLECTION, database_name)
    collection.delete_many({'public_id': {'$in': USER_IDS}})
    collection.insert_many([_user_document(public_id, database_name) for public_id in USER_IDS])
    yield collection
    collection.delete_many({'public_id': {'$in': USER_IDS}})


def _as_self_editor() -> CmdbUser:
    """The test client's identity for the self-editor."""
    return CmdbUser(public_id=SELF_EDITOR_ID, user_name=f'self-edit-{SELF_EDITOR_ID}', active=True,
                    group_id=USER_GROUP_ID)


def _read_back(rest_api, public_id: int, **overrides: Any) -> dict[str, Any]:
    """What the frontend sends: the user as the single read answers it, with the edits merged in."""
    document: dict[str, Any] = rest_api.get(f'{ROUTE_URL}/{public_id}').get_json()['result']

    return {**document, **overrides}


def _stored(users, public_id: int) -> dict[str, Any]:
    """The user document as it sits in the database."""
    return users.find_one({'public_id': public_id}, {'_id': 0})


# -------------------------------------------------------------------------------------------------------------------- #
#                                                    SELF-EDIT                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class TestSelfEdit:
    """A user without the edit right, editing their own record"""

    def test_the_profile_screen_request_is_accepted_and_keeps_the_password(self, rest_api, users) -> None:
        """The frontend's own save: a changed first name goes through, the stored digest survives"""
        response = rest_api.put(f'{ROUTE_URL}/{SELF_EDITOR_ID}',
                                json=_read_back(rest_api, SELF_EDITOR_ID, first_name='Changed'),
                                user=_as_self_editor())

        assert response.status_code == HTTPStatus.ACCEPTED
        stored = _stored(users, SELF_EDITOR_ID)
        assert stored['first_name'] == 'Changed'
        assert stored['password'] == STORED_DIGEST

    @pytest.mark.parametrize('field', sorted(REFUSED_SELF_CHANGES))
    def test_a_field_that_is_not_the_profile_is_refused(self, rest_api, users, field: CmdbUserKey) -> None:
        """Group, activation, authenticator, API level, login name, tenant and limit stay as stored"""
        before = _stored(users, SELF_EDITOR_ID)

        response = rest_api.put(f'{ROUTE_URL}/{SELF_EDITOR_ID}',
                                json=_read_back(rest_api, SELF_EDITOR_ID, **{field.value: REFUSED_SELF_CHANGES[field]}),
                                user=_as_self_editor())

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert field.value in response.get_json()['message']
        assert _stored(users, SELF_EDITOR_ID) == before

    def test_the_promotion_into_the_admin_group_is_refused(self, rest_api, users) -> None:
        """The escalation itself: a "user"-group account cannot put itself in the admin group"""
        rest_api.put(f'{ROUTE_URL}/{SELF_EDITOR_ID}',
                     json=_read_back(rest_api, SELF_EDITOR_ID, group_id=ADMIN_GROUP_ID),
                     user=_as_self_editor())

        assert _stored(users, SELF_EDITOR_ID)['group_id'] == USER_GROUP_ID

    def test_a_password_in_the_body_is_refused(self, rest_api, users) -> None:
        """A password changes through PATCH /users/<id>/password only"""
        response = rest_api.put(f'{ROUTE_URL}/{SELF_EDITOR_ID}',
                                json=_read_back(rest_api, SELF_EDITOR_ID, password='plaintext'),
                                user=_as_self_editor())

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert _stored(users, SELF_EDITOR_ID)['password'] == STORED_DIGEST

    def test_editing_someone_else_is_still_forbidden(self, rest_api, users) -> None:
        """The carve-out covers the caller's own record only"""
        del users
        response = rest_api.put(f'{ROUTE_URL}/{OTHER_USER_ID}',
                                json=_read_back(rest_api, OTHER_USER_ID, first_name='Hijacked'),
                                user=_as_self_editor())

        assert response.status_code == HTTPStatus.FORBIDDEN


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  ADMINISTRATOR                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
class TestAdministratorEdit:
    """The default test client holds the edit right"""

    def test_an_administrator_may_change_the_group(self, rest_api, users) -> None:
        """The administrative fields are exactly what the right unlocks"""
        response = rest_api.put(f'{ROUTE_URL}/{OTHER_USER_ID}',
                                json=_read_back(rest_api, OTHER_USER_ID, group_id=ADMIN_GROUP_ID))

        assert response.status_code == HTTPStatus.ACCEPTED
        assert _stored(users, OTHER_USER_ID)['group_id'] == ADMIN_GROUP_ID

    @pytest.mark.parametrize('field', [CmdbUserKey.DATABASE, CmdbUserKey.CONFIG_ITEMS_LIMIT])
    def test_an_administrator_may_not_change_a_server_owned_field(self, rest_api, users,
                                                                  field: CmdbUserKey) -> None:
        """The tenant database and the ConfigItem limit are refused whoever asks"""
        response = rest_api.put(f'{ROUTE_URL}/{OTHER_USER_ID}',
                                json=_read_back(rest_api, OTHER_USER_ID, **{field.value: REFUSED_SELF_CHANGES[field]}))

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert _stored(users, OTHER_USER_ID)[field.value] != REFUSED_SELF_CHANGES[field]

    def test_the_admin_edit_screen_request_keeps_the_password(self, rest_api, users) -> None:
        """The edit screen removes the password control; saving keeps the stored digest rather than a null"""
        response = rest_api.put(f'{ROUTE_URL}/{OTHER_USER_ID}',
                                json=_read_back(rest_api, OTHER_USER_ID, email='changed@example.com'))

        assert response.status_code == HTTPStatus.ACCEPTED
        assert _stored(users, OTHER_USER_ID)['password'] == STORED_DIGEST


# -------------------------------------------------------------------------------------------------------------------- #
#                                                    CLOUD MODE                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
class TestCloudTenantSwitch:
    """In cloud mode the stored database binds every manager, so moving it would move the user"""

    def test_a_self_edit_cannot_move_the_user_into_another_tenant(
            self, rest_api, users, monkeypatch, database_manager: MongoDatabaseManager, database_name: str) -> None:
        """Refused, and the next request still reads the user's own tenant"""
        own_count: int = database_manager.get_collection(CmdbObject.COLLECTION, database_name).count_documents({})
        # One object more than the own tenant holds, so reading the wrong tenant shows in the count
        database_manager.connector.client[OTHER_TENANT][CmdbObject.COLLECTION].insert_many(
            [{'public_id': public_id, 'type_id': 1} for public_id in range(1, own_count + 2)]
        )
        enable_hosted_cloud_mode(rest_api, monkeypatch, database_manager)
        header: dict[str, str] = cloud_auth_header(rest_api, SELF_EDITOR_ID, database_name)

        try:
            body = rest_api.get(f'{ROUTE_URL}/{SELF_EDITOR_ID}', environ_overrides=header).get_json()['result']
            response = rest_api.put(f'{ROUTE_URL}/{SELF_EDITOR_ID}', json={**body, 'database': OTHER_TENANT},
                                    environ_overrides=header)
            count = rest_api.get('/objects/count', environ_overrides=header)

            assert response.status_code == HTTPStatus.BAD_REQUEST
            assert _stored(users, SELF_EDITOR_ID)['database'] == database_name
            assert count.get_json() == own_count
        finally:
            database_manager.connector.client.drop_database(OTHER_TENANT)
