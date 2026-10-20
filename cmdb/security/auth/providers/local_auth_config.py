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

    Holds whether the local provider is active. The provider itself reports active whatever this
    flag says - local login is the way back into an instance - so the flag is the stored setting the
    settings page shows, not a switch that can lock anyone out

    A missing flag (None) reads as the class default, active - the base class resolves it. A stored config
    written without the key would otherwise carry None, which is falsy, and be shown and re-saved as inactive.
    A flag that is no boolean is refused (`ProviderConfigError`), like every provider's

    Extends: BaseAuthProviderConfig
    """
