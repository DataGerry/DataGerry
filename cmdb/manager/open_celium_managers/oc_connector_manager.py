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
from logging import Logger, getLogger
from typing import Any

from requests import Response

from cmdb.open_celium import OcApiConnector

from cmdb.errors.open_celium.connector import OcConnectorCreateError, OcConnectorGetError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

POST_CONNECTOR_URL: str = "/connector"
GET_ALL_CONNECTORS_URL: str = "/connector/all"

# -------------------------------------------------------------------------------------------------------------------- #
#                                              OcConnectorManager - CLASS                                              #
# -------------------------------------------------------------------------------------------------------------------- #
class OcConnectorManager:
    """
    Manages Connectors of OpenCelium
    """
    def __init__(self) -> None:
        self.oc_connector: OcApiConnector = OcApiConnector()

# --------------------------------------------------- CRUD - CREATE -------------------------------------------------- #

    def create_connector(self, params: dict[str, Any]) -> dict[str, Any]:
        """
        TODO: document
        """
        create_connector_response: Response = self.oc_connector.oc_post(params, POST_CONNECTOR_URL)

        if create_connector_response.status_code >= 200 and create_connector_response.status_code < 300:
            return create_connector_response.text

        raise OcConnectorCreateError("Failed to create the Connector in OpenCelium!")

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

    def get_all_connectors(self) -> list[dict[str, Any]]:
        """
        TODO: document
        """
        all_connectors_response: Response = self.oc_connector.oc_get(GET_ALL_CONNECTORS_URL)

        if all_connectors_response.status_code >= 200 and all_connectors_response.status_code < 300:
            return all_connectors_response.text

        raise OcConnectorGetError("Failed to retrieve Connectors from OpenCelium!")
