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
Integration tests for cmdb.database.updater.versions.updater_20261015 against a real MongoDB

Seeds a stored auth section whose provider flags are spelled "true" / "false", one that is neither, and booleans;
runs the migration and asserts:
  - the two spellings are stored as booleans - the provider flag and the LDAP group-mapping flag
  - any other value and every other key are left as they were
  - the section then builds as the strings meant: "true" keeps LDAP on, "false" switches it off
  - a second run changes nothing; a database without a section gets none
"""
from copy import deepcopy
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.database.updater.versions.updater_20261015 import Update20261015
from cmdb.manager.system_manager.settings_manager import SettingsManager
from cmdb.models.security_models.auth_settings_constants import AUTH_SETTINGS_ID
from cmdb.security.auth.auth_module import AuthModule
from cmdb.security.auth.providers.ldap_auth_config import LdapAuthenticationProviderConfig
from cmdb.security.auth.providers.ldap_auth_provider import LdapAuthenticationProvider
from cmdb.security.auth.providers.local_auth_provider import LocalAuthenticationProvider
# -------------------------------------------------------------------------------------------------------------------- #

LDAP: str = LdapAuthenticationProvider.get_name()
LOCAL: str = LocalAuthenticationProvider.get_name()
HOST: str = 'ldap.upd-20261015.example'
LEFT_ALONE: str = 'yes'


def _section(ldap_active: Any, groups_active: Any, local_active: Any) -> dict[str, Any]:
    """A stored auth section"""
    ldap_config: dict[str, Any] = deepcopy(LdapAuthenticationProviderConfig.DEFAULT_CONFIG_VALUES)
    ldap_config.update({'active': ldap_active, 'server_config': {'host': HOST, 'port': 389, 'use_ssl': False}})
    ldap_config['groups']['active'] = groups_active

    return {'_id': AUTH_SETTINGS_ID, 'enable_external': True, 'token_lifetime': 60, 'providers': [
        {'class_name': LOCAL, 'config': {'active': local_active}},
        {'class_name': LDAP, 'config': ldap_config},
    ]}


@pytest.fixture(name='settings')
def fixture_settings(database_manager: MongoDatabaseManager, database_name: str):
    """The settings collection; the stored auth section is restored afterwards"""
    collection = database_manager.get_collection(SettingsManager.COLLECTION, database_name)
    before = collection.find_one({'_id': AUTH_SETTINGS_ID})

    yield collection

    if before is None:
        collection.delete_one({'_id': AUTH_SETTINGS_ID})
    else:
        collection.replace_one({'_id': AUTH_SETTINGS_ID}, before, upsert=True)


def _seed(settings, section: dict[str, Any]) -> None:
    """Stores the section as the only auth section"""
    settings.replace_one({'_id': AUTH_SETTINGS_ID}, section, upsert=True)


def _run(database_manager: MongoDatabaseManager, database_name: str) -> None:
    """One run of the migration"""
    Update20261015(database_manager, database_name).start_update()


def _stored(settings) -> dict[str, Any]:
    """The stored section"""
    return settings.find_one({'_id': AUTH_SETTINGS_ID})


@pytest.mark.parametrize('spelled, meant', [('true', True), ('false', False)])
def test_the_spellings_become_booleans_and_nothing_else_changes(database_manager, database_name, settings,
                                                                spelled: str, meant: bool) -> None:
    """Both LDAP flags rewritten; the value that is neither left; every other key kept"""
    _seed(settings, _section(spelled, spelled, LEFT_ALONE))

    _run(database_manager, database_name)

    assert _stored(settings) == _section(meant, meant, LEFT_ALONE)


@pytest.mark.parametrize('spelled, meant', [('true', True), ('false', False)])
def test_the_section_then_builds_as_the_string_meant(database_manager, database_name, settings,
                                                     spelled: str, meant: bool) -> None:
    """Read back the way the routes read it"""
    _seed(settings, _section(spelled, False, True))

    _run(database_manager, database_name)

    stored = SettingsManager(database_manager, database_name).get_all_values_from_section(AUTH_SETTINGS_ID)
    config = AuthModule(stored).build_provider_config(LdapAuthenticationProvider)
    assert LdapAuthenticationProvider.is_active_for(config) is meant
    assert config.server_config['host'] == HOST


def test_a_second_run_changes_nothing(database_manager, database_name, settings) -> None:
    """Idempotent"""
    _seed(settings, _section('false', 'true', LEFT_ALONE))
    _run(database_manager, database_name)
    after_first = _stored(settings)

    _run(database_manager, database_name)

    assert _stored(settings) == after_first


def test_booleans_are_left_as_they_were(database_manager, database_name, settings) -> None:
    """Nothing to do"""
    _seed(settings, _section(True, False, True))

    _run(database_manager, database_name)

    assert _stored(settings) == _section(True, False, True)


def test_no_section_is_created(database_manager, database_name, settings) -> None:
    """A database that stores none keeps reading the defaults"""
    settings.delete_one({'_id': AUTH_SETTINGS_ID})

    _run(database_manager, database_name)

    assert _stored(settings) is None
