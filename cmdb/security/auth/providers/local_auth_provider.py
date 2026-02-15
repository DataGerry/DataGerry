# DATAGERRY - OpenSource Enterprise CMDB
# Copyright (C) 2025 becon GmbH
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
"""
import logging
from flask import current_app

from cmdb.manager import (
    UsersManager,
    SecurityManager,
)

from cmdb.security.auth.base_authentication_provider import BaseAuthenticationProvider
from cmdb.security.auth.providers.local_auth_config import LocalAuthenticationProviderConfig
from cmdb.models.user_model import CmdbUser

from cmdb.errors.manager import BaseManagerGetError
from cmdb.errors.provider import AuthenticationError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER = logging.getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                          LocalAuthenticationProvider - CLASS                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class LocalAuthenticationProvider(BaseAuthenticationProvider):
    """
    Provides authentication services using a local username and password system.

    This provider is responsible for authenticating users based on their username (or email in cloud mode)
    and comparing the hashed password stored in the system with the provided password during login.

    Extends: BaseAuthenticationProvider
    """
    PROVIDER_CONFIG_CLASS = LocalAuthenticationProviderConfig

    def __init__(
            self,
            config: LocalAuthenticationProviderConfig = None,
            security_manager: SecurityManager = None,
            users_manager: UsersManager = None):
        """
        Initializes the LocalAuthenticationProvider

        Args:
            config (LocalAuthenticationProviderConfig, optional): The configuration for the authentication provider
            security_manager (SecurityManager, optional): The security manager used for password hashing and
                                                          HMAC generation
            users_manager (UsersManager, optional): The manager responsible for user data retrieval and management
        """
        super().__init__(config=config,
                         security_manager=security_manager,
                         users_manager=users_manager)


    def authenticate(self, user_name: str, password: str) -> CmdbUser:
        """
        Authenticates a user by verifying their username (or email in cloud mode) and password.

        This method checks if the provided username exists and if the password matches the stored password hash (HMAC).

        Args:
            user_name (str): The username (or email in cloud mode) of the user attempting to authenticate.
            password (str): The plain-text password provided by the user.

        Raises:
            AuthenticationError: If the user is not found or the password does not match the stored hash

        Returns:
            CmdbUser: The authenticated user object if the credentials are valid
        """
        try:
            if current_app.cloud_mode:
                user = self.users_manager.get_user_by({'email': user_name})
            else:
                user = self.users_manager.get_user_by({'user_name': user_name})

            if not user:
                raise AuthenticationError("User not found!")
        except BaseManagerGetError as err:
            raise AuthenticationError(str(err)) from err

        login_pass = self.security_manager.generate_hmac(password)

        if login_pass == user.password:
            return user

        raise AuthenticationError(f"{LocalAuthenticationProvider.get_name()}: Password did not matched with hmac!")


    def is_active(self) -> bool:
        """
        Checks if the local authentication provider is active

        Since this provider always supports local authentication, it will always return True

        Returns:
            bool: Always returns True, indicating that the local authentication provider is active
        """
        return True
