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
Unit tests for cmdb.database.updater.versions.updater_20261015

The migration stores the auth providers' flags spelled exactly "true" / "false" as booleans - the provider flag and
the LDAP group-mapping flag - and leaves every other non-boolean value alone, logged. Its run against a real
collection is its own integration test; this module owns the frozen literals, the rewrite rule, the conditioned
write, that nothing is written when nothing changed, and the failure tail
"""
from copy import deepcopy
from typing import Any
from unittest.mock import MagicMock

import pytest

from cmdb.database.updater.versions import updater_20261015 as module
from cmdb.database.updater.versions.updater_20261015 import Update20261015, flag_holders, normalised_providers
from cmdb.errors.updater import UpdaterException
from cmdb.manager import SettingsManager
from cmdb.models.security_models.auth_settings_constants import AUTH_SETTINGS_ID, AuthSettingsKey, ProviderEntryKey
from cmdb.security.auth.base_provider_config import PROVIDER_ACTIVE_KEY
from cmdb.security.auth.providers.ldap_auth_config import GROUPS_ACTIVE_FLAG
from cmdb.security.auth.providers.ldap_constants import LDAP_PROVIDER_CLASS_NAME, LdapConfigKey, LdapGroupsKey
# -------------------------------------------------------------------------------------------------------------------- #

CREATION_DATE: int = 20261015
DATABASE_NAME: str = 'cmdb-unit'
LOCAL: str = 'LocalAuthenticationProvider'


def _entry(name: str, active: Any, groups_active: Any = None, with_groups: bool = False) -> dict[str, Any]:
    """A stored provider entry"""
    config: dict[str, Any] = {} if active is None else {'active': active}

    if with_groups or groups_active is not None:
        config['groups'] = {'mapping': []} if groups_active is None else {'active': groups_active, 'mapping': []}

    return {'class_name': name, 'config': config}


def _build_stubbed_updater(section: dict[str, Any] | None) -> tuple[Update20261015, MagicMock]:
    """The updater with a stubbed database manager whose settings collection answers the section"""
    updater = Update20261015.__new__(Update20261015)
    updater.dbm = MagicMock()
    updater.dbm.get_collection.return_value.find_one.return_value = section
    updater.db_name = DATABASE_NAME
    updater.increase_updater_version = MagicMock()

    return updater, updater.dbm


@pytest.mark.parametrize('frozen, live', [
    (module.SETTINGS_COLLECTION, SettingsManager.COLLECTION),
    (module.AUTH_SETTINGS_ID, AUTH_SETTINGS_ID),
    (module.PROVIDERS, AuthSettingsKey.PROVIDERS.value),
    (module.CLASS_NAME, ProviderEntryKey.CLASS_NAME.value),
    (module.CONFIG, ProviderEntryKey.CONFIG.value),
    (module.ACTIVE, PROVIDER_ACTIVE_KEY),
    (module.ACTIVE, LdapGroupsKey.ACTIVE.value),
    (module.LDAP_GROUPS, LdapConfigKey.GROUPS.value),
    (module.GROUPS_ACTIVE_FLAG, GROUPS_ACTIVE_FLAG),
], ids=['settings', 'auth-id', 'providers', 'class-name', 'config', 'active', 'groups-active', 'groups',
        'groups-flag'])
def test_a_frozen_literal_names_what_the_code_names_today(frozen: Any, live: Any) -> None:
    """Frozen on purpose - and right when it shipped"""
    assert frozen == live


class TestFlagHolders:
    """flag_holders"""

    def test_a_config_without_groups_holds_one_flag(self) -> None:
        """The provider flag"""
        config: dict[str, Any] = {'active': True}

        assert flag_holders(config) == [(config, module.ACTIVE)]

    def test_groups_hold_the_second(self) -> None:
        """The very dicts, so a rewrite lands in the copy being built"""
        config: dict[str, Any] = {'active': True, 'groups': {'active': False}}

        holders = flag_holders(config)

        assert [label for _holder, label in holders] == [module.ACTIVE, module.GROUPS_ACTIVE_FLAG]
        assert holders[1][0] is config['groups']

    @pytest.mark.parametrize('groups', ['x', None, ['active']])
    def test_groups_that_are_no_document_hold_none(self, groups: Any) -> None:
        """Nothing to read a flag from"""
        assert len(flag_holders({'groups': groups})) == 1


class TestNormalisedProviders:
    """normalised_providers"""

    @pytest.mark.parametrize('stored, expected', [('true', True), ('false', False)])
    def test_the_two_spellings_become_booleans(self, stored: str, expected: bool) -> None:
        """The provider flag and the group-mapping flag"""
        rewritten, changed, left_alone = normalised_providers(
            [_entry(LDAP_PROVIDER_CLASS_NAME, stored, groups_active=stored)],
        )

        config = rewritten[0]['config']
        assert config['active'] is expected and config['groups']['active'] is expected
        assert changed == [f'{LDAP_PROVIDER_CLASS_NAME} {module.ACTIVE}={stored!r}',
                           f'{LDAP_PROVIDER_CLASS_NAME} {module.GROUPS_ACTIVE_FLAG}={stored!r}']
        assert not left_alone

    @pytest.mark.parametrize('stored', ['True', 'FALSE', ' true', 'yes', '0', 1, 0, [], {}])
    def test_any_other_non_boolean_is_left_alone_and_named(self, stored: Any) -> None:
        """Its meaning is not unambiguous"""
        providers = [_entry(LOCAL, stored)]

        rewritten, changed, left_alone = normalised_providers(providers)

        assert rewritten == providers
        assert not changed
        assert left_alone == [f'{LOCAL} {module.ACTIVE}={stored!r}']

    @pytest.mark.parametrize('stored', [True, False, None])
    def test_a_boolean_or_absent_flag_is_neither(self, stored: Any) -> None:
        """Nothing to do"""
        providers = [_entry(LDAP_PROVIDER_CLASS_NAME, stored, with_groups=True)]

        assert normalised_providers(providers) == (providers, [], [])

    def test_entries_without_a_config_document_are_skipped(self) -> None:
        """A malformed stored list is read as far as it can be"""
        providers: list[Any] = ['x', {'class_name': LOCAL}, {'class_name': LOCAL, 'config': 'off'},
                                _entry(LDAP_PROVIDER_CLASS_NAME, 'false')]

        rewritten, changed, _left_alone = normalised_providers(providers)

        assert rewritten[:3] == providers[:3]
        assert rewritten[3]['config']['active'] is False
        assert len(changed) == 1

    @pytest.mark.parametrize('providers', [None, 'x', {}])
    def test_a_stored_value_that_is_no_list_reads_as_empty(self, providers: Any) -> None:
        """Nothing to rewrite"""
        assert normalised_providers(providers) == ([], [], [])

    def test_the_stored_list_is_left_as_it_was(self) -> None:
        """The rewrite is a copy: the original is the write's condition"""
        providers = [_entry(LDAP_PROVIDER_CLASS_NAME, 'true', groups_active='false')]
        before = deepcopy(providers)

        normalised_providers(providers)

        assert providers == before


