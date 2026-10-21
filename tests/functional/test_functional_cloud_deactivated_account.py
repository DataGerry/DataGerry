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
Functional coverage of `CmdbUser.active` on the two hosted-cloud paths

The ServicePortal decides whether credentials are right; the tenant's stored flag decides whether
the tenant's account may be used. So a deactivated account gets no token from the cloud login and no
access through Basic + `x-api-key`, reactivating restores both, and credentials the portal refused are
answered by the portal's refusal. The portal is stubbed at both call sites. An `x-api-key` next to a
Bearer token is resolved from the token, like any other request
"""
import base64
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.user_model import CmdbUser
from cmdb.interface import route_utils
from cmdb.interface.route_utils import API_KEY_HEADER, USER_DEACTIVATED_MESSAGE
from cmdb.interface.rest_api.routes import auth_helper
from tests.utils.cloud_mode import cloud_auth_header, enable_hosted_cloud_mode
# -------------------------------------------------------------------------------------------------------------------- #

LOGIN_URL: str = '/auth/login'
PROTECTED_URL: str = '/types/?limit=1'

USER_ID: int = 93997
EMAIL: str = 'cloud-deactivation@x.io'
PASSWORD: str = 'portal-password'
API_KEY: str = 'subscription-key'
PORTAL_REFUSAL: str = 'Invalid user data. Failed to login!'

API_KEY_ENVIRON: str = f'HTTP_{API_KEY_HEADER.upper().replace("-", "_")}'


def _portal_user(database: str) -> dict[str, Any]:
    """The ServicePortal's answer for the account: one subscription on the test database."""
    return {
        'email': EMAIL, 'user_name': 'cloud-deactivation', 'password': PASSWORD, 'api_level': 3,
        'subscriptions': [{'id': 1, 'name': 'sub', 'database': database, 'api_level': 3,
                           'config_item_limit': 100}],
    }


@pytest.fixture(name='users')
def fixture_users(rest_api, monkeypatch: pytest.MonkeyPatch, database_manager: MongoDatabaseManager,
                  database_name: str):
    """A hosted-cloud app, a stored ACTIVE tenant user and a portal that accepts it; yields the collection."""
    users = database_manager.get_collection(CmdbUser.COLLECTION, database_name)
    users.delete_many({'public_id': USER_ID})
    users.insert_one({
        'public_id': USER_ID, 'user_name': 'cloud-deactivation', 'email': EMAIL, 'active': True,
        'group_id': 1, 'database': database_name, 'api_level': 3,
        'registration_time': datetime.now(timezone.utc),
    })

    enable_hosted_cloud_mode(rest_api, monkeypatch, database_manager)
    portal = _portal_user(database_name)
    monkeypatch.setattr(auth_helper, 'check_user_in_service_portal', lambda *_args, **_kwargs: portal)
    monkeypatch.setattr(route_utils, 'check_user_in_service_portal', lambda *_args, **_kwargs: portal)
    monkeypatch.setattr(auth_helper, 'check_db_exists', lambda _database: True)

    yield users

    users.delete_many({'public_id': USER_ID})


def _set_active(users, active: bool) -> None:
    """Flips the stored flag directly, as a tenant administrator's deactivation would."""
    users.update_one({'public_id': USER_ID}, {'$set': {'active': active}})


def _login(rest_api):
    """POST /auth/login without the test client's own token."""
    return rest_api.post(LOGIN_URL, json={'user_name': EMAIL, 'password': PASSWORD}, unauthorized=True)


def _with_api_key(rest_api):
    """A protected request authenticated by Basic credentials and the subscription's API key."""
    basic: str = base64.b64encode(f'{EMAIL}:{PASSWORD}'.encode('utf-8')).decode('utf-8')

    return rest_api.get(PROTECTED_URL, environ_overrides={'HTTP_AUTHORIZATION': f'Basic {basic}',
                                                          API_KEY_ENVIRON: API_KEY})


