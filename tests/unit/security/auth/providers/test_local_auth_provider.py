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
Unit tests for cmdb.security.auth.providers.local_auth_provider

DB-free: the UsersManager and the SecurityManager are MagicMocks and the cloud-mode flag is driven through
a minimal Flask app, so the whole credential check runs without a database.

Covered: the hash comparison in both directions, the lookup field per mode (user name on premise, email in
cloud mode), the case-fallback that keeps the AuthModule's two login paths in agreement, a read failure
becoming a refusal rather than escaping as a 500, the missing-collaborator guard, and that a CmdbUser
without a stored password - what an external provider creates - can never authenticate here.
"""
from typing import Any
from unittest.mock import MagicMock

import pytest
from flask import Flask

from cmdb.models.user_model import CmdbUser
from cmdb.errors.provider import AuthenticationError
from cmdb.errors.manager.users_manager import UsersManagerGetError
from cmdb.security.auth.providers.local_auth_config import LocalAuthenticationProviderConfig
from cmdb.security.auth.providers.local_auth_provider import (
    LocalAuthenticationProvider,
    USER_NAME_FIELD,
    EMAIL_FIELD,
)
# -------------------------------------------------------------------------------------------------------------------- #

USER_NAME: str = 'alice'
MIXED_CASE_USER_NAME: str = 'Alice'
EMAIL: str = 'alice@example.com'
PASSWORD: str = 'secret'
PASSWORD_HASH: str = 'hashed-secret'
USER_PUBLIC_ID: int = 42


def _app(cloud_mode: bool = False) -> Flask:
    """A minimal app carrying only the flag the provider reads off current_app."""
    app = Flask(__name__)
    app.cloud_mode = cloud_mode

    return app


def _user(password: str | None = PASSWORD_HASH, user_name: str = USER_NAME) -> CmdbUser:
    """A CmdbUser as the UsersManager hands it back."""
    return CmdbUser.from_data({
        'public_id': USER_PUBLIC_ID,
        'user_name': user_name,
        'active': True,
        'password': password,
    })


def _provider(stored_user: Any = None, hashed: str = PASSWORD_HASH) -> LocalAuthenticationProvider:
    """Builds the provider with mocked collaborators; `stored_user` is what the lookup returns."""
    users_manager = MagicMock(name='users_manager')
    users_manager.get_user_by.return_value = stored_user

    security_manager = MagicMock(name='security_manager')
    security_manager.generate_hmac.return_value = hashed

    return LocalAuthenticationProvider(
        config=LocalAuthenticationProviderConfig(active=True),
        security_manager=security_manager,
        users_manager=users_manager,
    )


class TestConstruction:
    """The provider takes the inherited constructor - it adds nothing of its own."""

    def test_uses_its_own_config_class_by_default(self) -> None:
        """Without a config the base class builds this provider's configuration."""
        provider = LocalAuthenticationProvider()

        assert isinstance(provider.get_config(), LocalAuthenticationProviderConfig)

    def test_keeps_the_injected_collaborators(self) -> None:
        """AuthModule injects both managers by keyword; the inherited constructor stores them."""
        users_manager = MagicMock()
        security_manager = MagicMock()

        provider = LocalAuthenticationProvider(security_manager=security_manager, users_manager=users_manager)

        assert provider.users_manager is users_manager
        assert provider.security_manager is security_manager

    def test_is_active_is_pinned(self) -> None:
        """Local login is the way back into an instance, so it is never reported as inactive."""
        assert LocalAuthenticationProvider(config=LocalAuthenticationProviderConfig(active=False)).is_active()


class TestCredentialCheck:
    """The submitted password is hashed and compared with the stored hash."""

    def test_matching_hash_returns_the_user(self) -> None:
        """The stored CmdbUser is handed back when the hashes are equal."""
        stored = _user()
        provider = _provider(stored)

        with _app().test_request_context('/'):
            assert provider.authenticate(USER_NAME, PASSWORD) is stored

        provider.security_manager.generate_hmac.assert_called_once_with(PASSWORD)

    def test_wrong_password_is_refused(self) -> None:
        """A hash that does not match the stored one is an authentication failure."""
        provider = _provider(_user(), hashed='something-else')

        with _app().test_request_context('/'):
            with pytest.raises(AuthenticationError) as exc_info:
                provider.authenticate(USER_NAME, PASSWORD)

        assert 'hmac' in str(exc_info.value)

    def test_unknown_user_is_refused(self) -> None:
        """No matching CmdbUser is refused the same way a wrong password is."""
        provider = _provider(None)

        with _app().test_request_context('/'):
            with pytest.raises(AuthenticationError) as exc_info:
                provider.authenticate(USER_NAME, PASSWORD)

        assert 'User not found' in str(exc_info.value)
        provider.security_manager.generate_hmac.assert_not_called()

    def test_a_user_without_a_password_can_not_authenticate(self) -> None:
        """A user an external provider created carries no password and must never pass here."""
        provider = _provider(_user(password=None))

        with _app().test_request_context('/'):
            with pytest.raises(AuthenticationError):
                provider.authenticate(USER_NAME, PASSWORD)

    def test_an_empty_stored_password_can_not_authenticate(self) -> None:
        """An empty stored hash must not be matchable by an empty submitted password either."""
        provider = _provider(_user(password=''), hashed='hash-of-empty')

        with _app().test_request_context('/'):
            with pytest.raises(AuthenticationError):
                provider.authenticate('', '')


