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
from http import HTTPStatus
from logging import Logger, getLogger
from typing import Any
from requests import Response, request
from requests.exceptions import Timeout, RequestException

from flask import current_app

from cmdb.database.mongo_database_manager import MongoDatabaseManager
from cmdb.manager.system_manager.system_config_reader import SystemConfigReader
from cmdb.manager.system_manager.settings_manager import SettingsManager

from cmdb.open_celium.oc_constants import (
    OC_REQUEST_TIMEOUT,
    OC_AUTH_URL,
    MAX_AUTH_RETRIES,
    OC_TOKEN_SECTION,
    OC_TOKEN_KEY,
    OC_HEADER_AUTHORIZATION,
    OC_HEADER_MASTER_PASSWORD,
    OC_HEADER_CONTENT_TYPE,
    OC_CONTENT_TYPE_JSON,
    OC_CONFIG_SECTION,
    OC_CONFIG_BASE_URL_KEY,
    OcConfigKey,
)

from cmdb.errors.open_celium import AuthError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                OcApiConnector - CLASS                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class OcApiConnector:
    """
    Handles the OpenCelium connection
    """
    def __init__(self, dbm: MongoDatabaseManager, db_name: str) -> None:
        """
        Initialises the OcApiConnector

        The OpenCelium connection settings come from environment variables in cloud (non-local) mode and
        from the `[OpenCelium]` config section otherwise; the resolved values are assigned as instance
        attributes and the token cache is opened via the SettingsManager.

        Args:
            dbm (MongoDatabaseManager): Database interaction manager (for the token settings)
            db_name (str): The database the token is cached in

        Raises:
            ValueError: If cloud mode is active but the OpenCelium connection env variables are incomplete
        """
        config: dict[str, Any] = (
            self._load_cloud_config() if current_app.cloud_mode and not current_app.local_mode
            else self._load_local_config()
        )

        self.host: str = config[OcConfigKey.HOST]
        self.port: int = config[OcConfigKey.PORT]
        self.protocol: str = config[OcConfigKey.PROTOCOL]
        self.email: str = config[OcConfigKey.EMAIL]
        self.user: str = config[OcConfigKey.USER]
        self.password: str = config[OcConfigKey.PASSWORD]
        self.base_url: str = config[OC_CONFIG_BASE_URL_KEY]

        self.settings_manager: SettingsManager = SettingsManager(dbm, db_name)


    @staticmethod
    def _load_cloud_config() -> dict[str, Any]:
        """
        Resolves the OpenCelium connection config from environment variables (cloud mode)

        Returns:
            dict[str, Any]: The connection config (host, port, protocol, email, user, password, base_url)

        Raises:
            ValueError: If any of the required OpenCelium env variables is missing
        """
        host = os.getenv('OC_HOST')
        port = os.getenv('OC_PORT')
        protocol = os.getenv('OC_PROTOCOL')
        email = os.getenv('OC_EMAIL')
        user = os.getenv('OC_USER')
        password = os.getenv('OC_PASSWORD')

        if not all([host, port, protocol, email, user, password]):
            raise ValueError(
                "Missing OpenCelium connection env variables "
                "(OC_HOST/OC_PORT/OC_PROTOCOL/OC_EMAIL/OC_USER/OC_PASSWORD)!"
            )

        return {
            OcConfigKey.HOST.value: host,
            OcConfigKey.PORT.value: int(port),
            OcConfigKey.PROTOCOL.value: protocol,
            OcConfigKey.EMAIL.value: email,
            OcConfigKey.USER.value: user,
            OcConfigKey.PASSWORD.value: password,
            OC_CONFIG_BASE_URL_KEY: f"{protocol}://{host}:{int(port)}",
        }


    @staticmethod
    def _load_local_config() -> dict[str, Any]:
        """
        Resolves the OpenCelium connection config from the `[OpenCelium]` config section (on-prem mode)

        Returns:
            dict[str, Any]: The connection config (host, port, protocol, email, user, password, base_url)
        """
        scr = SystemConfigReader()
        host = scr.get_value(OcConfigKey.HOST, OC_CONFIG_SECTION)
        port = int(scr.get_value(OcConfigKey.PORT, OC_CONFIG_SECTION))
        protocol = scr.get_value(OcConfigKey.PROTOCOL, OC_CONFIG_SECTION)

        return {
            OcConfigKey.HOST.value: host,
            OcConfigKey.PORT.value: port,
            OcConfigKey.PROTOCOL.value: protocol,
            OcConfigKey.EMAIL.value: scr.get_value(OcConfigKey.EMAIL, OC_CONFIG_SECTION),
            OcConfigKey.USER.value: scr.get_value(OcConfigKey.USER, OC_CONFIG_SECTION),
            OcConfigKey.PASSWORD.value: scr.get_value(OcConfigKey.PASSWORD, OC_CONFIG_SECTION),
            OC_CONFIG_BASE_URL_KEY: f"{protocol}://{host}:{port}/api",
        }

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
        Reads the cached OpenCelium JWT token from the settings

        Returns:
            str | None: The JWT token of OpenCelium, or None if it is not cached / cannot be read
        """
        try:
            token_data: dict[str, Any] | None = self.settings_manager.get_all_values_from_section(OC_TOKEN_SECTION)
            token: str = token_data.get(OC_TOKEN_KEY)
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
        Sends an authenticated request towards OpenCelium, refreshing the token on a 403

        Ensures a token is present before the call (when ``with_auth``), then, if OpenCelium answers
        403 (expired/invalid token), re-authenticates and re-sends once at this level. Because
        ``authenticate`` itself issues a request, a persistently rejected login recurses through this
        method up to ``MAX_AUTH_RETRIES`` attempts before giving up (raising AuthError). It is always
        bounded by ``counter``.

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
            if response.status_code == HTTPStatus.FORBIDDEN and counter < MAX_AUTH_RETRIES:
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
            counter (int, optional): The current authentication-retry depth. Defaults to 0

        Returns:
            Response: The POST response from OpenCelium
        """
        return self._request('POST', endpoint, payload=payload, with_auth=with_auth, counter=counter)


    def oc_get(self, endpoint: str, password: str | None = None, counter: int = 0) -> Response:
        """
        Handles GET requests towards the OpenCelium API

        Args:
            endpoint (str): target url
            password (str | None, optional): Optional master password sent as 'X-Master-Password'
            counter (int, optional): The current authentication-retry depth. Defaults to 0

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
            counter (int, optional): The current authentication-retry depth. Defaults to 0

        Returns:
            Response: The PUT response from OpenCelium
        """
        return self._request('PUT', endpoint, payload=payload, counter=counter)


    def oc_delete(self, endpoint: str, counter: int = 0) -> Response:
        """
        Handles DELETE requests towards the OpenCelium API

        Args:
            endpoint (str): target url
            counter (int, optional): The current authentication-retry depth. Defaults to 0

        Returns:
            Response: The DELETE response from OpenCelium
        """
        return self._request('DELETE', endpoint, counter=counter)

