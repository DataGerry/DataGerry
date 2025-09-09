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
Implementation of BaseAuthenticationProvider
"""
import logging

from cmdb.manager import (
    UsersManager,
    SecurityManager,
)

from cmdb.security.auth.base_provider_config import BaseAuthProviderConfig
from cmdb.models.user_model import CmdbUser
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER = logging.getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                          BaseAuthenticationProvider - CLASS                                          #
# -------------------------------------------------------------------------------------------------------------------- #
class BaseAuthenticationProvider:
    """
    Base class for authentication providers

    This is the super class for all authentication providers. It defines common attributes and methods
    that can be used or overridden by subclasses to implement specific authentication mechanisms. 

    Attributes:
        PASSWORD_ABLE (bool): Flag indicating if the provider supports password-based authentication
        EXTERNAL_PROVIDER (bool): Flag indicating if the provider is an external authentication provider
        PROVIDER_CONFIG_CLASS (type): The configuration class used by the authentication provider
    """
    PASSWORD_ABLE: bool = True
    EXTERNAL_PROVIDER: bool = False
    PROVIDER_CONFIG_CLASS: 'BaseAuthProviderConfig' = BaseAuthProviderConfig

    def __init__(
        self,
        config: BaseAuthProviderConfig | None = None,
        security_manager: SecurityManager | None = None,
        users_manager: UsersManager | None = None
    ) -> None:
        """
        Initializes the base authentication provider

        Args:
            config (BaseAuthProviderConfig, optional): The configuration object for the provider.
                                                       If not provided, the default configuration is used.
            security_manager (SecurityManager, optional): The security manager used for password hashing
                                                          and HMAC generation.
            users_manager (UsersManager, optional): The users manager used to retrieve and manage users
        """
        self.users_manager = users_manager
        self.security_manager = security_manager
        self.config = config or self.PROVIDER_CONFIG_CLASS(**self.PROVIDER_CONFIG_CLASS.DEFAULT_CONFIG_VALUES)


    def authenticate(self, user_name: str, password: str) -> CmdbUser:
        """
        Authenticates a user using the provided username and password.

        This method must be implemented by subclasses as the authentication mechanism can vary 
        depending on the provider.

        Args:
            user_name (str): The username of the user attempting to authenticate
            password (str): The password provided by the user for authentication

        Returns:
            CmdbUser: The authenticated user object

        Raises:
            NotImplementedError: If this method is not overridden by a subclass
        """
        raise NotImplementedError


    def get_config(self) -> BaseAuthProviderConfig:
        """
        Returns the configuration object for the authentication provider

        Returns:
            BaseAuthProviderConfig: The configuration object associated with this provider
        """
        return self.config


    @classmethod
    def is_password_able(cls):
        """
        Checks if the authentication provider supports password-based authentication

        Returns:
            bool: Returns `True` if the provider supports password authentication, otherwise `False`
        """
        return cls.PASSWORD_ABLE


    @classmethod
    def get_name(cls):
        """
        Returns the name of the authentication provider class

        This can be used to identify the provider class in logs, error messages, etc

        Returns:
            str: The fully qualified name of the provider class
        """
        return cls.__qualname__
