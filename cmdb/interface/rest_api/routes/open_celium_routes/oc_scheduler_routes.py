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
All API routes for OpenCelium Schedulers
"""
from logging import Logger, getLogger
from typing import Any

from flask import abort, request, current_app
from werkzeug import Response
from werkzeug.exceptions import HTTPException

from cmdb.manager import OcSchedulerManager, OcConnectionManager, DgServicePortalManager, CachedUserManager
from cmdb.open_celium import map_oc_name, unmap_oc_name

from cmdb.models.user_model import CmdbUser
from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.route_utils import insert_request_user, verify_api_access, handle_oc_errors
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.rest_api.responses import DefaultResponse
from cmdb.interface.rest_api.routes.open_celium_routes.oc_scheduler_helper import (
    assert_scheduler_access,
    get_accessible_scheduler_ids,
    unmap_scheduler_titles,
)
from cmdb.interface.rest_api.routes.open_celium_routes.oc_connection_helper import connection_in_subscription
from cmdb.interface.rest_api.routes.open_celium_routes.oc_routes_constants import OcResponseKey

from cmdb.errors.open_celium.scheduler import (
    OcSchedulerCreateError,
    OcSchedulerGetError,
    OcSchedulerUpdateError,
    OcSchedulerDeleteError,
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
@handle_oc_errors("creating an Automation!")
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
def create_oc_scheduler(request_user: CmdbUser) -> Response:
    """
    POST route to create an OcScheduler in OpenCelium.

    Cloud mode behavior:
        - Map title for tenant
        - Create connection if it does not exist
        - Save new connectionId to DG SP
        - Save new schedulerId to DG SP
        - Delete cache *after* failed ID save OR after successful creation

    Returns:
        Response: The created scheduler
    """
    try:
        oc_scheduler_manager = OcSchedulerManager(
            current_app.database_manager,
            request_user.database
        )
        oc_connection_manager = OcConnectionManager(
            current_app.database_manager,
            request_user.database
        )

        # Cloud-only collaborators; left None on-premise where the cloud branches are skipped
        dg_sp_manager = None
        cached_user_manager = None

        params: dict[str, Any] = request.json

        if not params.get(OcResponseKey.CONNECTION.value):
            abort(400, "No 'connection' data provided to create the Automation!")

        if not params.get(OcResponseKey.SCHEDULER.value):
            abort(400, "No 'scheduler' data provided to create the Automation!")

        created_connection: dict[str, Any] = None
        conn_data = params[OcResponseKey.CONNECTION.value]
        sched_data = params[OcResponseKey.SCHEDULER.value]

        conn_title = conn_data[OcResponseKey.TITLE.value]

        # CLOUD MODE → map connection title
        if current_app.cloud_mode and not current_app.local_mode:
            dg_sp_manager = DgServicePortalManager()
            cached_user_manager = CachedUserManager(current_app.database_manager)

            conn_title = map_oc_name(request_user.database, conn_title)
            conn_data[OcResponseKey.TITLE.value] = conn_title

        # Create connection (scheduler always requires a connection)
        # Reject if connection name already exists
        if oc_connection_manager.check_connection_name_exists(conn_title):
            # Unmap for frontend error message
            if current_app.cloud_mode and not current_app.local_mode:
                conn_title = unmap_oc_name(conn_title)

            abort(400, f"The connection name: {conn_title} already exists!")

        # Create connection in OC
        created_connection = oc_connection_manager.create_connection(conn_data)

        # CLOUD MODE → save connectionId in DG SP
        if current_app.cloud_mode and not current_app.local_mode:
            dg_sp_manager.save_connection_id(
                created_connection[OcResponseKey.CONNECTION_ID.value],
                request_user.email,
                request_user.database
            )

            # Clear cache because it now contains inconsistent IDs
            cached_user_manager.delete_cached_user(request_user.email)

        # Create scheduler
        sched_data[OcResponseKey.CONNECTION_ID.value] = created_connection[OcResponseKey.CONNECTION_ID.value]

        if current_app.cloud_mode and not current_app.local_mode:
            sched_data[OcResponseKey.TITLE.value] = map_oc_name(
                request_user.database, sched_data[OcResponseKey.TITLE.value]
            )

        created_scheduler = oc_scheduler_manager.create_scheduler(sched_data)

        # CLOUD MODE → save schedulerId in DG SP
        if current_app.cloud_mode and not current_app.local_mode:
            dg_sp_manager.save_scheduler_id(
                created_scheduler[OcResponseKey.SCHEDULER_ID.value],
                request_user.email,
                request_user.database
            )

            cached_user_manager.delete_cached_user(request_user.email)

            # Unmap title for frontend
            created_scheduler[OcResponseKey.TITLE.value] = unmap_oc_name(
                created_scheduler[OcResponseKey.TITLE.value]
            )

        return DefaultResponse(created_scheduler).make_response()
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
@handle_oc_errors("retrieving the Automation!")
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
def get_oc_scheduler(request_user: CmdbUser, scheduler_id: int) -> Response:
    """
    GET/HEAD route to retrieve an OcScheduler by schedulerId.

    Cloud mode:
        - Validate access using cache first, then DG SP
        - Unmap title for frontend display
    """
    try:
        oc_scheduler_manager = OcSchedulerManager(
            current_app.database_manager,
            request_user.database
        )

        # In cloud mode, verify the Automation belongs to the requesting user (cache-first)
        assert_scheduler_access(request_user, scheduler_id)

        # Fetch scheduler
        scheduler = oc_scheduler_manager.get_scheduler(scheduler_id)

        # CLOUD MODE → Unmap title before sending to frontend
        if scheduler and current_app.cloud_mode and not current_app.local_mode:
            scheduler[OcResponseKey.TITLE.value] = unmap_oc_name(scheduler[OcResponseKey.TITLE.value])
            connection = scheduler[OcResponseKey.CONNECTION.value]
            connection[OcResponseKey.TITLE.value] = unmap_oc_name(connection[OcResponseKey.TITLE.value])

        return DefaultResponse(scheduler).make_response()
    except HTTPException as http_err:
        raise http_err
    except OcSchedulerGetError as err:
        LOGGER.error("[get_oc_scheduler] OcSchedulerGetError: %s.", err, exc_info=True)
        abort(500, f"Failed to retrieve Automation with ID:{scheduler_id}!")


@oc_schedulers_blueprint.route('/schedulers', methods=['GET', 'HEAD'])
@handle_oc_errors("retrieving Automations!")
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
def get_all_oc_schedulers(request_user: CmdbUser) -> Response:
    """
    GET/HEAD route to retrieve all accessible OcSchedulers.

    Cloud mode:
        - Scheduler IDs come from cache first, then DG SP if cache missing.
        - Each scheduler's title is unmapped for frontend usage.

    Local mode:
        - Returns all schedulers directly.
    """
    try:
        oc_scheduler_manager = OcSchedulerManager(
            current_app.database_manager,
            request_user.database
        )

        # CLOUD MODE → Retrieve scheduler IDs (CACHE FIRST)
        if current_app.cloud_mode and not current_app.local_mode:
            scheduler_ids = get_accessible_scheduler_ids(request_user)

            schedulers = None

            if scheduler_ids:
                schedulers = oc_scheduler_manager.get_schedulers_by_ids(scheduler_ids)

                # Unmap for UI
                for sched in schedulers:
                    unmap_scheduler_titles(sched)

        # LOCAL MODE → Retrieve all schedulers
        else:
            schedulers = oc_scheduler_manager.get_all_schedulers()

        return DefaultResponse(schedulers).make_response()
    except HTTPException as http_err:
        raise http_err
    except OcSchedulerGetError as err:
        LOGGER.error("[get_all_oc_schedulers] %s: %s.", type(err).__name__, err, exc_info=True)
        abort(500, "Failed to retrieve Automations!")


@oc_schedulers_blueprint.route('/schedulers/running', methods=['GET', 'HEAD'])
@handle_oc_errors("retrieving running Automations!")
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
def get_oc_running_schedulers(request_user: CmdbUser) -> Response:
    """
    GET/HEAD route to retrieve running schedulers
    """
    try:
        oc_scheduler_manager = OcSchedulerManager(
            current_app.database_manager,
            request_user.database
        )

        running_schedulers: list[dict[str, Any]] = oc_scheduler_manager.get_running_schedulers()

        if current_app.cloud_mode and not current_app.local_mode:
            scheduler_ids: list[int] = get_accessible_scheduler_ids(request_user)

            if scheduler_ids:
                schedulers = [
                        sched for sched in running_schedulers
                        if sched[OcResponseKey.SCHEDULER_ID.value] in scheduler_ids
                    ]

                if schedulers:
                    # Unmap for UI (running schedulers carry the connector titles at the top level)
                    for sched in schedulers:
                        sched[OcResponseKey.TITLE.value] = unmap_oc_name(sched[OcResponseKey.TITLE.value], False)
                        sched[OcResponseKey.FROM_CONNECTOR.value] = unmap_oc_name(
                            sched[OcResponseKey.FROM_CONNECTOR.value], False
                        )
                        sched[OcResponseKey.TO_CONNECTOR.value] = unmap_oc_name(
                            sched[OcResponseKey.TO_CONNECTOR.value], False
                        )

                    running_schedulers = schedulers

        return DefaultResponse(running_schedulers).make_response()
    except HTTPException as http_err:
        raise http_err
    except OcSchedulerGetError as err:
        LOGGER.error("[get_oc_running_schedulers] %s: %s.", type(err).__name__, err, exc_info=True)
        abort(500, "Failed to retrieve running Automations!")


@oc_schedulers_blueprint.route('/schedulers/logs', methods=['GET', 'HEAD'])
@handle_oc_errors("retrieving Automation logs!")
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
def get_oc_scheduler_logs(request_user: CmdbUser) -> Response:
    """
    GET/HEAD route to retrieve logs of an OC scheduler

    status (str): It can either be s (success) or f (failed)
    """
    try:
        scheduler_id: int | None = request.args.get("scheduler_id", type=int)
        status: str | None = request.args.get("status")

        if not scheduler_id:
            abort(400, "No schedulerId for Logs provided!")

        if not status:
            abort(400, "No status is provided. Provide either 's' for success or 'f' for failed logs!")

        if not status in ["s", "f"]:
            abort(400, "Invalid status provided. Status can be either 's' for success or 'f' for failed logs!")

        oc_scheduler_manager = OcSchedulerManager(
            current_app.database_manager,
            request_user.database
        )

        # In cloud mode, verify the Automation belongs to the requesting user (cache-first)
        assert_scheduler_access(request_user, scheduler_id)

        # Retrieve the Logs
        scheduler_logs: list[dict[str, Any]] = oc_scheduler_manager.get_scheduler_logs(scheduler_id, status)

        return DefaultResponse(scheduler_logs).make_response()
    except HTTPException as http_err:
        raise http_err
    except OcSchedulerGetError as err:
        LOGGER.error("[get_oc_scheduler_logs] %s: %s.", type(err).__name__, err, exc_info=True)
        abort(500, "Failed to retrieve Automation logs!")


@oc_schedulers_blueprint.route('/schedulers/execute/<int:scheduler_id>', methods=['GET', 'HEAD'])
@handle_oc_errors("executing the Automation!")
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
def execute_oc_scheduler(request_user: CmdbUser, scheduler_id: int) -> Response:
    """
    GET/HEAD route to execute an OC Scheduler with the given scheduler_id.

    Cloud mode:
        - Scheduler ID validity is checked via cache first, then DG SP.
    """
    try:
        oc_scheduler_manager = OcSchedulerManager(
            current_app.database_manager,
            request_user.database
        )

        # In cloud mode, verify the Automation belongs to the requesting user (cache-first)
        assert_scheduler_access(request_user, scheduler_id)

        # Execute Scheduler
        scheduler_result = oc_scheduler_manager.execute_scheduler(scheduler_id)

        return DefaultResponse(scheduler_result).make_response()
    except HTTPException as http_err:
        raise http_err
    except OcSchedulerGetError as err:
        LOGGER.error("[execute_oc_scheduler] %s: %s.", type(err).__name__, err, exc_info=True)
        abort(500, f"Failed to execute Automation with ID: {scheduler_id}!")

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

@oc_schedulers_blueprint.route('/schedulers/<int:scheduler_id>', methods=['PUT'])
@handle_oc_errors("updating an Automation!")
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
def update_oc_scheduler(request_user: CmdbUser, scheduler_id: int) -> Response:
    """
    PUT route to update an OcScheduler.

    Cloud mode:
        - Scheduler ID access validated via cache first, then DG Service Portal
        - Title is mapped/unmapped per tenant
    """
    try:
        oc_scheduler_manager = OcSchedulerManager(
            current_app.database_manager,
            request_user.database
        )

        # In cloud mode, verify the Automation belongs to the requesting user (cache-first)
        assert_scheduler_access(request_user, scheduler_id)

        # UPDATE PARAMS
        params: dict[str, Any] = request.json

        # Map titles
        if current_app.cloud_mode and not current_app.local_mode:
            params[OcResponseKey.TITLE.value] = map_oc_name(request_user.database, params[OcResponseKey.TITLE.value])

        updated_oc_scheduler = oc_scheduler_manager.update_scheduler(params, scheduler_id)

        # Unmap for UI
        if current_app.cloud_mode and not current_app.local_mode:
            unmap_scheduler_titles(updated_oc_scheduler)

        return DefaultResponse(updated_oc_scheduler).make_response()
    except HTTPException as http_err:
        raise http_err
    except OcSchedulerUpdateError as err:
        LOGGER.error("[update_oc_scheduler] %s: %s", type(err), err, exc_info=True)
        abort(400, f"Failed to update the Automation with ID: {scheduler_id}!")

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

@oc_schedulers_blueprint.route('/schedulers/<int:scheduler_id>', methods=['DELETE'])
@handle_oc_errors("deleting the Automation!")
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
def delete_oc_scheduler(request_user: CmdbUser, scheduler_id: int) -> Response:
    """
    DELETE route to delete an OcScheduler

    Cloud mode:
        - Validate schedulerId and its connectionId via cache first,
          then Service Portal.
        - Remove deleted IDs from Service Portal.
    """
    try:
        oc_scheduler_manager = OcSchedulerManager(
            current_app.database_manager,
            request_user.database
        )
        oc_connection_manager = OcConnectionManager(
            current_app.database_manager,
            request_user.database
        )

        # Cloud-only collaborators; left None on-premise where the cloud branches are skipped
        dg_sp_manager = None
        cached_user_manager = None

        # FETCH SCHEDULER FIRST (NEEDED TO ACCESS connectionId)
        scheduler = oc_scheduler_manager.get_scheduler(scheduler_id)
        if not scheduler:
            abort(400, f"Automation with ID:{scheduler_id} does not exist!")

        connection_id = int(scheduler[OcResponseKey.CONNECTION.value][OcResponseKey.CONNECTION_ID.value])

        # CLOUD MODE → VALIDATE ID ACCESS (CACHE FIRST)
        if current_app.cloud_mode and not current_app.local_mode:
            dg_sp_manager = DgServicePortalManager()
            cached_user_manager = CachedUserManager(current_app.database_manager)

            # Validate the scheduler + its backing connection both belong to the user (cache-first)
            assert_scheduler_access(request_user, scheduler_id)

            if not connection_in_subscription(request_user, connection_id, cached_user_manager, dg_sp_manager):
                abort(400, f"The target Connection with ID:{connection_id} was not found!")

        # DELETE SCHEDULER
        deleted_scheduler: bool = oc_scheduler_manager.delete_scheduler(scheduler_id)

        # Only cascade the connection cleanup when the scheduler was actually deleted, so a failed
        # scheduler delete cannot orphan its backing connection (or the Service Portal entries)
        if deleted_scheduler:
            # Cleanup ServicePortal scheduler entry
            if current_app.cloud_mode and not current_app.local_mode:
                dg_sp_manager.delete_scheduler_id(
                    scheduler_id,
                    request_user.email,
                    request_user.database
                )

                cached_user_manager.delete_cached_user(request_user.email)

            # Delete Connection
            oc_connection_manager.delete_connection(connection_id)

            # Cleanup ServicePortal connection entry
            if current_app.cloud_mode and not current_app.local_mode:
                dg_sp_manager.delete_connection_id(
                    connection_id,
                    request_user.email,
                    request_user.database
                )

                cached_user_manager.delete_cached_user(request_user.email)

        return DefaultResponse(deleted_scheduler).make_response()
    except HTTPException as http_err:
        raise http_err
    except OcSchedulerDeleteError as err:
        LOGGER.error("[delete_oc_scheduler] %s: %s", type(err), err, exc_info=True)
        abort(500, f"Failed to delete the Automation with ID: {scheduler_id}!")
