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
All API routes for OpenCelium connectors
"""
from logging import Logger, getLogger
from typing import Any

from flask import abort#, request
from werkzeug import Response
# from werkzeug.exceptions import HTTPException

from cmdb.manager import OcConnectorManager

from cmdb.models.user_model import CmdbUser
from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.route_utils import insert_request_user, verify_api_access, handle_oc_errors
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.rest_api.responses import DefaultResponse

from cmdb.errors.open_celium.connector import (
    OcConnectorCreateError,
    OcConnectorGetError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

oc_connectors_blueprint = APIBlueprint('oc_connectors', __name__)

# --------------------------------------------------- CRUD - CREATE -------------------------------------------------- #

@oc_connectors_blueprint.route('/connectors', methods=['POST'])
@handle_oc_errors("creating an OpenCelium Connector!")
@oc_connectors_blueprint.parse_request_parameters()
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
def create_oc_connector(params: dict[str, Any], request_user: CmdbUser) -> Response:
    """
    HTTP `POST` route to create an OcConnector into the database

    Args:
        request_user (CmdbUser): User requesting this data

    Returns:
        dict[str, Any]: The created OcConnector
    """
    try:
        oc_connector_manager: OcConnectorManager = OcConnectorManager()

        create_oc_connector_response: dict[str, Any] = oc_connector_manager.create_connector(params)

        return DefaultResponse(create_oc_connector_response).make_response()
    except OcConnectorCreateError as err:
        LOGGER.error("[create_oc_connector] OcConnectorCreateError: %s", err, exc_info=True)
        abort(400, "Failed to create an OpenCelium Connector!")

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

@oc_connectors_blueprint.route('/connectors', methods=['GET', 'HEAD'])
@handle_oc_errors("retrieving OpenCelium Connectors!")
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
def get_all_oc_connectors(request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route for getting multiple OcConnectors

    Args:
        request_user (CmdbUser): User requesting this data

    Returns:
        list[dict[str, Any]]: All OcConnectors from OpenCelium
    """
    try:
        oc_connector_manager: OcConnectorManager = OcConnectorManager()

        connectors: list[dict[str, Any]] = oc_connector_manager.get_all_connectors()

        # LOGGER.debug(f"all connectors: {connectors}")

        return DefaultResponse(connectors).make_response()
    except OcConnectorGetError as err:
        LOGGER.error("[get_all_oc_connectors] OcConnectorGetError: %s.", err, exc_info=True)
        abort(500, "Failed to retrieve OpenCelium Connectors!")
