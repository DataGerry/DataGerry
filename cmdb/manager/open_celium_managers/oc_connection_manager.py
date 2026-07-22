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
Implementation of OpenCelium ConnectionManager
"""
import json
from logging import Logger, getLogger
from typing import Any

from requests import Response

from cmdb.manager.open_celium_managers.oc_base_manager import OcBaseManager

from cmdb.open_celium.oc_constants import UNIQUE_POSITIVE

from cmdb.errors.open_celium.connection import (
    OcConnectionCreateError,
    OcConnectionGetError,
    OcConnectionUpdateError,
    OcConnectionTestError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

CONNECTION_URL: str = "/connection"
CONNECTION_REMOTE_API_URL: str = f"{CONNECTION_URL}/remoteapi"
CONNECTIONS_BY_IDS_URL: str = f"{CONNECTION_URL}/list/by-ids"
CON_UNIQUE_CHECK_URL: str = f"{CONNECTION_URL}/check"
CONNECTION_TEST_URL: str = f"{CONNECTION_URL}/execution/test"

# -------------------------------------------------------------------------------------------------------------------- #
#                                              OcConnectionManager - CLASS                                             #
# -------------------------------------------------------------------------------------------------------------------- #
class OcConnectionManager(OcBaseManager):
    """
    Manages Connections of OpenCelium
    """
# --------------------------------------------------- CRUD - CREATE -------------------------------------------------- #

    def create_connection(self, params: dict[str, Any]) -> dict[str, Any]:
        """
        Creates a Connection in OpenCelium

        Args:
            params (dict[str, Any]): params of an OcConnection

        Raises:
            OcConnectionCreateError: When creating the OcConnection failed

        Returns:
            dict[str, Any]: The created OcConnection
        """
        create_connection_response: Response = self.oc_connector.oc_post(params, CONNECTION_URL)

        if self.is_valid_response(create_connection_response):
            return json.loads(create_connection_response.text)

        LOGGER.error("[create_connection] OC Error: %s", create_connection_response.text)
        raise OcConnectionCreateError("Failed to create the Connection in OpenCelium!")


    def send_to_remote_api(self, payload: dict[str, Any]) -> dict[str, Any]:
        """
        Sends data to remote API

        Args:
            payload (dict[str, Any]): payload for remote API

        Raises:
            OcConnectionCreateError: When sending the payload to remote API failed

        Returns:
            dict[str, Any]: The created OcConnection
        """
        create_connection_response: Response = self.oc_connector.oc_post(payload, CONNECTION_REMOTE_API_URL)

        if self.is_valid_response(create_connection_response):
            return json.loads(create_connection_response.text)

        LOGGER.error("[send_to_remote_api] OC Error: %s", create_connection_response.text)
        raise OcConnectionCreateError("Failed to send the payload to remote API!")


    def get_connections_by_ids(self, connection_ids: list[int]) -> list[dict[str, Any]]:
        """
        Retrieves a list of OcConnections with the provided 'connection_ids'

        Args:
            connection_ids (list[int]): List of connection_ids of OcConnections

        Raises:
            OcConnectionGetError: When the connection_ids were not provided to this method
            OcConnectionGetError: When the OcConnections could not be retrieved

        Returns:
            list[dict[str, Any]]: The OcConnections with the given connection_ids
        """
        if not connection_ids:
            raise OcConnectionGetError("No connectionIds for Connections provided!")

        params: dict[str, Any] = {
            "identifiers": connection_ids
        }

        connections_response: Response = self.oc_connector.oc_post(params, CONNECTIONS_BY_IDS_URL)

        if self.is_valid_response(connections_response):
            return json.loads(connections_response.text)

        LOGGER.error("[get_connections_by_ids] OC Error: %s", connections_response.text)
        raise OcConnectionGetError(f"Failed to retrieve OpenCelium Connections with IDs: {connection_ids}")


    def test_connection(self, connection_data: dict[str, Any], channel_id: int) -> dict[str, Any]:
        """
        Tests a Connection in OpenCelium

        Args:
            connection_data (dict[str, Any]): data of the OcConnection
            channel_id (int): ID of the channel

        Raises:
            OcConnectionTestError: When creating the OcConnection failed

        Returns:
            dict[str, Any]: The result of the OcConnection test
        """
        connection_test_response: Response = self.oc_connector.oc_post(
            connection_data,
            f"{CONNECTION_TEST_URL}?channelId={channel_id}"
        )

        if self.is_valid_response(connection_test_response):
            return json.loads(connection_test_response.text)

        LOGGER.error("[test_connection] OC Error: %s", connection_test_response.text)
        raise OcConnectionTestError("Failed to test OpenCelium Connection!")

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

    def get_connection(self, connection_id: int) -> dict[str, Any]:
        """
        Retrieves a single OcConnection from OpenCelium

        Args:
            connection_id (int): connectionId of the OcConnection

        Raises:
            OcConnectionGetError: When the connectionId was not provided to this method
            OcConnectionGetError: When the OcConnection could not be retrieved

        Returns:
            dict[str, Any]: The retrieved OcConnection
        """
        if not connection_id:
            raise OcConnectionGetError("No connectionId for Connection provided!")

        target_connection_response: Response = self.oc_connector.oc_get(f"{CONNECTION_URL}/{connection_id}")

        if self.is_valid_response(target_connection_response):
            return json.loads(target_connection_response.text)

        LOGGER.error("[get_connection] OC Error: %s", target_connection_response.text)
        raise OcConnectionGetError(f"Failed to retrieve OpenCelium Connection with ID: {connection_id}")


    def check_connection_name_exists(self, conn_name: str) -> bool:
        """
        Checks a connection name for uniqueness

        Args:
            conn_name (int): name of the OcConnection

        Raises:
            OcConnectionGetError: When the OcConnection could not be checked

        Returns:
            dict[str, Any]: The retrieved OcConnection
        """
        conn_name_check_response: Response = self.oc_connector.oc_get(f"{CON_UNIQUE_CHECK_URL}/{conn_name}")

        # LOGGER.debug(f"check_connector_response body: {conn_name_check_response.text}")

        if self.is_valid_response(conn_name_check_response):
            conn_resp: dict[str, Any] = json.loads(conn_name_check_response.text)
            if conn_resp.get('message') == UNIQUE_POSITIVE:
                return False

            return True

        LOGGER.error("[check_connection_name_exists] OC Error: %s", conn_name_check_response.text)
        raise OcConnectionGetError(f"Failed to check Connection name for uniqueness: {conn_name}!")

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

    def update_connection(self, params: dict[str, Any], connection_id: int) -> dict[str, Any]:
        """
        Updates an OcConnection with the given connection_id

        Args:
            params (dict[str, Any]): the new data of the OcConnection
            connection_id (int): connectionId of the OcConnection

        Raises:
            OcConnectionUpdateError: When updating the OcConnection fails

        Returns:
            dict[str, Any]: The updated OcConnection
        """
        updated_connection_response: Response = self.oc_connector.oc_put(params, f"{CONNECTION_URL}/{connection_id}")

        if self.is_valid_response(updated_connection_response):
            return json.loads(updated_connection_response.text)

        LOGGER.error("[update_connection] OC Error: %s", updated_connection_response.text)
        raise OcConnectionUpdateError(f"Failed to update Connection with ID:{connection_id} in OpenCelium!")

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

    def delete_connection(self, connection_id: int) -> bool:
        """
        Deletes a Connection in OpenCelium with the given connection_id

        Args:
            connection_id (int): the connectionId of the OcConnection which should be deleted

        Returns:
            bool: True if deletion was a success else False
        """
        delete_connection_response: Response = self.oc_connector.oc_delete(f"{CONNECTION_URL}/{connection_id}")

        if self.is_valid_response(delete_connection_response):
            return True

        return False
