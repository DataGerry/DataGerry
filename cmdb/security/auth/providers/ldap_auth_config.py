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
Implementation of LdapAuthenticationProviderConfig
"""
from copy import deepcopy
from logging import Logger, getLogger
from typing import Any

from cmdb.security.auth.base_provider_config import BaseAuthProviderConfig, validated_flag
from cmdb.security.auth.providers.ldap_constants import LdapConfigKey, LdapGroupsKey

from cmdb.errors.provider import GroupMappingError, ProviderConfigError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# The group-mapping flag's name in a refusal: it lives inside 'groups'
GROUPS_ACTIVE_FLAG: str = f'{LdapConfigKey.GROUPS.value}.{LdapGroupsKey.ACTIVE.value}'

# Why a 'groups' value is refused - `kind` is the type it arrived as
GROUPS_NOT_AN_OBJECT_MSG: str = f"'{LdapConfigKey.GROUPS.value}' must be an object, got {{kind}}"

# -------------------------------------------------------------------------------------------------------------------- #
#                                       LdapAuthenticationProviderConfig - CLASS                                       #
# -------------------------------------------------------------------------------------------------------------------- #
class LdapAuthenticationProviderConfig(BaseAuthProviderConfig):
    """
    Configuration class for the LDAP Authentication Provider.

    This class holds all settings needed to connect to an LDAP server,
    search for users, and optionally map LDAP groups to internal application groups.

    Extends: BaseAuthProviderConfig
    """
    DEFAULT_CONFIG_VALUES = {
        'active': False,
        'default_group': 2,
        'server_config': {
            'host': 'localhost',
            'port': 389,
            'use_ssl': False
        },
        'connection_config': {
            'user': 'cn=reader,dc=example,dc=com',
            'password': 'secret1234',
            'version': 3
        },
        'search': {
            'basedn': 'dc=example,dc=com',
            'searchfilter': '(uid=%username%)'
        },
        'groups': {
            'active': False,
            'searchfiltergroup': '(memberUid=%username%)',
            'mapping': []
        }
    }

    # The LDAP bind credential. It is the one value in this configuration that must never be served
    # back to a client, and the only reason it is stored at all is that a search bind needs it
    SECRET_CONFIG_PATHS: tuple[tuple[str, ...], ...] = (
        ('connection_config', 'password'),
    )

    def __init__(
        self,
        active: bool | None = None,
        default_group: int | None = None,
        server_config: dict[str, Any] | None = None,
        connection_config: dict[str, Any] | None = None,
        search: dict[str, Any] | None = None,
        groups: dict[str, Any] | None = None,
        **kwargs: Any) -> None:
        """
        Initialize an LDAP Authentication Provider Configuration instance

        Args:
            active (bool | None): Whether the LDAP provider is active. Defaults to False
            default_group (int | None): Default group ID for users. Defaults to 2
            server_config (dict[str, Any] | None): Configuration for the LDAP server (host, port, SSL)
            connection_config (dict[str, Any] | None): Configuration for the LDAP connection (bind user, password,
                version)
            search (dict[str, Any] | None): Search parameters for finding users
            groups (dict[str, Any] | None): Group mapping settings
            **kwargs (Any): Stored keys this configuration does not declare. Accepted, so a settings
                document carrying an extra key still loads, and dropped - unlike the local provider's
                configuration, which hands them to the base class to be set as attributes

        Raises:
            ProviderConfigError: When `active` or the group-mapping flag is present and not a boolean, or
                `groups` is not an object
        """
        defaults: dict[str, Any] = LdapAuthenticationProviderConfig.DEFAULT_CONFIG_VALUES
        self.default_group = int(default_group or defaults.get('default_group'))
        # The defaults are copied: an instance must never hand out the class's own dicts to be changed
        self.server_config: dict[str, Any] = server_config or deepcopy(defaults.get('server_config'))
        self.connection_config: dict[str, Any] = connection_config or deepcopy(defaults.get('connection_config'))
        self.search: dict[str, Any] = search or deepcopy(defaults.get('search'))
        self.groups: dict[str, Any] = self.validated_groups(groups) or deepcopy(defaults.get('groups'))

        super().__init__(active)


    @staticmethod
    def validated_groups(groups: Any) -> Any:
        """
        Checks the group-mapping settings far enough that the login reads their flag as stored

        The provider asks `groups.active` whether to map a user's directory groups at all, so the flag must be a
        real boolean - a stored ``"false"`` would switch the mapping on

        Args:
            groups (Any): The `groups` settings as stored or sent, None or empty when absent

        Raises:
            ProviderConfigError: When `groups` is present and not an object, or its flag is present and not a boolean

        Returns:
            Any: The settings as given
        """
        if not groups:
            return groups

        if not isinstance(groups, dict):
            raise ProviderConfigError(GROUPS_NOT_AN_OBJECT_MSG.format(kind=type(groups).__name__))

        validated_flag(groups.get(LdapGroupsKey.ACTIVE.value), False, GROUPS_ACTIVE_FLAG)

        return groups


    def mapping(self, group_dn: str) -> int:
        """
        Get the internal group ID mapped to a specific LDAP group distinguished name (DN)

        Args:
            group_dn (str): The distinguished name (DN) of the LDAP group

        Raises:
            GroupMappingError: If no mapping is found for the given group DN

        Returns:
            int: The corresponding internal group ID
        """
        try:
            return next(int(group['group_id']) for group in self.groups['mapping'] if
                        group['group_dn'].lower() == group_dn.lower())
        except StopIteration as err:
            raise GroupMappingError(err) from err
