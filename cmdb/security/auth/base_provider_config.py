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
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

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
        'active': True
    }

    def __init__(self, active: bool, **kwargs):
        """
        Initializes the configuration for an authentication provider

        Args:
            active (bool): A flag indicating whether the authentication provider is activated (`True`)
                           or deactivated (`False`)
            **kwargs: Any additional keyword arguments are dynamically set as attributes on the configuration object
        """
        self.active: bool = active

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
