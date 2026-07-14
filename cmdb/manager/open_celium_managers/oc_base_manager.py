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
Implementation of OpenCelium BaseManager
"""
import json
from logging import Logger, getLogger
from typing import Any

from requests import Response

from cmdb.database import MongoDatabaseManager

from cmdb.open_celium import OcApiConnector
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

ALL_TEMPLATES_URL: str = "/template/all"

# -------------------------------------------------------------------------------------------------------------------- #
#                                                 OcBaseManager - CLASS                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class OcBaseManager:
    """
    Manages Automations of OpenCelium
    """
    def __init__(self, dbm: MongoDatabaseManager, db_name: str) -> None:
        self.oc_connector: OcApiConnector = OcApiConnector(dbm, db_name)

# ------------------------------------------------------ HELPER ------------------------------------------------------ #

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


    def parse_response(self, response: Response, error_cls: type[Exception], error_msg: str) -> Any:
        """
        Returns the parsed JSON body of a successful OpenCelium response, else logs and raises

        Centralises the ``if is_valid_response(...): return json body else log + raise`` pattern that
        every read/create/update manager method shares.

        Args:
            response (Response): The response from OpenCelium
            error_cls (type[Exception]): The error to raise when the response is not a 2xx
            error_msg (str): The message for the raised error

        Raises:
            error_cls: When the response status code is outside 200-299

        Returns:
            Any: The parsed JSON body of the response
        """
        if self.is_valid_response(response):
            return json.loads(response.text)

        LOGGER.error("OC Error: %s", response.text)
        raise error_cls(error_msg)
