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
What `insert_request_user` answers when the request's user cannot be resolved - through the real REST app

Only the caller's credentials may answer 401: the frontend answers a 401 by logging the user out. A database outage
during the user read is left to the app's handlers (503 / 423) and the next request works again; a stored user that
cannot be read and a programming error are 500s. A token without a user claim, and one naming a user the database
does not hold, stay 401s with their own message
"""
from http import HTTPStatus
from typing import Any
from unittest.mock import patch

import pytest

from cmdb.errors.database import DocumentLockTimeoutError, DocumentNetworkError
from cmdb.errors.manager.users_manager import UsersManagerGetError
from cmdb.interface.route_utils import INVALID_TOKEN_MESSAGE, INVALID_USER_MESSAGE, USER_UNREADABLE_MESSAGE
# -------------------------------------------------------------------------------------------------------------------- #

PROBE_URL: str = '/types/'
USER_READ: str = 'cmdb.interface.route_utils.UsersManager.get_user'
TOKEN_DECODE: str = 'cmdb.interface.route_utils.decode_request_token'
AUTHORIZATION_ENVIRON_KEY: str = 'HTTP_AUTHORIZATION'
UNKNOWN_USER_ID: int = 97001


def _message(response: Any) -> str | None:
    """The error message of a JSON answer"""
    return response.get_json().get('message') if response.is_json else None


def _bearer(rest_api, payload: dict[str, Any]) -> dict[str, Any]:
    """Request kwargs carrying a token the test app signs, with `payload` as its DataGerry claim"""
    generator = rest_api._token_generator  # pylint: disable=protected-access
    token: str = generator.generate_token(payload=payload).decode('UTF-8')

    return {'environ_overrides': {AUTHORIZATION_ENVIRON_KEY: f'Bearer {token}'}}


@pytest.mark.parametrize('outage, status', [
    (DocumentNetworkError('lost'), HTTPStatus.SERVICE_UNAVAILABLE),
    (DocumentLockTimeoutError('locked'), HTTPStatus.LOCKED),
], ids=['network', 'lock'])
def test_an_outage_during_the_user_read_is_no_logout(rest_api, outage: Exception, status: HTTPStatus) -> None:
    """The app's handler answers it, and the same token works once the database is back"""
    with patch(USER_READ, side_effect=outage):
        assert rest_api.get(PROBE_URL).status_code == status

    assert rest_api.get(PROBE_URL).status_code == HTTPStatus.OK


def test_an_unreadable_user_is_a_500(rest_api) -> None:
    """The server's fault, with its own message"""
    with patch(USER_READ, side_effect=UsersManagerGetError('broken document')):
        response = rest_api.get(PROBE_URL)

    assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
    assert _message(response) == USER_UNREADABLE_MESSAGE


@pytest.mark.parametrize('target', [USER_READ, TOKEN_DECODE], ids=['user-read', 'token-decode'])
def test_a_bug_is_a_500_not_an_expired_session(rest_api, monkeypatch: pytest.MonkeyPatch, target: str) -> None:
    """Neither half turns a programming error into a 401 - answered as production does, not re-raised to the test"""
    monkeypatch.setitem(rest_api.application.config, 'PROPAGATE_EXCEPTIONS', False)

    with patch(target, side_effect=TypeError('bug')):
        response = rest_api.get(PROBE_URL)

    assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR


def test_a_token_without_a_user_claim_is_an_invalid_token(rest_api) -> None:
    """Signed by the server, but naming nobody"""
    response = rest_api.get(PROBE_URL, **_bearer(rest_api, {}))

    assert response.status_code == HTTPStatus.UNAUTHORIZED
    assert _message(response) == INVALID_TOKEN_MESSAGE


def test_a_token_naming_an_unknown_user_is_an_invalid_user(rest_api) -> None:
    """The credentials are wrong - the one case the user read answers 401"""
    response = rest_api.get(PROBE_URL, **_bearer(rest_api, {'user': {'public_id': UNKNOWN_USER_ID}}))

    assert response.status_code == HTTPStatus.UNAUTHORIZED
    assert _message(response) == INVALID_USER_MESSAGE
