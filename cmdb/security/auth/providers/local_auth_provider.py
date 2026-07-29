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
Implementation of LocalAuthenticationProvider

Authenticates against the CmdbUsers stored in this installation: the submitted password is hashed and
compared with the stored hash. Two properties of that hash decide what this provider can and cannot do
(see `SecurityManager.generate_hmac`):

    - it is keyed by the instance's symmetric AES key with ONE application-wide salt, deliberately with
      no per-user salt, and the scheme is frozen - changing it would invalidate every stored password
    - a CmdbUser without a stored password can therefore never authenticate here. That is what keeps
      users provisioned by an external provider (the LDAP one creates them without a password) out of the
      local login instead of letting an empty or absent hash decide

Every refusal is an `AuthenticationError`, because `AuthModule.login` treats exactly that as "this
provider says no" and moves on to the next configured provider. The caller never learns which refusal it
was: `auth_helper.local_login` maps them all to one 401, on purpose, so a failed login does not reveal
whether the user name exists.
"""
from logging import Logger, getLogger

from flask import current_app

from cmdb.security.auth.base_authentication_provider import BaseAuthenticationProvider
from cmdb.security.auth.providers.local_auth_config import LocalAuthenticationProviderConfig
from cmdb.models.user_model import CmdbUser

from cmdb.errors.manager.users_manager import UsersManagerGetError
from cmdb.errors.provider import AuthenticationError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# CmdbUser fields a login is looked up by: the user name on premise, the email in cloud mode (where the
# login form submits an email address)
USER_NAME_FIELD: str = 'user_name'
EMAIL_FIELD: str = 'email'

# -------------------------------------------------------------------------------------------------------------------- #
#                                          LocalAuthenticationProvider - CLASS                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class LocalAuthenticationProvider(BaseAuthenticationProvider):
    """
    Provides authentication services using a local username and password system.

    This provider is responsible for authenticating users based on their username (or email in cloud mode)
    and comparing the hashed password stored in the system with the provided password during login.

    The constructor is inherited unchanged from the base class: `config` defaults to this provider's own
    configuration, and `security_manager` / `users_manager` are injected by `AuthModule`

    Extends: BaseAuthenticationProvider
    """
    PROVIDER_CONFIG_CLASS = LocalAuthenticationProviderConfig

    def authenticate(self, user_name: str, password: str) -> CmdbUser:
        """
        Authenticates a user by verifying their username (or email in cloud mode) and password.

        This method checks if the provided username exists and if the password matches the stored password
        hash (HMAC). A user that does not exist and a user whose password does not match are reported the
        same way on purpose - the distinction stays in the log and never reaches the client.

        Args:
            user_name (str): The username (or email in cloud mode) of the user attempting to authenticate.
            password (str): The plain-text password provided by the user.

        Raises:
            AuthenticationError: If the provider was built without its collaborators, the user could not
                                 be read, no such user exists, or the password does not match the stored
                                 hash

        Returns:
            CmdbUser: The authenticated user object if the credentials are valid
        """
        self._require_collaborators()

        user = self._read_user(user_name)

        if not user:
            raise AuthenticationError(f"{LocalAuthenticationProvider.get_name()}: User not found!")

        if self.security_manager.generate_hmac(password) == user.password:
            return user

        raise AuthenticationError(f"{LocalAuthenticationProvider.get_name()}: Password did not matched with hmac!")


    def _require_collaborators(self) -> None:
        """
        Makes sure the managers this provider authenticates with were injected

        Both are optional in the constructor (the base class keeps them that way for providers that need
        neither), so a provider built without them would otherwise fail with an AttributeError deep in
        the login instead of saying what is missing

        Raises:
            AuthenticationError: If the users manager or the security manager is missing
        """
        if self.users_manager is None or self.security_manager is None:
            raise AuthenticationError(
                f"{LocalAuthenticationProvider.get_name()}: The provider was built without a users or "
                'security manager and can not authenticate!'
            )


    def _read_user(self, user_name: str) -> CmdbUser | None:
        """
        Reads the CmdbUser a login is for, by email in cloud mode and by user name on premise

        User names are stored exactly as they were created, so the submitted value is tried as given and
        only then - if nothing matched - as its lower-case form. `AuthModule.login` lower-cases the name
        before it reaches its primary provider but NOT in its fallback loop, so without that second try
        the same credentials would work through one path and fail through the other. The extra read only
        happens for a name that is not already lower-case and that matched nothing

        Args:
            user_name (str): The submitted user name, or the email address in cloud mode

        Raises:
            AuthenticationError: If the CmdbUser could not be read

        Returns:
            CmdbUser | None: The stored CmdbUser, or None when no user matches
        """
        if current_app.cloud_mode:
            return self._read_user_by({EMAIL_FIELD: user_name})

        user = self._read_user_by({USER_NAME_FIELD: user_name})

        if user or user_name == user_name.lower():
            return user

        return self._read_user_by({USER_NAME_FIELD: user_name.lower()})


    def _read_user_by(self, query: dict[str, str]) -> CmdbUser | None:
        """
        Runs one CmdbUser lookup and turns a read failure into an authentication refusal

        `UsersManagerGetError` covers both a database problem and a stored user document that cannot be
        built into a CmdbUser. Reporting it as an AuthenticationError keeps `AuthModule.login` free to try
        the remaining providers - the alternative, letting it escape, turns a single unreadable user
        document into a 500 for the whole login route

        Args:
            query (dict[str, str]): The CmdbUser filter to read by

        Raises:
            AuthenticationError: If the lookup failed

        Returns:
            CmdbUser | None: The matching CmdbUser, or None when nothing matched
        """
        try:
            return self.users_manager.get_user_by(query)
        except UsersManagerGetError as err:
            LOGGER.error('[_read_user_by] Could not read the CmdbUser to authenticate: %s', err)
            raise AuthenticationError(str(err)) from err


    def is_active(self) -> bool:
        """
        Checks if the local authentication provider is active

        Pinned to True by design: local login is the way back into an instance, so it must not be
        possible to switch off the only provider that never depends on an external system.

        NOTE the provider's configuration does carry an `active` flag, and `AuthModule.login` reads it in
        its fallback loop (where it filters on the CONFIG, not on the provider) - so a local provider
        configured inactive is skipped there while the primary path, which asks this method, still accepts
        it. Whether that flag should exist at all is open (discussion-backlog item)

        Returns:
            bool: Always returns True, indicating that the local authentication provider is active
        """
        return True
