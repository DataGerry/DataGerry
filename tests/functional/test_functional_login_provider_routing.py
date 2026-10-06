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
Functional coverage for which provider a login reaches, through the real AuthModule

A user whose own provider is deactivated (LDAP, off by default) or not installed at all falls back to the
providers that are active - the local one, which can never be switched off. Whatever the primary attempt ran
into, a failed login is one 401 "Invalid user credentials!": the response never says which provider was off or
missing
"""
from http import HTTPStatus

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.user_model import CmdbUser

from tests.functional.test_functional_login_name import _stored_user
# -------------------------------------------------------------------------------------------------------------------- #

LOGIN_URL: str = '/auth/login'
PASSWORD: str = 'routing-secret'
WRONG_PASSWORD: str = 'not-the-secret'
INVALID_CREDENTIALS_MSG: str = 'Invalid user credentials!'

LDAP_USER_ID: int = 99181
LDAP_USER_NAME: str = 'routing-ldap-user'
GONE_USER_ID: int = 99182
GONE_USER_NAME: str = 'routing-gone-provider-user'
GONE_PROVIDER: str = 'UninstalledAuthenticationProvider'

# user name -> the provider the stored user names
USERS: dict[str, str] = {LDAP_USER_NAME: 'LdapAuthenticationProvider', GONE_USER_NAME: GONE_PROVIDER}


@pytest.fixture(autouse=True)
def _users(rest_api, database_manager: MongoDatabaseManager, database_name: str):
    """One user naming the deactivated LDAP provider, one naming a provider that is not installed"""
    users = database_manager.get_collection(CmdbUser.COLLECTION, database_name)
    users.delete_many({'public_id': {'$in': [LDAP_USER_ID, GONE_USER_ID]}})

    with rest_api.application.app_context():
        users.insert_many([
            _stored_user(database_manager, database_name, LDAP_USER_ID, LDAP_USER_NAME, PASSWORD,
                         authenticator=USERS[LDAP_USER_NAME]),
            _stored_user(database_manager, database_name, GONE_USER_ID, GONE_USER_NAME, PASSWORD,
                         authenticator=USERS[GONE_USER_NAME]),
        ])

    yield

    users.delete_many({'public_id': {'$in': [LDAP_USER_ID, GONE_USER_ID]}})


def _login(rest_api, user_name: str, password: str):
    """POST /auth/login without the test client's own token"""
    return rest_api.post(LOGIN_URL, json={'user_name': user_name, 'password': password}, unauthorized=True)


@pytest.mark.parametrize('user_name', list(USERS), ids=['deactivated-provider', 'uninstalled-provider'])
class TestTheUsersOwnProviderIsUnavailable:
    """The primary attempt cannot run; the sweep decides"""

    def test_the_local_provider_still_logs_the_user_in(self, rest_api, user_name: str) -> None:
        """Local login is never off, and the user carries a local password"""
        response = _login(rest_api, user_name, PASSWORD)

        assert response.status_code == HTTPStatus.OK, response.get_json()
        assert response.get_json()['user']['user_name'] == user_name

    def test_a_wrong_password_is_the_one_401(self, rest_api, user_name: str) -> None:
        """Not the 400 'provider is not active / was not found' the route used to declare and never sent"""
        response = _login(rest_api, user_name, WRONG_PASSWORD)

        assert response.status_code == HTTPStatus.UNAUTHORIZED
        assert response.get_json()['message'] == INVALID_CREDENTIALS_MSG
