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
Shared constants for the LDAP authentication provider

Names the keys of the stored provider settings (which are a free-form dict, so every read is a literal
otherwise), the placeholder the configured search filters carry, the group-DN parsing and the messages
the provider reports. Both the provider and its config class read them
"""
import re

from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'USERNAME_PLACEHOLDER',
    'GROUP_DN_CN_PATTERN',
    'LdapSearchKey',
    'LdapGroupsKey',
    'LdapGroupMappingKey',
    'ProvisionedUserKey',
    'LdapAuthMessage',
]

# Token the configured search filters carry where the login name belongs. The name is ALWAYS escaped
# (ldap3's escape_filter_chars) before it is substituted - it comes straight from the login request, and
# an unescaped value would let the caller rewrite the filter it is interpolated into
USERNAME_PLACEHOLDER: str = '%username%'

# Reads the first RDN value out of a group DN ('cn=admins,ou=groups,dc=example,dc=com' -> 'admins'), used
# as the fallback when a group mapping is configured with the bare CN instead of the full DN
GROUP_DN_CN_PATTERN: re.Pattern = re.compile(r'.*?=(.*?),.*')


class LdapSearchKey(BaseStrEnum):
    """Keys of the provider's ``search`` settings"""
    BASE_DN = 'basedn'
    SEARCH_FILTER = 'searchfilter'


class LdapGroupsKey(BaseStrEnum):
    """Keys of the provider's ``groups`` settings"""
    ACTIVE = 'active'
    SEARCH_FILTER = 'searchfiltergroup'
    MAPPING = 'mapping'


class LdapGroupMappingKey(BaseStrEnum):
    """Keys of a single entry of the ``groups.mapping`` list"""
    GROUP_DN = 'group_dn'
    GROUP_ID = 'group_id'


class ProvisionedUserKey(BaseStrEnum):
    """
    CmdbUser document fields the provider stamps when it provisions a user it found in the directory

    Only these are written: the directory owns the credentials, so the created user carries no password,
    and everything else (email, names, image) is left to be filled in locally
    """
    USER_NAME = 'user_name'
    ACTIVE = 'active'
    GROUP_ID = 'group_id'
    REGISTRATION_TIME = 'registration_time'
    AUTHENTICATOR = 'authenticator'


class LdapAuthMessage(BaseStrEnum):
    """
    Reasons the provider refuses a login

    Every one of them is reported as an ``AuthenticationError``. Members with a `{...}` placeholder are
    filled via `format()`
    """
    MISSING_USER_NAME = 'No user name was provided!'
    MISSING_PASSWORD = 'No password was provided - an LDAP login requires one!'
    CONNECTION_FAILED = 'Could not connect to the LDAP server: {detail}'
    NOT_CONNECTED = 'Could not connect to the LDAP server!'
    NO_MATCHING_ENTRY = '{provider}: No matching entry!'
    AMBIGUOUS_ENTRY = '{provider}: The search filter matched {count} entries for one user name!'
    INVALID_CREDENTIALS = '{provider}: The LDAP server refused the credentials: {detail}'
    USER_READ_FAILED = 'Could not read the CmdbUser of the authenticated LDAP user: {detail}'
    GROUP_UPDATE_FAILED = 'Could not apply the mapped group to the CmdbUser: {detail}'
    USER_CREATION_FAILED = 'Could not create a CmdbUser for the authenticated LDAP user: {detail}'
    CREATED_USER_UNREADABLE = 'The CmdbUser created for the authenticated LDAP user could not be read!'
