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
Implementation of LdapAuthenticationProvider

Authenticates against an LDAP directory in the usual two steps: the configured service account binds and
searches for the login name, then the entry that was found is bound WITH THE SUBMITTED PASSWORD - that
bind is the actual proof of identity, the search only locates the DN.

The directory owns the credentials, DataGerry owns the CmdbUser: a user the directory accepts but this
installation does not know yet is PROVISIONED here (see `_provision_user`), and with group mapping
enabled the mapped group is re-applied on every login. Nothing about the password is ever stored.

Every refusal - a failed connection, no or several matching entries, credentials the directory rejects,
or a local CmdbUser that cannot be read or written - is reported as an `AuthenticationError`, because
`AuthModule.login` falls back to the other configured providers on exactly that error.

Two rules the provider enforces itself instead of trusting the directory:

    - the login name is escaped (`escape_filter_chars`) before it is substituted into a search filter, so
      a caller cannot rewrite the filter - which for the GROUP filter would mean choosing its own group
    - an empty password is refused up front. A simple bind with a DN and an empty password is an
      "unauthenticated bind" (RFC 4513 §5.1.2) that some directories accept, which would otherwise turn
      into a password-less login here
"""
from logging import Logger, getLogger
from datetime import datetime, timezone

from ldap3 import Server, Connection
from ldap3.core.exceptions import LDAPExceptionError
from ldap3.utils.conv import escape_filter_chars

from cmdb.manager import (
    UsersManager,
    SecurityManager,
)

from cmdb.models.user_model import CmdbUser
from cmdb.security.auth.base_authentication_provider import BaseAuthenticationProvider
from cmdb.security.auth.providers.ldap_auth_config import LdapAuthenticationProviderConfig
from cmdb.security.auth.providers.ldap_constants import (
    USERNAME_PLACEHOLDER,
    GROUP_DN_CN_PATTERN,
    LdapSearchKey,
    LdapGroupsKey,
    LdapGroupMappingKey,
    ProvisionedUserKey,
    LdapAuthMessage,
)

from cmdb.errors.provider import GroupMappingError, AuthenticationError
from cmdb.errors.manager.users_manager import (
    UsersManagerGetError,
    UsersManagerInsertError,
    UsersManagerUpdateError,
)
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
        EXTERNAL_PROVIDER (bool): Marks this as an external authentication source. `AuthModule` skips
                                  the provider entirely when external providers are disabled
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

        The server and the service-account connection are derived from `self.config`, which the base
        class fills with the provider defaults when no config is passed - so the documented
        `config=None` really works instead of raising

        Args:
            config (LdapAuthenticationProviderConfig, optional): The LDAP provider configuration
            security_manager (SecurityManager, optional): The security manager instance
            users_manager (UsersManager, optional): The users manager instance
        """
        super().__init__(config,
                         security_manager=security_manager,
                         users_manager=users_manager)

        self.__ldap_server = Server(**self.config.server_config)
        self.__ldap_connection = Connection(self.__ldap_server, **self.config.connection_config)


    def __enter__(self) -> "LdapAuthenticationProvider":
        """
        Enters a context that guarantees the service-account connection is released

        Returns:
            LdapAuthenticationProvider: This provider
        """
        return self


    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """
        Close the LDAP connection when exiting the context

        Args:
            exc_type (Type[BaseException]): Exception type
            exc_val (BaseException): Exception value
            exc_tb (TracebackType): Traceback object
        """
        self.disconnect()


    def connect(self) -> bool:
        """
        Attempt to bind (connect) to the LDAP server with the configured service account

        Returns:
            bool: True if the connection is successful, False otherwise
        """
        return self.__ldap_connection.bind()


    def disconnect(self) -> None:
        """
        Releases the service-account connection

        `authenticate` calls this on every path, successful or not: the connection is bound per login
        attempt, and leaving it open would leak a socket and a directory connection each time. A failure
        while unbinding is logged and swallowed - the login outcome is already decided by then
        """
        try:
            self.__ldap_connection.unbind()
        except LDAPExceptionError as err:
            LOGGER.debug("[disconnect] Could not unbind the LDAP connection: %s", err)


    def is_active(self) -> bool:
        """
        Check if the LDAP authentication provider is active

        Returns:
            bool: True if the provider is active, False otherwise
        """
        return self.config.active


    def authenticate(self, user_name: str, password: str) -> CmdbUser:
        """
        Authenticate a user against the LDAP server using username and password

        The steps, in order: refuse unusable credentials, bind the service account, locate exactly one
        entry for the login name, bind that entry with the submitted password (the actual authentication),
        resolve the mapped group, and finally hand back the local CmdbUser - provisioning it when the
        directory knows the user but this installation does not yet.

        The group is resolved only AFTER the password was accepted, so an unauthenticated caller never
        triggers a group search

        Args:
            user_name (str): The username to authenticate
            password (str): The password for the user

        Raises:
            AuthenticationError: If authentication fails at any point

        Returns:
            CmdbUser: The authenticated CMDB user object
        """
        if not user_name or not user_name.strip():
            raise AuthenticationError(LdapAuthMessage.MISSING_USER_NAME.value)

        # An empty password would be sent as an unauthenticated simple bind, which some directories
        # accept - that must never pass for an authenticated login
        if not password or not password.strip():
            raise AuthenticationError(LdapAuthMessage.MISSING_PASSWORD.value)

        self._bind_service_account()

        try:
            entry_dn = self._find_user_dn(user_name)
            self._verify_credentials(entry_dn, password)
            user_group_id = self._resolve_group_id(user_name)
        finally:
            self.disconnect()

        return self._sync_local_user(user_name, user_group_id)


    def _bind_service_account(self) -> None:
        """
        Binds the configured service account, which every search runs through

        Raises:
            AuthenticationError: If the bind raised, or simply did not succeed
        """
        try:
            connected = self.connect()
        except LDAPExceptionError as err:
            raise AuthenticationError(LdapAuthMessage.CONNECTION_FAILED.format(detail=err)) from err

        if not connected:
            raise AuthenticationError(LdapAuthMessage.NOT_CONNECTED.value)


    def _find_user_dn(self, user_name: str) -> str:
        """
        Searches the directory for the login name and returns the DN of the single matching entry

        Several matches are refused rather than resolved: the DN found here is the identity the password
        is then checked against, so guessing which of them was meant would decide who the caller becomes

        Args:
            user_name (str): The submitted login name

        Raises:
            AuthenticationError: If the search matched no entry, or more than one

        Returns:
            str: The distinguished name of the matching entry
        """
        search_filter = self._build_filter(self.config.search[LdapSearchKey.SEARCH_FILTER.value], user_name)
        found = self.__ldap_connection.search(self.config.search[LdapSearchKey.BASE_DN.value], search_filter)
        entries = self.__ldap_connection.entries or []

        if not found or len(entries) == 0:
            raise AuthenticationError(
                LdapAuthMessage.NO_MATCHING_ENTRY.format(provider=LdapAuthenticationProvider.get_name())
            )

        if len(entries) > 1:
            raise AuthenticationError(
                LdapAuthMessage.AMBIGUOUS_ENTRY.format(
                    provider=LdapAuthenticationProvider.get_name(), count=len(entries),
                )
            )

        return entries[0].entry_dn


    def _verify_credentials(self, entry_dn: str, password: str) -> None:
        """
        Binds the found entry with the submitted password - the actual authentication step

        The connection opened for the check is released immediately; it exists only to let the directory
        judge the password

        Args:
            entry_dn (str): The distinguished name the password belongs to
            password (str): The submitted password

        Raises:
            AuthenticationError: If the directory refuses the credentials
        """
        user_connection = None

        try:
            user_connection = Connection(self.__ldap_server, entry_dn, password, auto_bind=True)
        except Exception as err:
            raise AuthenticationError(
                LdapAuthMessage.INVALID_CREDENTIALS.format(
                    provider=LdapAuthenticationProvider.get_name(), detail=err,
                )
            ) from err
        finally:
            if user_connection is not None:
                try:
                    user_connection.unbind()
                except LDAPExceptionError as err:
                    LOGGER.debug("[_verify_credentials] Could not unbind the user connection: %s", err)


    def _resolve_group_id(self, user_name: str) -> int:
        """
        Determines which DataGerry group the user belongs to

        With group mapping switched off, or when the group search finds nothing, the configured default
        group is used - a login is never refused because of group mapping

        Args:
            user_name (str): The submitted login name

        Returns:
            int: The group_id to apply to the CmdbUser
        """
        if not self.config.groups.get(LdapGroupsKey.ACTIVE.value, False):
            return self.config.default_group

        search_filter = self._build_filter(self.config.groups[LdapGroupsKey.SEARCH_FILTER.value], user_name)
        found = self.__ldap_connection.search(self.config.search[LdapSearchKey.BASE_DN.value], search_filter)
        entries = self.__ldap_connection.entries or []

        if not found or len(entries) == 0:
            return self.config.default_group

        return self._map_group([entry.entry_dn for entry in entries])


    def _map_group(self, group_dns: list[str]) -> int:
        """
        Maps the user's LDAP groups onto a DataGerry group_id, first match wins

        A configured mapping matches a group either by its FULL DN - what the settings UI asks for - or by
        the bare CN of its first RDN, which is what the provider used to compare against. Both are
        accepted so an installation configured either way keeps working. A mapping entry that cannot be
        resolved to a usable group_id is skipped rather than failing the login

        Args:
            group_dns (list[str]): The distinguished names of the groups the user belongs to

        Returns:
            int: The mapped group_id, or the configured default group when nothing matched
        """
        mappings = self.config.groups.get(LdapGroupsKey.MAPPING.value) or []

        if not mappings or not group_dns:
            return self.config.default_group

        candidates = {dn.lower() for dn in group_dns}
        candidates.update(self._extract_group_cns(group_dns))

        for mapping in mappings:
            configured_dn = mapping.get(LdapGroupMappingKey.GROUP_DN.value)

            if not configured_dn or configured_dn.lower() not in candidates:
                continue

            try:
                return self.config.mapping(configured_dn)
            except (GroupMappingError, TypeError, ValueError) as err:
                # An entry without a resolvable group_id (unmapped, or one that is not a number) is a
                # configuration mistake - it must not decide whether the user may log in
                LOGGER.warning("[_map_group] Skipping unusable group mapping '%s': %s", configured_dn, err)
                continue

        return self.config.default_group


    @staticmethod
    def _extract_group_cns(group_dns: list[str]) -> set[str]:
        """
        Reads the first RDN value out of every group DN, lower-cased

        A DN the pattern does not fit (no `=` or no `,`) is skipped instead of raising: a directory that
        returns an unusual DN must not make the login fail with an AttributeError

        Args:
            group_dns (list[str]): The distinguished names of the groups the user belongs to

        Returns:
            set[str]: The extracted CN values
        """
        extracted: set[str] = set()

        for group_dn in group_dns:
            match = GROUP_DN_CN_PATTERN.search(group_dn)

            if match:
                extracted.add(match.group(1).lower())

        return extracted


    @staticmethod
    def _build_filter(configured_filter: str, user_name: str) -> str:
        """
        Substitutes the login name into a configured search filter, escaped

        `escape_filter_chars` is what stops the name - which comes straight from the login request - from
        rewriting the filter it is placed into

        Args:
            configured_filter (str): The filter as configured, carrying the `%username%` placeholder
            user_name (str): The submitted login name

        Returns:
            str: The filter to send to the directory
        """
        return configured_filter.replace(USERNAME_PLACEHOLDER, escape_filter_chars(user_name))


    def _sync_local_user(self, user_name: str, user_group_id: int) -> CmdbUser:
        """
        Returns the local CmdbUser of the authenticated directory user, creating it when it is new

        Args:
            user_name (str): The authenticated login name
            user_group_id (int): The group the directory says the user belongs to

        Raises:
            AuthenticationError: If the CmdbUser could not be read, written or created

        Returns:
            CmdbUser: The stored CmdbUser
        """
        try:
            stored_user: CmdbUser | None = self.users_manager.get_user_by({ProvisionedUserKey.USER_NAME.value:
                                                                           user_name})
        except UsersManagerGetError as err:
            raise AuthenticationError(LdapAuthMessage.USER_READ_FAILED.format(detail=err)) from err

        if not stored_user:
            LOGGER.debug('[authenticate] CmdbUser %s exists on LDAP but not in the database', user_name)

            return self._provision_user(user_name, user_group_id)

        if self.config.groups.get(LdapGroupsKey.ACTIVE.value, False) and stored_user.group_id != user_group_id:
            return self._apply_mapped_group(stored_user, user_group_id)

        return stored_user


    def _apply_mapped_group(self, stored_user: CmdbUser, user_group_id: int) -> CmdbUser:
        """
        Moves the stored CmdbUser into the group the directory mapped it to

        The updated instance is returned as it was written, so the caller does not pay for a second read

        Args:
            stored_user (CmdbUser): The stored CmdbUser, whose group is outdated
            user_group_id (int): The mapped group_id to apply

        Raises:
            AuthenticationError: If the update failed. It is NOT treated as "this user does not exist
                                 here" - that would send the login on to provision a duplicate

        Returns:
            CmdbUser: The CmdbUser with the mapped group
        """
        stored_user.group_id = user_group_id

        try:
            self.users_manager.update_user(stored_user.public_id, stored_user)
        except UsersManagerUpdateError as err:
            # NOT reported as "unknown user": that is what used to send a failed group update on to
            # provision a second CmdbUser for a user that already exists
            raise AuthenticationError(LdapAuthMessage.GROUP_UPDATE_FAILED.format(detail=err)) from err

        return stored_user


    def _provision_user(self, user_name: str, user_group_id: int) -> CmdbUser:
        """
        Creates the local CmdbUser for a directory user this installation does not know yet

        The directory stays the authority for the credentials, so the new CmdbUser carries no password -
        it can only ever be authenticated through this provider

        Args:
            user_name (str): The authenticated login name
            user_group_id (int): The group the directory says the user belongs to

        Raises:
            AuthenticationError: If the CmdbUser could not be created or not be read back

        Returns:
            CmdbUser: The created CmdbUser
        """
        new_user_data = {
            ProvisionedUserKey.USER_NAME.value: user_name,
            ProvisionedUserKey.ACTIVE.value: True,
            ProvisionedUserKey.GROUP_ID.value: int(user_group_id),
            ProvisionedUserKey.REGISTRATION_TIME.value: datetime.now(timezone.utc),
            ProvisionedUserKey.AUTHENTICATOR.value: LdapAuthenticationProvider.get_name(),
        }

        try:
            user_id = self.users_manager.insert_user(new_user_data)
        except UsersManagerInsertError as err:
            LOGGER.error('[_provision_user] Could not create the CmdbUser: %s', err)
            raise AuthenticationError(LdapAuthMessage.USER_CREATION_FAILED.format(detail=err)) from err

        try:
            created_user: CmdbUser | None = self.users_manager.get_user(user_id)
        except UsersManagerGetError as err:
            LOGGER.error('[_provision_user] Could not read the created CmdbUser: %s', err)
            raise AuthenticationError(LdapAuthMessage.USER_READ_FAILED.format(detail=err)) from err

        if not created_user:
            raise AuthenticationError(LdapAuthMessage.CREATED_USER_UNREADABLE.value)

        return created_user
