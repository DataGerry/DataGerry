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
Unit tests for cmdb.security.auth.auth_module

DB-free and app-free: the managers are MagicMocks, ``current_app.cloud_mode`` is driven through a
BaseCmdbApp test request context, and the providers are small stand-in classes so no real LDAP / local
authentication runs.

Covers the settings normalisation (topping up a missing provider with a WELL-FORMED entry, parsing a
stored config through its config class, falling back to the defaults on an unparsable one), the
class-level provider registry (install / uninstall / duplicate / lookup / internal-vs-external split),
the provider builders (the stored config really reaching the instance), and ``login`` - the primary
attempt plus the fallback sweep with all of its skip and continue rules.

The registry is process-wide class state, so an autouse fixture snapshots and restores it; without that
a test installing a stand-in provider would leak into every later test in the session.
"""
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from cmdb.interface.cmdb_app import BaseCmdbApp
from cmdb.models.user_model import CmdbUser, CmdbUserKey
from cmdb.models.security_models import DEFAULT_TOKEN_LIFETIME
from cmdb.security.auth.auth_module import (
    PROVIDER_CLASS_NAME_KEY,
    PROVIDER_CONFIG_KEY,
    PROVIDERS_KEY,
    AuthModule,
)
from cmdb.security.auth.base_authentication_provider import BaseAuthenticationProvider
from cmdb.security.auth.base_provider_config import BaseAuthProviderConfig, PROVIDER_ACTIVE_KEY
from cmdb.security.auth.providers.local_auth_provider import LocalAuthenticationProvider
from cmdb.security.auth.providers.ldap_auth_provider import LdapAuthenticationProvider
from cmdb.security.auth.providers.ldap_auth_config import LdapAuthenticationProviderConfig
from cmdb.errors.provider import AuthenticationError
from cmdb.errors.manager import BaseManagerGetError
# -------------------------------------------------------------------------------------------------------------------- #

MODULE_PATH: str = 'cmdb.security.auth.auth_module'

LOCAL_PROVIDER_NAME: str = 'LocalAuthenticationProvider'
LDAP_PROVIDER_NAME: str = 'LdapAuthenticationProvider'

USER_NAME: str = 'testuser'
USER_EMAIL: str = 'test@example.org'
PASSWORD: str = 'secret'

LDAP_HOST: str = 'ldap.example.org'


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  STAND-IN PROVIDERS                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
class _StubConfig(BaseAuthProviderConfig):
    """A provider config whose 'active' flag the tests set directly."""
    DEFAULT_CONFIG_VALUES: dict[str, Any] = {'active': True}

    def __init__(self, active: bool = True, **_kwargs: Any) -> None:
        super().__init__(active=active)


class _StubProvider(BaseAuthenticationProvider):
    """A provider that authenticates by returning a canned user, or raises what a test asks for."""
    PROVIDER_CONFIG_CLASS = _StubConfig
    EXTERNAL_PROVIDER = False

    authenticate_result: Any = None
    authenticate_error: Exception | None = None
    calls: list[tuple[str, str]] = []

    def authenticate(self, user_name: str, password: str) -> CmdbUser:
        """Records the attempt, then returns / raises whatever the test configured."""
        type(self).calls.append((user_name, password))

        if type(self).authenticate_error is not None:
            raise type(self).authenticate_error

        return type(self).authenticate_result


class _StrictConfig(BaseAuthProviderConfig):
    """A config class that does NOT swallow unknown keys, so a stale stored config raises."""
    DEFAULT_CONFIG_VALUES: dict[str, Any] = {'active': True}

    def __init__(self, active: bool = True) -> None:
        super().__init__(active=active)


class _StrictProvider(BaseAuthenticationProvider):
    """A provider whose config class rejects anything but 'active'."""
    PROVIDER_CONFIG_CLASS = _StrictConfig


class _ExternalStubProvider(_StubProvider):
    """The same stand-in, flagged external."""
    EXTERNAL_PROVIDER = True
    calls: list[tuple[str, str]] = []


def _reset_stub(provider: type[_StubProvider], result: Any = None, error: Exception | None = None) -> None:
    """Resets a stand-in provider's canned behaviour."""
    provider.authenticate_result = result
    provider.authenticate_error = error
    provider.calls = []


