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
Implementation of OcApiConnector
"""
import os
from logging import Logger, getLogger
from typing import Any
from requests import Response, request
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
# Maximum number of token-refresh attempts before giving up on a 403 loop
MAX_AUTH_RETRIES: int = 6

# -------------------------------------------------------------------------------------------------------------------- #
#                                                OcApiConnector - CLASS                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class OcApiConnector:
    """
    Handles the OpenCelium connection
    """
    def __init__(self, dbm: MongoDatabaseManager, db_name: str) -> None:
        if current_app.cloud_mode and not current_app.local_mode:
            self.host: str = os.getenv('OC_HOST')
            port: str | None = os.getenv('OC_PORT')
            self.protocol: str = os.getenv('OC_PROTOCOL')
            self.email: str = os.getenv('OC_EMAIL')
            self.user: str = os.getenv('OC_USER')
            self.password: str = os.getenv('OC_PASSWORD')

            if not all([self.host, port, self.protocol, self.email, self.user, self.password]):
                raise ValueError(
                    "Missing OpenCelium connection env variables "
                    "(OC_HOST/OC_PORT/OC_PROTOCOL/OC_EMAIL/OC_USER/OC_PASSWORD)!"
                )

            self.port = int(port)
            self.base_url: str = f"{self.protocol}://{self.host}:{self.port}"

        else:
            scr = SystemConfigReader()
            self.host: str = scr.get_value("host", "OpenCelium")
            self.port = int(scr.get_value("port", "OpenCelium"))
            self.protocol: str = scr.get_value("protocol", "OpenCelium")
            self.email: str = scr.get_value("email", "OpenCelium")
            self.user: str = scr.get_value("user", "OpenCelium")
            self.password: str = scr.get_value("password", "OpenCelium")
            self.base_url: str = f"{self.protocol}://{self.host}:{self.port}/api"

        self.settings_manager: SettingsManager = SettingsManager(dbm, db_name)

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


    def get_jwt_token(self) -> str | None:
        """
        Returns:
            str: Jwt Token of OpenCelium
        """
        try:
            token_data: dict[str, Any] | None = self.settings_manager.get_all_values_from_section('oc_token')
            token: str = token_data.get('token')
        except Exception:
            return None

        return token

# ----------------------------------------------------- REQUESTS ----------------------------------------------------- #

    def _send(
            self,
            method: str,
            endpoint: str,
            payload: dict[str, Any] | None,
            with_auth: bool,
            password: str | None,
        ) -> Response:
        """
        Dispatches a single HTTP request towards OpenCelium (no auth/retry logic)

        Args:
            method (str): The HTTP method ('GET', 'POST', 'PUT', 'DELETE')
            endpoint (str): The target endpoint (excluding the base URL)
            payload (dict[str, Any] | None): The JSON body, or None for bodyless requests
            with_auth (bool): Whether to send the 'Authorization' header
            password (str | None): Optional master password sent as 'X-Master-Password'

        Returns:
            Response: The raw response from OpenCelium
        """
        return request(
            method,
            self.build_url(endpoint),
            headers=self.get_headers(with_auth, password),
            json=payload,
            timeout=OC_REQUEST_TIMEOUT,
        )


    def _request(
            self,
            method: str,
            endpoint: str,
            payload: dict[str, Any] | None = None,
            with_auth: bool = True,
            password: str | None = None,
            counter: int = 0,
        ) -> Response:
        """
        Sends an authenticated request towards OpenCelium, refreshing the token once on a 403

        Ensures a token is present before the call (when ``with_auth``), then retries the request a
        single time after re-authenticating if OpenCelium answers 403 (expired/invalid token), up to
        MAX_AUTH_RETRIES nested attempts

        Args:
            method (str): The HTTP method ('GET', 'POST', 'PUT', 'DELETE')
            endpoint (str): The target endpoint (excluding the base URL)
            payload (dict[str, Any] | None): The JSON body, or None for bodyless requests
            with_auth (bool): Whether the request carries the 'Authorization' header
            password (str | None): Optional master password sent as 'X-Master-Password'
            counter (int): The current authentication-retry depth

        Raises:
            Timeout: When the timeout threshold is reached
            RequestException: When the request fails at the transport level

        Returns:
            Response: The response from OpenCelium
        """
        try:
            if with_auth and not self.token_is_set():
                counter += 1
                self.authenticate(counter)

            response: Response = self._send(method, endpoint, payload, with_auth, password)

            # If the token expired or is invalid -> try once to recover
            if response.status_code == 403 and counter < MAX_AUTH_RETRIES:
                LOGGER.warning("[_request] 403 received -> refreshing token (attempt %s)", counter)
                self.authenticate(counter)  # writes new token to DB
                response = self._send(method, endpoint, payload, with_auth, password)

            return response
        except (Timeout, RequestException) as err:
            raise err
        except Exception as err:
            LOGGER.error("[_request] %s %s failed: %s. Type: %s!", method, endpoint, err, type(err), exc_info=True)
            raise err


    def oc_post(
            self,
            payload: dict[str, Any],
            endpoint: str,
            with_auth: bool = True,
            counter: int = 0,
        ) -> Response:
        """
        Handles POST requests towards the OpenCelium API

        Args:
            payload (dict[str, Any]): payload for the POST request
            endpoint (str): target url
            with_auth (bool, optional): If True the 'Authorization' header is sent. Defaults to True

        Returns:
            Response: The POST response from OpenCelium
        """
        return self._request('POST', endpoint, payload=payload, with_auth=with_auth, counter=counter)


    def oc_get(self, endpoint: str, password: str = None, counter: int = 0) -> Response:
        """
        Handles GET requests towards the OpenCelium API

        Args:
            endpoint (str): target url
            password (str, optional): Optional master password sent as 'X-Master-Password'

        Returns:
            Response: The GET response from OpenCelium
        """
        return self._request('GET', endpoint, password=password, counter=counter)


    def oc_put(self, payload: dict[str, Any], endpoint: str, counter: int = 0) -> Response:
        """
        Handles PUT requests towards the OpenCelium API

        Args:
            payload (dict[str, Any]): payload for the PUT request
            endpoint (str): target url

        Returns:
            Response: The PUT response from OpenCelium
        """
        return self._request('PUT', endpoint, payload=payload, counter=counter)


    def oc_delete(self, endpoint: str, counter: int = 0) -> Response:
        """
        Handles DELETE requests towards the OpenCelium API

        Args:
            endpoint (str): target url

        Returns:
            Response: The DELETE response from OpenCelium
        """
        return self._request('DELETE', endpoint, counter=counter)

# ------------------------------------------------------ HELPER ------------------------------------------------------ #

    def authenticate(self, counter: int = 0) -> None:
        """
        Gets the JWT-Token for the API

        Raises:
            AuthError: When authentication failed
        """
        payload: dict[str, str] = {
            "email": self.get_email(),
            "password": self.get_password(),
        }

        counter += 1
        response: Response = self.oc_post(payload, AUTH_URL, False, counter)

        if response.status_code == 200:
            oc_token_data = {
                "_id": "oc_token",
                "token":  response.headers['Authorization']
            }

            self.settings_manager.write(_id='oc_token', data=oc_token_data)
        else:
            LOGGER.error("OC Auth error: [%s] %s", response.status_code, response.text)
            raise AuthError("Authentication in OpenCelium failed. Confirm your credentails!")


    def get_headers(self, with_auth: bool = True, password: str = None) -> dict[str, Any]:
        """
        Sets the headers for requests towards OpenCelium

        Args:
            with_auth (bool, optional): If True the 'Authorization' header will be set. Defaults to True.
            password (str, optional): If set, sent as the 'X-Master-Password' header

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