# -------------------------------------------------------------------------------------------------------------------- #
#                                          the cloud login                                                             #
# -------------------------------------------------------------------------------------------------------------------- #
def test_a_deactivated_tenant_account_gets_no_token(rest_api, users) -> None:
    """The portal accepted the credentials, the tenant deactivated the account: 401 and no token"""
    _set_active(users, False)

    response = _login(rest_api)

    assert response.status_code == HTTPStatus.UNAUTHORIZED
    assert response.get_json()['message'] == USER_DEACTIVATED_MESSAGE
    assert 'token' not in response.get_json()


def test_reactivating_restores_the_cloud_login(rest_api, users) -> None:
    """Deactivated, then active again: the login issues a token"""
    _set_active(users, False)
    assert _login(rest_api).status_code == HTTPStatus.UNAUTHORIZED

    _set_active(users, True)
    response = _login(rest_api)

    assert response.status_code == HTTPStatus.OK
    assert response.get_json()['token']


def test_a_portal_refusal_does_not_reveal_the_deactivation(rest_api, users,
                                                           monkeypatch: pytest.MonkeyPatch) -> None:
    """Credentials the portal refused are the portal's answer - the account's state is never reached"""
    _set_active(users, False)
    monkeypatch.setattr(auth_helper, 'check_user_in_service_portal', lambda *_args, **_kwargs: None)

    response = _login(rest_api)

    assert response.status_code == HTTPStatus.UNAUTHORIZED
    assert response.get_json()['message'] == PORTAL_REFUSAL


# -------------------------------------------------------------------------------------------------------------------- #
#                                          Basic + x-api-key                                                           #
# -------------------------------------------------------------------------------------------------------------------- #
def test_an_active_account_is_let_through_by_api_key(rest_api, users) -> None:
    """The ordinary case is unaffected"""
    assert _with_api_key(rest_api).status_code == HTTPStatus.OK


def test_a_deactivated_account_is_refused_by_api_key(rest_api, users) -> None:
    """An API key does not outlive a deactivation: 401 naming it"""
    _set_active(users, False)

    response = _with_api_key(rest_api)

    assert response.status_code == HTTPStatus.UNAUTHORIZED
    assert response.get_json()['message'] == USER_DEACTIVATED_MESSAGE


def test_reactivating_restores_api_key_access(rest_api, users) -> None:
    """Deactivated, then active again: the same credentials and key work"""
    _set_active(users, False)
    assert _with_api_key(rest_api).status_code == HTTPStatus.UNAUTHORIZED

    _set_active(users, True)

    assert _with_api_key(rest_api).status_code == HTTPStatus.OK


# -------------------------------------------------------------------------------------------------------------------- #
#                                          x-api-key next to a Bearer token                                            #
# -------------------------------------------------------------------------------------------------------------------- #
def test_an_api_key_next_to_a_bearer_token_is_resolved_from_the_token(rest_api, users,
                                                                      database_name: str) -> None:
    """The key alone decides nothing: the token's user is resolved, instead of a 401 for a missing user"""
    environ: dict[str, str] = {**cloud_auth_header(rest_api, USER_ID, database_name), API_KEY_ENVIRON: API_KEY}

    assert rest_api.get(PROTECTED_URL, environ_overrides=environ).status_code == HTTPStatus.OK


def test_a_deactivated_account_is_refused_with_a_bearer_token_and_an_api_key(rest_api, users,
                                                                             database_name: str) -> None:
    """Adding the key to the header set does not skip the deactivation check"""
    _set_active(users, False)
    environ: dict[str, str] = {**cloud_auth_header(rest_api, USER_ID, database_name), API_KEY_ENVIRON: API_KEY}

    response = rest_api.get(PROTECTED_URL, environ_overrides=environ)

    assert response.status_code == HTTPStatus.UNAUTHORIZED
    assert response.get_json()['message'] == USER_DEACTIVATED_MESSAGE
