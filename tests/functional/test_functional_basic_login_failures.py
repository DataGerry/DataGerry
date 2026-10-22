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
Functional tests for what an on-premise login answers when the server, not the caller, fails

Both on-premise entry points log in through `AuthModule.login`: HTTP Basic on any route
(`route_utils._authenticate_basic`) and `POST /auth/login` (`auth_helper.local_login`). Only the caller's credentials
answer 401. A database outage or lock timeout - during the user read or the key read the password HMAC needs - is the
app's 503 / 423, and the same credentials work once the database is back; a stored user that cannot be read is the
500 with its own message; a programming error is the app's 500, as production answers it
"""
import base64
from http import HTTPStatus
from typing import Any
from unittest.mock import patch

import pytest

from cmdb.errors.database import DocumentLockTimeoutError, DocumentNetworkError
from cmdb.errors.manager.users_manager import UsersManagerGetError
from cmdb.interface.route_utils import INVALID_CREDENTIALS_MESSAGE, LOGIN_USER_UNREADABLE_MESSAGE
from cmdb.manager.license_manager.license_service import LicenseService
# -------------------------------------------------------------------------------------------------------------------- #

PROTECTED_ROUTE: str = '/types/'
LOGIN_URL: str = '/auth/login'
ADMIN_NAME: str = 'admin'
ADMIN_PASSWORD: str = 'admin'
WRONG_PASSWORD: str = 'not-the-password'
AUTHORIZATION_ENVIRON_KEY: str = 'HTTP_AUTHORIZATION'

USER_READ: str = 'cmdb.manager.users_manager.UsersManager.get_user_by'
KEY_READ: str = 'cmdb.manager.security_manager.SecurityManager.get_symmetric_aes_key'

OUTAGES: list[Any] = [
    pytest.param(DocumentNetworkError('lost'), HTTPStatus.SERVICE_UNAVAILABLE, id='network'),
    pytest.param(DocumentLockTimeoutError('locked'), HTTPStatus.LOCKED, id='lock'),
]
READS: list[Any] = [pytest.param(USER_READ, id='user-read'), pytest.param(KEY_READ, id='key-read')]


@pytest.fixture(name='licensed', autouse=True)
def fixture_licensed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Licenses every feature, so a Basic request that authenticates reaches the route (REST API is licensed)"""
    monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, _feature: True)


@pytest.fixture(name='production_errors')
def fixture_production_errors(rest_api, monkeypatch: pytest.MonkeyPatch) -> None:
    """Unhandled errors answered as production answers them (500), not re-raised into the test"""
    monkeypatch.setitem(rest_api.application.config, 'PROPAGATE_EXCEPTIONS', False)


def _basic(password: str = ADMIN_PASSWORD) -> dict[str, Any]:
    """Request kwargs replacing the client's Bearer token with HTTP Basic credentials"""
    value: str = base64.b64encode(f'{ADMIN_NAME}:{password}'.encode('utf-8')).decode('utf-8')

    return {'environ_overrides': {AUTHORIZATION_ENVIRON_KEY: f'Basic {value}'}}


def _login(rest_api, password: str = ADMIN_PASSWORD) -> Any:
    """POST /auth/login for the seeded admin"""
    return rest_api.post(LOGIN_URL, json={'user_name': ADMIN_NAME, 'password': password})


def _message(response: Any) -> str | None:
    """The error message of a JSON answer"""
    return response.get_json().get('message') if response.is_json else None


class TestHttpBasic:
    """HTTP Basic on a protected route"""

    def test_the_credentials_authenticate(self, rest_api) -> None:
        """The control: the seeded admin gets through"""
        assert rest_api.get(PROTECTED_ROUTE, **_basic()).status_code == HTTPStatus.OK

    def test_a_wrong_password_is_a_401_naming_the_credentials(self, rest_api) -> None:
        """Not "Invalid Token!": a Basic client sent no token"""
        response = rest_api.get(PROTECTED_ROUTE, **_basic(WRONG_PASSWORD))

        assert response.status_code == HTTPStatus.UNAUTHORIZED
        assert _message(response) == INVALID_CREDENTIALS_MESSAGE

    @pytest.mark.parametrize('read', READS)
    @pytest.mark.parametrize('outage, status', OUTAGES)
    def test_an_outage_is_no_401(self, rest_api, read: str, outage: Exception, status: HTTPStatus) -> None:
        """The app's handler answers it, and the same credentials work once the database is back"""
        with patch(read, side_effect=outage):
            assert rest_api.get(PROTECTED_ROUTE, **_basic()).status_code == status

        assert rest_api.get(PROTECTED_ROUTE, **_basic()).status_code == HTTPStatus.OK

    def test_an_outage_reads_the_user_once(self, rest_api) -> None:
        """No provider sweep re-reads it - a second retry budget during an outage"""
        with patch(USER_READ, side_effect=DocumentNetworkError('lost')) as read:
            rest_api.get(PROTECTED_ROUTE, **_basic())

        assert read.call_count == 1

    def test_an_unreadable_stored_user_is_a_500(self, rest_api) -> None:
        """The server's fault, with its own message"""
        with patch(USER_READ, side_effect=UsersManagerGetError('broken document')):
            response = rest_api.get(PROTECTED_ROUTE, **_basic())

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert _message(response) == LOGIN_USER_UNREADABLE_MESSAGE

    @pytest.mark.usefixtures('production_errors')
    def test_a_bug_is_a_500(self, rest_api) -> None:
        """Not a silent 401"""
        with patch(USER_READ, side_effect=RuntimeError('bug')):
            assert rest_api.get(PROTECTED_ROUTE, **_basic()).status_code == HTTPStatus.INTERNAL_SERVER_ERROR


class TestLoginRoute:
    """POST /auth/login"""

    def test_a_wrong_password_is_a_401(self, rest_api) -> None:
        """The control"""
        response = _login(rest_api, WRONG_PASSWORD)

        assert response.status_code == HTTPStatus.UNAUTHORIZED
        assert _message(response) == INVALID_CREDENTIALS_MESSAGE

    @pytest.mark.parametrize('read', READS)
    @pytest.mark.parametrize('outage, status', OUTAGES)
    def test_an_outage_is_no_500(self, rest_api, read: str, outage: Exception, status: HTTPStatus) -> None:
        """The route's handle_route_errors lets it through to the app's handler; the login works afterwards"""
        with patch(read, side_effect=outage):
            assert _login(rest_api).status_code == status

        assert _login(rest_api).status_code == HTTPStatus.OK

    def test_an_unreadable_stored_user_is_a_500(self, rest_api) -> None:
        """Not "Invalid user credentials!": the user exists and cannot be read"""
        with patch(USER_READ, side_effect=UsersManagerGetError('broken document')):
            response = _login(rest_api)

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert _message(response) == LOGIN_USER_UNREADABLE_MESSAGE

    @pytest.mark.usefixtures('production_errors')
    def test_a_bug_is_a_500(self, rest_api) -> None:
        """The route's own tail"""
        with patch(USER_READ, side_effect=RuntimeError('bug')):
            assert _login(rest_api).status_code == HTTPStatus.INTERNAL_SERVER_ERROR
