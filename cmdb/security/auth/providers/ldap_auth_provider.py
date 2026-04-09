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
Implementation of LdapAuthenticationProvider
"""
from logging import Logger, getLogger
import re
from datetime import datetime, timezone

from ldap3 import Server, Connection
from ldap3.core.exceptions import LDAPExceptionError

from cmdb.manager import (
    UsersManager,
    SecurityManager,
)

from cmdb.models.user_model import CmdbUser
from cmdb.security.auth.base_authentication_provider import BaseAuthenticationProvider
from cmdb.security.auth.providers.ldap_auth_config import LdapAuthenticationProviderConfig

from cmdb.errors.provider import GroupMappingError, AuthenticationError
from cmdb.errors.manager import BaseManagerUpdateError
from cmdb.errors.manager.users_manager import UsersManagerGetError, UsersManagerInsertError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                          LdapAuthenticationProvider - CLASS                                          #
# -------------------------------------------------------------------------------------------------------------------- #
class LdapAuthenticationProvider(BaseAuthenticationProvider):
    """
    LDAP authentication provider that integrates with an LDAP server to authenticate users
    and manage their user group mappings

    Extends: BaseAuthenticationProvider

    Attributes:
        PASSWORD_ABLE (bool): Flag indicating if the provider supports password-based authentication
        EXTERNAL_PROVIDER (bool): Flag indicating if the provider is an external authentication source
        PROVIDER_CONFIG_CLASS: The associated configuration class for this provider
    """
    PASSWORD_ABLE: bool = False
    EXTERNAL_PROVIDER: bool = True
    PROVIDER_CONFIG_CLASS = LdapAuthenticationProviderConfig

    def __init__(self,
                 config: LdapAuthenticationProviderConfig = None,
                 security_manager: SecurityManager = None,
                 users_manager: UsersManager = None):
        """
        Initialize the LDAP authentication provider.

        Args:
            config (LdapAuthenticationProviderConfig, optional): The LDAP provider configuration
            security_manager (SecurityManager, optional): The security manager instance
            users_manager (UsersManager, optional): The users manager instance
        """
        self.__ldap_server = Server(**config.server_config)
        self.__ldap_connection = Connection(self.__ldap_server, **config.connection_config)
        super().__init__(config,
                         security_manager=security_manager,
                         users_manager=users_manager)


    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """
        Close the LDAP connection when exiting the context

        Args:
            exc_type (Type[BaseException]): Exception type
            exc_val (BaseException): Exception value
            exc_tb (TracebackType): Traceback object
        """
        if self.__ldap_connection:
            self.__ldap_connection.unbind()


    def connect(self) -> bool:
        """
        Attempt to bind (connect) to the LDAP server

        Returns:
            bool: True if the connection is successful, False otherwise
        """
        return self.__ldap_connection.bind()


    def __map_group(self, possible_user_groups: list[str]) -> int:
        """
        Determine the user's group based on LDAP group memberships

        Args:
            possible_user_groups (list[str]): List of LDAP group names the user belongs to

        Returns:
            int: The internal group ID mapped from the user's LDAP groups
        """
        user_group = self.config.default_group
        if not self.config.groups['mapping'] or len(self.config.groups['mapping']) == 0 or\
           len(possible_user_groups) == 0:
            return user_group

        mappings = self.config.groups['mapping']
        for mapping in mappings:
            if mapping['group_dn'] in possible_user_groups:

                try:
                    user_group = self.config.mapping(mapping['group_dn'])
                    break
                except GroupMappingError:
                    continue
        return user_group


    def authenticate(self, user_name: str, password: str) -> CmdbUser:
        """
        Authenticate a user against the LDAP server using username and password

        Args:
            user_name (str): The username to authenticate
            password (str): The password for the user

        Raises:
            AuthenticationError: If authentication fails at any point

        Returns:
            CmdbUser: The authenticated CMDB user object
        """
        #TODO: REFACTOR-FIX
        try:
            ldap_connection_status = self.connect()
            if not ldap_connection_status:
                raise AuthenticationError('Could not connection to ldap server.')
        except LDAPExceptionError as err:
            raise AuthenticationError(err) from err

        user_search_filter = self.config.search['searchfilter'].replace("%username%", user_name)
        user_search_result = self.__ldap_connection.search(self.config.search['basedn'], user_search_filter)
        user_search_result_entries = self.__ldap_connection.entries

        if not user_search_result or len(user_search_result_entries) == 0:
            raise AuthenticationError(f"{LdapAuthenticationProvider.get_name()}: No matching entry!")

        user_group_id = self.config.default_group
        group_mapping_active = self.config.groups.get('active', False)

        if group_mapping_active:
            group_search_filter = self.config.groups['searchfiltergroup'].replace("%username%", user_name)
            group_search_result = self.__ldap_connection.search(self.config.search['basedn'], group_search_filter)
            group_search_result_entries = self.__ldap_connection.entries
            if not group_search_result or len(group_search_result_entries) == 0:
                user_group_id = self.config.default_group
            else:
                group_dns: list = [entry.entry_dn for entry in
                                   self.__ldap_connection.entries]
                possible_user_groups = [re.search('.*?=(.*?),.*', group_name).group(1) for group_name in group_dns]
                user_group_id = self.__map_group(possible_user_groups)

        for entry in user_search_result_entries:
            entry_dn = entry.entry_dn

            try:
                Connection(self.__ldap_server, entry_dn, password, auto_bind=True)
            except Exception as err:
                raise AuthenticationError(err) from err

        try:
            user_instance: CmdbUser = self.users_manager.get_user_by({'user_name': user_name})

            if (user_instance.group_id != user_group_id) and group_mapping_active:
                user_instance.group_id = user_group_id

                try:
                    self.users_manager.update_user(user_instance.public_id, user_instance)
                    user_instance: CmdbUser = self.users_manager.get_user_by({'user_name': user_name})
                except BaseManagerUpdateError as err:
                    raise AuthenticationError(err) from err
        except Exception as err:
            #TODO: ERROR-FIX
            LOGGER.warning('[authenticate] CmdbUser exists on LDAP but not in database: %s', err)
            LOGGER.debug('[authenticate] Try creating user: %s', user_name)
            try:
                new_user_data = {}
                new_user_data['user_name'] = user_name
                new_user_data['active'] = True
                new_user_data['group_id'] = int(user_group_id)
                new_user_data['registration_time'] = datetime.now(timezone.utc)
                new_user_data['authenticator'] = LdapAuthenticationProvider.get_name()
            except Exception as error:
                #TODO: ERROR-FIX
                LOGGER.error("[authenticate] Exception: %s. Type: %s",error, type(err), exc_info=True)
                raise AuthenticationError(error) from error
            LOGGER.debug('[authenticate] New user was init')

            try:
                user_id = self.users_manager.insert_user(new_user_data)
            except UsersManagerInsertError as error:
                LOGGER.error('[authenticate] UsersManagerInsertError: %s', error)
                raise AuthenticationError(error) from error

            try:
                user_instance = self.users_manager.get_user(user_id)

                if not user_instance:
                    raise AuthenticationError("Invalid user!") from err
            except UsersManagerGetError as error:
                LOGGER.error("[authenticate] UsersManagerGetError: %s",error)
                raise AuthenticationError(error) from error

        return user_instance


    def is_active(self) -> bool:
        """
        Check if the LDAP authentication provider is active

        Returns:
            bool: True if the provider is active, False otherwise
        """
        return self.config.active
