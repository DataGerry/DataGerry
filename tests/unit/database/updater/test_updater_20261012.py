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
Unit tests for cmdb.database.updater.versions.updater_20261012

The migration only reports: users in a missing group, LDAP settings naming a missing group, type ACL entries for a
missing group, and - as an error - types whose activated list grants no existing group. Its run against real
collections is its own integration test; this module owns the frozen literals and rule, the reads, the reports, that
nothing is written, and the failure tail
"""
from typing import Any
from unittest.mock import MagicMock

import pytest

from cmdb.database.updater.versions import updater_20261012 as module
from cmdb.database.updater.versions.updater_20261012 import (
    Update20261012,
    is_locked,
    ldap_group_values,
    names_existing_group,
    unknown_acl_keys,
)
from cmdb.errors.updater import UpdaterException
from cmdb.manager import SettingsManager
from cmdb.models.group_model import CmdbUserGroup
from cmdb.models.security_models.auth_settings_constants import AUTH_SETTINGS_ID
from cmdb.models.type_model import CmdbType
from cmdb.models.user_model import CmdbUser, CmdbUserKey
from cmdb.security.acl.acl_groups import granting_group_ids
from cmdb.security.auth.providers.ldap_auth_config import LdapAuthenticationProviderConfig
from cmdb.security.auth.providers.ldap_constants import LDAP_PROVIDER_CLASS_NAME, LdapConfigKey
from cmdb.security.auth.providers.ldap_group_references import as_group_id, ldap_group_references
# -------------------------------------------------------------------------------------------------------------------- #

CREATION_DATE: int = 20261012
DATABASE_NAME: str = 'cmdb-unit'
GROUP: int = 5
MISSING_GROUP: int = 99
EXISTING: set[int] = {1, 2, GROUP}
USER_ID: int = 41
TYPE_ID: int = 61
READ: list[str] = ['READ']
GROUP_DN: str = 'cn=admins,dc=example,dc=com'

# Stored ACL blocks and LDAP sections the frozen rule must judge as the live one does
SAMPLE_ACLS: list[Any] = [
    None,
    {'activated': True, 'groups': {'includes': {str(GROUP): READ}}},
    {'activated': True, 'groups': {'includes': {str(MISSING_GROUP): READ}}},
    {'activated': True, 'groups': {'includes': {str(MISSING_GROUP): READ, str(GROUP): []}}},
    {'activated': False, 'groups': {'includes': {str(MISSING_GROUP): READ}}},
    {'activated': True, 'groups': {'includes': {}}},
]
SAMPLE_VALUES: list[Any] = [GROUP, str(GROUP), MISSING_GROUP, 'x', True, None, 0]


def _section(default_group: Any, mapped: Any = None) -> dict[str, Any]:
    """A stored auth section with one LDAP entry."""
    rows = [] if mapped is None else [{'group_dn': GROUP_DN, 'group_id': mapped}]

    return {'providers': [{'class_name': LDAP_PROVIDER_CLASS_NAME,
                           'config': {'default_group': default_group, 'groups': {'mapping': rows}}}]}


def _build_stubbed_updater(collections: dict[str, list[dict[str, Any]]]) -> Any:
    """The updater with a stubbed database manager answering each collection's documents"""
    updater = Update20261012.__new__(Update20261012)
    updater.dbm = MagicMock()
    updater.dbm.find.side_effect = lambda collection, **_kwargs: iter(collections.get(collection, []))
    updater.db_name = DATABASE_NAME
    updater.increase_updater_version = MagicMock()

    return updater


def _groups() -> list[dict[str, Any]]:
    """The existing groups, as projected"""
    return [{'public_id': group_id} for group_id in sorted(EXISTING)]


@pytest.mark.parametrize('frozen, live', [
    (module.GROUP_COLLECTION, CmdbUserGroup.COLLECTION),
    (module.USER_COLLECTION, CmdbUser.COLLECTION),
    (module.TYPE_COLLECTION, CmdbType.COLLECTION),
    (module.SETTINGS_COLLECTION, SettingsManager.COLLECTION),
    (module.GROUP_ID_FIELD, CmdbUserKey.GROUP_ID.value),
    (module.USER_NAME_FIELD, CmdbUserKey.USER_NAME.value),
    (module.AUTH_SETTINGS_ID, AUTH_SETTINGS_ID),
    (module.LDAP_PROVIDER_CLASS_NAME, LDAP_PROVIDER_CLASS_NAME),
    (module.DEFAULT_GROUP, LdapConfigKey.DEFAULT_GROUP.value),
    (module.LDAP_GROUPS, LdapConfigKey.GROUPS.value),
    (module.LDAP_DEFAULT_GROUP_ID, LdapAuthenticationProviderConfig.DEFAULT_CONFIG_VALUES['default_group']),
], ids=['groups', 'users', 'types', 'settings', 'group-id', 'user-name', 'auth-id', 'ldap-class', 'default-group',
        'ldap-groups', 'ldap-default'])
def test_a_frozen_literal_names_what_the_code_names_today(frozen: Any, live: Any) -> None:
    """Frozen on purpose - and right when it shipped"""
    assert frozen == live


