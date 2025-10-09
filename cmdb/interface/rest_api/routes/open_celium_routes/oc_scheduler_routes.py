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
All API routes for OpenCelium Schedulers
"""
from logging import Logger, getLogger
from typing import Any

from flask import abort, request
from werkzeug import Response
from werkzeug.exceptions import HTTPException

from cmdb.manager import OcSchedulerManager, OcConnectionManager

from cmdb.models.user_model import CmdbUser
from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.route_utils import insert_request_user, verify_api_access, handle_oc_errors
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.rest_api.responses import DefaultResponse

from cmdb.errors.open_celium.scheduler import (
    OcSchedulerCreateError,
    OcSchedulerGetError,
    OcSchedulerUpdateError,
)
from cmdb.errors.open_celium.connection import (
    OcConnectionCreateError,
    OcConnectionGetError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

oc_schedulers_blueprint = APIBlueprint('oc_schedulers', __name__)

# --------------------------------------------------- CRUD - CREATE -------------------------------------------------- #

@oc_schedulers_blueprint.route('/schedulers', methods=['POST'])
@handle_oc_errors("creating an OpenCelium Scheduler!")
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
def create_oc_scheduler(request_user: CmdbUser) -> Response:
    """
    POST route to create an OcSchedulers in OpenCelium

    Args:
        params (dict[str, Any]): the data of the new OcSchedulers
        request_user (CmdbUser): User requesting this data

    Returns:
        dict[str, Any]: The created OcSchedulers
    """
    try:
        oc_scheduler_manager: OcSchedulerManager = OcSchedulerManager()
        oc_connection_manager: OcConnectionManager = OcConnectionManager()

        params: dict[str, Any] = request.json

        if not params.get('connection'):
            abort(400, "No 'connection' data provided to create the Connection of the Automation!")

        if not params.get('scheduler'):
            abort(400, "No 'scheduler' data provided to create the Automation!")

        created_connection: dict[str, Any] = []
        conn_title: str = params['connection']['title']

        if not oc_connection_manager.check_connection_name_exists(conn_title):
            created_connection = oc_connection_manager.create_connection(params['connection'])
        else:
            abort(400, f"The connection name: {conn_title} already exists!")

        scheduler_params: dict[str, Any] = params['scheduler']
        scheduler_params['connectionId'] = created_connection['connectionId']

        created_oc_scheduler: dict[str, Any] = oc_scheduler_manager.create_scheduler(scheduler_params)

        return DefaultResponse(created_oc_scheduler).make_response()
    except HTTPException as http_err:
        raise http_err
    except OcConnectionCreateError as err:
        LOGGER.error("[create_oc_scheduler] %s: %s", type(err).__name__, err, exc_info=True)
        abort(500, "Failed to create Connection of Automation!")
    except OcConnectionGetError as err:
        LOGGER.error("[create_oc_scheduler] %s: %s", type(err).__name__, err, exc_info=True)
        abort(500, "Failed to check Connection name uniqueness!")
    except OcSchedulerCreateError as err:
        LOGGER.error("[create_oc_scheduler] %s: %s", type(err).__name__, err, exc_info=True)
        abort(500, "Failed to create the Automation!")

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

@oc_schedulers_blueprint.route('/schedulers/<int:scheduler_id>', methods=['GET', 'HEAD'])
@handle_oc_errors("retrieving the OpenCelium Scheduler!")
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
def get_oc_scheduler(request_user: CmdbUser, scheduler_id: int) -> Response:
    """
    GET/HEAD route to retrive an OcScheduler with the given scheduler_id

    Args:
        request_user (CmdbUser): User requesting this data
        scheduler_id (int): schedulerId of the OcSchedulers

    Returns:
        dict[str, Any]: The OcSchedulers from OpenCelium
    """
    try:
        oc_scheduler_manager: OcSchedulerManager = OcSchedulerManager()

        connector: dict[str, Any] = oc_scheduler_manager.get_scheduler(scheduler_id)

        # LOGGER.debug(f"connector: {connector}")

        return DefaultResponse(connector).make_response()
    except OcSchedulerGetError as err:
        LOGGER.error("[get_oc_scheduler] OcSchedulerGetError: %s.", err, exc_info=True)
        abort(500, f"Failed to retrieve OpenCelium Scheduler with ID:{scheduler_id}!")


@oc_schedulers_blueprint.route('/schedulers', methods=['GET', 'HEAD'])
@handle_oc_errors("retrieving OpenCelium Schedulers!")
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
def get_all_oc_schedulers(request_user: CmdbUser) -> Response:
    """
    **GET**/**HEAD** route for getting multiple OcSchedulers

    Args:
        request_user (CmdbUser): User requesting this data

    Returns:
        list[dict[str, Any]]: All OcSchedulers from OpenCelium
    """
    try:
        oc_scheduler_manager: OcSchedulerManager = OcSchedulerManager()

        schedulers: list[dict[str, Any]] = oc_scheduler_manager.get_all_schedulers()

        return DefaultResponse(schedulers).make_response()
    except OcSchedulerGetError as err:
        LOGGER.error("[get_all_oc_schedulers] %s: %s.", type(err).__name__, err, exc_info=True)
        abort(500, "Failed to retrieve OpenCelium Schedulers!")

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

@oc_schedulers_blueprint.route('/schedulers/<int:scheduler_id>', methods=['PUT'])
@handle_oc_errors("updating an OpenCelium Scheduler!")
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
def update_oc_scheduler(request_user: CmdbUser, scheduler_id: int) -> Response:
    """
    **PUT** route to update an OcSchedulers

    Args:
        params (dict[str, Any]): new data of the OcSchedulers
        request_user (CmdbUser): User requesting this data
        scheduler_id (int): the schedulerId of the OcSchedulers

    Returns:
        dict[str, Any]: The updated OcSchedulers
    """
    try:
        oc_scheduler_manager: OcSchedulerManager = OcSchedulerManager()

        params: dict[str, Any] = request.json

        updated_oc_scheduler: dict[str, Any] = oc_scheduler_manager.update_scheduler(params, scheduler_id)

        return DefaultResponse(updated_oc_scheduler).make_response()
    except OcSchedulerUpdateError as err:
        LOGGER.error("[update_oc_scheduler] %s: %s", type(err), err, exc_info=True)
        abort(400, f"Failed to update the OpenCelium Scheduler with ID: {scheduler_id}!")

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

@oc_schedulers_blueprint.route('/schedulers/<int:scheduler_id>', methods=['DELETE'])
@handle_oc_errors("deleting the OpenCelium Scheduler!")
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
def delete_oc_scheduler(request_user: CmdbUser, scheduler_id: int) -> Response:
    """
    **DELETE** route to delete an OcSchedulers

    Args:
        request_user (CmdbUser): User requesting this data
        scheduler_id (int): the schedulerId of the OcSchedulers

    Returns:
        bool: True if deletion was a success else False
    """
    try:
        oc_scheduler_manager: OcSchedulerManager = OcSchedulerManager()

        deleted_oc_scheduler: bool = oc_scheduler_manager.delete_scheduler(scheduler_id)

        return DefaultResponse(deleted_oc_scheduler).make_response()
    except OcSchedulerUpdateError as err:
        LOGGER.error("[delete_oc_scheduler] %s: %s", type(err), err, exc_info=True)
        abort(400, f"Failed to delete the OpenCelium Scheduler with ID: {scheduler_id}!")
