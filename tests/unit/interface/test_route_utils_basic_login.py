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
Unit tests for the steps of an on-premise HTTP Basic login in cmdb.interface.route_utils

`decode_basic_credentials` (the header value, or None for malformed credentials), `build_local_auth_module` (the
AuthModule both on-premise entry points log in with) and `login_basic_user` (only a refused login is "no user";
an unreadable stored user is the 500; an outage or a bug passes through). `_authenticate_basic`, which runs them in
order, is tested with the rest of the request authentication in test_route_utils
"""
import base64
from http import HTTPStatus
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from werkzeug.exceptions import HTTPException

import cmdb.interface.route_utils as ru
from cmdb.errors.database import DocumentLockTimeoutError, DocumentNetworkError
from cmdb.errors.manager.users_manager import UsersManagerGetError
from cmdb.errors.provider import AuthenticationError
from cmdb.models.security_models.auth_settings_constants import AUTH_SETTINGS_ID
from tests.utils.cmdb_app_stub import stub_cmdb_app
# -------------------------------------------------------------------------------------------------------------------- #

MODULE_PATH: str = 'cmdb.interface.route_utils'

BASIC_EMAIL: str = 'user@test.com'
BASIC_PASSWORD: str = 'secret'
AUTH_DEFAULTS: dict[str, Any] = {'defaults': True}


# ============================================== decode_basic_credentials ============================================ #

class TestDecodeBasicCredentials:
    """The Basic value decoded, or None for the caller's malformed credentials"""

    def test_the_pair_is_decoded_and_the_login_stripped(self) -> None:
        """The whitespace goes, the case stays (AuthModule tries it)"""
        assert ru.decode_basic_credentials(base64.b64encode(b' Admin :se:cret').decode('utf-8')) == (
            'Admin', 'se:cret')

    @pytest.mark.parametrize('value', [
        'not-valid-base64!!',
        base64.b64encode(b'no-colon').decode('utf-8'),
        base64.b64encode(b'\xff\xfe:secret').decode('utf-8'),
    ], ids=['no-base64', 'no-colon', 'no-utf8'])
    def test_malformed_credentials_are_none(self, value: str) -> None:
        """Every malformed shape is the same None"""
        assert ru.decode_basic_credentials(value) is None


# ============================================== build_local_auth_module ============================================= #

def test_the_local_auth_module_is_built_from_the_stored_settings() -> None:
    """The 'auth' section with the module's defaults, and the installation's managers"""
    auth_module_cls = MagicMock()
    auth_module_cls.__DEFAULT_SETTINGS__ = AUTH_DEFAULTS
    settings_manager = MagicMock()

    with patch.multiple(MODULE_PATH, UsersManager=MagicMock(), SecurityManager=MagicMock(),
                        SettingsManager=MagicMock(return_value=settings_manager), AuthModule=auth_module_cls):
        with stub_cmdb_app(cloud_mode=False).test_request_context():
            assert ru.build_local_auth_module() is auth_module_cls.return_value

    settings_manager.get_all_values_from_section.assert_called_once_with(AUTH_SETTINGS_ID, default=AUTH_DEFAULTS)
    assert auth_module_cls.call_args.args == (settings_manager.get_all_values_from_section.return_value,)
    assert set(auth_module_cls.call_args.kwargs) == {'security_manager', 'users_manager'}


# ================================================= login_basic_user ================================================= #

class TestLoginBasicUser:
    """Only a refusal is "no user"; an unreadable user is the 500 and everything else passes through"""

    @staticmethod
    def _login(outcome: Any) -> Any:
        """Runs login_basic_user with AuthModule.login answering `outcome`"""
        auth_module = MagicMock()

        if isinstance(outcome, Exception):
            auth_module.login.side_effect = outcome
        else:
            auth_module.login.return_value = outcome

        with patch(f'{MODULE_PATH}.build_local_auth_module', return_value=auth_module):
            with stub_cmdb_app(cloud_mode=False).test_request_context():
                return ru.login_basic_user(BASIC_EMAIL, BASIC_PASSWORD)

    def test_the_authenticated_user(self) -> None:
        """What the login answered"""
        user = MagicMock()

        assert self._login(user) is user

    def test_a_refusal_is_no_user(self) -> None:
        """The caller's credentials"""
        assert self._login(AuthenticationError('refused')) is None

    def test_an_unreadable_stored_user_is_the_500(self) -> None:
        """The server's fault, with its own message"""
        with pytest.raises(HTTPException) as exc_info:
            self._login(UsersManagerGetError('broken document'))

        assert (exc_info.value.code, exc_info.value.description) == (
            HTTPStatus.INTERNAL_SERVER_ERROR, ru.LOGIN_USER_UNREADABLE_MESSAGE)

    @pytest.mark.parametrize('failure', [
        DocumentNetworkError('lost'), DocumentLockTimeoutError('locked'), RuntimeError('bug'),
    ], ids=['network', 'lock', 'bug'])
    def test_anything_else_passes_through(self, failure: Exception) -> None:
        """Left to the app's handlers"""
        with pytest.raises(type(failure)):
            self._login(failure)
