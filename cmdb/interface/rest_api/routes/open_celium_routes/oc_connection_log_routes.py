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
All API routes for OpenCelium Connection Logs

These six routes read (and delete) the **execution log** of an automation run: OpenCelium answers a
tree - the flowcharts of a run, the first level of log entries under one flowchart, the children of an
operator, the details of one method or operator - and each route is a thin proxy to one of its
endpoints. DataGerry stores none of it, so every payload here is another product's shape and any key
in it may be absent or null.

**On a hosted installation the connector names are rewritten before they reach a client.** Every
OpenCelium connector is registered under a `<database>_<name>` prefix so tenants cannot see each
other's; the flowchart route strips it (see `oc_connection_log_helper`). That rewrite is the one piece
of logic in the file - everything else forwards.

The blueprint is license-gated as part of the `AUTOMATIONS` feature (see `init_rest_api`) but carries
no per-route ACL right, unlike the sibling connection and connector routes; that gap is
discussion-backlog #115, which lists this file by name and records that the rights it would need do
not exist yet.

**No frontend calls these.** The Automations view's log menu and viewer read
`open_celium/schedulers/logs` (a scheduler route); this file is API-only surface, which is also why a
defect in its cloud-only branch could go unnoticed.
"""
from logging import Logger, getLogger
from typing import Any

from flask import abort, current_app
from werkzeug import Response
from werkzeug.exceptions import HTTPException

from cmdb.manager import OcConnectionLogManager

from cmdb.models.user_model import CmdbUser
from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.route_utils import insert_request_user, verify_api_access, handle_oc_errors
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.rest_api.responses import DefaultResponse
from cmdb.interface.rest_api.routes.open_celium_routes.oc_routes_constants import OcLogQueryParam
from cmdb.interface.rest_api.routes.open_celium_routes.oc_connection_log_helper import (
    build_connection_log_manager,
    required_int_param_or_abort,
    required_str_param_or_abort,
    unmap_flowchart_connector_names,
)

from cmdb.errors.open_celium.connection_log import OcConnectionLogGetError, OcConnectionLogDeleteError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

oc_connection_log_blueprint = APIBlueprint('oc_connection_logs', __name__)

# --------------------------------------------------- GET - ROUTES --------------------------------------------------- #

@oc_connection_log_blueprint.route('/connections/logs/<string:target_id>', methods=['GET', 'HEAD'])
@handle_oc_errors("retrieving the Method/Operator details!")
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
def oc_get_method_or_operator_details(request_user: CmdbUser, target_id: str) -> Response:
    """
    GET/HEAD route to retrieve details about one Method or Operator of an execution log

    Args:
        request_user (CmdbUser): User requesting this data
        target_id (str): id of the log ELEMENT - a method or an operator inside one flowchart, not
                         the connection

    Returns:
        Response: The details of the Method/Operator as OpenCelium answered them
    """
    try:
        oc_connection_log_manager: OcConnectionLogManager = build_connection_log_manager(request_user)

        requested_details: Any = oc_connection_log_manager.get_details_method_or_operator(target_id)

        return DefaultResponse(requested_details).make_response()
    except OcConnectionLogGetError as err:
        LOGGER.error("[oc_get_method_or_operator_details] %s: %s", type(err).__name__, err, exc_info=True)
        abort(500, f"Failed to retrieve details for Method/Operator with ID:{target_id}!")


@oc_connection_log_blueprint.route('/connections/logs/children/<string:target_id>', methods=['GET', 'HEAD'])
@handle_oc_errors("retrieving the Method/Operator details!")
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
def oc_get_operator_children(request_user: CmdbUser, target_id: str) -> Response:
    """
    GET/HEAD route to retrieve the children of one Operator of an execution log

    An operator that loops has one set of children per iteration, which is what `?loopIndex=` selects

    Args:
        request_user (CmdbUser): User requesting this data
        target_id (str): id of the log ELEMENT - the operator whose children are requested

    Raises:
        HTTPException: 400 when `loopIndex` is absent or empty

    Returns:
        Response: The Operator children as OpenCelium answered them
    """
    try:
        oc_connection_log_manager: OcConnectionLogManager = build_connection_log_manager(request_user)

        loop_index: str = required_str_param_or_abort(OcLogQueryParam.LOOP_INDEX)

        operator_children: Any = oc_connection_log_manager.get_operator_children(target_id, loop_index)

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
    GET/HEAD route to retrieve the Flowcharts of one execution

    **On a hosted installation the connector names are unprefixed first**: every OpenCelium connector
    is registered as `<database>_<name>` so tenants cannot see each other's, and the prefix is not
    the customer's to read. The rewrite is tolerant of the payload it is handed - see
    `unmap_flowchart_connector_names`, which is where that had never been exercised

    Args:
        request_user (CmdbUser): User requesting this data
        target_id (int): executionId of the automation run

    Returns:
        Response: The Flowcharts as OpenCelium answered them, connector names unprefixed in cloud mode
    """
    try:
        oc_connection_log_manager: OcConnectionLogManager = build_connection_log_manager(request_user)

        flowcharts: Any = oc_connection_log_manager.get_flowcharts(target_id)

        if current_app.cloud_mode and not current_app.local_mode:
            flowcharts = unmap_flowchart_connector_names(flowcharts)

        return DefaultResponse(flowcharts).make_response()
    except OcConnectionLogGetError as err:
        LOGGER.error("[oc_get_flowcharts] %s: %s", type(err).__name__, err, exc_info=True)
        abort(500, f"Failed to retrieve Flowcharts for target with ID:{target_id}!")