@pytest.mark.parametrize('acl', SAMPLE_ACLS)
def test_the_frozen_lock_rule_is_the_live_one(acl: Any) -> None:
    """Locked = an activated list that grants no existing group anything"""
    live: bool = isinstance(acl, dict) and acl.get('activated') is True and not granting_group_ids(acl) & EXISTING

    assert is_locked(acl, EXISTING) == live


@pytest.mark.parametrize('value', SAMPLE_VALUES)
def test_the_frozen_value_rule_is_the_live_one(value: Any) -> None:
    """An existing group is named exactly when the live reader resolves it to one"""
    assert names_existing_group(value, EXISTING) == (as_group_id(value) in EXISTING)


MALFORMED_SECTION: dict[str, Any] = {'providers': ['x', {'class_name': LDAP_PROVIDER_CLASS_NAME,
                                                          'config': {'groups': {'mapping': ['row']}}}]}


@pytest.mark.parametrize('section', [_section(GROUP, MISSING_GROUP), _section(None), {'providers': None}, None,
                                     MALFORMED_SECTION],
                         ids=['default-and-mapping', 'default-missing', 'providers-null', 'none', 'malformed'])
def test_the_frozen_ldap_reader_is_the_live_one(section: Any) -> None:
    """Same values, same DNs"""
    assert ldap_group_values(section) == [(reference.value, reference.group_dn)
                                          for reference in ldap_group_references(section)]


def test_unknown_acl_keys_are_the_keys_naming_no_existing_group() -> None:
    """A key that is no number is unknown too"""
    acl = {'groups': {'includes': {str(GROUP): READ, str(MISSING_GROUP): [], 'x': READ}}}

    assert unknown_acl_keys(acl, EXISTING) == [str(MISSING_GROUP), 'x']


def test_every_kind_is_reported_and_nothing_written(caplog: pytest.LogCaptureFixture) -> None:
    """Users, LDAP default and mapping, ACL entries, locked types"""
    locked_acl = {'activated': True, 'groups': {'includes': {str(MISSING_GROUP): READ}}}
    stale_acl = {'activated': True, 'groups': {'includes': {str(GROUP): READ, str(MISSING_GROUP): READ}}}
    updater = _build_stubbed_updater({
        CmdbUserGroup.COLLECTION: _groups(),
        CmdbUser.COLLECTION: [{'public_id': USER_ID, 'user_name': 'ghost', 'group_id': MISSING_GROUP}],
        SettingsManager.COLLECTION: [_section(MISSING_GROUP, MISSING_GROUP)],
        CmdbType.COLLECTION: [{'public_id': TYPE_ID, 'name': 'locked', 'acl': locked_acl},
                              {'public_id': TYPE_ID + 1, 'name': 'stale', 'acl': stale_acl}],
    })

    updater.start_update()

    text = caplog.text
    assert 'ghost' in text and 'default group' in text and GROUP_DN in text
    assert 'LOCKED' in text and "'stale'" in text
    assert [record.levelname for record in caplog.records if 'LOCKED' in record.getMessage()] == ['ERROR']
    updater.dbm.update.assert_not_called()
    updater.dbm.update_many_raw.assert_not_called()
    updater.increase_updater_version.assert_called_once_with(CREATION_DATE)


def test_the_users_are_read_by_a_group_outside_the_existing_ones() -> None:
    """The query does the selecting"""
    updater = _build_stubbed_updater({CmdbUserGroup.COLLECTION: _groups()})

    updater.start_update()

    user_read = next(call for call in updater.dbm.find.call_args_list
                     if call.kwargs['collection'] == CmdbUser.COLLECTION)
    assert user_read.kwargs['filter'] == {'group_id': {'$nin': sorted(EXISTING)}}


def test_a_clean_database_reports_nothing(caplog: pytest.LogCaptureFixture) -> None:
    """Only the version moves"""
    updater = _build_stubbed_updater({
        CmdbUserGroup.COLLECTION: _groups(),
        SettingsManager.COLLECTION: [_section(GROUP)],
        CmdbType.COLLECTION: [{'public_id': TYPE_ID, 'name': 'fine',
                               'acl': {'activated': True, 'groups': {'includes': {str(GROUP): READ}}}}],
    })

    updater.start_update()

    assert 'Update20261012' not in caplog.text
    updater.increase_updater_version.assert_called_once_with(CREATION_DATE)


def test_a_failed_read_is_wrapped_with_the_error_itself_and_leaves_the_version() -> None:
    """The next start runs the report again"""
    updater = _build_stubbed_updater({})
    error = RuntimeError('down')
    updater.dbm.find.side_effect = error

    with pytest.raises(UpdaterException) as exc_info:
        updater.start_update()

    assert exc_info.value.__cause__ is error
    assert exc_info.value.args[0] is error
    updater.increase_updater_version.assert_not_called()


def test_the_description_says_it_writes_nothing() -> None:
    """The line the updater log prints"""
    assert 'writes nothing' in Update20261012.__new__(Update20261012).description()
