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
Functional coverage of how a submitted login is normalised, on every entry point

On premise a login is stripped and tried as typed, then lower-cased, through the login route and HTTP
Basic alike - so ``ADMIN`` and `` admin `` log in as ``admin``, and a user stored as ``Mixed-Name`` is
still found as typed. In hosted cloud mode the portal is sent the stripped, lower-cased email, and the
tenant user is looked up by the address the portal answered with - so Basic credentials typed in
another case reach the account they belong to. Without an ``x-api-key`` cloud Basic credentials are refused

The portal is stubbed where the entry points call it, with the answer it sends to an ``x-api-key`` request
(``tests.utils.service_portal_answers``)
"""
import base64
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.interface import route_utils
from cmdb.interface.route_utils import API_KEY_HEADER
from cmdb.manager import SecurityManager
from cmdb.manager.security_manager import SYMMETRIC_KEY_ENV_VAR
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.models.user_model import CmdbUser
from tests.utils.cloud_mode import enable_hosted_cloud_mode
from tests.utils.service_portal_answers import portal_api_key_answer, portal_subscription
# -------------------------------------------------------------------------------------------------------------------- #

LOGIN_URL: str = '/auth/login'
PROTECTED_URL: str = '/types/?limit=1'

ADMIN_NAME: str = 'admin'
ADMIN_PASSWORD: str = 'admin'

MIXED_USER_ID: int = 93981
MIXED_USER_NAME: str = 'Mixed-Name'
MIXED_PASSWORD: str = 'mixed-password'

CLOUD_USER_ID: int = 93982
CLOUD_EMAIL: str = 'login-name@cloud.io'
TYPED_CLOUD_EMAIL: str = ' Login-Name@Cloud.IO '
CLOUD_PASSWORD: str = 'portal-password'
API_KEY: str = 'subscription-key'
CLOUD_AES_KEY: bytes = b'k' * 32
API_KEY_ENVIRON: str = f'HTTP_{API_KEY_HEADER.upper().replace("-", "_")}'


def _basic(user_name: str, password: str) -> dict[str, str]:
    """environ_overrides replacing the client's token with HTTP Basic credentials."""
    credentials: str = base64.b64encode(f'{user_name}:{password}'.encode('utf-8')).decode('utf-8')

    return {'HTTP_AUTHORIZATION': f'Basic {credentials}'}


def _login(rest_api, user_name: str, password: str):
    """POST /auth/login without the test client's own token."""
    return rest_api.post(LOGIN_URL, json={'user_name': user_name, 'password': password}, unauthorized=True)


def _stored_user(database_manager: MongoDatabaseManager, database_name: str, public_id: int, user_name: str,
                 password: str, **extra: Any) -> dict[str, Any]:
    """A user document carrying the password hash the local provider compares against."""
    security_manager = SecurityManager(database_manager, database_name)

    return {
        'public_id': public_id, 'user_name': user_name, 'active': True, 'group_id': 1,
        'registration_time': datetime.now(timezone.utc), 'authenticator': 'LocalAuthenticationProvider',
        'password': security_manager.generate_hmac(password), **extra,
    }