class TestUserLookup:
    """What the provider looks a login up by, and how it survives a failing read."""

    def test_reads_by_user_name_on_premise(self) -> None:
        """On premise the submitted value is a user name."""
        provider = _provider(_user())

        with _app().test_request_context('/'):
            provider.authenticate(USER_NAME, PASSWORD)

        provider.users_manager.get_user_by.assert_called_once_with({USER_NAME_FIELD: USER_NAME})

    def test_reads_by_email_in_cloud_mode(self) -> None:
        """In cloud mode the login form submits an email address."""
        provider = _provider(_user())

        with _app(cloud_mode=True).test_request_context('/'):
            provider.authenticate(EMAIL, PASSWORD)

        provider.users_manager.get_user_by.assert_called_once_with({EMAIL_FIELD: EMAIL})

    def test_a_mixed_case_name_falls_back_to_lower_case(self) -> None:
        """AuthModule lower-cases the name on one login path only - both must find the same user."""
        stored = _user()
        provider = _provider()
        provider.users_manager.get_user_by.side_effect = [None, stored]

        with _app().test_request_context('/'):
            assert provider.authenticate(MIXED_CASE_USER_NAME, PASSWORD) is stored

        assert [call.args[0] for call in provider.users_manager.get_user_by.call_args_list] == [
            {USER_NAME_FIELD: MIXED_CASE_USER_NAME},
            {USER_NAME_FIELD: USER_NAME},
        ]

    def test_an_exact_match_costs_one_read(self) -> None:
        """A name that matched as given is never looked up a second time."""
        provider = _provider(_user(user_name=MIXED_CASE_USER_NAME))

        with _app().test_request_context('/'):
            provider.authenticate(MIXED_CASE_USER_NAME, PASSWORD)

        provider.users_manager.get_user_by.assert_called_once()

    def test_an_already_lower_case_name_costs_one_read(self) -> None:
        """There is no second candidate for a name that is already lower-case."""
        provider = _provider(None)

        with _app().test_request_context('/'):
            with pytest.raises(AuthenticationError):
                provider.authenticate(USER_NAME, PASSWORD)

        provider.users_manager.get_user_by.assert_called_once()

    def test_no_case_fallback_in_cloud_mode(self) -> None:
        """The cloud lookup is by email and is left exactly as the caller submitted it."""
        provider = _provider(None)

        with _app(cloud_mode=True).test_request_context('/'):
            with pytest.raises(AuthenticationError):
                provider.authenticate('Alice@Example.com', PASSWORD)

        provider.users_manager.get_user_by.assert_called_once_with({EMAIL_FIELD: 'Alice@Example.com'})

    def test_a_failing_read_is_an_authentication_error(self) -> None:
        """The old handler caught an error type the UsersManager never raises, so this became a 500."""
        provider = _provider()
        provider.users_manager.get_user_by.side_effect = UsersManagerGetError('db down')

        with _app().test_request_context('/'):
            with pytest.raises(AuthenticationError) as exc_info:
                provider.authenticate(USER_NAME, PASSWORD)

        assert 'db down' in str(exc_info.value)


class TestCollaboratorGuard:
    """A provider built without its managers says so instead of failing with an AttributeError."""

    @pytest.mark.parametrize(
        'security_manager, users_manager',
        [(None, MagicMock()), (MagicMock(), None), (None, None)],
        ids=['no-security-manager', 'no-users-manager', 'neither'],
    )
    def test_missing_collaborators_are_reported(self, security_manager: Any, users_manager: Any) -> None:
        """Both managers are optional in the constructor, so the check belongs at authentication time."""
        provider = LocalAuthenticationProvider(
            security_manager=security_manager, users_manager=users_manager,
        )

        with _app().test_request_context('/'):
            with pytest.raises(AuthenticationError) as exc_info:
                provider.authenticate(USER_NAME, PASSWORD)

        assert 'without a users or security manager' in str(exc_info.value)