# ------------------------------------------------------ HELPER ------------------------------------------------------ #

    def authenticate(self, counter: int = 0) -> None:
        """
        Authenticates against OpenCelium and caches the returned JWT token

        Posts the credentials to the login endpoint and, on success, stores the token from the
        response's Authorization header via the SettingsManager.

        Args:
            counter (int): The current authentication-retry depth (bounds the token-refresh recursion)

        Raises:
            AuthError: When authentication fails or the successful response carries no token
        """
        payload: dict[str, str] = {
            "email": self.get_email(),
            "password": self.get_password(),
        }

        counter += 1
        response: Response = self.oc_post(payload, OC_AUTH_URL, False, counter)

        if response.status_code == HTTPStatus.OK:
            token: str | None = response.headers.get(OC_HEADER_AUTHORIZATION)

            if not token:
                LOGGER.error("[authenticate] OC login succeeded but returned no Authorization token")
                raise AuthError("Authentication in OpenCelium failed. No token was returned!")

            oc_token_data = {
                "_id": OC_TOKEN_SECTION,
                OC_TOKEN_KEY: token
            }

            self.settings_manager.write(_id=OC_TOKEN_SECTION, data=oc_token_data)
        else:
            LOGGER.error("OC Auth error: [%s] %s", response.status_code, response.text)
            raise AuthError("Authentication in OpenCelium failed. Confirm your credentails!")


    def get_headers(self, with_auth: bool = True, password: str | None = None) -> dict[str, Any]:
        """
        Sets the headers for requests towards OpenCelium

        Args:
            with_auth (bool, optional): If True the 'Authorization' header will be set. Defaults to True.
            password (str | None, optional): If set, sent as the 'X-Master-Password' header

        Returns:
            dict[str, Any]: The headers for the request
        """
        headers: dict[str, str] = {
            OC_HEADER_CONTENT_TYPE: OC_CONTENT_TYPE_JSON
        }

        if with_auth:
            token: str | None = self.get_jwt_token()
            # Only attach the header when a token is actually available (a None value breaks requests)
            if token:
                headers[OC_HEADER_AUTHORIZATION] = token
        if password:
            headers[OC_HEADER_MASTER_PASSWORD] = password

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
