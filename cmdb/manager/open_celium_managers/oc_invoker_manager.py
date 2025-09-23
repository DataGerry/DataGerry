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
Implementation of OpenCelium InvokerManager
"""
import json
from logging import Logger, getLogger
from typing import Any

from requests import Response

from cmdb.open_celium import OcApiConnector

from cmdb.errors.open_celium.invoker import OcInvokerGetError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

INVOKER_URL: str = "/invoker"
GET_ALL_INVOKERS_URL: str = f"{INVOKER_URL}/all"

# -------------------------------------------------------------------------------------------------------------------- #
#                                               OcInvokerManager - CLASS                                               #
# -------------------------------------------------------------------------------------------------------------------- #
class OcInvokerManager:
    """
    Manages Invokers of OpenCelium
    """
    def __init__(self) -> None:
        self.oc_connector: OcApiConnector = OcApiConnector()

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

    def get_all_invokers(self) -> list[dict[str, Any]]:
        """
        Retrieves all Invokers from OpenCelium

        Raises:
            OcInvokerGetError: When retrieving the Invokers fails

        Returns:
            list[dict[str, Any]]: All Invokers from OpenCelium
        """
        all_invokers_response: Response = self.oc_connector.oc_get(GET_ALL_INVOKERS_URL)

        if self.oc_connector.is_valid_response(all_invokers_response):
            return json.loads(all_invokers_response.text)

        raise OcInvokerGetError("Failed to retrieve Invokers from OpenCelium!")
