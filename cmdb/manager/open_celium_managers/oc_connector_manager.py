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
from typing import Any, Optional

from requests import Response

from cmdb.manager.open_celium_managers.oc_base_manager import OcBaseManager

from cmdb.errors.open_celium.connector import OcConnectorCreateError, OcConnectorGetError, OcConnectorUpdateError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

CONNECTOR_URL: str = "/connector"
CHECK_CONNECTOR_URL: str = f"{CONNECTOR_URL}/check"
ALL_CONNECTORS_URL: str = f"{CONNECTOR_URL}/all"
CHECK_MASTER_PW_URL: str = f"{CONNECTOR_URL}/master-password/status"
CONNECTOR_EXISTS_URL: str = f"{CONNECTOR_URL}/exists"

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

        # LOGGER.debug(f"[create_connector] create_connector_response: {create_connector_response}")
        # LOGGER.debug(f"[create_connector] create_connector_response status: {create_connector_response.status_code}")
        # LOGGER.debug(f"[create_connector] create_connector_response body: {create_connector_response.text}")

        if self.is_valid_response(create_connector_response):
            return json.loads(create_connector_response.text)

        raise OcConnectorCreateError("Failed to create the Connector in OpenCelium!")


    def check_connector(self, params: dict[str, Any]) -> bool:
        """
        Checks the credentials of the assigned Invoker of the Connector

        Args:
            params (dict[str, Any]): data of the Invoker and Connector

        Returns:
            bool: True if credentials are valid else False
        """
        check_connector_response: Response = self.oc_connector.oc_post(params, CHECK_CONNECTOR_URL)

        # LOGGER.debug(f"[check_connector] check_connector_response: {check_connector_response}")
        # LOGGER.debug(f"[check_connector] check_connector_response status: {check_connector_response.status_code}")
        # LOGGER.debug(f"[check_connector] headers: {check_connector_response.headers}")
        # LOGGER.debug(f"[check_connector] check_connector_response body: {check_connector_response.text}")

        if self.is_valid_response(check_connector_response):
            return True

        return False


    def check_master_pw(self, password: str) -> bool:
        """
        Checks the master password of the Connector

        Args:
            password (str): the master password

        Returns:
            bool: True if password is correct else False
        """
        check_pw_response: Response = self.oc_connector.oc_get(CHECK_MASTER_PW_URL, password)

        # LOGGER.debug(f"[check_master_pw] response: {check_pw_response}")
        # LOGGER.debug(f"[check_master_pw] status_code: {check_pw_response.status_code}")
        # LOGGER.debug(f"[check_master_pw] headers: {check_pw_response.headers}")
        # LOGGER.debug(f"[check_master_pw] body: {check_pw_response.text}")

        if self.is_valid_response(check_pw_response):
            return True

        return False

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

    def get_connector(self, connector_id: int, password: str = None) -> dict[str, Any]:
        """
        Retrieves a single OcConnector from OpenCelium

        Args:
            connector_id (int): connectorId of the OcConnector

        Raises:
            OcConnectorGetError: When the connectorId was not provided to this method
            OcConnectorGetError: When the OcConnector could not be retrieved

        Returns:
            dict[str, Any]: The retrieved OcConnector
        """
        if not connector_id:
            raise OcConnectorGetError("No connectorId for Connector provided!")

        # LOGGER.debug(f"[get_connector] password: {password}")

        target_connector_response: Response = self.oc_connector.oc_get(f"{CONNECTOR_URL}/{connector_id}", password)

        # LOGGER.debug(f"[get_connector] status_code: {target_connector_response.status_code}")
        # LOGGER.debug(f"[get_connector] headers: {target_connector_response.headers}")
        # LOGGER.debug(f"[get_connector] body: {target_connector_response.text}")

        if self.is_valid_response(target_connector_response):
            return json.loads(target_connector_response.text)

        raise OcConnectorGetError(f"Failed to retrieve OpenCelium Connector with ID: {connector_id}")


    def get_connector_by_name(self, title: str, password: str = None) -> dict[str, Any]:
        """
        Retrieves a single OcConnector from OpenCelium

        Args:
            title (str): title of the Connector

        Raises:
            OcConnectorGetError: When the title was not provided to this method
            OcConnectorGetError: When the OcConnector could not be retrieved

        Returns:
            dict[str, Any]: The retrieved OcConnector
        """
        if not title:
            raise OcConnectorGetError("No connectorId for Connector provided!")

        target_connector_response: Response = self.oc_connector.oc_get(f"{CONNECTOR_URL}?title={title}", password)

        if self.is_valid_response(target_connector_response):
            return json.loads(target_connector_response.text)

        raise OcConnectorGetError(f"Failed to retrieve OpenCelium Connector with title: {title}")


    def connector_exists(self, title: str) -> bool:
        """
        Checks if a connector with the given title exists in OpenCelium

        Args:
            title (str): title of the Connector

        Returns:
            bool: True if it exists, else False
        """
        if not title:
            raise OcConnectorGetError("No connectorId for Connector provided!")

        target_connector_response: Response = self.oc_connector.oc_get(f"{CONNECTOR_EXISTS_URL}/{title}")

        if self.is_valid_response(target_connector_response):
            conn_resp: dict[str, Any] = json.loads(target_connector_response.text)
            return conn_resp['result']

        raise OcConnectorGetError(f"Failed to check if Connector with title: {title} exists!")


    def get_all_connectors(self) -> Optional[list[dict[str, Any]]]:
        """
        Retrieves all Connectors from OpenCelium

        Raises:
            OcConnectorGetError: When retrieving the OcConnectors fails

        Returns:
            Optional[list[dict[str, Any]]]: All Connectors from OpenCelium
        """
        all_connectors_response: Response = self.oc_connector.oc_get(ALL_CONNECTORS_URL)

        # LOGGER.debug(f"[get_all_connectors] response: {all_connectors_response}")
        # LOGGER.debug(f"[get_all_connectors] status_code: {all_connectors_response.status_code}")
        # LOGGER.debug(f"[get_all_connectors] headers: {all_connectors_response.headers}")
        # LOGGER.debug(f"[get_all_connectors] body: {all_connectors_response.text}")

        if self.is_valid_response(all_connectors_response):
            if all_connectors_response.text:
                return json.loads(all_connectors_response.text)

            return None

        # LOGGER.debug(f"[get_all_connectors] response: {all_connectors_response}")
        # LOGGER.debug(f"[get_all_connectors] status_code: {all_connectors_response.status_code}")
        # LOGGER.debug(f"[get_all_connectors] headers: {all_connectors_response.headers}")
        # LOGGER.debug(f"[get_all_connectors] body: {all_connectors_response.text}")

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