@pytest.fixture(name='licensed')
def fixture_licensed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Licenses every feature, so HTTP Basic reaches the route rather than the REST API licence gate."""
    monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, _feature: True)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                     ON PREMISE                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
@pytest.fixture(name='mixed_user')
def fixture_mixed_user(rest_api, database_manager: MongoDatabaseManager, database_name: str):
    """A user stored with a mixed-case name, as the user form stores it."""
    users = database_manager.get_collection(CmdbUser.COLLECTION, database_name)
    users.delete_many({'public_id': MIXED_USER_ID})
    with rest_api.application.app_context():
        users.insert_one(_stored_user(database_manager, database_name, MIXED_USER_ID, MIXED_USER_NAME,
                                      MIXED_PASSWORD))
    yield
    users.delete_many({'public_id': MIXED_USER_ID})


class TestOnPremiseLogin:
    """POST /auth/login and HTTP Basic, against the stored admin and a mixed-case user"""

    @pytest.mark.parametrize('typed', ['ADMIN', 'Admin', f'  {ADMIN_NAME} ', f'{ADMIN_NAME}\t'],
                             ids=['upper', 'capitalised', 'padded', 'trailing-tab'])
    def test_the_login_route_normalises_the_name(self, rest_api, typed: str) -> None:
        """Case and surrounding whitespace do not decide a correct login"""
        response = _login(rest_api, typed, ADMIN_PASSWORD)

        assert response.status_code == HTTPStatus.OK
        assert response.get_json()['user']['user_name'] == ADMIN_NAME

    def test_a_mixed_case_name_is_found_as_typed(self, rest_api, mixed_user) -> None:
        """Stored as 'Mixed-Name', typed as 'Mixed-Name': found by the first lookup"""
        assert _login(rest_api, MIXED_USER_NAME, MIXED_PASSWORD).status_code == HTTPStatus.OK

    def test_a_wrong_password_is_still_refused(self, rest_api) -> None:
        """Normalising the name changes nothing about the password"""
        assert _login(rest_api, 'ADMIN', 'not-the-password').status_code == HTTPStatus.UNAUTHORIZED

    @pytest.mark.parametrize('typed', ['ADMIN', f' {ADMIN_NAME} '], ids=['upper', 'padded'])
    def test_basic_credentials_are_normalised_the_same_way(self, rest_api, licensed, typed: str) -> None:
        """The API client's path follows the login route's rule"""
        response = rest_api.get(PROTECTED_URL, environ_overrides=_basic(typed, ADMIN_PASSWORD))

        assert response.status_code == HTTPStatus.OK


# -------------------------------------------------------------------------------------------------------------------- #
#                                                     HOSTED CLOUD                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
@pytest.fixture(name='portal_calls')
def fixture_portal_calls(rest_api, monkeypatch: pytest.MonkeyPatch, database_manager: MongoDatabaseManager,
                         database_name: str):
    """A hosted-cloud app, a tenant user stored under the lower-case address, and a recording portal stub."""
    users = database_manager.get_collection(CmdbUser.COLLECTION, database_name)
    users.delete_many({'public_id': CLOUD_USER_ID})

    # Hosted cloud mode keys the password hash with the environment's AES key, so the stored hash is
    # computed after the switch
    enable_hosted_cloud_mode(rest_api, monkeypatch, database_manager)
    monkeypatch.setenv(SYMMETRIC_KEY_ENV_VAR, base64.b64encode(CLOUD_AES_KEY).decode('ascii'))
    with rest_api.application.app_context():
        users.insert_one(_stored_user(
            database_manager, database_name, CLOUD_USER_ID, 'login-name', CLOUD_PASSWORD,
            email=CLOUD_EMAIL, database=database_name, api_level=3,
        ))

    calls: list[str] = []
    portal: dict[str, Any] = portal_api_key_answer(
        CLOUD_EMAIL, 'login-name', CLOUD_PASSWORD,
        portal_subscription(database_name, api_level=3, config_item_limit=100, api_key=API_KEY),
    )

    def _portal(email: str, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
        calls.append(email)
        return portal

    monkeypatch.setattr(route_utils, 'check_user_in_service_portal', _portal)

    yield calls

    users.delete_many({'public_id': CLOUD_USER_ID})


class TestHostedCloudBasic:
    """HTTP Basic with an email typed in another case than the tenant user is stored under"""

    def test_without_an_api_key_the_request_is_refused(self, rest_api, licensed, portal_calls: list[str]) -> None:
        """No tenant to log into without the key: its own 401, before the portal is asked"""
        response = rest_api.get(PROTECTED_URL, environ_overrides=_basic(TYPED_CLOUD_EMAIL, CLOUD_PASSWORD))

        assert response.status_code == HTTPStatus.UNAUTHORIZED
        assert response.get_json()['message'] == route_utils.CLOUD_BASIC_WITHOUT_API_KEY_MESSAGE
        assert not portal_calls

    def test_with_an_api_key_the_account_is_reached_too(self, rest_api, licensed, portal_calls: list[str]) -> None:
        """The key-based path already used the portal's address; it still does"""
        environ: dict[str, str] = {**_basic(TYPED_CLOUD_EMAIL, CLOUD_PASSWORD), API_KEY_ENVIRON: API_KEY}

        assert rest_api.get(PROTECTED_URL, environ_overrides=environ).status_code == HTTPStatus.OK
