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
Implementation of LocalAuthenticationProviderConfig
"""
from cmdb.security.auth.base_provider_config import BaseAuthProviderConfig
# -------------------------------------------------------------------------------------------------------------------- #

class LocalAuthenticationProviderConfig(BaseAuthProviderConfig):
    """
    Configuration class for the LocalAuthenticationProvider

    This class holds the configuration settings specific to the local authentication provider, 
    such as whether the provider is active.

    Extends: BaseAuthProviderConfig
    """

    def __init__(self, active: bool = None, **kwargs):
        """
        Initializes the configuration for the LocalAuthenticationProvider

        Args:
            active (bool, optional): A flag indicating whether the authentication provider is active
            **kwargs: Any additional keyword arguments passed to the base class initialization

        Inherited Attributes:
            active (bool): Set to True if the provider is enabled, otherwise False
        """
        super().__init__(active, **kwargs)
