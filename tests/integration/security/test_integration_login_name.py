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
Integration tests for the login lookup rule against real stored users

``AuthModule.resolve_user`` and the local provider make the same lookups (stripped, as typed, then -
on premise - lower-cased), so a user is found by the PRIMARY attempt whatever case the stored name has,
instead of only by the fallback sweep. Checked with a real UsersManager over two stored users - one
named in mixed case, one in lower case - and with the real local provider verifying the password
"""
from datetime import datetime, timezone

import pytest
from flask import current_app

from cmdb.database import MongoDatabaseManager
from cmdb.manager import SecurityManager, UsersManager
from cmdb.models.user_model import CmdbUser
from cmdb.security.auth.auth_module import AuthModule
# -------------------------------------------------------------------------------------------------------------------- #

MIXED_ID: int = 93991
LOWER_ID: int = 93992
MIXED_NAME: str = 'Mixed-Login'
LOWER_NAME: str = 'lower-login'
EMAIL: str = 'Mixed-Login@Example.io'
PASSWORD: str = 'correct-horse'
LOCAL_PROVIDER: str = 'LocalAuthenticationProvider'


@pytest.fixture(name='auth_module')
def fixture_auth_module(rest_api, database_manager: MongoDatabaseManager, database_name: str):
    """Stores the two users with real password digests; yields a real AuthModule inside an app context."""
    users = database_manager.get_collection(CmdbUser.COLLECTION, database_name)
    users.delete_many({'public_id': {'$in': [MIXED_ID, LOWER_ID]}})

    with rest_api.application.app_context():
        security_manager = SecurityManager(database_manager)
        digest: str = security_manager.generate_hmac(PASSWORD)
        now: datetime = datetime.now(timezone.utc)
        users.insert_many([
            {'public_id': MIXED_ID, 'user_name': MIXED_NAME, 'email': EMAIL, 'active': True, 'group_id': 1,
             'authenticator': LOCAL_PROVIDER, 'password': digest, 'registration_time': now},
            {'public_id': LOWER_ID, 'user_name': LOWER_NAME, 'active': True, 'group_id': 1,
             'authenticator': LOCAL_PROVIDER, 'password': digest, 'registration_time': now},
        ])

        yield AuthModule(dict(AuthModule.__DEFAULT_SETTINGS__), security_manager=security_manager,
                         users_manager=UsersManager(database_manager))

    users.delete_many({'public_id': {'$in': [MIXED_ID, LOWER_ID]}})


class TestResolveUser:
    """Which stored user a typed login resolves to."""

    @pytest.mark.parametrize('typed, expected_id', [
        (MIXED_NAME, MIXED_ID), (f' {MIXED_NAME} ', MIXED_ID),
        (LOWER_NAME, LOWER_ID), (LOWER_NAME.upper(), LOWER_ID), (f'{LOWER_NAME.title()}\t', LOWER_ID),
    ], ids=['mixed-as-stored', 'mixed-padded', 'lower-as-stored', 'lower-typed-upper', 'lower-typed-title'])
    def test_the_stored_user_is_found(self, auth_module: AuthModule, typed: str, expected_id: int) -> None:
        """As typed first, then lower-cased - both stored spellings are reachable"""
        user: CmdbUser | None = auth_module.resolve_user(typed)

        assert user is not None
        assert user.public_id == expected_id

    def test_a_mixed_case_name_typed_otherwise_is_not_guessed(self, auth_module: AuthModule) -> None:
        """'mixed-login' is neither the stored 'Mixed-Login' nor its lower-case form's source"""
        assert auth_module.resolve_user(MIXED_NAME.lower()) is None

    def test_cloud_mode_resolves_by_email_as_given(self, auth_module: AuthModule,
                                                   monkeypatch: pytest.MonkeyPatch) -> None:
        """The caller passes the portal's address; only the whitespace is removed"""
        monkeypatch.setattr(current_app, 'cloud_mode', True)

        user: CmdbUser | None = auth_module.resolve_user(f' {EMAIL} ')

        assert user is not None
        assert user.public_id == MIXED_ID


class TestLogin:
    """The whole login, with the real local provider checking the password."""

    @pytest.mark.parametrize('typed, expected_id', [
        (f' {MIXED_NAME}', MIXED_ID), (LOWER_NAME.upper(), LOWER_ID),
    ], ids=['mixed-padded', 'lower-typed-upper'])
    def test_the_primary_attempt_authenticates(self, auth_module: AuthModule, monkeypatch: pytest.MonkeyPatch,
                                               typed: str, expected_id: int) -> None:
        """The user's own provider authenticates it - the fallback sweep is never reached"""
        def _no_sweep(*_args, **_kwargs):
            raise AssertionError('the fallback sweep ran')

        monkeypatch.setattr(auth_module, 'authenticate_with_any_provider', _no_sweep)

        assert auth_module.login(typed, PASSWORD).public_id == expected_id
