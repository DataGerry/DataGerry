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
Implementation of OpenCelium ConnectorManager
"""
import os
from logging import Logger, getLogger
from typing import Any
from urllib.parse import quote

from flask import current_app

from cmdb.database.mongo_database_manager import MongoDatabaseManager
from cmdb.manager.open_celium_managers.oc_base_manager import OcBaseManager

from cmdb.errors.open_celium.connector import OcConnectorCreateError, OcConnectorGetError, OcConnectorUpdateError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

CONNECTOR_URL: str = "/connector"
CHECK_CONNECTOR_URL: str = f"{CONNECTOR_URL}/check"
CONNECTORS_BY_IDS_URL: str = f"{CONNECTOR_URL}/list/by-ids"
ALL_CONNECTORS_URL: str = f"{CONNECTOR_URL}/all"
CHECK_MASTER_PW_URL: str = f"{CONNECTOR_URL}/master-password/status"
CHECK_MASTER_PW_EXISTS_URL: str = f"{CHECK_MASTER_PW_URL}/exist"
CONNECTOR_EXISTS_URL: str = f"{CONNECTOR_URL}/exists"

# -------------------------------------------------------------------------------------------------------------------- #
#                                              OcConnectorManager - CLASS                                              #
# -------------------------------------------------------------------------------------------------------------------- #
class OcConnectorManager(OcBaseManager):
    """
    Manages Connectors of OpenCelium

    Extends: OcBaseManager
    """
    def __init__(self, dbm: MongoDatabaseManager, db_name: str) -> None:
        """
        Initialises the OcConnectorManager
        """
        self.master_pw: str = None

        if current_app.cloud_mode and not current_app.local_mode:
            self.master_pw = os.getenv('OC_MASTER_PW')

            if not self.master_pw and not current_app.local_mode:
                raise ValueError("No OC master password provided via env variables!")

        super().__init__(dbm, db_name)
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
        return self.parse_response(
            self.oc_connector.oc_post(params, CONNECTOR_URL),
            OcConnectorCreateError,
            "Failed to create the Connector in OpenCelium!",
        )


    def check_connector(self, params: dict[str, Any]) -> bool:
        """
        Checks the credentials of the assigned Invoker of the Connector

        Args:
            params (dict[str, Any]): data of the Invoker and Connector

        Returns:
            bool: True if credentials are valid else False
        """
        return self.is_valid_response(self.oc_connector.oc_post(params, CHECK_CONNECTOR_URL))


    def check_master_pw(self, password: str, raw: bool = False) -> bool | dict[str, Any]:
        """
        Checks the master password of the Connector

        Args:
            password (str): the master password
            raw (bool): when True, return the OpenCelium response body instead of a bool

        Raises:
            OcConnectorGetError: When raw is True and the check could not be performed

        Returns:
            bool | dict[str, Any]: True/False when raw is False, else the OpenCelium response body
        """
        check_pw_response = self.oc_connector.oc_get(CHECK_MASTER_PW_URL, password)

        if not raw:
            return self.is_valid_response(check_pw_response)

        return self.parse_response(check_pw_response, OcConnectorGetError, "Failed to check master password!")


    def check_master_pw_exists(self) -> dict[str, Any]:
        """
        Checks if a master password exist in OpenCelium

        Raises:
            OcConnectorGetError: When the check could not be performed

        Returns:
            dict[str, Any]: The OpenCelium response body
        """
        return self.parse_response(
            self.oc_connector.oc_get(CHECK_MASTER_PW_EXISTS_URL),
            OcConnectorGetError,
            "Failed to check if master password exists!",
        )


    def get_connectors_by_ids(self, connector_ids: list[int]) -> list[dict[str, Any]]:
        """
        Retrieves a list of OcConnectors with the provided 'connector_ids'

        Args:
            connector_ids (list[int]): List of connector_ids of OcConnectors

        Raises:
            OcConnectorGetError: When the connector_ids were not provided to this method
            OcConnectorGetError: When the OcConnectors could not be retrieved

        Returns:
            list[dict[str, Any]]: The OcConnectors with the given connector_ids
        """
        if not connector_ids:
            raise OcConnectorGetError("No connectorIds for Connectors provided!")

        params: dict[str, Any] = {
            "identifiers": connector_ids
        }

        return self.parse_response(
            self.oc_connector.oc_post(params, CONNECTORS_BY_IDS_URL),
            OcConnectorGetError,
            f"Failed to retrieve OpenCelium Connectors with IDs: {connector_ids}",
        )

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

        return self.parse_response(
            self.oc_connector.oc_get(f"{CONNECTOR_URL}/{connector_id}", password),
            OcConnectorGetError,
            f"Failed to retrieve OpenCelium Connector with ID: {connector_id}",
        )


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
            raise OcConnectorGetError("No title for Connector provided!")

        return self.parse_response(
            self.oc_connector.oc_get(f"{CONNECTOR_URL}?title={quote(title)}", password),
            OcConnectorGetError,
            f"Failed to retrieve OpenCelium Connector with title: {title}",
        )


    def connector_exists(self, title: str) -> bool:
        """
        Checks if a connector with the given title exists in OpenCelium

        Args:
            title (str): title of the Connector

        Raises:
            OcConnectorGetError: When the title was not provided, or the check could not be performed

        Returns:
            bool: True if it exists, else False
        """
        if not title:
            raise OcConnectorGetError("No title for Connector provided!")

        conn_resp: dict[str, Any] = self.parse_response(
            self.oc_connector.oc_get(f"{CONNECTOR_EXISTS_URL}/{quote(title)}"),
            OcConnectorGetError,
            f"Failed to check if Connector with title: {title} exists!",
        )

        return bool(conn_resp.get('result'))


    def get_all_connectors(self) -> list[dict[str, Any]] | None:
        """
        Retrieves all Connectors from OpenCelium

        Raises:
            OcConnectorGetError: When retrieving the OcConnectors fails

        Returns:
            list[dict[str, Any]] | None: All Connectors from OpenCelium, or None when the body is empty
        """
        all_connectors_response = self.oc_connector.oc_get(ALL_CONNECTORS_URL)

        if self.is_valid_response(all_connectors_response) and not all_connectors_response.text:
            return None

        return self.parse_response(
            all_connectors_response,
            OcConnectorGetError,
            "Failed to retrieve Connectors from OpenCelium!",
        )

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
        return self.parse_response(
            self.oc_connector.oc_put(params, f"{CONNECTOR_URL}/{connector_id}"),
            OcConnectorUpdateError,
            f"Failed to update Connector with ID:{connector_id} in OpenCelium!",
        )

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

    def delete_connector(self, connector_id: int) -> bool:
        """
        Deletes a Connector in OpenCelium with the given connector_id

        Args:
            connector_id (int): the connectorId of the OcConnector which should be deleted

        Returns:
            bool: True if deletion was a success else False
        """
        return self.is_valid_response(self.oc_connector.oc_delete(f"{CONNECTOR_URL}/{connector_id}"))

# ------------------------------------------------------ HELPERS ----------------------------------------------------- #

    def get_master_pw(self) -> str:
        """
        Retrieves the master password for OpenCelium (cloud version only)

        Returns:
            str: The master passwaord for OpenCelium
        """
        return self.master_pw
