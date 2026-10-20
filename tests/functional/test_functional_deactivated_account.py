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
Functional coverage of `CmdbUser.active` on the on-premise login and on every request

A deactivated account gets no token, and a token issued while it was active stops working on its next
request - the request user is read from the database each time, so no revocation list is needed.
Reactivating restores access. The deactivation is only revealed to a caller who proved the password:
a wrong password is the ordinary credentials failure
"""
from datetime import datetime, timezone
from http import HTTPStatus

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import SecurityManager
from cmdb.models.user_model import CmdbUser
from cmdb.interface.route_utils import USER_DEACTIVATED_MESSAGE
# -------------------------------------------------------------------------------------------------------------------- #

LOGIN_URL: str = '/auth/login'
PROTECTED_URL: str = '/types/?limit=1'

USER_ID: int = 93991
USER_NAME: str = 'deactivation-user'
PASSWORD: str = 'correct-battery'
WRONG_PASSWORD: str = 'wrong-battery'
CREDENTIALS_REFUSED: str = 'Invalid user credentials!'


@pytest.fixture(name='users')
def fixture_users(rest_api, database_manager: MongoDatabaseManager, database_name: str):
    """Stores an ACTIVE local admin-group user with a real password digest; yields the collection."""
    users = database_manager.get_collection(CmdbUser.COLLECTION, database_name)
    users.delete_many({'public_id': USER_ID})

    with rest_api.application.app_context():
        digest: str = SecurityManager(database_manager).generate_hmac(PASSWORD)

    users.insert_one({
        'public_id': USER_ID, 'user_name': USER_NAME, 'active': True, 'group_id': 1,
        'authenticator': 'LocalAuthenticationProvider', 'password': digest,
        'registration_time': datetime.now(timezone.utc),
    })
    yield users
    users.delete_many({'public_id': USER_ID})


def _set_active(users, active: bool) -> None:
    """Flips the stored flag directly, as a later deactivation would."""
    users.update_one({'public_id': USER_ID}, {'$set': {'active': active}})


def _login(rest_api, password: str = PASSWORD):
    """POST /auth/login without the test client's own token."""
    return rest_api.post(LOGIN_URL, json={'user_name': USER_NAME, 'password': password}, unauthorized=True)


def _with_token(rest_api, token: str):
    """A protected request carrying the given token."""
    return rest_api.get(PROTECTED_URL, environ_overrides={'HTTP_AUTHORIZATION': f'Bearer {token}'})


def test_a_deactivated_account_gets_no_token(rest_api, users) -> None:
    """The right password, a deactivated account: 401 naming the reason, and no token in the answer"""
    _set_active(users, False)

    response = _login(rest_api)

    assert response.status_code == HTTPStatus.UNAUTHORIZED
    assert response.get_json()['message'] == USER_DEACTIVATED_MESSAGE
    assert 'token' not in response.get_json()


def test_a_wrong_password_does_not_reveal_the_deactivation(rest_api, users) -> None:
    """The ordinary credentials failure - the account's state is never reached"""
    _set_active(users, False)

    response = _login(rest_api, WRONG_PASSWORD)

    assert response.status_code == HTTPStatus.UNAUTHORIZED
    assert response.get_json()['message'] == CREDENTIALS_REFUSED


def test_a_token_stops_working_once_the_account_is_deactivated(rest_api, users) -> None:
    """Issued while active, refused on the next request after the deactivation"""
    token: str = _login(rest_api).get_json()['token']
    assert _with_token(rest_api, token).status_code == HTTPStatus.OK

    _set_active(users, False)
    refused = _with_token(rest_api, token)

    assert refused.status_code == HTTPStatus.UNAUTHORIZED
    assert refused.get_json()['message'] == USER_DEACTIVATED_MESSAGE


def test_reactivating_restores_access(rest_api, users) -> None:
    """The same token works again, and a new login succeeds"""
    token: str = _login(rest_api).get_json()['token']
    _set_active(users, False)
    assert _with_token(rest_api, token).status_code == HTTPStatus.UNAUTHORIZED

    _set_active(users, True)

    assert _with_token(rest_api, token).status_code == HTTPStatus.OK
    assert _login(rest_api).status_code == HTTPStatus.OK
