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
Implementation of SystemConfigReader
"""
from logging import Logger, getLogger
from typing import Any
import threading
from requests import Response, post, get
from requests.exceptions import Timeout, RequestException

from cmdb.manager.system_manager.system_config_reader import SystemConfigReader
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

AUTH_URL = "/login"

###
# payload: dict[str, Any] = {
#     "email": email,
#     "database_name": database,
#     "config_item_count": config_item_count
# }
# -------------------------------------------------------------------------------------------------------------------- #
#                                              OpenCeliumConnector - CLASS                                             #
# -------------------------------------------------------------------------------------------------------------------- #
class OpenCeliumConnector:
    """
    Handles the OpenCelium connection
    """
    _instance: "OpenCeliumConnector" | None = None

    _initialized = False
    _lock = threading.Lock()

    def __new__(cls) -> "OpenCeliumConnector":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:  # double-checked locking
                    cls._instance = super().__new__(cls)

        return cls._instance


    def __init__(self) -> None:
        if not self._initialized:
            scr = SystemConfigReader()
            self.host = scr.get_value("host", "OpenCelium")
            self.port = int(scr.get_value("port", "OpenCelium"))
            self.protocol = scr.get_value("protocol", "OpenCelium")
            self.email = scr.get_value("email", "OpenCelium")
            self.user = scr.get_value("user", "OpenCelium")
            self.password = scr.get_value("password", "OpenCelium")
            self.base_url: str = f"{self.protocol}://{self.host}:{self.port}"
            self.jwt_token: str = None
            self._initialized = True


    def get_email(self) -> str:
        """
        TODO: document
        """
        return self.email


    def get_password(self) -> str:
        """
        TODO: document
        """
        return self.password


    def get_base_url(self) -> str:
        """
        TODO: document
        """
        return self.base_url


    def get_jwt_token(self) -> str:
        """
        TODO: document
        """
        return self.jwt_token

# ----------------------------------------------------- REQUESTS ----------------------------------------------------- #

    def oc_post(self, payload: dict[str, Any], endpoint: str, with_auth: bool = True) -> Response:
        """
        TODO: document
        """
        try:
            if not self.token_is_set and with_auth:
                self.authenticate()

            response: Response = post(
                self.build_url(endpoint),
                headers=self.get_headers(with_auth),
                json=payload,
                timeout=3
            )

            return response
        except Timeout as err:
            LOGGER.error("[oc_post] Timeout: %s!", err)
            raise err
        except RequestException as err:
            LOGGER.error("[oc_post] RequestException: %s!", err)
            raise err
        except Exception as err:
            LOGGER.error("[oc_post] Exception: %s. Type: %s!", err, type(err), exc_info=True)
            raise err


    def oc_get(self, endpoint: str) -> Response:
        """
        TODO: document
        """
        try:
            if not self.token_is_set:
                self.authenticate()

            response: Response = get(self.build_url(endpoint), headers=self.get_headers(), timeout=3)

            return response
        except Timeout as err:
            LOGGER.error("[oc_get] Timeout: %s!", err)
            raise err
        except RequestException as err:
            LOGGER.error("[oc_get] RequestException: %s!", err)
            raise err
        except Exception as err:
            LOGGER.error("[oc_get] Exception: %s. Type: %s!", err, type(err), exc_info=True)
            raise err

# ------------------------------------------------------ HELPER ------------------------------------------------------ #

    def authenticate(self) -> None:
        """
        TODO: document
        """
        payload: dict[str, str] = {
            "email": self.get_email(),
            "password": self.get_password()
        }

        response: Response = self.oc_post(payload, AUTH_URL, False)
        # LOGGER.debug(f"authenticate response: {response}")
        # LOGGER.debug(f"authenticate response headers: {response}")
        # LOGGER.debug(f"authenticate response headers: {response}")
        #TODO: Set the jwt_token from the response


    def get_headers(self, with_auth: bool = True) -> dict[str, Any]:
        """
        TODO: document
        """
        headers: dict[str, str] = {
            "Content-Type": "application/json"
        }

        if with_auth:
            headers["Authorization"] = self.jwt_token

        return headers


    def build_url(self, endpoint: str) -> str:
        """
        TODO: document
        """
        return f"{self.get_base_url()}{endpoint}"


    def token_is_set(self) -> bool:
        """
        TODO: document
        """
        return bool(self.get_jwt_token())
