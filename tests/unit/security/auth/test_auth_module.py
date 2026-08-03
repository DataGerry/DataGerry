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
from cmdb.models.user_model import CmdbUser
from cmdb.security.auth.auth_module import (
    PROVIDER_CLASS_NAME_KEY,
    PROVIDER_CONFIG_KEY,
    PROVIDERS_KEY,
    AuthModule,
)
from cmdb.security.auth.base_authentication_provider import BaseAuthenticationProvider
from cmdb.security.auth.base_provider_config import BaseAuthProviderConfig
from cmdb.security.auth.providers.local_auth_provider import LocalAuthenticationProvider
from cmdb.security.auth.providers.ldap_auth_provider import LdapAuthenticationProvider
from cmdb.errors.provider import AuthenticationError
from cmdb.errors.manager import BaseManagerGetError, BaseManagerInsertError
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
    provider_is_active: bool = True
    calls: list[tuple[str, str]] = []

    def authenticate(self, user_name: str, password: str) -> CmdbUser:
        """Records the attempt, then returns / raises whatever the test configured."""
        type(self).calls.append((user_name, password))

        if type(self).authenticate_error is not None:
            raise type(self).authenticate_error

        return type(self).authenticate_result

    def is_active(self) -> bool:
        """Reports the provider-level activation flag the test set."""
        return type(self).provider_is_active


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
    provider.provider_is_active = True
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
    tests/fixtures/fixture_rest_api, and shadowing it leaves the session without an app context.
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
        'token_lifetime': 1400,
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
        """The topped-up entry can be read back by name (it used to raise KeyError 'class_name')."""
        module = _module([_stub_entry(LOCAL_PROVIDER_NAME)])

        assert isinstance(module.settings.get_provider_settings(LDAP_PROVIDER_NAME), dict)

    def test_a_second_module_over_the_same_section_still_works(self) -> None:
        """Re-normalising an already topped-up section does not break (the old malformed entry did)."""
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
        """register_provider must not extend the pre-installed list (they used to be the same object)."""
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

    def test_internals_and_external_are_split_by_the_flag(self) -> None:
        """The two accessors filter on EXTERNAL_PROVIDER (they used to both return everything)."""
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
        """The configured provider really gets the stored values (it used to always get the defaults)."""
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
                _stub_entry(LOCAL_PROVIDER_NAME, active=False),
                _stub_entry(LDAP_PROVIDER_NAME, active=False),
                _stub_entry('_StubProvider', active=active),
            ], enable_external=enable_external),
            security_manager=MagicMock(),
            users_manager=MagicMock(),
        )

    @staticmethod
    def _user(authenticator: str) -> MagicMock:
        """A stored CmdbUser stand-in naming its provider."""
        user = MagicMock()
        user.authenticator = authenticator

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
    def test_the_lookup_lower_cases_the_user_name_on_premise(self, cmdb_app) -> None:
        """On-premise the stored user is resolved by a lower-cased user_name."""
        module = self._module_with_stub()
        _reset_stub(_StubProvider, result=self._user('_StubProvider'))
        module.users_manager.get_user_by.return_value = self._user('_StubProvider')

        module.login('TestUser', PASSWORD)

        assert module.users_manager.get_user_by.call_args.args[0] == {'user_name': 'testuser'}

    def test_cloud_mode_resolves_the_user_by_email(self, cmdb_app) -> None:
        """In cloud mode the login is looked up as an email."""
        cmdb_app.cloud_mode = True
        module = self._module_with_stub()
        _reset_stub(_StubProvider, result=self._user('_StubProvider'))
        module.users_manager.get_user_by.return_value = self._user('_StubProvider')

        module.login(USER_EMAIL, PASSWORD)

        assert module.users_manager.get_user_by.call_args.args[0] == {'email': USER_EMAIL}

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
        """A provider whose instance reports inactive does not authenticate on the primary path."""
        module = self._module_with_stub(active=False)
        expected_user = self._user('_StubProvider')
        _reset_stub(_StubProvider, result=expected_user)
        _StubProvider.provider_is_active = False
        module.users_manager.get_user_by.return_value = expected_user

        with pytest.raises(AuthenticationError):
            module.login(USER_NAME, PASSWORD)

    def test_an_external_provider_is_refused_when_external_is_disabled(self, cmdb_app) -> None:
        """With external providers disabled neither the primary attempt nor the sweep uses them."""
        AuthModule.register_provider(_ExternalStubProvider)
        module = AuthModule(
            _settings([
                _stub_entry(LOCAL_PROVIDER_NAME, active=False),
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

    def test_the_sweep_continues_after_a_rejected_credential(self, cmdb_app) -> None:
        """A provider that rejects the credentials does not end the sweep."""
        module = self._module_with_stub()
        _reset_stub(_StubProvider, error=AuthenticationError('nope'))
        module.users_manager.get_user_by.return_value = None

        with pytest.raises(AuthenticationError):
            module.login(USER_NAME, PASSWORD)

        assert _StubProvider.calls == [(USER_NAME, PASSWORD)]

    @pytest.mark.parametrize('manager_error', [BaseManagerGetError('x'), BaseManagerInsertError('x')])
    def test_the_sweep_continues_after_a_manager_error(
        self, cmdb_app, manager_error: Exception,
    ) -> None:
        """A provider that finds the user but cannot store it does not end the sweep either."""
        module = self._module_with_stub()
        _reset_stub(_StubProvider, error=manager_error)
        module.users_manager.get_user_by.return_value = None

        with pytest.raises(AuthenticationError):
            module.login(USER_NAME, PASSWORD)

    def test_the_final_error_chains_the_primary_failure(self, cmdb_app) -> None:
        """The refusal carries the primary failure as its cause, so the log shows the real reason."""
        module = self._module_with_stub(active=False)
        module.users_manager.get_user_by.return_value = None

        with pytest.raises(AuthenticationError) as err:
            module.login(USER_NAME, PASSWORD)

        assert err.value.__cause__ is not None
