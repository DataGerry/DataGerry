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
All API routes for OpenCelium Connections
"""
from logging import Logger, getLogger
from typing import Any

from flask import abort, request
from werkzeug import Response

from cmdb.manager import OcConnectionManager

from cmdb.models.user_model import CmdbUser
from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.route_utils import insert_request_user, verify_api_access, handle_oc_errors
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.rest_api.responses import DefaultResponse

from cmdb.errors.open_celium.connection import (
    OcConnectionCreateError,
    OcConnectionGetError,
    OcConnectionUpdateError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

oc_connections_blueprint = APIBlueprint('oc_connections', __name__)

# --------------------------------------------------- CRUD - CREATE -------------------------------------------------- #

@oc_connections_blueprint.route('/connections', methods=['POST'])
@handle_oc_errors("creating an OpenCelium Connection!")
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
def create_oc_connection(request_user: CmdbUser) -> Response:
    """
    **POST** route to create an OcConnection in OpenCelium

    Args:
        params (dict[str, Any]): the data of the new OcConnection
        request_user (CmdbUser): User requesting this data

    Returns:
        dict[str, Any]: The created OcConnection
    """
    try:
        oc_connection_manager: OcConnectionManager = OcConnectionManager()

        params: dict[str, Any] = request.json

        create_oc_connection_response: dict[str, Any] = oc_connection_manager.create_connection(params)

        return DefaultResponse(create_oc_connection_response).make_response()
    except OcConnectionCreateError as err:
        LOGGER.error("[create_oc_connection] %s: %s", type(err).__name__, err, exc_info=True)
        abort(400, "Failed to create an OpenCelium Connection!")

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

@oc_connections_blueprint.route('/connections/<int:connection_id>', methods=['GET', 'HEAD'])
@handle_oc_errors("retrieving the OpenCelium Connection!")
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
def get_oc_connection(request_user: CmdbUser, connection_id: int) -> Response:
    """
    GET/HEAD route to retrive an OcConnection with the given connection_id

    Args:
        request_user (CmdbUser): User requesting this data
        connection_id (int): connectionId of the OcConnection

    Returns:
        dict[str, Any]: The OcConnection from OpenCelium
    """
    try:
        oc_connection_manager: OcConnectionManager = OcConnectionManager()

        connection: dict[str, Any] = oc_connection_manager.get_connection(connection_id)

        # LOGGER.debug(f"connection: {connection}")

        return DefaultResponse(connection).make_response()
    except OcConnectionGetError as err:
        LOGGER.error("[get_oc_connection] %s: %s", type(err).__name__, err, exc_info=True)
        abort(500, f"Failed to retrieve OpenCelium Connection with ID:{connection_id}!")

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

@oc_connections_blueprint.route('/connections/<int:connection_id>', methods=['PUT'])
@handle_oc_errors("updating an OpenCelium Connection!")
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
def update_oc_connection(request_user: CmdbUser, connection_id: int) -> Response:
    """
    **PUT** route to update an OcConnection

    Args:
        params (dict[str, Any]): new data of the OcConnection
        request_user (CmdbUser): User requesting this data
        connection_id (int): the connection_id of the OcConnection

    Returns:
        dict[str, Any]: The updated OcConnection
    """
    try:
        oc_connection_manager: OcConnectionManager = OcConnectionManager()

        params: dict[str, Any] = request.json

        updated_oc_connection_response: dict[str, Any] = oc_connection_manager.update_connection(params, connection_id)

        return DefaultResponse(updated_oc_connection_response).make_response()
    except OcConnectionUpdateError as err:
        LOGGER.error("[update_oc_connection] %s: %s", type(err), err, exc_info=True)
        abort(400, f"Failed to update the OpenCelium Connection with ID: {connection_id}!")
