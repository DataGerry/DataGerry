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
Integration tests for the LDAP provider's flags against a stored auth section

The section is written to MongoDB and read back the way the login route reads it, and a login for a name no local
user carries runs the fallback sweep - the one place an external provider is asked. The LDAP provider's
`authenticate` is recorded, never run against a directory. A flag stored as anything but a boolean - which the
auth-settings write refuses - makes the LDAP config unbuildable, so it reads as the defaults: switched off,
never asked. A stored boolean decides, the control
"""
from copy import deepcopy
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import SecurityManager, UsersManager
from cmdb.manager.system_manager.settings_manager import SettingsManager
from cmdb.models.security_models.auth_settings_constants import AUTH_SETTINGS_ID
from cmdb.security.auth.auth_module import AuthModule
from cmdb.security.auth.providers.ldap_auth_config import LdapAuthenticationProviderConfig
from cmdb.security.auth.providers.ldap_auth_provider import LdapAuthenticationProvider
from cmdb.security.auth.providers.local_auth_provider import LocalAuthenticationProvider
from cmdb.errors.provider import AuthenticationError
# -------------------------------------------------------------------------------------------------------------------- #

UNKNOWN_USER: str = 'directory-only-flag-user'
PASSWORD: str = 'directory-password'
LDAP: str = LdapAuthenticationProvider.get_name()
LOCAL: str = LocalAuthenticationProvider.get_name()
NOT_BOOLEANS: list[Any] = ['false', 'true', 1]


@pytest.fixture(name='settings_manager')
def fixture_settings_manager(rest_api, database_manager: MongoDatabaseManager, database_name: str):
    """A SettingsManager inside an app context; the stored auth section is restored afterwards"""
    collection = database_manager.get_collection(SettingsManager.COLLECTION, database_name)
    before = collection.find_one({'_id': AUTH_SETTINGS_ID})

    with rest_api.application.app_context():
        yield SettingsManager(database_manager)

    if before is None:
        collection.delete_one({'_id': AUTH_SETTINGS_ID})
    else:
        collection.replace_one({'_id': AUTH_SETTINGS_ID}, before, upsert=True)


@pytest.fixture(name='ldap_calls')
def fixture_ldap_calls(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Every user name the LDAP provider was asked to authenticate; it refuses each"""
    calls: list[str] = []

    def _authenticate(_self: LdapAuthenticationProvider, user_name: str, _password: str) -> None:
        calls.append(user_name)
        raise AuthenticationError('recorded')

    monkeypatch.setattr(LdapAuthenticationProvider, 'authenticate', _authenticate)

    return calls


def _module_over_stored_section(settings_manager: SettingsManager, database_manager: MongoDatabaseManager,
                                ldap_active: Any, groups_active: Any = False) -> AuthModule:
    """Stores a section with LDAP's flags as given and reads it back as the login route does"""
    ldap_config: dict[str, Any] = deepcopy(LdapAuthenticationProviderConfig.DEFAULT_CONFIG_VALUES)
    ldap_config['active'] = ldap_active
    ldap_config['groups']['active'] = groups_active
    settings_manager.write(_id=AUTH_SETTINGS_ID, data={'enable_external': True, 'token_lifetime': 60, 'providers': [
        {'class_name': LOCAL, 'config': {'active': True}},
        {'class_name': LDAP, 'config': ldap_config},
    ]})
    stored = settings_manager.get_all_values_from_section(AUTH_SETTINGS_ID, default=AuthModule.__DEFAULT_SETTINGS__)

    return AuthModule(stored, security_manager=SecurityManager(database_manager),
                      users_manager=UsersManager(database_manager))


@pytest.mark.parametrize('ldap_active', NOT_BOOLEANS)
def test_a_stored_flag_that_is_no_boolean_never_asks_ldap(settings_manager, database_manager, ldap_calls,
                                                         ldap_active: Any) -> None:
    """'false' among them - a truthy string, whatever it spells"""
    module = _module_over_stored_section(settings_manager, database_manager, ldap_active)

    with pytest.raises(AuthenticationError):
        module.login(UNKNOWN_USER, PASSWORD)

    assert not ldap_calls


def test_a_stored_group_mapping_flag_that_is_no_boolean_switches_ldap_off(settings_manager, database_manager,
                                                                          ldap_calls) -> None:
    """The whole config reads as the defaults - LDAP itself included"""
    module = _module_over_stored_section(settings_manager, database_manager, True, groups_active='false')

    with pytest.raises(AuthenticationError):
        module.login(UNKNOWN_USER, PASSWORD)

    assert not ldap_calls


@pytest.mark.parametrize('ldap_active', [True, False])
def test_a_stored_boolean_decides(settings_manager, database_manager, ldap_calls, ldap_active: bool) -> None:
    """The control: on, the sweep asks LDAP; off, it does not"""
    module = _module_over_stored_section(settings_manager, database_manager, ldap_active)

    with pytest.raises(AuthenticationError):
        module.login(UNKNOWN_USER, PASSWORD)

    assert ldap_calls == ([UNKNOWN_USER] if ldap_active else [])
