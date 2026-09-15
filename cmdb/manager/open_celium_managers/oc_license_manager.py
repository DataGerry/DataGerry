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

**OpenCelium's licence, not DataGerry's own** (`cmdb/manager/license_manager/`) - everything here is
a read-only proxy onto the `/subs` endpoints of the OpenCelium installation the tenant is connected
to, and every answer is whatever that API returned.
"""
from logging import Logger, getLogger
from typing import Any
from datetime import datetime, timedelta
from urllib.parse import urlencode

from cmdb.manager.open_celium_managers.oc_base_manager import OcBaseManager

from cmdb.open_celium.oc_constants import (
    OC_DEFAULT_USAGE_PAGE,
    OC_DEFAULT_USAGE_SIZE,
    OC_PAGE_PARAM,
    OC_SIZE_PARAM,
)

from cmdb.errors.open_celium.license import OcLicenseGetError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

LICENSE_URL: str = "/subs"
LICENSE_ACTIVATION_URL: str = f"{LICENSE_URL}/activation/request/generate"
ACTIVE_LICENSE_URL: str = f"{LICENSE_URL}/active"
LICENSE_USAGE_URL: str = f"{LICENSE_URL}/operation/usage"

# The window parameters of the usage endpoint. Only this module spells them - unlike page/size, which
# the REST route reads off its own query string as well
OC_START_DATE_PARAM: str = "startDate"
OC_END_DATE_PARAM: str = "endDate"

# Milliseconds per second: OpenCelium takes the window as epoch MILLISECONDS, `datetime.timestamp()`
# answers seconds
MILLIS_PER_SECOND: int = 1000

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
        Retrieves the license activation request from OpenCelium

        What an operator sends to becon to have their OpenCelium licence issued. Read through
        `parse_response`, so **the body has to be JSON** - the route documented a text file, which
        this cannot answer; which of the two OpenCelium actually returns is discussion-backlog #224

        Raises:
            OcLicenseGetError: When OpenCelium refused the request or answered no readable body

        Returns:
            Any: The retrieved OpenCelium License activation request
        """
        return self.parse_response(
            self.oc_connector.oc_get(LICENSE_ACTIVATION_URL),
            OcLicenseGetError,
            "Failed to retrieve License activation!",
        )


    def get_active_license(self) -> dict[str, Any]:
        """
        Retrieves the active License from OpenCelium

        Raises:
            OcLicenseGetError: When OpenCelium refused the request or answered no readable body

        Returns:
            dict[str, Any]: The retrieved OpenCelium License
        """
        return self.parse_response(
            self.oc_connector.oc_get(ACTIVE_LICENSE_URL),
            OcLicenseGetError,
            "Failed to retrieve active License!",
        )


    def get_license_usage(
            self,
            page: int = OC_DEFAULT_USAGE_PAGE,
            size: int = OC_DEFAULT_USAGE_SIZE) -> dict[str, Any]:
        """
        Retrieves the License usage of the current month from OpenCelium

        The window is **always the current month** - it is not a parameter - and is computed on the
        host's LOCAL timezone, so a tenant in another zone is reported a month that is not theirs
        (discussion-backlog #225, together with the 999 ms the window ends short of)

        Args:
            page (int): Zero-based page of the usage report to ask OpenCelium for. Forwarded as sent;
                        OpenCelium decides what exists
            size (int): Number of entries per page. Defaults to the 5 the frontend asks for

        Raises:
            OcLicenseGetError: When OpenCelium refused the request or answered no readable body

        Returns:
            dict[str, Any]: The retrieved OpenCelium License usage
        """
        start_date, end_date = get_current_month_boundaries()

        # urlencode rather than an f-string: the values are ints today, but a query string built by
        # interpolation is one caller away from carrying an unescaped value
        query: str = urlencode({
            OC_PAGE_PARAM: page,
            OC_SIZE_PARAM: size,
            OC_START_DATE_PARAM: start_date,
            OC_END_DATE_PARAM: end_date,
        })

        return self.parse_response(
            self.oc_connector.oc_get(f"{LICENSE_USAGE_URL}?{query}"),
            OcLicenseGetError,
            "Failed to retrieve License usage!",
        )

# -------------------------------------------------- HELPER METHODS -------------------------------------------------- #

def get_current_month_boundaries() -> tuple[int, int]:
    """
    Retrieves the start and end of the current month as epoch millisecond timestamps

    A pure function of the clock - it touches no manager state, which is why it sits at module level:
    it can be read and tested without an OpenCelium connector.

    Two properties are behaviour rather than intent, both discussion-backlog #225:

    - the month is the one of the **host's local timezone**, since `datetime.now()` and
      `datetime.timestamp()` are both local, so a tenant elsewhere is reported another month
    - the end is the last WHOLE SECOND of the month, leaving the final 999 ms outside the window

    Returns:
        tuple[int, int]: Start and end timestamp of the current month, in milliseconds
    """
    now: datetime = datetime.now()

    # Beginning of the current month (00:00:00)
    start_of_month: datetime = datetime(now.year, now.month, 1)

    # The first day of the next month, minus one second: the last moment of the current month
    if now.month == 12:
        next_month = datetime(now.year + 1, 1, 1)
    else:
        next_month = datetime(now.year, now.month + 1, 1)

    end_of_month: datetime = next_month - timedelta(seconds=1)

    return (
        int(start_of_month.timestamp() * MILLIS_PER_SECOND),
        int(end_of_month.timestamp() * MILLIS_PER_SECOND),
    )
