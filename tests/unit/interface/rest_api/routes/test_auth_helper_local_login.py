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
Unit tests for `auth_helper.local_login` and a deactivated account

The check runs after `AuthModule.login` returned, never inside it: a refusal raised within `login` would
be caught by its fallback sweep and handed to every other provider. So what is pinned: an authenticated
but deactivated user is a 401 with the deactivation message and no token is generated, and a wrong
password for a deactivated user still gets the ordinary credentials failure - the deactivation is only
ever revealed to a caller who proved the password

Only the credentials answer 401: an unreadable stored user is the 500, and an outage or a bug leaves
`local_login` as itself for the route's `handle_route_errors` and the app's handlers
"""
from http import HTTPStatus
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask
from werkzeug.exceptions import HTTPException

from cmdb.interface.route_utils import (
    INVALID_CREDENTIALS_MESSAGE,
    LOGIN_USER_UNREADABLE_MESSAGE,
    USER_DEACTIVATED_MESSAGE,
)
from cmdb.interface.rest_api.routes import auth_helper
from cmdb.errors.database import DocumentLockTimeoutError, DocumentNetworkError
from cmdb.errors.manager.users_manager import UsersManagerGetError
from cmdb.errors.provider import AuthenticationError
# -------------------------------------------------------------------------------------------------------------------- #

PATH: str = 'cmdb.interface.rest_api.routes.auth_helper'


def _login(login_outcome) -> tuple[HTTPException | None, MagicMock]:
    """Runs local_login with AuthModule.login answering `login_outcome`; returns the refusal and the token mock."""
    app = Flask(__name__)
    app.database_manager = MagicMock()
    auth_module = MagicMock()

    if isinstance(login_outcome, Exception):
        auth_module.login.side_effect = login_outcome
    else:
        auth_module.login.return_value = login_outcome

    with app.test_request_context(), \
         patch(f'{PATH}.build_local_auth_module', return_value=auth_module), \
         patch(f'{PATH}.generate_token_with_params', return_value=('t', 1, 2)) as token, \
         patch(f'{PATH}.LoginResponse'):
        try:
            auth_helper.local_login('someone', 'password')
        except HTTPException as refused:
            return refused, token

    return None, token


def test_a_deactivated_user_that_authenticated_gets_no_token() -> None:
    """401 naming the deactivation, and the token generator is never reached"""
    refused, token = _login(SimpleNamespace(active=False))

    assert refused is not None
    assert refused.code == HTTPStatus.UNAUTHORIZED
    assert refused.description == USER_DEACTIVATED_MESSAGE
    token.assert_not_called()


def test_an_active_user_is_issued_a_token() -> None:
    """The check lets an active account through untouched"""
    refused, token = _login(SimpleNamespace(active=True))

    assert refused is None
    token.assert_called_once()


@pytest.mark.parametrize('failure', [AuthenticationError('no provider accepted the credentials')])
def test_a_failed_authentication_is_the_ordinary_refusal(failure: Exception) -> None:
    """A wrong password never reaches the deactivation check, so it cannot reveal the account's state"""
    refused, token = _login(failure)

    assert refused.code == HTTPStatus.UNAUTHORIZED
    assert refused.description == INVALID_CREDENTIALS_MESSAGE
    token.assert_not_called()


def test_an_unreadable_stored_user_is_the_servers_500() -> None:
    """Not "wrong credentials": the user exists and the server cannot read it"""
    refused, token = _login(UsersManagerGetError('broken document'))

    assert refused.code == HTTPStatus.INTERNAL_SERVER_ERROR
    assert refused.description == LOGIN_USER_UNREADABLE_MESSAGE
    token.assert_not_called()


@pytest.mark.parametrize('failure', [
    DocumentNetworkError('lost'), DocumentLockTimeoutError('locked'), RuntimeError('bug'),
], ids=['network', 'lock', 'bug'])
def test_an_outage_or_a_bug_leaves_the_login_as_itself(failure: Exception) -> None:
    """The route's handle_route_errors and the app's handlers answer them (503 / 423 / 500), never a 401"""
    with pytest.raises(type(failure)):
        _login(failure)
