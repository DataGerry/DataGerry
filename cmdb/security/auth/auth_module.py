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
Implementation of AuthModule
"""
from logging import Logger, getLogger
from typing import Type

from flask import current_app

from cmdb.manager import (
    UsersManager,
    SecurityManager,
)

from cmdb.models.user_model import CmdbUser
from cmdb.security.auth.base_authentication_provider import BaseAuthenticationProvider
from cmdb.models.security_models.auth_settings import CmdbAuthSettings
from cmdb.security.auth.providers.ldap_auth_provider import LdapAuthenticationProvider
from cmdb.security.auth.providers.local_auth_provider import LocalAuthenticationProvider
from cmdb.security.auth.base_provider_config import BaseAuthProviderConfig

from cmdb.errors.provider import (
    AuthenticationProviderNotActivated,
    AuthenticationProviderNotFoundError,
    AuthenticationError,
)
from cmdb.errors.manager import BaseManagerGetError, BaseManagerInsertError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                  AuthModule - CLASS                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
class AuthModule:
    """
    Implementation of AuthModule
    """

    __pre_installed_providers: list[BaseAuthenticationProvider] = [
        LocalAuthenticationProvider,
        LdapAuthenticationProvider
    ]

    __installed_providers: list[BaseAuthenticationProvider] = __pre_installed_providers

    __DEFAULT_SETTINGS__ = {
        '_id': 'auth',
        'enable_external': True,
        'token_lifetime': 1400,
        'providers': [
            {
                'class_name': provider.get_name(),
                'config': provider.PROVIDER_CONFIG_CLASS.DEFAULT_CONFIG_VALUES
            } for provider in __installed_providers
        ]
    }


    def __init__(self, settings: dict,
                 security_manager: SecurityManager = None,
                 users_manager: UsersManager = None):
        self.__settings: CmdbAuthSettings = self.__init_settings(settings)
        self.users_manager = users_manager
        self.__security_manager = security_manager


    @staticmethod
    def __init_settings(auth_settings_values: dict) -> CmdbAuthSettings:
        """
        Merge default values with database entries
        """
        provider_config_list: list[dict] = auth_settings_values.get('providers')
        installed_providers = AuthModule.get_installed_providers()

        for provider in installed_providers:
            if not any(p['class_name'] == provider.get_name() for p in provider_config_list):
                auth_settings_values['providers'].append(provider.PROVIDER_CONFIG_CLASS.DEFAULT_CONFIG_VALUES)
            else:
                provider_index = next(
                    (i for i, item in enumerate(provider_config_list) if item['class_name'] == provider.get_name()), -1)
                try:
                    auth_settings_values['providers'][provider_index]['config'] = provider.PROVIDER_CONFIG_CLASS(
                        **auth_settings_values['providers'][provider_index]['config']).__dict__
                except Exception as err:
                    LOGGER.error(
                        'Error while parsing auth provider settings for: %s: %s\n Fallback to default values!',
                        provider.get_name(),err)

                    default_config_values = provider.PROVIDER_CONFIG_CLASS.DEFAULT_CONFIG_VALUES
                    auth_settings_values['providers'][provider_index]['config'] = default_config_values

        return CmdbAuthSettings(**auth_settings_values)


    @classmethod
    def register_provider(cls, provider: BaseAuthenticationProvider) -> BaseAuthenticationProvider:
        """
        Install a provider

        Notes:
            This only means that a provider is installed, not that the provider is used or activated!
        """
        cls.__installed_providers.append(provider)
        return provider


    @classmethod
    def unregister_provider(cls, provider: BaseAuthenticationProvider) -> bool:
        """
        Uninstall a provider
        """
        try:
            AuthModule.__installed_providers.remove(provider)
            return True
        except ValueError:
            return False


    @staticmethod
    def get_provider_class(provider_name: str) -> 'BaseAuthenticationProvider':
        """
        Get a specific provider class by class name
        """
        return next(_ for _ in AuthModule.__installed_providers if _.__qualname__ == provider_name)


    @staticmethod
    def provider_exists(provider_name: str) -> bool:
        """
        Check if provider exists

        Notes:
            Checks for installation not activation!
        """
        try:
            AuthModule.get_provider_class(provider_name=provider_name)
            return True
        except StopIteration:
            return False


    @classmethod
    def get_installed_providers(cls) -> list['BaseAuthenticationProvider']:
        """
        Get all installed providers as static list
        """
        return cls.__installed_providers


    @classmethod
    def get_installed_internals(cls) -> list['BaseAuthenticationProvider']:
        """
        Get all installed providers as static list
        """
        return cls.__installed_providers


    @classmethod
    def get_installed_external(cls) -> list['BaseAuthenticationProvider']:
        """
        Get all installed providers as static list
        """
        return cls.__installed_providers


    @property
    def providers(self) -> list['BaseAuthenticationProvider']:
        """
        Get all installed providers as property list
        """
        return AuthModule.__installed_providers


    @property
    def settings(self) -> CmdbAuthSettings:
        """
        Get the current auth settings
        """
        return self.__settings


    def get_provider(self, provider_name: str) -> BaseAuthenticationProvider:
        """
        Get a initialized provider instance
        """
        try:
            _provider_class_name: Type[str] = provider_name
            if not AuthModule.provider_exists(provider_name=_provider_class_name):
                return None
            _provider_class: Type[BaseAuthenticationProvider] = AuthModule.get_provider_class(_provider_class_name)
            _provider_config_class: Type[BaseAuthProviderConfig] = _provider_class.PROVIDER_CONFIG_CLASS
            _provider_config_values: dict = self.settings.get_provider_settings(_provider_class_name) \
                .get('config', _provider_config_class.DEFAULT_CONFIG_VALUES)
            _provider_config_instance = _provider_config_class(**_provider_config_values)
            _provider_instance = _provider_class(config=_provider_config_instance,
                                                 security_manager=self.__security_manager,
                                                 users_manager=self.users_manager)

            return _provider_instance
        except Exception as err:
            LOGGER.error('[AuthModule] %s', err)
            return None


    def login(self, user_name: str, password: str) -> CmdbUser:
        """
        Performs a login try with given username and password
        If the user is not found, iterate over all installed and activated providers
        Args:
            user_name: Name of the user
            password: Password

        Returns:
            CmdbUser: instance if user was found and password was correct
        """
        try:
            if current_app.cloud_mode:
                user = self.users_manager.get_user_by({'email': user_name})
            else:
                user_name = user_name.lower()
                user = self.users_manager.get_user_by({'user_name': user_name})

            provider_class_name = user.authenticator

            if not self.provider_exists(provider_class_name):
                raise AuthenticationProviderNotFoundError(f"Provider with name {provider_class_name} does not exist!")

            provider: Type[BaseAuthenticationProvider] = self.get_provider_class(provider_class_name)
            provider_config_class: Type[str] = provider.PROVIDER_CONFIG_CLASS
            provider_config_settings = self.settings.get_provider_settings(provider.get_name())

            provider_config_instance = provider_config_class(**provider_config_settings)

            provider_instance = provider(config=provider_config_instance,
                                         security_manager=self.__security_manager,
                                         users_manager=self.users_manager)

            if not provider_instance.is_active():
                raise AuthenticationProviderNotActivated(f'Provider {provider_class_name} is deactivated')

            if provider_instance.EXTERNAL_PROVIDER and not self.settings.enable_external:
                raise AuthenticationProviderNotActivated('External providers are deactivated')

            return provider_instance.authenticate(user_name, password)
        except Exception as err:
            # get installed providers
            provider_list = self.providers

            for provider in provider_list:

                provider_config_class = provider.PROVIDER_CONFIG_CLASS
                provider_settings = self.settings.get_provider_settings(provider.get_name())
                provider_config_instance = provider_config_class(**provider_settings)

                if not provider_config_instance.is_active():
                    continue
                if provider.EXTERNAL_PROVIDER and not self.settings.enable_external:
                    continue
                provider_instance = provider(config=provider_config_instance,
                                             security_manager=self.__security_manager,
                                             users_manager=self.users_manager)
                try:
                    return provider_instance.authenticate(user_name, password)
                except AuthenticationError:
                    continue
                except (BaseManagerGetError, BaseManagerInsertError) as error:
                    LOGGER.debug("User found by provider but could not be inserted or found %s",error)
                    continue

            raise AuthenticationError('Could not login.') from err