@oc_connection_log_blueprint.route('/connections/logs/first_level/<string:target_id>', methods=['GET', 'HEAD'])
@handle_oc_errors("retrieving the first level Logs!")
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
def oc_get_first_level_logs(request_user: CmdbUser, target_id: str) -> Response:
    """
    GET/HEAD route to retrieve the first level of log entries under one Flowchart

    Args:
        request_user (CmdbUser): User requesting this data
        target_id (str): flowchartId whose direct log entries are requested

    Returns:
        Response: The first level Logs as OpenCelium answered them
    """
    try:
        oc_connection_log_manager: OcConnectionLogManager = build_connection_log_manager(request_user)

        requested_logs: Any = oc_connection_log_manager.get_first_level_logs(target_id)

        return DefaultResponse(requested_logs).make_response()
    except OcConnectionLogGetError as err:
        LOGGER.error("[oc_get_first_level_logs] %s: %s", type(err).__name__, err, exc_info=True)
        abort(500, f"Failed to retrieve first level Logs for Flowchart with ID:{target_id}!")


@oc_connection_log_blueprint.route('/connections/logs/list', methods=['GET', 'HEAD'])
@handle_oc_errors("retrieving the Log list!")
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
def oc_get_log_list(request_user: CmdbUser) -> Response:
    """
    GET/HEAD route to retrieve the available execution Logs of one automation

    All three query parameters are required and are forwarded to OpenCelium, which decides what
    exists. **An id of 0 counts as provided**: reading the parsed value for truthiness used to report
    `?connectionId=0` as missing

    Args:
        request_user (CmdbUser): User requesting this data

    Raises:
        HTTPException: 400 when `connectionId`, `schedulerId` or `status` is absent, when an id is
                       not a whole number, or when the status is empty

    Returns:
        Response: The log list as OpenCelium answered it
    """
    try:
        oc_connection_log_manager: OcConnectionLogManager = build_connection_log_manager(request_user)

        connection_id: int = required_int_param_or_abort(OcLogQueryParam.CONNECTION_ID)
        scheduler_id: int = required_int_param_or_abort(OcLogQueryParam.SCHEDULER_ID)
        status: str = required_str_param_or_abort(OcLogQueryParam.STATUS)

        log_list: Any = oc_connection_log_manager.get_log_list(connection_id, scheduler_id, status)

        return DefaultResponse(log_list).make_response()
    except HTTPException as http_err:
        raise http_err
    except OcConnectionLogGetError as err:
        LOGGER.error("[oc_get_log_list] %s: %s", type(err).__name__, err, exc_info=True)
        abort(500, "Failed to retrieve the Log List!")

# -------------------------------------------------- DELETE - ROUTES ------------------------------------------------- #

@oc_connection_log_blueprint.route('/connections/logs/<int:target_id>', methods=['DELETE'])
@handle_oc_errors("deleting execution Logs!")
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
def oc_delete_logs(request_user: CmdbUser, target_id: int) -> Response:
    """
    **DELETE** route to delete the execution Logs of one automation run

    Args:
        request_user (CmdbUser): User requesting this data
        target_id (int): executionId whose logs should be deleted

    Returns:
        Response: OpenCelium's answer to the deletion
    """
    try:
        oc_connection_log_manager: OcConnectionLogManager = build_connection_log_manager(request_user)

        requested_logs: Any = oc_connection_log_manager.delete_logs(target_id)

        return DefaultResponse(requested_logs).make_response()
    except OcConnectionLogDeleteError as err:
        LOGGER.error("[oc_delete_logs] %s: %s", type(err).__name__, err, exc_info=True)
        abort(500, f"Failed to delete Logs for executionId:{target_id}!")
