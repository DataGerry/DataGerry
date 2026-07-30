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
Implementation of AuthModule - the authentication entry point

An AuthModule wraps two things: the process-wide registry of *installed* provider classes (installed
means available, not necessarily activated) and the ``auth`` settings section that configures them.

``login`` uses a primary attempt plus a fallback sweep: the stored CmdbUser names the provider that
should authenticate it, and if that attempt fails **for any reason** - unknown user, unknown or
deactivated provider, wrong credentials, a malformed settings section - every installed and activated
provider is tried in turn before the login is refused. That second pass exists so a user who does not
exist locally yet can still be provisioned by an external provider.

Provider settings live in the section as ``{'class_name': ..., 'config': {...}}`` entries; a provider
that the stored section does not list is topped up with its own defaults.
"""
from logging import Logger, getLogger

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

# Keys of one entry of the 'providers' list inside the 'auth' settings section
PROVIDER_CLASS_NAME_KEY: str = 'class_name'
PROVIDER_CONFIG_KEY: str = 'config'

# Key of the provider list itself
PROVIDERS_KEY: str = 'providers'

# -------------------------------------------------------------------------------------------------------------------- #
#                                                  AuthModule - CLASS                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
class AuthModule:
    """
    Registry of the installed authentication providers plus the parsed 'auth' settings

    The registry is class-level (shared by every instance and by the classmethods); the settings are
    per instance. See the module docstring for the login strategy
    """

    __pre_installed_providers: list[type[BaseAuthenticationProvider]] = [
        LocalAuthenticationProvider,
        LdapAuthenticationProvider
    ]

    # A copy on purpose: register_provider / unregister_provider must not mutate the shipped baseline
    __installed_providers: list[type[BaseAuthenticationProvider]] = list(__pre_installed_providers)

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
        Normalises the stored 'auth' section against the installed providers

        For every installed provider: an entry the section does not list yet is appended with the
        provider's default configuration, and an entry it does list has its config parsed through the
        provider's config class - so a stored config that no longer matches the class (renamed or
        removed keys) falls back to the defaults with the error logged instead of breaking the login

        Args:
            auth_settings_values (dict): The stored 'auth' settings section (mutated in place)

        Returns:
            CmdbAuthSettings: The normalised settings
        """
        provider_config_list: list[dict] = auth_settings_values.setdefault(PROVIDERS_KEY, [])

        for provider in AuthModule.get_installed_providers():
            provider_name: str = provider.get_name()
            default_config_values: dict = provider.PROVIDER_CONFIG_CLASS.DEFAULT_CONFIG_VALUES
            provider_index: int = next(
                (
                    index for index, entry in enumerate(provider_config_list)
                    if entry.get(PROVIDER_CLASS_NAME_KEY) == provider_name
                ),
                -1,
            )

            if provider_index == -1:
                # A full entry, not the bare config values: every consumer reads 'class_name' / 'config'
                provider_config_list.append({
                    PROVIDER_CLASS_NAME_KEY: provider_name,
                    PROVIDER_CONFIG_KEY: default_config_values,
                })
                continue

            try:
                stored_config: dict = provider_config_list[provider_index][PROVIDER_CONFIG_KEY]
                provider_config_list[provider_index][PROVIDER_CONFIG_KEY] = provider.PROVIDER_CONFIG_CLASS(
                    **stored_config
                ).__dict__
            except Exception as err:
                LOGGER.error(
                    'Error while parsing auth provider settings for: %s: %s\n Fallback to default values!',
                    provider_name, err)

                provider_config_list[provider_index][PROVIDER_CONFIG_KEY] = default_config_values

        return CmdbAuthSettings(**auth_settings_values)


    @classmethod
    def register_provider(cls, provider: type[BaseAuthenticationProvider]) -> type[BaseAuthenticationProvider]:
        """
        Installs a provider class, ignoring a provider that is already installed

        Notes:
            This only means that a provider is installed, not that the provider is used or activated!

        Args:
            provider (type[BaseAuthenticationProvider]): The provider class to install

        Returns:
            type[BaseAuthenticationProvider]: The same provider class, so this can be used as a decorator
        """
        if provider not in cls.__installed_providers:
            cls.__installed_providers.append(provider)

        return provider


    @classmethod
    def unregister_provider(cls, provider: type[BaseAuthenticationProvider]) -> bool:
        """
        Uninstalls a provider class

        Args:
            provider (type[BaseAuthenticationProvider]): The provider class to remove

        Returns:
            bool: True when the provider was installed and got removed, False when it was not installed
        """
        try:
            cls.__installed_providers.remove(provider)
            return True
        except ValueError:
            return False


    @staticmethod
    def get_provider_class(provider_name: str) -> type[BaseAuthenticationProvider]:
        """
        Retrieves an installed provider class by its class name

        Args:
            provider_name (str): Class name of the provider (see BaseAuthenticationProvider.get_name)

        Raises:
            StopIteration: If no installed provider carries that class name (use provider_exists first)

        Returns:
            type[BaseAuthenticationProvider]: The installed provider class
        """
        return next(
            provider for provider in AuthModule.__installed_providers if provider.__qualname__ == provider_name
        )


    @staticmethod
    def provider_exists(provider_name: str) -> bool:
        """
        Reports whether a provider of that class name is installed

        Notes:
            Checks for installation not activation!

        Args:
            provider_name (str): Class name of the provider

        Returns:
            bool: True when the provider is installed
        """
        try:
            AuthModule.get_provider_class(provider_name=provider_name)
            return True
        except StopIteration:
            return False


    @classmethod
    def get_installed_providers(cls) -> list[type[BaseAuthenticationProvider]]:
        """
        Retrieves every installed provider class

        Returns:
            list[type[BaseAuthenticationProvider]]: The installed providers, internal and external
        """
        return cls.__installed_providers


    @classmethod
    def get_installed_internals(cls) -> list[type[BaseAuthenticationProvider]]:
        """
        Retrieves the installed providers that authenticate against DataGerry itself

        Returns:
            list[type[BaseAuthenticationProvider]]: The installed providers with EXTERNAL_PROVIDER False
        """
        return [provider for provider in cls.__installed_providers if not provider.EXTERNAL_PROVIDER]


    @classmethod
    def get_installed_external(cls) -> list[type[BaseAuthenticationProvider]]:
        """
        Retrieves the installed providers that authenticate against an external system

        Returns:
            list[type[BaseAuthenticationProvider]]: The installed providers with EXTERNAL_PROVIDER True
        """
        return [provider for provider in cls.__installed_providers if provider.EXTERNAL_PROVIDER]


    @property
    def providers(self) -> list[type[BaseAuthenticationProvider]]:
        """
        Retrieves every installed provider class

        Returns:
            list[type[BaseAuthenticationProvider]]: The installed providers, internal and external
        """
        return AuthModule.__installed_providers


    @property
    def settings(self) -> CmdbAuthSettings:
        """
        Retrieves the normalised 'auth' settings of this instance

        Returns:
            CmdbAuthSettings: The settings the providers are configured from
        """
        return self.__settings


    def get_provider_config_values(self, provider: type[BaseAuthenticationProvider]) -> dict:
        """
        Retrieves the stored configuration values of a provider, falling back to its defaults

        ``CmdbAuthSettings.get_provider_settings`` already returns the entry's ``config`` sub-document,
        so the result is handed straight to the provider's config class

        Args:
            provider (type[BaseAuthenticationProvider]): The provider whose configuration is read

        Returns:
            dict: The stored config values, or the provider's DEFAULT_CONFIG_VALUES when the settings
                section carries no entry for it
        """
        try:
            return self.settings.get_provider_settings(provider.get_name())
        except StopIteration:
            LOGGER.warning(
                '[AuthModule] No settings entry for provider %s - using its default configuration',
                provider.get_name(),
            )

            return provider.PROVIDER_CONFIG_CLASS.DEFAULT_CONFIG_VALUES


    def build_provider_config(self, provider: type[BaseAuthenticationProvider]) -> BaseAuthProviderConfig:
        """
        Builds a provider's configuration instance from the stored (or default) values

        Args:
            provider (type[BaseAuthenticationProvider]): The provider to configure

        Returns:
            BaseAuthProviderConfig: The provider's config instance
        """
        return provider.PROVIDER_CONFIG_CLASS(**self.get_provider_config_values(provider))


    def build_provider_instance(
        self,
        provider: type[BaseAuthenticationProvider],
        config: BaseAuthProviderConfig | None = None,
    ) -> BaseAuthenticationProvider:
        """
        Builds a ready-to-use provider instance wired to this module's managers

        Shared by every path that needs a provider (the provider-config route, the primary login attempt
        and the fallback sweep), so all of them configure a provider the same way

        Args:
            provider (type[BaseAuthenticationProvider]): The provider class to instantiate
            config (BaseAuthProviderConfig | None): An already built config instance; when None it is
                built from the stored settings

        Returns:
            BaseAuthenticationProvider: The configured provider instance
        """
        return provider(
            config=config or self.build_provider_config(provider),
            security_manager=self.__security_manager,
            users_manager=self.users_manager,
        )


    def get_provider(self, provider_name: str) -> BaseAuthenticationProvider | None:
        """
        Retrieves an initialised provider instance by class name

        Args:
            provider_name (str): Class name of the installed provider

        Returns:
            BaseAuthenticationProvider | None: The configured provider, or None when it is not installed
                or its configuration could not be built (the cause is logged)
        """
        try:
            if not AuthModule.provider_exists(provider_name=provider_name):
                return None

            return self.build_provider_instance(AuthModule.get_provider_class(provider_name))
        except Exception as err:
            LOGGER.error('[AuthModule] %s', err)

            return None


    def resolve_user(self, user_name: str) -> CmdbUser | None:
        """
        Looks the login up as a stored CmdbUser

        Cloud mode identifies a user by email, on-premise by the (lower-cased) user name

        Args:
            user_name (str): The login the user typed

        Returns:
            CmdbUser | None: The stored user, or None when no user carries that login
        """
        if current_app.cloud_mode:
            return self.users_manager.get_user_by({'email': user_name})

        return self.users_manager.get_user_by({'user_name': user_name.lower()})


    def login(self, user_name: str, password: str) -> CmdbUser:
        """
        Authenticates a login, first with the user's own provider and then with every other one

        The stored CmdbUser names the provider that should authenticate it; that primary attempt is used
        when the user exists, its provider is installed and activated, and external providers are
        enabled for an external one. If **anything** about that attempt fails - unknown user, unknown or
        deactivated provider, wrong credentials, unusable settings - every installed provider whose
        configuration is active is tried in turn, which is how a user that does not exist locally yet
        gets provisioned by an external provider

        Args:
            user_name (str): Name (or, in cloud mode, email) of the user
            password (str): The password to verify

        Raises:
            AuthenticationError: When no provider accepted the credentials; the primary failure is
                chained as the cause

        Returns:
            CmdbUser: The authenticated user
        """
        try:
            user: CmdbUser | None = self.resolve_user(user_name)

            if not user:
                # Not an error case: the fallback sweep below may still provision this login
                raise AuthenticationError(f"No CmdbUser found for login '{user_name}'")

            provider_class_name: str = user.authenticator

            if not self.provider_exists(provider_class_name):
                raise AuthenticationProviderNotFoundError(f"Provider with name {provider_class_name} does not exist!")

            provider: type[BaseAuthenticationProvider] = self.get_provider_class(provider_class_name)
            provider_instance: BaseAuthenticationProvider = self.build_provider_instance(provider)

            if not provider_instance.is_active():
                raise AuthenticationProviderNotActivated(f'Provider {provider_class_name} is deactivated')

            if provider_instance.EXTERNAL_PROVIDER and not self.settings.enable_external:
                raise AuthenticationProviderNotActivated('External providers are deactivated')

            return provider_instance.authenticate(user_name, password)
        except Exception as err:
            return self.authenticate_with_any_provider(user_name, password, err)


    def authenticate_with_any_provider(
        self,
        user_name: str,
        password: str,
        primary_error: Exception,
    ) -> CmdbUser:
        """
        Tries every installed provider whose configuration is active, in installation order

        The fallback half of ``login``. A provider that rejects the credentials, or that finds the user
        but cannot store it, does not end the sweep - the next provider gets its turn. Note this filters
        on the provider's CONFIG 'active' flag, while the primary attempt asks the provider instance
        itself (see the discussion backlog on that asymmetry)

        Args:
            user_name (str): Name (or, in cloud mode, email) of the user
            password (str): The password to verify
            primary_error (Exception): Why the primary attempt failed; chained onto the final error

        Raises:
            AuthenticationError: When no provider accepted the credentials

        Returns:
            CmdbUser: The user authenticated by the first provider that accepted the credentials
        """
        for provider in self.providers:
            provider_config: BaseAuthProviderConfig = self.build_provider_config(provider)

            if not provider_config.is_active():
                continue

            if provider.EXTERNAL_PROVIDER and not self.settings.enable_external:
                continue

            provider_instance: BaseAuthenticationProvider = self.build_provider_instance(provider, provider_config)

            try:
                return provider_instance.authenticate(user_name, password)
            except AuthenticationError:
                continue
            except (BaseManagerGetError, BaseManagerInsertError) as error:
                LOGGER.debug("User found by provider but could not be inserted or found %s", error)
                continue

        raise AuthenticationError('Could not login.') from primary_error
