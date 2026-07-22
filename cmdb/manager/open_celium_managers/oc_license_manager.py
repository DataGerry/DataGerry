# DataGerry - OpenSource Enterprise CMDB
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
Implementation of OpenCelium LicenseManager
"""
import json
from logging import Logger, getLogger
from typing import Any
from datetime import datetime, timedelta

from requests import Response

from cmdb.manager.open_celium_managers.oc_base_manager import OcBaseManager

from cmdb.errors.open_celium.license import OcLicenseGetError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

LICENSE_URL: str = "/subs"
LICENSE_ACTIVATION_URL: str = f"{LICENSE_URL}/activation/request/generate"
ACTIVE_LICENSE_URL: str = f"{LICENSE_URL}/active"
LICENSE_USAGE_URL: str = f"{LICENSE_URL}/operation/usage"

# -------------------------------------------------------------------------------------------------------------------- #
#                                               OcLicenseManager - CLASS                                               #
# -------------------------------------------------------------------------------------------------------------------- #
class OcLicenseManager(OcBaseManager):
    """
    Manages Licenses of OpenCelium
    """

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

    def get_license_activation(self) -> Any:
        """
        Retrieves the license activation file from OpenCelium

        Returns:
            Any: The retrieved OpenCelium License activation
        """
        license_activation_response: Response = self.oc_connector.oc_get(LICENSE_ACTIVATION_URL)

        if self.is_valid_response(license_activation_response):
            return json.loads(license_activation_response.text)

        raise OcLicenseGetError("Failed to retrieve License activation!")


    def get_active_license(self) -> dict[str, Any]:
        """
        Retrieves the active License from OpenCelium

        Returns:
            dict[str, Any]: The retrieved OpenCelium License
        """
        active_license_response: Response = self.oc_connector.oc_get(ACTIVE_LICENSE_URL)

        if self.is_valid_response(active_license_response):
            return json.loads(active_license_response.text)

        raise OcLicenseGetError("Failed to retrieve active License!")


    def get_license_usage(self, page: int = 0, size: int = 5) -> dict[str, Any]:
        """
        Retrieves a the License usage from OpenCelium

        Returns:
            dict[str, Any]: The retrieved OpenCelium License usage
        """
        start_date, end_date = self.get_current_month_boundaries()

        license_usage_response: Response = self.oc_connector.oc_get(
            f"{LICENSE_USAGE_URL}?page={page}&size={size}&startDate={start_date}&endDate={end_date}"
        )

        if self.is_valid_response(license_usage_response):
            return json.loads(license_usage_response.text)

        raise OcLicenseGetError("Failed to retrieve License usage!")

# -------------------------------------------------- HELPER METHODS -------------------------------------------------- #

    def get_current_month_boundaries(self) -> tuple[int, int]:
        """
        Retrieves the start and end of the current month as timestamps

        Returns:
            tuple[int, int]: start and end timestamp of the current month
        """
        # Get current date
        now: datetime = datetime.now()

        # Beginning of the current month (00:00:00)
        start_of_month = datetime(now.year, now.month, 1)

        # Compute the first day of the next month, then subtract 1 second to get the last moment of the current month
        if now.month == 12:
            next_month = datetime(now.year + 1, 1, 1)
        else:
            next_month = datetime(now.year, now.month + 1, 1)
        end_of_month: datetime = next_month - timedelta(seconds=1)

        # Convert to timestamps (milliseconds)
        start_timestamp = int(start_of_month.timestamp() * 1000)
        end_timestamp = int(end_of_month.timestamp() * 1000)

        return start_timestamp, end_timestamp
