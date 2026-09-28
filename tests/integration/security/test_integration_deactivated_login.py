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
Integration tests for a deactivated account against the real login machinery

`AuthModule.login` authenticates - it does not decide whether an account may be used - so with a real
stored user and the real local provider it still returns the deactivated user; `refuse_inactive_user`,
which the login route runs on that result, is what refuses it. A wrong password never gets that far:
the provider refuses first, so the deactivation is only revealed after the password was proven
"""
from datetime import datetime, timezone

import pytest
from werkzeug.exceptions import HTTPException

from cmdb.database import MongoDatabaseManager
from cmdb.manager import SecurityManager, UsersManager
from cmdb.models.user_model import CmdbUser
from cmdb.security.auth.auth_module import AuthModule
from cmdb.interface.route_utils import USER_DEACTIVATED_MESSAGE, refuse_inactive_user

from cmdb.errors.provider import AuthenticationError
# -------------------------------------------------------------------------------------------------------------------- #

USER_ID: int = 93981
USER_NAME: str = 'deactivated-login-user'
PASSWORD: str = 'correct-horse'
WRONG_PASSWORD: str = 'wrong-horse'
LOCAL_PROVIDER: str = 'LocalAuthenticationProvider'


@pytest.fixture(name='auth_module')
def fixture_auth_module(rest_api, database_manager: MongoDatabaseManager, database_name: str):
    """Stores a deactivated local user with a real password digest; yields a real AuthModule in app context."""
    users = database_manager.get_collection(CmdbUser.COLLECTION, database_name)
    users.delete_many({'public_id': USER_ID})

    with rest_api.application.app_context():
        security_manager = SecurityManager(database_manager)
        users.insert_one({
            'public_id': USER_ID, 'user_name': USER_NAME, 'active': False, 'group_id': 1,
            'authenticator': LOCAL_PROVIDER, 'password': security_manager.generate_hmac(PASSWORD),
            'registration_time': datetime.now(timezone.utc),
        })

        yield AuthModule(dict(AuthModule.__DEFAULT_SETTINGS__), security_manager=security_manager,
                         users_manager=UsersManager(database_manager))

    users.delete_many({'public_id': USER_ID})


def test_login_authenticates_the_deactivated_user(auth_module: AuthModule) -> None:
    """The credentials are right, so AuthModule answers the user - the refusal is not its job"""
    user: CmdbUser = auth_module.login(USER_NAME, PASSWORD)

    assert user.public_id == USER_ID
    assert user.active is False


def test_the_authenticated_deactivated_user_is_refused(auth_module: AuthModule) -> None:
    """What the login route runs on that result: a 401 naming the deactivation"""
    user: CmdbUser = auth_module.login(USER_NAME, PASSWORD)

    with pytest.raises(HTTPException) as refused:
        refuse_inactive_user(user)

    assert refused.value.code == 401
    assert refused.value.description == USER_DEACTIVATED_MESSAGE


def test_a_wrong_password_fails_before_the_deactivation_is_ever_asked(auth_module: AuthModule) -> None:
    """The provider refuses the credentials; nothing about the account's state is reached"""
    with pytest.raises(AuthenticationError):
        auth_module.login(USER_NAME, WRONG_PASSWORD)
