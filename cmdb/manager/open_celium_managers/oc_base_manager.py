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
Implementation of OpenCelium BaseManager
"""
import json
from logging import Logger, getLogger
from typing import Any
from requests import Response

from cmdb.open_celium import OcApiConnector

from cmdb.errors.open_celium import OcGetError
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
    def __init__(self) -> None:
        self.oc_connector: OcApiConnector = OcApiConnector()

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
