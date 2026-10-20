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
Implementation of BaseAuthProviderConfig
"""
from logging import Logger, getLogger
from typing import Any

from cmdb.errors.provider import ProviderConfigError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# The key of a provider config that switches the provider on or off
PROVIDER_ACTIVE_KEY: str = 'active'

# Why a flag of a provider config is refused - `key` names it, `kind` is the type it arrived as
FLAG_NOT_BOOLEAN_MSG: str = "'{key}' must be a boolean, got {kind}"


def validated_flag(value: Any, default: bool, key: str) -> bool:
    """
    Checks an on/off flag of a provider config

    Only a real boolean is a flag: a truthy string such as ``"false"`` would otherwise switch on what it names

    Args:
        value (Any): The flag as stored or sent, None when it is absent
        default (bool): What an absent flag reads as
        key (str): The flag's name, for the refusal

    Raises:
        ProviderConfigError: When the value is present and not a boolean

    Returns:
        bool: The flag
    """
    if value is None:
        return default

    if not isinstance(value, bool):
        raise ProviderConfigError(FLAG_NOT_BOOLEAN_MSG.format(key=key, kind=type(value).__name__))

    return value

# -------------------------------------------------------------------------------------------------------------------- #
#                                              AuthProviderConfig - CLASS                                              #
# -------------------------------------------------------------------------------------------------------------------- #
class BaseAuthProviderConfig:
    """
    Base configuration class for authentication providers.

    This class serves as the base configuration for authentication providers, 
    handling the activation state (`active`) and providing a mechanism to store 
    additional configuration parameters as attributes. Subclasses should extend this 
    class to define more specific configuration for their respective authentication providers.

    Attributes:
        active (bool): A flag indicating whether the authentication provider is active
    """

    DEFAULT_CONFIG_VALUES = {
        PROVIDER_ACTIVE_KEY: True
    }

    # Paths into DEFAULT_CONFIG_VALUES whose value is a credential and must never leave the backend.
    # Declared by the provider that owns the secret rather than listed centrally, so adding a provider
    # with a credential is what registers it - see cmdb.security.auth.auth_settings_masking, which
    # masks these on read and restores them on a write that sends the mask back unchanged
    SECRET_CONFIG_PATHS: tuple[tuple[str, ...], ...] = ()

    def __init__(self, active: bool | None = None, **kwargs: Any) -> None:
        """
        Initializes the configuration for an authentication provider

        Args:
            active (bool | None): Whether the provider is activated; None reads as the class's default
                (`DEFAULT_CONFIG_VALUES`)
            **kwargs: Any additional keyword arguments are dynamically set as attributes on the configuration object

        Raises:
            ProviderConfigError: When `active` is present and not a boolean
        """
        self.active: bool = validated_flag(active, self.DEFAULT_CONFIG_VALUES[PROVIDER_ACTIVE_KEY], PROVIDER_ACTIVE_KEY)

        # Set additional configuration values as object attributes
        for key, value in kwargs.items():
            setattr(self, key, value)


    def is_active(self) -> bool:
        """
        Checks if the authentication provider is active

        Returns:
            bool: Returns `True` if the provider is active, otherwise `False`
        """
        return self.active