@pytest.fixture(autouse=True)
def _isolate_registry():
    """Snapshots and restores the class-level provider registry around every test."""
    original: list[type[BaseAuthenticationProvider]] = list(AuthModule.get_installed_providers())
    _reset_stub(_StubProvider)
    _reset_stub(_ExternalStubProvider)
    yield
    installed = AuthModule.get_installed_providers()
    installed.clear()
    installed.extend(original)


@pytest.fixture(name='cmdb_app')
def fixture_cmdb_app():
    """Provides a request context so current_app.cloud_mode is readable.

    Deliberately NOT named 'app_context': that name belongs to the session-scoped autouse fixture in
    the REST API fixture, and shadowing it leaves the session without an app context.
    """
    app = BaseCmdbApp(__name__)
    app.cloud_mode = False

    with app.test_request_context():
        yield app


def _settings(providers: list[dict[str, Any]] | None = None, enable_external: bool = True) -> dict[str, Any]:
    """Builds an 'auth' settings section carrying the given provider entries."""
    return {
        '_id': 'auth',
        'enable_external': enable_external,
        'token_lifetime': DEFAULT_TOKEN_LIFETIME,
        PROVIDERS_KEY: providers if providers is not None else [
            {PROVIDER_CLASS_NAME_KEY: LOCAL_PROVIDER_NAME, PROVIDER_CONFIG_KEY: {'active': True}},
        ],
    }


def _module(providers: list[dict[str, Any]] | None = None, enable_external: bool = True) -> AuthModule:
    """Builds an AuthModule with mocked managers."""
    return AuthModule(
        _settings(providers, enable_external),
        security_manager=MagicMock(),
        users_manager=MagicMock(),
    )


def _stub_entry(name: str, active: bool = True) -> dict[str, Any]:
    """Builds a settings entry for a stand-in provider."""
    return {PROVIDER_CLASS_NAME_KEY: name, PROVIDER_CONFIG_KEY: {'active': active}}


