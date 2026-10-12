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
Which CmdbUserGroups the stored LDAP settings name

The LDAP provider names a group in two places of its stored ``config``: the ``default_group`` every directory user
lands in when no mapping applies, and the ``group_id`` of each ``groups.mapping`` row. These readers take the raw
auth settings section (``{'providers': [{'class_name': ..., 'config': {...}}, ...]}``) as stored or sent, so the
auth-settings write can refuse a group that does not exist and the group delete can refuse a group the settings
still name. A missing ``default_group`` reads as the provider's own default, the way the provider config reads it
"""
from dataclasses import dataclass
from typing import Any

from cmdb.models.security_models.auth_settings_constants import AuthSettingsKey, ProviderEntryKey
from cmdb.security.auth.providers.ldap_auth_config import LdapAuthenticationProviderConfig
from cmdb.security.auth.providers.ldap_constants import (
    LDAP_PROVIDER_CLASS_NAME,
    LdapConfigKey,
    LdapGroupMappingKey,
    LdapGroupsKey,
)
# -------------------------------------------------------------------------------------------------------------------- #

__all__ = ['LdapGroupReference', 'as_group_id', 'ldap_group_references']


@dataclass(frozen=True)
class LdapGroupReference:
    """
    One place the LDAP settings name a CmdbUserGroup

    Attributes:
        value (Any): The group id as stored - an int when it is usable
        group_dn (str | None): The directory group DN of a mapping row; None for the default group
    """
    value: Any
    group_dn: str | None = None

    @property
    def is_default(self) -> bool:
        """Whether this is the provider's default group rather than a mapping row"""
        return self.group_dn is None


def as_group_id(value: Any) -> int | None:
    """
    Reads a group public_id the way the provider reads it at login (``int()``), refusing what is no id

    Args:
        value (Any): A stored group reference

    Returns:
        int | None: The positive public_id; None for a boolean, a non-number or a number below 1
    """
    if isinstance(value, bool):
        return None

    if isinstance(value, int):
        return value if value > 0 else None

    if isinstance(value, str) and value.isdigit():
        return int(value) or None

    return None


def ldap_group_references(auth_settings: Any) -> list[LdapGroupReference]:
    """
    Answers every place the LDAP provider entries of an auth settings section name a group

    Args:
        auth_settings (Any): The auth settings section as stored or sent

    Returns:
        list[LdapGroupReference]: The default group of each LDAP entry, then its mapping rows, in order
    """
    providers: Any = auth_settings.get(AuthSettingsKey.PROVIDERS.value) if isinstance(auth_settings, dict) else None
    references: list[LdapGroupReference] = []

    for entry in providers if isinstance(providers, list) else []:
        if not isinstance(entry, dict) or entry.get(ProviderEntryKey.CLASS_NAME.value) != LDAP_PROVIDER_CLASS_NAME:
            continue

        config: Any = entry.get(ProviderEntryKey.CONFIG.value)
        config = config if isinstance(config, dict) else {}
        default_group: Any = config.get(LdapConfigKey.DEFAULT_GROUP.value) or \
            LdapAuthenticationProviderConfig.DEFAULT_CONFIG_VALUES[LdapConfigKey.DEFAULT_GROUP.value]
        references.append(LdapGroupReference(default_group))

        groups: Any = config.get(LdapConfigKey.GROUPS.value)
        mapping: Any = groups.get(LdapGroupsKey.MAPPING.value) if isinstance(groups, dict) else None

        for row in mapping if isinstance(mapping, list) else []:
            if isinstance(row, dict):
                references.append(LdapGroupReference(
                    row.get(LdapGroupMappingKey.GROUP_ID.value), str(row.get(LdapGroupMappingKey.GROUP_DN.value) or ''),
                ))

    return references