class TestNormaliseAuthFlags:
    """Update20261015.normalise_auth_flags"""

    def test_a_rewrite_is_written_conditioned_on_the_list_read(self) -> None:
        """A section saved in between is left alone"""
        providers = [_entry(LDAP_PROVIDER_CLASS_NAME, 'false')]
        updater, dbm = _build_stubbed_updater({'_id': AUTH_SETTINGS_ID, 'providers': providers})

        changed = updater.normalise_auth_flags()

        assert changed == [f"{LDAP_PROVIDER_CLASS_NAME} {module.ACTIVE}='false'"]
        dbm.get_collection.assert_called_with(module.SETTINGS_COLLECTION, DATABASE_NAME)
        dbm.get_collection.return_value.find_one.assert_called_once_with({'_id': AUTH_SETTINGS_ID})
        dbm.update.assert_called_once_with(
            module.SETTINGS_COLLECTION, DATABASE_NAME, {'_id': AUTH_SETTINGS_ID, 'providers': providers},
            {'providers': [_entry(LDAP_PROVIDER_CLASS_NAME, False)]},
        )

    def test_nothing_is_written_when_nothing_changed(self, caplog: pytest.LogCaptureFixture) -> None:
        """A value left alone is only logged"""
        updater, dbm = _build_stubbed_updater({'_id': AUTH_SETTINGS_ID,
                                               'providers': [_entry(LDAP_PROVIDER_CLASS_NAME, 'yes')]})

        with caplog.at_level('WARNING'):
            assert not updater.normalise_auth_flags()

        dbm.update.assert_not_called()
        assert f"{LDAP_PROVIDER_CLASS_NAME} {module.ACTIVE}='yes'" in caplog.text

    def test_no_stored_section_is_nothing_to_do(self) -> None:
        """A fresh database"""
        updater, dbm = _build_stubbed_updater(None)

        assert not updater.normalise_auth_flags()
        dbm.update.assert_not_called()


class TestStartUpdate:
    """Update20261015.start_update"""

    def test_the_metadata(self) -> None:
        """The date it runs at"""
        updater, _dbm = _build_stubbed_updater(None)

        assert updater.creation_date() == CREATION_DATE
        assert updater.description()

    def test_it_rewrites_then_bumps_the_version(self) -> None:
        """In that order"""
        updater, _dbm = _build_stubbed_updater(None)
        calls: list[str] = []
        updater.normalise_auth_flags = MagicMock(side_effect=lambda: calls.append('normalise'))
        updater.increase_updater_version.side_effect = lambda _version: calls.append('version')

        updater.start_update()

        assert calls == ['normalise', 'version']
        updater.increase_updater_version.assert_called_once_with(CREATION_DATE)

    def test_a_failure_is_wrapped_carrying_the_error(self) -> None:
        """The exception itself, never its text; the version is not bumped"""
        updater, dbm = _build_stubbed_updater(None)
        error = RuntimeError('read failed')
        dbm.get_collection.return_value.find_one.side_effect = error

        with pytest.raises(UpdaterException) as exc_info:
            updater.start_update()

        assert exc_info.value.args[0] is error
        updater.increase_updater_version.assert_not_called()
