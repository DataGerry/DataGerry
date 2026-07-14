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
Implementation of OpenCelium InvokerManager
"""
from logging import Logger, getLogger
from typing import Any
from urllib.parse import quote

from cmdb.manager.open_celium_managers.oc_base_manager import OcBaseManager

from cmdb.errors.open_celium.invoker import OcInvokerGetError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

INVOKER_URL: str = "/invoker"
ALL_INVOKERS_URL: str = f"{INVOKER_URL}/all"
INVOKER_EXISTS_URL: str = f"{INVOKER_URL}/exists"

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
            OcInvokerGetError: When retrieving the Invoker failed

        Returns:
            dict[str, Any]: The retrieved Invoker
        """
        if not name:
            raise OcInvokerGetError("No name for Invoker provided!")

        return self.parse_response(
            self.oc_connector.oc_get(f"{INVOKER_URL}/{quote(name)}"),
            OcInvokerGetError,
            f"Failed to retrieve OpenCelium Invoker with name: {name}",
        )


    def check_invoker_exists(self, name: str) -> bool:
        """
        Checks if an Invoker with the given name exists in OpenCelium

        Args:
            name (str): name of the Invoker

        Raises:
            OcInvokerGetError: When the name was not provided to this method
            OcInvokerGetError: When checking the Invoker failed

        Returns:
            bool: True if the Invoker exists, else False
        """
        if not name:
            raise OcInvokerGetError("No name for Invoker provided!")

        data: dict[str, Any] = self.parse_response(
            self.oc_connector.oc_get(f"{INVOKER_EXISTS_URL}/{quote(name)}"),
            OcInvokerGetError,
            f"Failed to check OpenCelium Invoker with name: {name}",
        )

        return bool(data.get('result'))


    def get_all_invokers(self, with_operations: bool = True) -> list[dict[str, Any]]:
        """
        Retrieves all Invokers from OpenCelium

        Args:
            with_operations (bool): When False, request the invokers without their operations

        Raises:
            OcInvokerGetError: When retrieving the Invokers fails

        Returns:
            list[dict[str, Any]]: All Invokers from OpenCelium
        """
        invoker_route: str = ALL_INVOKERS_URL

        if not with_operations:
            invoker_route = f"{ALL_INVOKERS_URL}?opsIncluded=false"

        return self.parse_response(
            self.oc_connector.oc_get(invoker_route),
            OcInvokerGetError,
            "Failed to retrieve Invokers from OpenCelium!",
        )
