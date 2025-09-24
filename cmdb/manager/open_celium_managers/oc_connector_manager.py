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
Implementation of OpenCelium ConnectorManager
"""
import json
from logging import Logger, getLogger
from typing import Any

from requests import Response

from cmdb.manager.open_celium_managers.oc_base_manager import OcBaseManager

from cmdb.errors.open_celium.connector import OcConnectorCreateError, OcConnectorGetError, OcConnectorUpdateError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

CONNECTOR_URL: str = "/connector"
CHECK_CONNECTOR_URL: str = f"{CONNECTOR_URL}/check"
ALL_CONNECTORS_URL: str = f"{CONNECTOR_URL}/all"

# -------------------------------------------------------------------------------------------------------------------- #
#                                              OcConnectorManager - CLASS                                              #
# -------------------------------------------------------------------------------------------------------------------- #
class OcConnectorManager(OcBaseManager):
    """
    Manages Connectors of OpenCelium
    """

# --------------------------------------------------- CRUD - CREATE -------------------------------------------------- #

    def create_connector(self, params: dict[str, Any]) -> dict[str, Any]:
        """
        Creates a Connector in OpenCelium

        Args:
            params (dict[str, Any]): params of an OcConnector

        Raises:
            OcConnectorCreateError: When creating the OcConnector failed

        Returns:
            dict[str, Any]: The created OcConnector
        """
        create_connector_response: Response = self.oc_connector.oc_post(params, CONNECTOR_URL)

        if self.is_valid_response(create_connector_response):
            return json.loads(create_connector_response.text)

        raise OcConnectorCreateError("Failed to create the Connector in OpenCelium!")


    def check_connector(self, params: dict[str, Any]) -> bool:
        """
        Checks the credentials of the assigned Invoker of the Connector

        Args:
            params (dict[str, Any]): data of the Invoker and Connector

        Returns:
            bool: True of credentials are valid else False
        """
        check_connector_response: Response = self.oc_connector.oc_post(params, CHECK_CONNECTOR_URL)

        if self.is_valid_response(check_connector_response):
            return True

        return False

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

    def get_connector(self, connector_id: int) -> dict[str, Any]:
        """
        Retrieves a single OcConnector from OpenCelium

        Args:
            connector_id (int): connectorId of the OcConnector

        Raises:
            OcConnectorGetError: When the connectorId was not provided to this method
            OcConnectorGetError: When the OcConnector could not be retrieved

        Returns:
            dict[str, Any]: _description_The retrieved OcConnector
        """
        if not connector_id:
            raise OcConnectorGetError("No connectorId provided!")

        target_connector: Response = self.oc_connector.oc_get(f"{CONNECTOR_URL}/{connector_id}")

        if self.is_valid_response(target_connector):
            return json.loads(target_connector.text)

        raise OcConnectorGetError(f"Failed to retrieve OpenCelium Connector with ID: {connector_id}")


    def get_all_connectors(self) -> list[dict[str, Any]]:
        """
        Retrieves all Connectors from OpenCelium

        Raises:
            OcConnectorGetError: When retrieving the OcConnectors fails

        Returns:
            list[dict[str, Any]]: All Connectors from OpenCelium
        """
        all_connectors_response: Response = self.oc_connector.oc_get(ALL_CONNECTORS_URL)

        if self.is_valid_response(all_connectors_response):
            return json.loads(all_connectors_response.text)

        raise OcConnectorGetError("Failed to retrieve Connectors from OpenCelium!")

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

    def update_connector(self, params: dict[str, Any], connector_id: int) -> dict[str, Any]:
        """
        Updates an OcConnector with the given connector_id

        Args:
            params (dict[str, Any]): the new data of the Connector
            connector_id (int): connectorId of the OcConnector

        Raises:
            OcConnectorUpdateError: When updating the Connector fails

        Returns:
            dict[str, Any]: The updated OcConnector
        """
        updated_connector_response: Response = self.oc_connector.oc_put(params, f"{CONNECTOR_URL}/{connector_id}")

        if self.is_valid_response(updated_connector_response):
            return json.loads(updated_connector_response.text)

        raise OcConnectorUpdateError(f"Failed to update Connector with ID:{connector_id} in OpenCelium!")

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

    def delete_connector(self, connector_id: int) -> bool:
        """
        Deletes a Connector in OpenCelium with the given connector_id

        Args:
            connector_id (int): the connectorId of the OcConnector which should be deleted

        Returns:
            bool: True if deletion was a success else False
        """
        delete_connector_response: Response = self.oc_connector.oc_delete(f"{CONNECTOR_URL}/{connector_id}")

        if self.is_valid_response(delete_connector_response):
            return True

        return False
