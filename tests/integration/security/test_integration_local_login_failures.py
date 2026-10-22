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
Integration tests for an on-premise login whose user cannot be read, against a real MongoDB

The real AuthModule, providers and UsersManager log in users written straight into the collection. A stored user the
model refuses (a registration date nothing can parse) is the server's fault on both entry points - the 500 with its
own message, never the refusal a wrong password gets. A lost database server during the user read leaves the login
after ONE read: the provider sweep, which would read the user again, does not run
"""
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any
from unittest.mock import patch

import pytest
from werkzeug.exceptions import HTTPException

from cmdb.database import MongoDatabaseManager
from cmdb.errors.database import DocumentNetworkError
from cmdb.interface.route_utils import LOGIN_USER_UNREADABLE_MESSAGE, build_local_auth_module, login_basic_user
from cmdb.manager import SecurityManager
from cmdb.models.group_model.group_constants import ADMIN_GROUP_ID
from cmdb.models.user_model import CmdbUser, CmdbUserKey
# -------------------------------------------------------------------------------------------------------------------- #

READABLE_ID: int = 97201
UNREADABLE_ID: int = 97202
USER_IDS: list[int] = [READABLE_ID, UNREADABLE_ID]
READABLE_NAME: str = 'login-readable'
UNREADABLE_NAME: str = 'login-unreadable'
PASSWORD: str = 'login-secret'
WRONG_PASSWORD: str = 'not-the-password'
UNPARSABLE_DATE: str = 'not a date'
LOGIN_URL: str = '/auth/login'


def _user(public_id: int, user_name: str, password_hash: str) -> dict[str, Any]:
    """A complete stored local user"""
    return {
        CmdbUserKey.PUBLIC_ID.value: public_id, CmdbUserKey.USER_NAME.value: user_name,
        CmdbUserKey.ACTIVE.value: True, CmdbUserKey.GROUP_ID.value: ADMIN_GROUP_ID,
        CmdbUserKey.REGISTRATION_TIME.value: datetime.now(timezone.utc), CmdbUserKey.PASSWORD.value: password_hash,
    }


@pytest.fixture(autouse=True)
def _users(rest_api, database_manager: MongoDatabaseManager, database_name: str):
    """A readable and an unreadable stored user with the same password - removed after"""
    users = database_manager.get_collection(CmdbUser.COLLECTION, database_name)
    users.delete_many({CmdbUserKey.PUBLIC_ID.value: {'$in': USER_IDS}})

    # The HMAC reads the stored key through current_app; the context is popped again before any request runs
    with rest_api.application.app_context():
        password_hash: str = SecurityManager(database_manager).generate_hmac(PASSWORD)

    users.insert_many([
        _user(READABLE_ID, READABLE_NAME, password_hash),
        {**_user(UNREADABLE_ID, UNREADABLE_NAME, password_hash), CmdbUserKey.REGISTRATION_TIME.value: UNPARSABLE_DATE},
    ])
    yield
    users.delete_many({CmdbUserKey.PUBLIC_ID.value: {'$in': USER_IDS}})


@pytest.mark.usefixtures('rest_api_app_context')
class TestHttpBasicLogin:
    """`login_basic_user` over the real login"""

    def test_a_readable_user_logs_in(self) -> None:
        """The control"""
        assert login_basic_user(READABLE_NAME, PASSWORD).public_id == READABLE_ID

    def test_a_wrong_password_is_no_user(self) -> None:
        """The caller's credentials: the request's 401"""
        assert login_basic_user(READABLE_NAME, WRONG_PASSWORD) is None

    def test_an_unreadable_stored_user_is_the_500(self) -> None:
        """Not the refusal: the user exists and cannot be read"""
        with pytest.raises(HTTPException) as refused:
            login_basic_user(UNREADABLE_NAME, PASSWORD)

        assert (refused.value.code, refused.value.description) == (
            HTTPStatus.INTERNAL_SERVER_ERROR, LOGIN_USER_UNREADABLE_MESSAGE)

    def test_a_lost_server_ends_the_login_after_one_read(self, database_manager: MongoDatabaseManager) -> None:
        """The outage leaves the login as itself; the sweep never reads the user a second time"""
        user_reads: list[str] = []

        def _lost(collection: str, *_args: Any, **_kwargs: Any) -> None:
            user_reads.append(collection)
            raise DocumentNetworkError('lost')

        # Built first: the module reads its settings through the same method
        auth_module = build_local_auth_module()

        with patch.object(database_manager, 'find_one_by', side_effect=_lost):
            with pytest.raises(DocumentNetworkError):
                auth_module.login(READABLE_NAME, PASSWORD)

        assert user_reads == [CmdbUser.COLLECTION]


class TestLoginRoute:
    """`POST /auth/login` over the real login"""

    def test_a_readable_user_gets_a_token(self, rest_api) -> None:
        """The control"""
        response = rest_api.post(LOGIN_URL, json={'user_name': READABLE_NAME, 'password': PASSWORD})

        assert response.status_code == HTTPStatus.OK

    def test_an_unreadable_stored_user_is_the_500(self, rest_api) -> None:
        """The same answer as HTTP Basic"""
        response = rest_api.post(LOGIN_URL, json={'user_name': UNREADABLE_NAME, 'password': PASSWORD})

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert response.get_json()['message'] == LOGIN_USER_UNREADABLE_MESSAGE
