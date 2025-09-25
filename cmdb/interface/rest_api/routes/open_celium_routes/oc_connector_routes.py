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
All API routes for OpenCelium Connectors
"""
from logging import Logger, getLogger
from typing import Any

from flask import abort, request
from werkzeug import Response

from cmdb.manager import OcConnectorManager

from cmdb.models.user_model import CmdbUser
from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.route_utils import insert_request_user, verify_api_access, handle_oc_errors
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.rest_api.responses import DefaultResponse

from cmdb.errors.open_celium.connector import (
    OcConnectorCreateError,
    OcConnectorGetError,
    OcConnectorUpdateError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

oc_connectors_blueprint = APIBlueprint('oc_connectors', __name__)

# --------------------------------------------------- CRUD - CREATE -------------------------------------------------- #

@oc_connectors_blueprint.route('/connectors', methods=['POST'])
@handle_oc_errors("creating an OpenCelium Connector!")
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
def create_oc_connector(request_user: CmdbUser) -> Response:
    """
    POST route to create an OcConnector in OpenCelium

    Args:
        params (dict[str, Any]): the data of the new OcConnector
        request_user (CmdbUser): User requesting this data

    Returns:
        dict[str, Any]: The created OcConnector
    """
    try:
        oc_connector_manager: OcConnectorManager = OcConnectorManager()

        params: dict[str, Any] = request.json

        create_oc_connector: dict[str, Any] = oc_connector_manager.create_connector(params)

        return DefaultResponse(create_oc_connector).make_response()
    except OcConnectorCreateError as err:
        LOGGER.error("[create_oc_connector] OcConnectorCreateError: %s", err, exc_info=True)
        abort(400, "Failed to create an OpenCelium Connector!")


@oc_connectors_blueprint.route('/connectors/check', methods=['POST'])
@handle_oc_errors("checking the credentials of the OpenCelium Connector!")
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
def check_oc_connector(request_user: CmdbUser) -> Response:
    """
    POST route validate credentials of the Invoker of the Connector

    Args:
        params (dict[str, Any]): the data of the new OcConnector
        request_user (CmdbUser): User requesting this data

    Returns:
        dict[str, Any]: The created OcConnector
    """
    oc_connector_manager: OcConnectorManager = OcConnectorManager()

    params: dict[str, Any] = request.json

    check_is_success: bool = oc_connector_manager.check_connector(params)

    return DefaultResponse(check_is_success).make_response()

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

@oc_connectors_blueprint.route('/connectors/<int:connector_id>', methods=['GET', 'HEAD'])
@handle_oc_errors("retrieving the OpenCelium Connector!")
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
def get_oc_connector(request_user: CmdbUser, connector_id: int) -> Response:
    """
    GET/HEAD route to retrive an OcConnector with the given connector_id

    Args:
        request_user (CmdbUser): User requesting this data
        connector_id (int): connectorId of the OcConnector

    Returns:
        dict[str, Any]: The OcConnector from OpenCelium
    """
    try:
        oc_connector_manager: OcConnectorManager = OcConnectorManager()

        connector: dict[str, Any] = oc_connector_manager.get_connector(connector_id)

        # LOGGER.debug(f"connector: {connector}")

        return DefaultResponse(connector).make_response()
    except OcConnectorGetError as err:
        LOGGER.error("[get_oc_connector] OcConnectorGetError: %s.", err, exc_info=True)
        abort(500, f"Failed to retrieve OpenCelium Connector with ID:{connector_id}!")


@oc_connectors_blueprint.route('/connectors', methods=['GET', 'HEAD'])
@handle_oc_errors("retrieving OpenCelium Connectors!")
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
def get_all_oc_connectors(request_user: CmdbUser) -> Response:
    """
    **GET**/**HEAD** route for getting multiple OcConnectors

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
        LOGGER.error("[get_all_oc_connectors] %s: %s.", type(err).__name__, err, exc_info=True)
        abort(500, "Failed to retrieve OpenCelium Connectors!")

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

@oc_connectors_blueprint.route('/connectors/<int:connector_id>', methods=['PUT'])
@handle_oc_errors("updating an OpenCelium Connector!")
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
def update_oc_connector(request_user: CmdbUser, connector_id: int) -> Response:
    """
    **PUT** route to update an OcConnector

    Args:
        params (dict[str, Any]): new data of the OcConnector
        request_user (CmdbUser): User requesting this data
        connector_id (int): the connectorId of the OcConnector

    Returns:
        dict[str, Any]: The updated OcConnector
    """
    try:
        oc_connector_manager: OcConnectorManager = OcConnectorManager()

        params: dict[str, Any] = request.json

        updated_oc_connector: dict[str, Any] = oc_connector_manager.update_connector(params, connector_id)

        return DefaultResponse(updated_oc_connector).make_response()
    except OcConnectorUpdateError as err:
        LOGGER.error("[update_oc_connector] %s: %s", type(err), err, exc_info=True)
        abort(400, f"Failed to update the OpenCelium Connector with ID: {connector_id}!")

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

@oc_connectors_blueprint.route('/connectors/<int:connector_id>', methods=['DELETE'])
@handle_oc_errors("deleting the OpenCelium Connector!")
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
def delete_oc_connector(request_user: CmdbUser, connector_id: int) -> Response:
    """
    HTTP `DELETE` route to delete an OcConnector

    Args:
        request_user (CmdbUser): User requesting this data
        connector_id (int): the connectorId of the OcConnector

    Returns:
        bool: True if deletion was a success else False
    """
    try:
        oc_connector_manager: OcConnectorManager = OcConnectorManager()

        delete_oc_connector: bool = oc_connector_manager.delete_connector(connector_id)

        return DefaultResponse(delete_oc_connector).make_response()
    except OcConnectorUpdateError as err:
        LOGGER.error("[delete_oc_connector] %s: %s", type(err), err, exc_info=True)
        abort(400, f"Failed to delete the OpenCelium Connector with ID: {connector_id}!")
