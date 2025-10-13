# DataGerry - OpenSource Enterprise CMDB
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
Implementation of OpenCelium LicenseManager
"""
import json
from logging import Logger, getLogger
from typing import Any

from requests import Response

from cmdb.manager.open_celium_managers.oc_base_manager import OcBaseManager

from cmdb.errors.open_celium.license import OcLicenseGetError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

LICENSE_URL: str = "/subs"
LICENSE_ACTIVATION_URL: str = f"{LICENSE_URL}/activation/request/generate"

# -------------------------------------------------------------------------------------------------------------------- #
#                                               OcLicenseManager - CLASS                                               #
# -------------------------------------------------------------------------------------------------------------------- #
class OcLicenseManager(OcBaseManager):
    """
    Manages Invokers of OpenCelium
    """

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

    def get_license_activation(self) -> Any:
        """
        Retrieves a single Invoker from OpenCelium

        Returns:
            Any: The retrieved OpenCelium License activation
        """
        license_activation_response: Response = self.oc_connector.oc_get(LICENSE_ACTIVATION_URL)

        if self.is_valid_response(license_activation_response):
            return json.loads(license_activation_response.text)

        raise OcLicenseGetError("Failed to retrieve License activation!")
