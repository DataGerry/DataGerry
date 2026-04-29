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
All API routes for OpenCelium Invokers
"""
from logging import Logger, getLogger
from typing import Any

from flask import abort, current_app, request
from werkzeug import Response
from werkzeug.exceptions import HTTPException

from cmdb.manager import OcConnectionLogManager

from cmdb.open_celium import unmap_oc_name
from cmdb.models.user_model import CmdbUser
from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.route_utils import insert_request_user, verify_api_access, handle_oc_errors
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.rest_api.responses import DefaultResponse

from cmdb.errors.open_celium.connection_log import OcConnectionLogGetError, OcConnectionLogDeleteError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

oc_connection_log_blueprint = APIBlueprint('oc_connection_logs', __name__)

# --------------------------------------------------- GET - ROUTES --------------------------------------------------- #

@oc_connection_log_blueprint.route('/connections/logs/<string:target_id>', methods=['GET', 'HEAD'])
@handle_oc_errors("retrieving the Method/Operator details!")
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
def oc_get_method_or_operator_details(request_user: CmdbUser, target_id: int) -> Response:
    """
    GET/HEAD route to retrieve details about Method or Operator

    Args:
        request_user (CmdbUser): User requesting this data
        target_id (int): The ID of the OcConnection

    Returns:
        Response: The details of the Method/Operator
    """
    try:
        oc_connection_log_manager: OcConnectionLogManager = OcConnectionLogManager(
            current_app.database_manager,
            request_user.database
        )

        requested_details: dict[str, Any] = oc_connection_log_manager.get_details_method_or_operator(target_id)

        return DefaultResponse(requested_details).make_response()

    except OcConnectionLogGetError as err:
        LOGGER.error("[oc_get_method_or_operator_details] %s: %s", type(err).__name__, err, exc_info=True)
        abort(500, f"Failed to retrieve details for Method/Operator with ID:{target_id}!")


@oc_connection_log_blueprint.route('/connections/logs/children/<string:target_id>', methods=['GET', 'HEAD'])
@handle_oc_errors("retrieving the Method/Operator details!")
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
def oc_get_operator_children(request_user: CmdbUser, target_id: int) -> Response:
    """
    GET/HEAD route to retrieve Operator children

    Args:
        request_user (CmdbUser): User requesting this data
        target_id (int): The ID of the OcConnection

    Returns:
        Response: The Operator children
    """
    try:
        oc_connection_log_manager: OcConnectionLogManager = OcConnectionLogManager(
            current_app.database_manager,
            request_user.database
        )

        loop_index = request.args.get("loopIndex", type=str)

        if not loop_index:
            abort(400, "The loopIndex was not provided!")

        operator_children: dict[str, Any] = oc_connection_log_manager.get_operator_children(target_id, loop_index)

        return DefaultResponse(operator_children).make_response()
    except HTTPException as http_err:
        raise http_err
    except OcConnectionLogGetError as err:
        LOGGER.error("[oc_get_operator_children] %s: %s", type(err).__name__, err, exc_info=True)
        abort(500, f"Failed to retrieve the Operator children for ID:{target_id}!")


@oc_connection_log_blueprint.route('/connections/logs/flowcharts/<int:target_id>', methods=['GET', 'HEAD'])
@handle_oc_errors("retrieving the Flowcharts!")
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
def oc_get_flowcharts(request_user: CmdbUser, target_id: int) -> Response:
    """
    GET/HEAD route to retrieve Flowcharts

    Args:
        request_user (CmdbUser): User requesting this data
        target_id (int): target executionId

    Returns:
        Response: The Flowcharts
    """
    try:
        oc_connection_log_manager: OcConnectionLogManager = OcConnectionLogManager(
            current_app.database_manager,
            request_user.database
        )

        flowcharts: dict[str, Any] = oc_connection_log_manager.get_flowcharts(target_id)

        if current_app.cloud_mode and not current_app.local_mode:
            for flowchart in flowcharts:
                flowchart["connectorName"] = unmap_oc_name(flowchart["connectorName"])

        return DefaultResponse(flowcharts).make_response()
    except OcConnectionLogGetError as err:
        LOGGER.error("[oc_get_flowcharts] %s: %s", type(err).__name__, err, exc_info=True)
        abort(500, f"Failed to retrieve Flowcharts for target with ID:{target_id}!")


@oc_connection_log_blueprint.route('/connections/logs/first_level/<string:target_id>', methods=['GET', 'HEAD'])
@handle_oc_errors("retrieving the first level Logs!")
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
def oc_get_first_level_logs(request_user: CmdbUser, target_id: int) -> Response:
    """
    GET/HEAD route to retrieve first level Logs

    Args:
        request_user (CmdbUser): User requesting this data
        target_id (int): flowchartId

    Returns:
        Response: The first level Logs
    """
    try:
        oc_connection_log_manager: OcConnectionLogManager = OcConnectionLogManager(
            current_app.database_manager,
            request_user.database
        )

        requested_logs: dict[str, Any] = oc_connection_log_manager.get_first_level_logs(target_id)

        return DefaultResponse(requested_logs).make_response()
    except OcConnectionLogGetError as err:
        LOGGER.error("[oc_get_first_level_logs] %s: %s", type(err).__name__, err, exc_info=True)
        abort(500, f"Failed to retrieve first level Logs for Flowchart with ID:{target_id}!")


@oc_connection_log_blueprint.route('/connections/logs/list', methods=['GET', 'HEAD'])
@handle_oc_errors("retrieving the Method/Operator details!")
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
def oc_get_log_list(request_user: CmdbUser) -> Response:
    """
    GET/HEAD route to retrieve the Log list

    Args:
        request_user (CmdbUser): User requesting this data

    Returns:
        Response: The log list
    """
    try:
        oc_connection_log_manager: OcConnectionLogManager = OcConnectionLogManager(
            current_app.database_manager,
            request_user.database
        )

        connection_id: int | None = request.args.get("connectionId", type=int)
        if not connection_id:
            abort(400, "The 'connectionId' was not provided!")

        scheduler_id: int | None = request.args.get("schedulerId", type=int)
        if not scheduler_id:
            abort(400, "The 'schedulerId' was not provided!")

        status: int | None = request.args.get("status")
        if not status:
            abort(400, "The 'status' was not provided!")

        log_list: dict[str, Any] = oc_connection_log_manager.get_log_list(connection_id, scheduler_id, status)

        return DefaultResponse(log_list).make_response()
    except HTTPException as http_err:
        raise http_err
    except OcConnectionLogGetError as err:
        LOGGER.error("[oc_get_operator_children] %s: %s", type(err).__name__, err, exc_info=True)
        abort(500, "Failed to retrieve the Log List!")

# -------------------------------------------------- DELETE - ROUTES ------------------------------------------------- #

oc_connection_log_blueprint.route('/connections/logs/<int:target_id>', methods=['DELETE'])
@handle_oc_errors("deleting execution Logs!")
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
def oc_delete_logs(request_user: CmdbUser, target_id: int) -> Response:
    """
    **DELETE** route to delete OpenCelium Logs

    Args:
        request_user (CmdbUser): User requesting this data
        target_id (int): executionId

    Returns:
        Response: The deleted Logs
    """
    try:
        oc_connection_log_manager: OcConnectionLogManager = OcConnectionLogManager(
            current_app.database_manager,
            request_user.database
        )

        requested_logs: dict[str, Any] = oc_connection_log_manager.delete_logs(target_id)

        return DefaultResponse(requested_logs).make_response()
    except OcConnectionLogDeleteError as err:
        LOGGER.error("[get_first_level_logs] %s: %s", type(err).__name__, err, exc_info=True)
        abort(500, f"Failed to delete Logs for executionId:{target_id}!")
