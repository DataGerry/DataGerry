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

from cmdb.manager.open_celium_managers.oc_base_manager import OcBaseManager

from cmdb.errors.open_celium.invoker import OcInvokerGetError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

INVOKER_URL: str = "/invoker"
ALL_INVOKERS_URL: str = f"{INVOKER_URL}/all"

# -------------------------------------------------------------------------------------------------------------------- #
#                                               OcInvokerManager - CLASS                                               #
# -------------------------------------------------------------------------------------------------------------------- #
class OcInvokerManager(OcBaseManager):
    """
    Manages Invokers of OpenCelium
    """

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

    def get_invoker_by_name(self, name: str) -> dict[str, Any]:
        """
        Retrieves a single Invoker from OpenCelium

        Args:
            name (str): name of the Invoker

        Raises:
            OcInvokerGetError: When the name was not provided to this method
            OcInvokerGetError: When  retrieving the Invoker failed

        Returns:
            dict[str, Any]: The retrieved OcConnector
        """
        if not name:
            raise OcInvokerGetError("No name for Invoker provided!")

        target_invoker_response: Response = self.oc_connector.oc_get(f"{INVOKER_URL}/{name}")

        if self.is_valid_response(target_invoker_response):
            return json.loads(target_invoker_response.text)

        raise OcInvokerGetError(f"Failed to retrieve OpenCelium Invoker with name: {name}")


    def get_all_invokers(self, with_operations: bool=True) -> list[dict[str, Any]]:
        """
        Retrieves all Invokers from OpenCelium

        Raises:
            OcInvokerGetError: When retrieving the Invokers fails

        Returns:
            list[dict[str, Any]]: All Invokers from OpenCelium
        """
        invoker_route: str = ALL_INVOKERS_URL

        if not with_operations:
            invoker_route = f"{ALL_INVOKERS_URL}?opsIncluded=false"

        all_invokers_response: Response = self.oc_connector.oc_get(invoker_route)

        if self.is_valid_response(all_invokers_response):
            return json.loads(all_invokers_response.text)

        raise OcInvokerGetError("Failed to retrieve Invokers from OpenCelium!")
