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
Implementation of SystemConfigReader
"""
import os
from logging import Logger, getLogger
from typing import Any, Optional
import threading
from requests import Response, delete, post, get, put
from requests.exceptions import Timeout, RequestException

from flask import current_app

from cmdb.database.mongo_database_manager import MongoDatabaseManager
from cmdb.manager.system_manager.system_config_reader import SystemConfigReader
from cmdb.manager.system_manager.settings_manager import SettingsManager

from cmdb.open_celium.oc_constants import OC_REQUEST_TIMEOUT

from cmdb.errors.open_celium import AuthError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

AUTH_URL = "/login"

# -------------------------------------------------------------------------------------------------------------------- #
#                                                OcApiConnector - CLASS                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class OcApiConnector:
    """
    Handles the OpenCelium connection
    """
    _lock = threading.Lock()


    def __init__(self, dbm: MongoDatabaseManager, db_name: str) -> None:
        if current_app.cloud_mode and not current_app.local_mode:
            self.host: str = os.getenv('OC_HOST')
            self.port = int(os.getenv('OC_PORT'))
            self.protocol: str = os.getenv('OC_PROTOCOL')
            self.email: str = os.getenv('OC_EMAIL')
            self.user: str = os.getenv('OC_USER')
            self.password: str = os.getenv('OC_PASSWORD')
        else:
            scr = SystemConfigReader()
            self.host: str = scr.get_value("host", "OpenCelium")
            self.port = int(scr.get_value("port", "OpenCelium"))
            self.protocol: str = scr.get_value("protocol", "OpenCelium")
            self.email: str = scr.get_value("email", "OpenCelium")
            self.user: str = scr.get_value("user", "OpenCelium")
            self.password: str = scr.get_value("password", "OpenCelium")

        self.settings_manager: SettingsManager = SettingsManager(dbm, db_name)
        self.base_url: str = f"{self.protocol}://{self.host}:{self.port}/api"

# -------------------------------------------------------------------------------------------------------------------- #

    def get_email(self) -> str:
        """
        Returns:
            str: Email of the credentials
        """
        return self.email


    def get_password(self) -> str:
        """
        Returns:
            str: password of the credentials
        """
        return self.password


    def get_base_url(self) -> str:
        """
        Returns:
            str: Base url of OpenCelium
        """
        return self.base_url


    def get_jwt_token(self) -> Optional[str]:
        """
        Returns:
            str: Jwt Token of OpenCelium
        """
        try:
            token_data: dict[str, Any] | None = self.settings_manager.get_all_values_from_section('oc_token')
            # LOGGER.debug(f"token_data: {token_data}")
            token:str = token_data.get('token')
        except Exception:
            return None

        return token

# ----------------------------------------------------- REQUESTS ----------------------------------------------------- #

    def oc_post(self, payload: dict[str, Any], endpoint: str, with_auth: bool = True) -> Response:
        """
        Handles POST requests towards OpenCelium API

        Args:
            payload (dict[str, Any]): payload for POST-request
            endpoint (str): target url
            with_auth (bool, optional): If True the 'Authorazation'-header is send. Defaults to True

        Raises:
            Timeout: When timeout treshhold is reached
            RequestException: When something went wrong with the request
            Exception: When something unexpected occurs

        Returns:
            Response: The POST response from OpenCelium
        """
        try:
            if not self.token_is_set() and with_auth:
                self.authenticate()

            response: Response = post(
                self.build_url(endpoint),
                headers=self.get_headers(with_auth),
                json=payload,
                timeout=OC_REQUEST_TIMEOUT
            )

            # LOGGER.debug("\n\n")
            # LOGGER.debug(f"[Request] method: {response.request.method}")
            # LOGGER.debug(f"[Request] url: {response.request.url}")
            # LOGGER.debug(f"[Request] headers: {response.request.headers}")
            # LOGGER.debug(f"[Request] payload: {response.request.body}\n\n")

            # If token expired or invalid → try once to recover
            if response.status_code == 403:
                LOGGER.warning("[oc_post] 403 received → trying token refresh")

                self.authenticate() # writes new token to DB

                response: Response = post(
                    self.build_url(endpoint),
                    headers=self.get_headers(with_auth),
                    json=payload,
                    timeout=OC_REQUEST_TIMEOUT
                )

            return response
        except (Timeout, RequestException) as err:
            raise err
        except Exception as err:
            LOGGER.error("[oc_post] Exception: %s. Type: %s!", err, type(err), exc_info=True)
            raise err


    def oc_get(self, endpoint: str, password: str = None) -> Response:
        """
        Handles GET requests towards OpenCelium API

        Args:
            endpoint (str): target_url

        Raises:
            Timeout: When timeout treshhold is reached
            RequestException: When something went wrong with the request
            Exception: When something unexpected occurs

        Returns:
            Response: The GET response from OpenCelium
        """
        try:
            if not self.token_is_set():
                self.authenticate()

            response: Response = get(
                self.build_url(endpoint),
                headers=self.get_headers(password=password),
                timeout=OC_REQUEST_TIMEOUT
            )

            # LOGGER.debug(f"[Response] response: {response}")
            # LOGGER.debug(f"[Response] status_code: {response.status_code}")
            # LOGGER.debug(f"[Response] headers: {response.headers}")
            # LOGGER.debug(f"[Response] body: {response.text}")

            # If token expired or invalid → try once to recover
            if response.status_code == 403:
                LOGGER.warning("[oc_get] 403 received → trying token refresh")

                self.authenticate() # writes new token to DB

                response: Response = get(
                    self.build_url(endpoint),
                    headers=self.get_headers(password=password),
                    timeout=OC_REQUEST_TIMEOUT
                )

            return response
        except (Timeout, RequestException) as err:
            raise err
        except Exception as err:
            LOGGER.error("[oc_get] Exception: %s. Type: %s!", err, type(err), exc_info=True)
            raise err


    def oc_put(self, payload: dict[str, Any], endpoint: str) -> Response:
        """
        Handles PUT requests towards OpenCelium API

        Args:
            payload (dict[str, Any]): payload for PUTs-request
            endpoint (str): target url

        Raises:
            Timeout: When timeout treshhold is reached
            RequestException: When something went wrong with the request
            Exception: When something unexpected occurs

        Returns:
            Response: The PUT response from OpenCelium
        """
        try:
            if not self.token_is_set():
                self.authenticate()

            response: Response = put(
                self.build_url(endpoint),
                headers=self.get_headers(),
                json=payload,
                timeout=OC_REQUEST_TIMEOUT
            )

            # If token expired or invalid → try once to recover
            if response.status_code == 403:
                LOGGER.warning("[oc_get] 403 received → trying token refresh")

                self.authenticate() # writes new token to DB

                response: Response = put(
                    self.build_url(endpoint),
                    headers=self.get_headers(),
                    json=payload,
                    timeout=OC_REQUEST_TIMEOUT
                )

            return response
        except (Timeout, RequestException) as err:
            raise err
        except Exception as err:
            LOGGER.error("[oc_put] Exception: %s. Type: %s!", err, type(err), exc_info=True)
            raise err


    def oc_delete(self, endpoint: str) -> Response:
        """
        Handles DELETE requests towards OpenCelium API

        Args:
            endpoint (str): target url

        Raises:
            Timeout: When timeout treshhold is reached
            RequestException: When something went wrong with the request
            Exception: When something unexpected occurs

        Returns:
            Response: The DELETE response from OpenCelium
        """
        try:
            if not self.token_is_set():
                self.authenticate()

            response: Response = delete(
                self.build_url(endpoint),
                headers=self.get_headers(),
                timeout=OC_REQUEST_TIMEOUT
            )

            # If token expired or invalid → try once to recover
            if response.status_code == 403:
                LOGGER.warning("[oc_delete] 403 received → trying token refresh")

                self.authenticate() # writes new token to DB

                response: Response = delete(
                    self.build_url(endpoint),
                    headers=self.get_headers(),
                    timeout=OC_REQUEST_TIMEOUT
                )

            return response
        except (Timeout, RequestException) as err:
            raise err
        except Exception as err:
            LOGGER.error("[oc_delete] Exception: %s. Type: %s!", err, type(err), exc_info=True)
            raise err
# ------------------------------------------------------ HELPER ------------------------------------------------------ #

    def authenticate(self) -> None:
        """
        Gets the JWT-Token for the API

        Raises:
            AuthError: When authentication failed
        """
        # LOGGER.debug("[authenticate] called")
        with self._lock:
            payload: dict[str, str] = {
                "email": self.get_email(),
                "password": self.get_password(),
            }

            response: Response = self.oc_post(payload, AUTH_URL, False)

            if response.status_code == 200:
                oc_token_data = {
                    "_id": "oc_token",
                    "token":  response.headers['Authorization']
                }

                self.settings_manager.write(_id='oc_token', data=oc_token_data)
            else:
                raise AuthError("Authentication in OpenCelium failed!")


    def get_headers(self, with_auth: bool = True, password: str = None) -> dict[str, Any]:
        """
        Sets the headers for requests towards OpenCelium

        Args:
            with_auth (bool, optional): If True the 'Authorization' header will be set. Defaults to True.

        Returns:
            dict[str, Any]: The headers for the request
        """
        headers: dict[str, str] = {
            "Content-Type": "application/json"
        }

        if with_auth:
            headers["Authorization"] = self.get_jwt_token()
        if password:
            headers["X-Master-Password"] = password

        return headers


    def build_url(self, endpoint: str) -> str:
        """
        Build the URL for requests towards OpenCelium

        Args:
            endpoint (str): target URL (excluding the base URL)

        Returns:
            str: The complete target URL
        """
        return f"{self.get_base_url()}{endpoint}"


    def token_is_set(self) -> bool:
        """
        Checks if the API JWT-Token is already retrieved from OpenCelium

        Returns:
            bool: True if a JWT-Token is set else False
        """
        return bool(self.get_jwt_token())
