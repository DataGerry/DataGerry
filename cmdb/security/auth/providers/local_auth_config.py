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
from typing import Any

from cmdb.security.auth.base_provider_config import BaseAuthProviderConfig, PROVIDER_ACTIVE_KEY
# -------------------------------------------------------------------------------------------------------------------- #

class LocalAuthenticationProviderConfig(BaseAuthProviderConfig):
    """
    Configuration class for the LocalAuthenticationProvider

    Holds whether the local provider is active. The provider itself reports active whatever this
    flag says - local login is the way back into an instance - so the flag is the stored setting the
    settings page shows, not a switch that can lock anyone out

    Extends: BaseAuthProviderConfig
    """

    def __init__(self, active: bool | None = None, **kwargs: Any) -> None:
        """
        Initializes the configuration for the LocalAuthenticationProvider

        A missing flag (None) reads as the class default, active. A stored config written without the
        key would otherwise carry None, which is falsy, and be shown and re-saved as inactive

        Args:
            active (bool | None): Whether the provider is configured active; None means the default, True
            **kwargs (Any): Any additional keyword arguments passed to the base class initialization

        Inherited Attributes:
            active (bool): The resolved flag - the given value, or True when none was given
        """
        if active is None:
            active = self.DEFAULT_CONFIG_VALUES[PROVIDER_ACTIVE_KEY]

        super().__init__(active, **kwargs)
