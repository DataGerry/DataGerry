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
Implementation of DataGerry Service-Portal Manager
"""
import os
import json
from logging import Logger, getLogger
from typing import Any
from requests import Response, delete, post, get

from flask import current_app

from cmdb.open_celium.oc_constants import OC_REQUEST_TIMEOUT

from cmdb.errors.security import (
    NoAccessTokenError,
)

# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

CHECK_MASTER_PW_URL: str = "/datagerry/check/master-password"

CONNECTOR_ID_URL: str = "/datagerry/opencelium/entity/connector"
GET_CONNECTOR_IDS: str = f"{CONNECTOR_ID_URL}/list"

CONNECTION_ID_URL: str = "/datagerry/opencelium/entity/connection"
GET_CONNECTION_IDS: str = f"{CONNECTION_ID_URL}/list"

SCHEDULER_ID_URL: str = "/datagerry/opencelium/entity/scheduler"
GET_SCHEDULER_IDS: str = f"{SCHEDULER_ID_URL}/list"

# -------------------------------------------------------------------------------------------------------------------- #
#                                            DgServicePortalManager - CLASS                                            #
# -------------------------------------------------------------------------------------------------------------------- #
class DgServicePortalManager:
    """
    Manages interactions with the DataGerry ServicePortal
    """
    def __init__(self) -> None:
        """
        Initialises the DgServicePortalManager
        """
        self.x_api_key: str = None
        self.x_access_token: str = None
        self.base_url: str = None

        if current_app.cloud_mode and not current_app.local_mode:
            self.x_access_token = os.getenv("X-ACCESS-TOKEN")

            if not self.x_access_token:
                raise NoAccessTokenError("No x-access-token provided!")

            self.base_url = os.getenv("DG_SP_BASE_URL")

            if not self.base_url:
                raise NoAccessTokenError("No base url for Service Portal provided!")


    def get_headers(self, password: str = None) -> dict[str, str]:
        """
        Retrieves the headers for DG-SP API calls

        Returns:
            dict[str, str]: The headers dictionary
        """
        headers: dict[str, str] = {
            "x-access-token": self.x_access_token
        }

        if password:
            headers['x-master-password'] = password

        return headers


    def create_full_url(self, endpoint: str) -> str:
        """
        Builds the full URL to the DG Service Portal for a request

        Args:
            endpoint (str): the endpoint of the request

        Returns:
            str: the full url for the request
        """
        return f"{self.base_url}{endpoint}"

# ---------------------------------------------------- CRUD - BASE --------------------------------------------------- #

    def sp_post(self, target:str, payload: dict[str, Any], password: str = None) -> Response:
        """
        Handles POST requests towards the DG ServicePortal

        Args:
            target (str): target URL of POST request
            payload (dict[str, Any]): payload for the POST request

        Returns:
            Response: The response for the POST request
        """
        response: Response = post(
            self.create_full_url(target),
            headers=self.get_headers(password),
            json=payload,
            timeout=OC_REQUEST_TIMEOUT
        )

        return response


    def sp_get(self, target:str) -> Response:
        """
        Handles GET requests towards the DG ServicePortal

        Args:
            target (str): target URL of GET request

        Returns:
            Response: The response for the GET request
        """
        response: Response = get(
            self.create_full_url(target),
            headers=self.get_headers(),
            timeout=OC_REQUEST_TIMEOUT
        )

        return response


    def sp_delete(self, target:str, payload: dict[str, Any]) -> Response:
        """
        Handles DELETE requests towards the DG ServicePortal

        Args:
            target (str): target URL of DELETE request
            payload (dict[str, Any]): payload for the POST request

        Returns:
            Response: The response for the DELETE request
        """
        response: Response = delete(
            self.create_full_url(target),
            headers=self.get_headers(),
            json=payload,
            timeout=OC_REQUEST_TIMEOUT
        )

        return response

# -------------------------------------------------- MASTER PASSWORD ------------------------------------------------- #

    def check_master_pw(self, password: str, email: str, db_name: str) -> bool:
        """
        Checks the custom master password

        Args:
            password (str): the password provided by user
            email (str): email of the user
            db_name (str): database name of the user

        Returns:
            bool: True if password is correct, else False
        """
        payload: dict[str, Any] = {
                "userEmail": email,
                "databaseName": db_name
        }

        response: Response = self.sp_post(CHECK_MASTER_PW_URL, payload, password)

        if self.is_valid_response(response):
            return True

        return False

# ------------------------------------------------ CONNECTOR FUNCTIONS ----------------------------------------------- #

    def save_connector_id(self, connector_id: int, email: str, db_name: str) -> bool:
        """
        Saves the connectorId in DG Service Portal for the user

        Args:
            connector_id (int): connectorId of OcScheduler
            email (str): email of the user
            db_name (str): database name of the user

        Returns:
            bool: True if the ID got saved, else False
        """
        payload: dict[str, Any] = {
                "id": connector_id,
                "userEmail": email,
                "databaseName": db_name
        }

        response: Response = self.sp_post(CONNECTOR_ID_URL, payload)

        if self.is_valid_response(response):
            return True

        return False


    def get_connector_ids(self, email: str, db_name: str) -> list[int]:
        """
        Retrieves all connectorIds from DG Service Portal for the user

        Args:
            email (str): email of the user
            db_name (str): database name of the user

        Returns:
            list[int]: All connectorIds
        """
        connections_resp: Response = self.sp_get(f"{GET_CONNECTOR_IDS}?userEmail={email}&databaseName={db_name}")

        if self.is_valid_response(connections_resp):
            data: dict[str, Any] = json.loads(connections_resp.text)
            return data['ids']

        return False


    def delete_connector_id(self, connector_id: int, email: str, db_name: str) -> bool:
        """
        Delete the connectorId in DG Service Portal for the user

        Args:
            connector_id (int): connectorId of OcConnector
            email (str): email of the user
            db_name (str): database name of the user

        Returns:
            bool: True if the ID got deleted, else False
        """
        payload: dict[str, Any] = {
                "userEmail": email,
                "databaseName": db_name
        }

        response: Response = self.sp_delete(f"{CONNECTOR_ID_URL}/{connector_id}", payload)

        if self.is_valid_response(response):
            return True

        return False


    def check_connector_in_sub(self, connector_id: int, email: str, db_name: str) -> bool:
        """
        Checks if a connectorId belongs to the users subscription

        Args:
            connector_id (int): target connectorId
            email (str): users email
            db_name (str): user database name

        Returns:
            bool: True if connectorId belongs to the users subscription else False
        """
        connector_ids: list[int] = self.get_connector_ids(email, db_name)

        return connector_id in connector_ids

# ----------------------------------------------- CONNECTION FUNCTIONS ----------------------------------------------- #

    def save_connection_id(self, connection_id: int, email: str, db_name: str) -> bool:
        """
        Saves the connectionId in DG Service Portal for the user

        Args:
            connection_id (int): connectionId of OcScheduler
            email (str): email of the user
            db_name (str): database name of the user

        Returns:
            bool: True if the ID got saved, else False
        """
        payload: dict[str, Any] = {
                "id": connection_id,
                "userEmail": email,
                "databaseName": db_name
        }

        response: Response = self.sp_post(CONNECTION_ID_URL, payload)

        if self.is_valid_response(response):
            return True

        return False


    def get_connection_ids(self, email: str, db_name: str) -> list[int]:
        """
        Retrieves all connectionIds from DG Service Portal for the user

        Args:
            email (str): email of the user
            db_name (str): database name of the user

        Returns:
            list[int]: All connectionIds
        """
        connections_resp: Response = self.sp_get(f"{GET_CONNECTION_IDS}?userEmail={email}&databaseName={db_name}")

        if self.is_valid_response(connections_resp):
            data: dict[str, Any] = json.loads(connections_resp.text)
            return data['ids']

        return False


    def delete_connection_id(self, connection_id: int, email: str, db_name: str) -> bool:
        """
        Delete the connectionId in DG Service Portal for the user

        Args:
            connection_id (int): connectionId of OcConnection
            email (str): email of the user
            db_name (str): database name of the user

        Returns:
            bool: True if the ID got deleted, else False
        """
        payload: dict[str, Any] = {
                "userEmail": email,
                "databaseName": db_name
        }

        response: Response = self.sp_delete(f"{CONNECTION_ID_URL}/{connection_id}", payload)

        if self.is_valid_response(response):
            return True

        return False


    def check_connection_in_sub(self, connection_id: int, email: str, db_name: str) -> bool:
        """
        Checks if a connectionId belongs to the users subscription

        Args:
            connection_id (int): target connectionId
            email (str): users email
            db_name (str): user database name

        Returns:
            bool: True if connectionId belongs to the users subscription else False
        """
        connection_ids: list[int] = self.get_connection_ids(email, db_name)

        return connection_id in connection_ids

# ------------------------------------------------ SCHEDULER FUNCTIONS ----------------------------------------------- #

    def save_scheduler_id(self, scheduler_id: int, email: str, db_name: str) -> bool:
        """
        Saves the schedulerId in DG Service Portal for the user

        Args:
            scheduler_id (int): schedulerId of OcScheduler
            email (str): email of the user
            db_name (str): database name of the user

        Returns:
            bool: True if the ID got saved, else False
        """
        payload: dict[str, Any] = {
                "id": scheduler_id,
                "userEmail": email,
                "databaseName": db_name
        }

        response: Response = self.sp_post(SCHEDULER_ID_URL, payload)

        if self.is_valid_response(response):
            return True

        return False


    def get_scheduler_ids(self, email: str, db_name: str) -> list[int]:
        """
        Retrieves all schedulerIds from DG Service Portal for the user

        Args:
            email (str): email of the user
            db_name (str): database name of the user

        Returns:
            list[int]: All Ids
        """
        schedulers_response: Response = self.sp_get(f"{GET_SCHEDULER_IDS}?userEmail={email}&databaseName={db_name}")

        if self.is_valid_response(schedulers_response):
            data: dict[str, Any] = json.loads(schedulers_response.text)
            return data['ids']

        return False


    def delete_scheduler_id(self, scheduler_id: int, email: str, db_name: str) -> bool:
        """
        Delete the schedulerId in DG Service Portal for the user

        Args:
            scheduler_id (int): schedulerId of OcScheduler
            email (str): email of the user
            db_name (str): database name of the user

        Returns:
            bool: True if the ID got deleted, else False
        """
        payload: dict[str, Any] = {
                "userEmail": email,
                "databaseName": db_name
        }

        response: Response = self.sp_delete(f"{SCHEDULER_ID_URL}/{scheduler_id}", payload)

        if self.is_valid_response(response):
            return True

        return False


    def check_scheduler_in_sub(self, scheduler_id: int, email: str, db_name: str) -> bool:
        """
        Checks if a schedulerId belongs to the users subscription

        Args:
            scheduler_id (int): target schedulerId
            email (str): users email
            db_name (str): user database name

        Returns:
            bool: True if schedulerId belongs to the users subscription else False
        """
        scheduler_ids: list[int] = self.get_scheduler_ids(email, db_name)

        return scheduler_id in scheduler_ids

# ------------------------------------------------- HELPER FUNCTIONS ------------------------------------------------- #

    def is_valid_response(self, response: Response) -> bool:
        """
        Determine whether the OpenCelium response indicates success.

        A response is considered valid if its HTTP status code is in the
        range 200-299 (inclusive). Any status code outside this range is
        treated as invalid.

        Args:
            Response: A response from OpenCelium

        Returns:
            bool: True if the response status code is between 200 and 299,
                False otherwise.
        """
        return response.status_code >= 200 and response.status_code < 300