# -------------------------------------------------------------------------------------------------------------------- #
#                                                 SETTINGS NORMALISATION                                               #
# -------------------------------------------------------------------------------------------------------------------- #
class TestInitSettings:
    """The stored 'auth' section is normalised against the installed providers."""

    def test_a_missing_provider_is_appended_as_a_full_entry(self) -> None:
        """A provider the section does not list gets a {class_name, config} entry, not bare config values."""
        module = _module([_stub_entry(LOCAL_PROVIDER_NAME)])

        appended = module.settings.get_provider_list()[-1]

        assert sorted(appended.keys()) == [PROVIDER_CLASS_NAME_KEY, PROVIDER_CONFIG_KEY]
        assert appended[PROVIDER_CLASS_NAME_KEY] == LDAP_PROVIDER_NAME

    def test_the_appended_entry_is_resolvable_afterwards(self) -> None:
        """The topped-up entry can be read back by name, rather than raising KeyError 'class_name'."""
        module = _module([_stub_entry(LOCAL_PROVIDER_NAME)])

        assert isinstance(module.settings.get_provider_settings(LDAP_PROVIDER_NAME), dict)

    def test_a_second_module_over_the_same_section_still_works(self) -> None:
        """Re-normalising an already topped-up section does not break (a malformed entry would)."""
        settings = _settings([_stub_entry(LOCAL_PROVIDER_NAME)])

        AuthModule(dict(settings), MagicMock(), MagicMock())
        second = AuthModule(dict(settings), MagicMock(), MagicMock())

        assert second.settings.get_provider_settings(LDAP_PROVIDER_NAME)

    def test_a_stored_config_is_parsed_through_its_config_class(self) -> None:
        """A valid stored config survives normalisation."""
        ldap_config = {
            **LdapAuthenticationProvider.PROVIDER_CONFIG_CLASS.DEFAULT_CONFIG_VALUES,
            'active': True,
            'server_config': {'host': LDAP_HOST, 'port': 389, 'use_ssl': False},
        }
        module = _module([
            _stub_entry(LOCAL_PROVIDER_NAME),
            {PROVIDER_CLASS_NAME_KEY: LDAP_PROVIDER_NAME, PROVIDER_CONFIG_KEY: ldap_config},
        ])

        stored = module.settings.get_provider_settings(LDAP_PROVIDER_NAME)

        assert stored['server_config']['host'] == LDAP_HOST

    def test_an_unparsable_config_falls_back_to_the_defaults(
        self, caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A stored config the class cannot accept is replaced by the provider defaults, with a log."""
        AuthModule.register_provider(_StrictProvider)

        with caplog.at_level('ERROR'):
            module = _module([
                _stub_entry(LOCAL_PROVIDER_NAME),
                _stub_entry(LDAP_PROVIDER_NAME),
                {PROVIDER_CLASS_NAME_KEY: '_StrictProvider',
                 PROVIDER_CONFIG_KEY: {'active': True, 'removed_setting': 'from an older release'}},
            ])

        assert module.settings.get_provider_settings('_StrictProvider') == _StrictConfig.DEFAULT_CONFIG_VALUES
        assert 'Fallback to default values' in caplog.text

    def test_a_section_without_providers_is_filled_in(self) -> None:
        """An 'auth' section carrying no provider list at all gets one entry per installed provider."""
        module = AuthModule({'_id': 'auth'}, MagicMock(), MagicMock())

        names = {entry[PROVIDER_CLASS_NAME_KEY] for entry in module.settings.get_provider_list()}

        assert names == {LOCAL_PROVIDER_NAME, LDAP_PROVIDER_NAME}


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  PROVIDER REGISTRY                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
class TestProviderRegistry:
    """Installing, uninstalling and classifying provider classes."""

    def test_the_shipped_providers_are_installed(self) -> None:
        """Local and LDAP are installed out of the box."""
        installed = AuthModule.get_installed_providers()

        assert LocalAuthenticationProvider in installed
        assert LdapAuthenticationProvider in installed

    def test_register_provider_installs_and_returns_it(self) -> None:
        """A registered provider is installed and handed back (usable as a decorator)."""
        assert AuthModule.register_provider(_StubProvider) is _StubProvider
        assert _StubProvider in AuthModule.get_installed_providers()

    def test_register_provider_does_not_install_a_duplicate(self) -> None:
        """Registering twice leaves one entry."""
        AuthModule.register_provider(_StubProvider)
        AuthModule.register_provider(_StubProvider)

        assert AuthModule.get_installed_providers().count(_StubProvider) == 1

    def test_unregister_provider_removes_it(self) -> None:
        """An installed provider can be uninstalled."""
        AuthModule.register_provider(_StubProvider)

        assert AuthModule.unregister_provider(_StubProvider) is True
        assert _StubProvider not in AuthModule.get_installed_providers()

    def test_unregister_provider_reports_an_unknown_provider(self) -> None:
        """Uninstalling something that was never installed returns False instead of raising."""
        assert AuthModule.unregister_provider(_StubProvider) is False

    def test_the_registry_does_not_mutate_the_shipped_baseline(self) -> None:
        """register_provider must not extend the pre-installed list, which one shared object would."""
        AuthModule.register_provider(_StubProvider)

        # pylint: disable=protected-access
        assert _StubProvider not in AuthModule._AuthModule__pre_installed_providers

    def test_get_provider_class_resolves_by_name(self) -> None:
        """A provider is found by its class name."""
        assert AuthModule.get_provider_class(LOCAL_PROVIDER_NAME) is LocalAuthenticationProvider

    def test_get_provider_class_raises_for_an_unknown_name(self) -> None:
        """An unknown name raises StopIteration (callers use provider_exists first)."""
        with pytest.raises(StopIteration):
            AuthModule.get_provider_class('NoSuchProvider')

    @pytest.mark.parametrize('provider_name, expected', [
        (LOCAL_PROVIDER_NAME, True),
        (LDAP_PROVIDER_NAME, True),
        ('NoSuchProvider', False),
    ])
    def test_provider_exists(self, provider_name: str, expected: bool) -> None:
        """provider_exists reports installation, not activation."""
        assert AuthModule.provider_exists(provider_name) is expected

    @pytest.mark.parametrize('provider_name, expected', [
        (LOCAL_PROVIDER_NAME, True),
        (LDAP_PROVIDER_NAME, False),
        ('NoSuchProvider', True),
    ])
    def test_provider_owns_passwords(self, provider_name: str, expected: bool) -> None:
        """
        Whether DataGerry may store a password for a user of that provider

        `PASSWORD_ABLE` does not mean "checks a password" - the LDAP bind is exactly that - it means
        the password lives HERE. An unknown provider answers True: such a user cannot be authenticated
        by its own provider at all, so the local password is the only way to reach the account.
        """
        assert AuthModule.provider_owns_passwords(provider_name) is expected

    def test_the_flag_is_what_the_answer_reads(self) -> None:
        """The lookup must follow the provider's own flag, not a hard-coded provider name."""
        AuthModule.register_provider(_ExternalStubProvider)

        assert AuthModule.provider_owns_passwords(_ExternalStubProvider.get_name()) \
            is _ExternalStubProvider.PASSWORD_ABLE

    def test_internals_and_external_are_split_by_the_flag(self) -> None:
        """The two accessors filter on EXTERNAL_PROVIDER rather than both returning everything."""
        internals = AuthModule.get_installed_internals()
        external = AuthModule.get_installed_external()

        assert LocalAuthenticationProvider in internals
        assert LdapAuthenticationProvider in external
        assert not set(internals) & set(external)

    def test_a_registered_external_provider_lands_in_the_external_list(self) -> None:
        """The split follows the registered provider's own flag."""
        AuthModule.register_provider(_ExternalStubProvider)

        assert _ExternalStubProvider in AuthModule.get_installed_external()
        assert _ExternalStubProvider not in AuthModule.get_installed_internals()

    def test_providers_property_lists_everything(self) -> None:
        """The instance property exposes the full registry."""
        module = _module()

        assert set(module.providers) == set(AuthModule.get_installed_providers())


# -------------------------------------------------------------------------------------------------------------------- #
#                                                 PROVIDER BUILDERS                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
class TestProviderBuilders:
    """Config values, config instances and provider instances."""

    def test_stored_config_values_are_used(self) -> None:
        """The stored config is returned as-is (it is already the entry's 'config' sub-document)."""
        module = _module([
            _stub_entry(LOCAL_PROVIDER_NAME),
            {PROVIDER_CLASS_NAME_KEY: LDAP_PROVIDER_NAME, PROVIDER_CONFIG_KEY: {
                **LdapAuthenticationProvider.PROVIDER_CONFIG_CLASS.DEFAULT_CONFIG_VALUES,
                'server_config': {'host': LDAP_HOST, 'port': 389, 'use_ssl': False},
            }},
        ])

        values = module.get_provider_config_values(LdapAuthenticationProvider)

        assert values['server_config']['host'] == LDAP_HOST

    def test_a_provider_without_a_settings_entry_falls_back_to_defaults(
        self, caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A provider installed after the settings were normalised uses its own defaults, with a warning."""
        module = _module([_stub_entry(LOCAL_PROVIDER_NAME), _stub_entry(LDAP_PROVIDER_NAME)])
        AuthModule.register_provider(_StubProvider)   # registered AFTER, so the section has no entry

        with caplog.at_level('WARNING'):
            values = module.get_provider_config_values(_StubProvider)

        assert values == _StubConfig.DEFAULT_CONFIG_VALUES
        assert 'No settings entry for provider' in caplog.text

    def test_get_provider_returns_an_instance_carrying_the_stored_config(self) -> None:
        """The configured provider really gets the stored values rather than the defaults."""
        module = _module([
            _stub_entry(LOCAL_PROVIDER_NAME),
            {PROVIDER_CLASS_NAME_KEY: LDAP_PROVIDER_NAME, PROVIDER_CONFIG_KEY: {
                **LdapAuthenticationProvider.PROVIDER_CONFIG_CLASS.DEFAULT_CONFIG_VALUES,
                'server_config': {'host': LDAP_HOST, 'port': 389, 'use_ssl': False},
            }},
        ])

        provider = module.get_provider(LDAP_PROVIDER_NAME)

        assert provider is not None
        assert provider.get_config().__dict__['server_config']['host'] == LDAP_HOST

    def test_get_provider_returns_none_for_an_unknown_provider(self) -> None:
        """An uninstalled provider name yields None (the route turns that into a 404)."""
        assert _module().get_provider('NoSuchProvider') is None

    def test_get_provider_returns_none_when_the_config_cannot_be_built(self) -> None:
        """A config class that rejects the stored values yields None instead of raising."""
        module = _module()

        with patch.object(LdapAuthenticationProvider, 'PROVIDER_CONFIG_CLASS') as config_class:
            config_class.side_effect = TypeError('bad config')
            config_class.DEFAULT_CONFIG_VALUES = {}

            assert module.get_provider(LDAP_PROVIDER_NAME) is None

    def test_build_provider_instance_wires_the_managers(self) -> None:
        """The built provider carries the module's security and users manager."""
        module = _module()

        instance = module.build_provider_instance(LocalAuthenticationProvider)

        assert instance.users_manager is module.users_manager


# -------------------------------------------------------------------------------------------------------------------- #
#                                                        LOGIN                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class TestLogin:
    """The primary attempt and the fallback sweep."""
    # every test needs the app context for current_app.cloud_mode, but only two read the app object
    # pylint: disable=unused-argument

    @staticmethod
    def _module_with_stub(active: bool = True, enable_external: bool = True) -> AuthModule:
        """Installs the stand-in provider and builds a module whose section configures it."""
        AuthModule.register_provider(_StubProvider)

        return AuthModule(
            _settings([
                _stub_entry(LDAP_PROVIDER_NAME, active=False),
                _stub_entry('_StubProvider', active=active),
            ], enable_external=enable_external),
            security_manager=MagicMock(),
            users_manager=MagicMock(),
        )

    @staticmethod
    def _user(authenticator: str) -> MagicMock:
        """
        A stored CmdbUser stand-in naming its provider

        It carries no local password, like every user an external provider provisions. The local
        provider is always part of the sweep, so this is what makes it refuse the login cleanly and
        leave the provider under test to decide
        """
        user = MagicMock()
        user.authenticator = authenticator
        user.password = None

        return user

    def test_the_users_own_provider_authenticates_it(self, cmdb_app) -> None:
        """The primary attempt uses the provider named on the stored user."""
        module = self._module_with_stub()
        expected_user = self._user('_StubProvider')
        _reset_stub(_StubProvider, result=expected_user)
        module.users_manager.get_user_by.return_value = expected_user

        assert module.login(USER_NAME, PASSWORD) is expected_user
        assert _StubProvider.calls == [(USER_NAME, PASSWORD)]

    # pylint: disable=unused-argument
    def test_a_name_stored_as_typed_is_found_by_the_first_read(self, cmdb_app) -> None:
        """On-premise a user name is stored as it was created - 'TestUser' finds 'TestUser' directly"""
        module = self._module_with_stub()
        _reset_stub(_StubProvider, result=self._user('_StubProvider'))
        module.users_manager.get_user_by.return_value = self._user('_StubProvider')

        module.login('TestUser', PASSWORD)

        assert [call.args[0] for call in module.users_manager.get_user_by.call_args_list] == [
            {CmdbUserKey.USER_NAME.value: 'TestUser'},
        ]

    def test_a_miss_as_typed_is_retried_lower_cased(self, cmdb_app) -> None:
        """'TESTUSER' finds 'testuser' on the primary path, not only through the fallback sweep"""
        module = self._module_with_stub()
        stored = self._user('_StubProvider')
        _reset_stub(_StubProvider, result=stored)
        module.users_manager.get_user_by.side_effect = [None, stored]

        assert module.login('TESTUSER', PASSWORD) is stored
        assert [call.args[0] for call in module.users_manager.get_user_by.call_args_list] == [
            {CmdbUserKey.USER_NAME.value: 'TESTUSER'}, {CmdbUserKey.USER_NAME.value: 'testuser'},
        ]
        assert len(_StubProvider.calls) == 1

    def test_surrounding_whitespace_is_stripped_before_the_lookup(self, cmdb_app) -> None:
        """A pasted trailing space finds the user"""
        module = self._module_with_stub()
        _reset_stub(_StubProvider, result=self._user('_StubProvider'))
        module.users_manager.get_user_by.return_value = self._user('_StubProvider')

        module.login(f' {USER_NAME} ', PASSWORD)

        assert module.users_manager.get_user_by.call_args.args[0] == {CmdbUserKey.USER_NAME.value: USER_NAME}

    def test_cloud_mode_resolves_the_user_by_email(self, cmdb_app) -> None:
        """In cloud mode the login is looked up as an email."""
        cmdb_app.cloud_mode = True
        module = self._module_with_stub()
        _reset_stub(_StubProvider, result=self._user('_StubProvider'))
        module.users_manager.get_user_by.return_value = self._user('_StubProvider')

        module.login(USER_EMAIL, PASSWORD)

        assert module.users_manager.get_user_by.call_args.args[0] == {CmdbUserKey.EMAIL.value: USER_EMAIL}

    def test_an_unknown_user_falls_back_to_the_provider_sweep(self, cmdb_app) -> None:
        """No stored user: every active provider is tried so an external one can provision it."""
        module = self._module_with_stub()
        provisioned = self._user('_StubProvider')
        _reset_stub(_StubProvider, result=provisioned)
        module.users_manager.get_user_by.return_value = None

        assert module.login(USER_NAME, PASSWORD) is provisioned
        assert _StubProvider.calls == [(USER_NAME, PASSWORD)]

    def test_an_unknown_provider_on_the_user_falls_back(self, cmdb_app) -> None:
        """A user naming an uninstalled provider still reaches the sweep."""
        module = self._module_with_stub()
        expected_user = self._user('GoneProvider')
        _reset_stub(_StubProvider, result=expected_user)
        module.users_manager.get_user_by.return_value = expected_user

        assert module.login(USER_NAME, PASSWORD) is expected_user

    def test_a_deactivated_provider_falls_back(self, cmdb_app) -> None:
        """A provider whose stored config is inactive authenticates neither on the primary path nor in the sweep"""
        module = self._module_with_stub(active=False)
        expected_user = self._user('_StubProvider')
        _reset_stub(_StubProvider, result=expected_user)
        module.users_manager.get_user_by.return_value = expected_user

        with pytest.raises(AuthenticationError):
            module.login(USER_NAME, PASSWORD)

        assert _StubProvider.calls == []

    def test_an_inactive_provider_is_never_built(self, cmdb_app) -> None:
        """The primary attempt asks the class before building, as the sweep does"""
        module = self._module_with_stub(active=False)
        module.users_manager.get_user_by.return_value = self._user('_StubProvider')

        with patch.object(module, 'build_provider_instance', wraps=module.build_provider_instance) as build:
            with pytest.raises(AuthenticationError):
                module.login(USER_NAME, PASSWORD)

        assert _StubProvider not in [call.args[0] for call in build.call_args_list]

    def test_a_provider_with_only_authenticate_wins_its_primary_attempt(self, cmdb_app) -> None:
        """No instance-level activity method is needed - the sweep is never reached"""
        module = self._module_with_stub()
        expected_user = self._user('_StubProvider')
        _reset_stub(_StubProvider, result=expected_user)
        module.users_manager.get_user_by.return_value = expected_user

        with patch.object(module, 'authenticate_with_any_provider') as sweep:
            assert module.login(USER_NAME, PASSWORD) is expected_user

        sweep.assert_not_called()
        assert _StubProvider.calls == [(USER_NAME, PASSWORD)]

    def test_an_external_provider_is_refused_when_external_is_disabled(self, cmdb_app) -> None:
        """With external providers disabled neither the primary attempt nor the sweep uses them."""
        AuthModule.register_provider(_ExternalStubProvider)
        module = AuthModule(
            _settings([
                _stub_entry(LDAP_PROVIDER_NAME, active=False),
                _stub_entry('_ExternalStubProvider', active=True),
            ], enable_external=False),
            security_manager=MagicMock(),
            users_manager=MagicMock(),
        )
        _reset_stub(_ExternalStubProvider, result=self._user('_ExternalStubProvider'))
        module.users_manager.get_user_by.return_value = self._user('_ExternalStubProvider')

        with pytest.raises(AuthenticationError):
            module.login(USER_NAME, PASSWORD)

        assert _ExternalStubProvider.calls == []

    def test_the_sweep_skips_providers_whose_config_is_inactive(self, cmdb_app) -> None:
        """An inactive configuration is skipped without an authentication attempt."""
        module = self._module_with_stub(active=False)
        _reset_stub(_StubProvider, result=self._user('_StubProvider'))
        module.users_manager.get_user_by.return_value = None

        with pytest.raises(AuthenticationError):
            module.login(USER_NAME, PASSWORD)

        assert _StubProvider.calls == []

    def test_the_sweep_never_builds_an_inactive_provider(self, cmdb_app) -> None:
        """Activity is asked of the class, so an inactive provider's config never reaches a constructor."""
        module = self._module_with_stub(active=False)
        module.users_manager.get_user_by.return_value = None

        with patch.object(AuthModule, 'build_provider_instance', wraps=module.build_provider_instance) as build:
            with pytest.raises(AuthenticationError):
                module.login(USER_NAME, PASSWORD)

        assert _StubProvider not in [call.args[0] for call in build.call_args_list]

    def test_the_sweep_continues_after_a_rejected_credential(self, cmdb_app) -> None:
        """A provider that rejects the credentials does not end the sweep."""
        module = self._module_with_stub()
        _reset_stub(_StubProvider, error=AuthenticationError('nope'))
        module.users_manager.get_user_by.return_value = None

        with pytest.raises(AuthenticationError):
            module.login(USER_NAME, PASSWORD)

        assert _StubProvider.calls == [(USER_NAME, PASSWORD)]

    @pytest.mark.parametrize('error', [RuntimeError('x'), BaseManagerGetError('x')], ids=['bug', 'manager'])
    def test_a_provider_failing_with_anything_but_a_refusal_fails_the_login(self, cmdb_app, error: Exception) -> None:
        """
        Only an AuthenticationError hands the turn to the next provider

        Every provider reports its own read and write failures as one; anything else is a defect, and
        sweeping past it would hide it
        """
        module = self._module_with_stub()
        _reset_stub(_StubProvider, error=error)
        module.users_manager.get_user_by.return_value = None

        with pytest.raises(type(error)):
            module.login(USER_NAME, PASSWORD)

    def test_the_final_error_chains_the_primary_failure(self, cmdb_app) -> None:
        """The refusal carries the primary failure as its cause, so the log shows the real reason."""
        module = self._module_with_stub(active=False)
        module.users_manager.get_user_by.return_value = None

        with pytest.raises(AuthenticationError) as err:
            module.login(USER_NAME, PASSWORD)

        assert err.value.__cause__ is not None


# -------------------------------------------------------------------------------------------------------------------- #
#                                          EXTERNAL PROVIDERS IN CLOUD MODE                                            #
# -------------------------------------------------------------------------------------------------------------------- #
class TestExternalProvidersInCloud:
    """External providers are on-premise only: a cloud login runs none, whatever the section says."""
    # every test needs the app context for current_app.cloud_mode; most do not read the app object
    # pylint: disable=unused-argument

    @staticmethod
    def _external_module(enable_external: bool = True, active: bool = True) -> AuthModule:
        """Installs the external stand-in and builds a module whose section activates it."""
        AuthModule.register_provider(_ExternalStubProvider)

        return AuthModule(
            _settings([
                _stub_entry(LDAP_PROVIDER_NAME, active=False),
                _stub_entry('_ExternalStubProvider', active=active),
            ], enable_external=enable_external),
            security_manager=MagicMock(),
            users_manager=MagicMock(),
        )

    @staticmethod
    def _external_user() -> MagicMock:
        """A stored user the external stand-in owns, without a local password"""
        user = MagicMock()
        user.authenticator = '_ExternalStubProvider'
        user.password = None
        return user

    @pytest.mark.parametrize(('cloud_mode', 'enable_external', 'expected'), [
        (False, True, True),
        (False, False, False),
        (True, True, False),
        (True, False, False),
    ], ids=['on-premise', 'on-premise-disabled', 'cloud', 'cloud-disabled'])
    def test_external_providers_are_allowed_only_on_premise_and_enabled(
            self, cmdb_app, cloud_mode: bool, enable_external: bool, expected: bool) -> None:
        """The one gate: the stored switch, and never in cloud mode"""
        cmdb_app.cloud_mode = cloud_mode

        assert self._external_module(enable_external=enable_external).external_providers_allowed() is expected

    def test_the_primary_attempt_skips_the_users_external_provider_in_cloud(self, cmdb_app) -> None:
        """A user owned by an active external provider is not authenticated by it in cloud mode"""
        cmdb_app.cloud_mode = True
        module = self._external_module()
        _reset_stub(_ExternalStubProvider, result=self._external_user())
        module.users_manager.get_user_by.return_value = self._external_user()

        with pytest.raises(AuthenticationError):
            module.login(USER_EMAIL, PASSWORD)

        assert _ExternalStubProvider.calls == []

    def test_the_sweep_never_builds_an_external_provider_in_cloud(self, cmdb_app) -> None:
        """An unknown login is not handed to the external provider, which would provision a user"""
        cmdb_app.cloud_mode = True
        module = self._external_module()
        module.users_manager.get_user_by.return_value = None

        with patch.object(AuthModule, 'build_provider_instance', wraps=module.build_provider_instance) as build:
            with pytest.raises(AuthenticationError):
                module.login(USER_EMAIL, PASSWORD)

        assert _ExternalStubProvider not in [call.args[0] for call in build.call_args_list]
        assert _ExternalStubProvider.calls == []

    def test_the_same_section_still_authenticates_on_premise(self, cmdb_app) -> None:
        """The contrast: on premise the external provider wins its primary attempt"""
        module = self._external_module()
        expected_user = self._external_user()
        _reset_stub(_ExternalStubProvider, result=expected_user)
        module.users_manager.get_user_by.return_value = expected_user

        assert module.login(USER_NAME, PASSWORD) is expected_user
        assert _ExternalStubProvider.calls == [(USER_NAME, PASSWORD)]

    def test_the_active_external_providers_are_named(self, cmdb_app) -> None:
        """An active external provider is listed; the inactive LDAP entry and the internal providers are not"""
        assert self._external_module().active_external_provider_names() == ['_ExternalStubProvider']

    def test_an_inactive_external_provider_is_not_named(self, cmdb_app) -> None:
        """Nothing to refuse when every external provider is off"""
        assert not self._external_module(active=False).active_external_provider_names()

    def test_an_active_ldap_entry_is_named(self, cmdb_app) -> None:
        """The real LDAP provider, activated in the section, is what the cloud update refuses"""
        module = _module([_stub_entry(LOCAL_PROVIDER_NAME), _stub_entry(LDAP_PROVIDER_NAME, active=True)])

        assert module.active_external_provider_names() == [LDAP_PROVIDER_NAME]

    def test_the_names_do_not_depend_on_the_external_switch(self, cmdb_app) -> None:
        """An active provider is named even with `enable_external` off: the section still activates it"""
        assert self._external_module(enable_external=False).active_external_provider_names() == [
            '_ExternalStubProvider'
        ]


# -------------------------------------------------------------------------------------------------------------------- #
#                                           THE LOCAL PROVIDER'S ACTIVE FLAG                                           #
# -------------------------------------------------------------------------------------------------------------------- #
GONE_PROVIDER_NAME: str = 'GoneProvider'


class TestLocalProviderActiveFlag:
    """Local login cannot be switched off - not by a missing flag, and not by a stored False."""
    # the app context is needed for current_app.cloud_mode, the app object itself is not
    # pylint: disable=unused-argument

    @staticmethod
    def _module_with_local_config(local_config: dict[str, Any]) -> AuthModule:
        """A module whose section stores the given local config, with the LDAP provider switched off."""
        return _module([
            {PROVIDER_CLASS_NAME_KEY: LOCAL_PROVIDER_NAME, PROVIDER_CONFIG_KEY: local_config},
            _stub_entry(LDAP_PROVIDER_NAME, active=False),
        ])

    @staticmethod
    def _stranded_user() -> MagicMock:
        """A local user whose `authenticator` names a provider that is no longer installed."""
        user = MagicMock()
        user.authenticator = GONE_PROVIDER_NAME

        return user

    def test_a_stored_config_without_the_flag_is_normalised_to_active(self) -> None:
        """This is the section GET /auth/settings serves - it used to answer `active: null`."""
        module = self._module_with_local_config({})

        assert module.settings.get_provider_settings(LOCAL_PROVIDER_NAME)[PROVIDER_ACTIVE_KEY] is True

    @pytest.mark.parametrize('local_config', [{}, {PROVIDER_ACTIVE_KEY: None}, {PROVIDER_ACTIVE_KEY: False}],
                             ids=['missing', 'null', 'false'])
    def test_the_sweep_tries_the_local_provider_whatever_its_flag(
        self, cmdb_app, local_config: dict[str, Any],
    ) -> None:
        """The primary attempt fails on the unknown provider; the sweep must still reach local login."""
        module = self._module_with_local_config(local_config)
        user = self._stranded_user()
        module.users_manager.get_user_by.return_value = user

        with patch.object(LocalAuthenticationProvider, 'authenticate', return_value=user) as authenticate:
            assert module.login(USER_NAME, PASSWORD) is user

        authenticate.assert_called_once_with(USER_NAME, PASSWORD)


class TestIsActiveFor:
    """The one activity rule both halves of a login follow."""

    @pytest.mark.parametrize('active', [True, False])
    def test_by_default_the_config_decides(self, active: bool) -> None:
        """A provider that does not override the rule is as active as its configuration."""
        assert _StubProvider.is_active_for(_StubConfig(active=active)) is active

    @pytest.mark.parametrize('provider', AuthModule.get_installed_providers(), ids=lambda cls: cls.__name__)
    def test_no_installed_provider_has_an_instance_level_rule(self, provider: type) -> None:
        """One rule, on the class: a second, instance-level answer could disagree with it"""
        assert not hasattr(provider, 'is_active')

    @pytest.mark.parametrize('active', [True, False])
    def test_ldap_follows_its_config(self, active: bool) -> None:
        """LDAP does not override the default rule"""
        config = LdapAuthenticationProviderConfig(
            **{**LdapAuthenticationProviderConfig.DEFAULT_CONFIG_VALUES, PROVIDER_ACTIVE_KEY: active}
        )

        assert LdapAuthenticationProvider.is_active_for(config) is active
