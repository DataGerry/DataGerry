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

A scheduler is the runnable half of an **Automation**; the create makes its OpenCelium connection with it and the
delete removes both, so every route asks for the connection right of the same operation (``OcRight``) - the
rights the frontend's automation screens are guarded by:

    - ``base.openCelium.connection.view``: the scheduler, the list, the running ones, the execution logs
    - ``base.openCelium.connection.add``: the create (it creates the connection too)
    - ``base.openCelium.connection.edit``: the update, and running an Automation (``/schedulers/execute/<id>``)
    - ``base.openCelium.connection.delete``: the delete (it deletes the connection too)

The blueprint is gated behind the AUTOMATIONS licence (``init_rest_api``). In cloud mode every route that addresses
one scheduler checks that it belongs to the caller's subscription (``assert_scheduler_access``). Running an
Automation is a GET, which a safe method should not be - backend backlog **T328**
"""
from logging import Logger, getLogger
from typing import Any

from flask import abort, request
from werkzeug import Response
from werkzeug.exceptions import HTTPException

from cmdb.manager import OcSchedulerManager, OcConnectionManager, DgServicePortalManager
from cmdb.open_celium import map_oc_name, unmap_oc_name, is_hosted_cloud

from cmdb.models.user_model import CmdbUser
from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.route_utils import insert_request_user, verify_api_access, handle_oc_errors, get_cached_user_manager
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.rest_api.responses import DefaultResponse
from cmdb.interface.rest_api.routes.open_celium_routes.oc_scheduler_helper import (
    build_scheduler_manager,
    read_scheduler_update_body,
    assert_scheduler_access,
    get_accessible_scheduler_ids,
    AutomationWriters,
    create_automation,
    read_automation_body,
    unmap_scheduler_titles,
)
from cmdb.interface.rest_api.routes.open_celium_routes.oc_connection_helper import (
    build_connection_manager,
    connection_in_subscription,
)
from cmdb.interface.rest_api.routes.open_celium_routes.oc_routes_constants import (
    OcAutomationMessage,
    OcResponseKey,
    OcRight,
)

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
from cmdb.errors.dg_service_portal import DgServicePortalSaveError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

oc_schedulers_blueprint = APIBlueprint('oc_schedulers', __name__)

# --------------------------------------------------- CRUD - CREATE -------------------------------------------------- #

@oc_schedulers_blueprint.route('/schedulers', methods=['POST'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@oc_schedulers_blueprint.protect(auth=True, right=OcRight.CONNECTION_ADD.value)
@handle_oc_errors("creating an Automation!")
def create_oc_scheduler(request_user: CmdbUser) -> Response:
    """
    POST route to create an OcScheduler (an Automation) in OpenCelium, together with its connection

    **All or nothing, by compensation** (``oc_scheduler_helper.create_automation``). The create is up to four remote
    writes - the connection and the scheduler in OpenCelium and, in cloud mode, each id registered with the DataGerry
    Service Portal. Each is recorded in a WriteLedger as it succeeds; when a later step fails, the ones already made
    are deleted again, newest first - the order the delete route uses - and the request answers the error it actually
    hit. A portal registration the portal does not acknowledge is such a failure: stepping over it left the connection
    or the Automation outside the user's subscription, refused by every later check. An undo that cannot finish
    answers a 500 naming what it left behind

    Both titles are checked before anything is written. In cloud mode the titles are mapped to the tenant and the
    user's cache entry is evicted after each portal registration, since its OpenCelium ids are stale then

    Status codes:
        200 OK: The created scheduler (its title unmapped in cloud mode)
        400 BAD_REQUEST: No ``connection`` / ``scheduler`` / either title, or the connection name exists
        500: A step failed (connection create, name check, scheduler create, a portal registration) - everything
            already made was undone; or the undo itself left something behind (``OcAutomationMessage.RESIDUE``)

    Returns:
        Response: The created scheduler
    """
    try:
        oc_scheduler_manager: OcSchedulerManager = build_scheduler_manager(request_user)
        oc_connection_manager: OcConnectionManager = build_connection_manager(request_user)

        # Cloud-only collaborators; left None on-premise where the cloud branches are skipped
        dg_sp_manager = None
        cached_user_manager = None

        conn_data, sched_data = read_automation_body(request.json)
        conn_title = conn_data[OcResponseKey.TITLE.value]

        # CLOUD MODE → map connection title
        if is_hosted_cloud():
            dg_sp_manager = DgServicePortalManager()
            cached_user_manager = get_cached_user_manager()

            conn_title = map_oc_name(request_user.database, conn_title)
            conn_data[OcResponseKey.TITLE.value] = conn_title

        # Create connection (scheduler always requires a connection)
        # Reject if connection name already exists
        if oc_connection_manager.check_connection_name_exists(conn_title):
            # Unmap for frontend error message
            if is_hosted_cloud():
                conn_title = unmap_oc_name(conn_title)

            abort(400, f"The connection name: {conn_title} already exists!")

        created_scheduler: dict[str, Any] = create_automation(
            AutomationWriters(oc_connection_manager, oc_scheduler_manager, dg_sp_manager, cached_user_manager),
            request_user, conn_data, sched_data,
        )

        # Unmap title for frontend - outside the block: nothing after the last write may undo it
        if is_hosted_cloud():
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
    except DgServicePortalSaveError as err:
        LOGGER.error("[create_oc_scheduler] %s: %s", type(err).__name__, err, exc_info=True)
        abort(500, OcAutomationMessage.PORTAL_REFUSED.value)

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

@oc_schedulers_blueprint.route('/schedulers/<int:scheduler_id>', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@oc_schedulers_blueprint.protect(auth=True, right=OcRight.CONNECTION_VIEW.value)
@handle_oc_errors("retrieving the Automation!")
def get_oc_scheduler(request_user: CmdbUser, scheduler_id: int) -> Response:
    """
    GET/HEAD route to retrieve an OcScheduler by schedulerId.

    Cloud mode:
        - Validate access using cache first, then DG SP
        - Unmap title for frontend display

    Raises:
        HTTPException: 403 without ``base.openCelium.connection.view``; in cloud mode 400 for an Automation outside the
                       subscription; 500 when OpenCelium cannot answer it
    """
    try:
        oc_scheduler_manager: OcSchedulerManager = build_scheduler_manager(request_user)

        # In cloud mode, verify the Automation belongs to the requesting user (cache-first)
        assert_scheduler_access(request_user, scheduler_id)

        # Fetch scheduler
        scheduler = oc_scheduler_manager.get_scheduler(scheduler_id)

        # CLOUD MODE → Unmap title before sending to frontend
        if scheduler and is_hosted_cloud():
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
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@oc_schedulers_blueprint.protect(auth=True, right=OcRight.CONNECTION_VIEW.value)
@handle_oc_errors("retrieving Automations!")
def get_all_oc_schedulers(request_user: CmdbUser) -> Response:
    """
    GET/HEAD route to retrieve all accessible OcSchedulers.

    Cloud mode:
        - Scheduler IDs come from cache first, then DG SP if cache missing.
        - Each scheduler's title is unmapped for frontend usage.

    Local mode:
        - Returns all schedulers directly.

    Raises:
        HTTPException: 403 without ``base.openCelium.connection.view``; 500 when OpenCelium cannot answer the list
    """
    try:
        oc_scheduler_manager: OcSchedulerManager = build_scheduler_manager(request_user)

        # CLOUD MODE → Retrieve scheduler IDs (CACHE FIRST)
        if is_hosted_cloud():
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
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@oc_schedulers_blueprint.protect(auth=True, right=OcRight.CONNECTION_VIEW.value)
@handle_oc_errors("retrieving running Automations!")
def get_oc_running_schedulers(request_user: CmdbUser) -> Response:
    """
    GET/HEAD route to retrieve running schedulers

    Raises:
        HTTPException: 403 without ``base.openCelium.connection.view``; 500 when OpenCelium cannot answer the running
                       ones
    """
    try:
        oc_scheduler_manager: OcSchedulerManager = build_scheduler_manager(request_user)

        running_schedulers: list[dict[str, Any]] = oc_scheduler_manager.get_running_schedulers()

        if is_hosted_cloud():
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
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@oc_schedulers_blueprint.protect(auth=True, right=OcRight.CONNECTION_VIEW.value)
@handle_oc_errors("retrieving Automation logs!")
def get_oc_scheduler_logs(request_user: CmdbUser) -> Response:
    """
    GET/HEAD route to retrieve logs of an OC scheduler

    status (str): It can either be s (success) or f (failed)

    Raises:
        HTTPException: 403 without ``base.openCelium.connection.view``; 400 for a missing or unknown log status, 500
                       when OpenCelium cannot answer
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

        oc_scheduler_manager: OcSchedulerManager = build_scheduler_manager(request_user)

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
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@oc_schedulers_blueprint.protect(auth=True, right=OcRight.CONNECTION_EDIT.value)
@handle_oc_errors("executing the Automation!")
def execute_oc_scheduler(request_user: CmdbUser, scheduler_id: int) -> Response:
    """
    GET/HEAD route to execute an OC Scheduler with the given scheduler_id.

    Cloud mode:
        - Scheduler ID validity is checked via cache first, then DG SP.

    Raises:
        HTTPException: 403 without ``base.openCelium.connection.edit``; in cloud mode 400 for an Automation outside the
                       subscription; 500 when OpenCelium cannot run it
    """
    try:
        oc_scheduler_manager: OcSchedulerManager = build_scheduler_manager(request_user)

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
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@oc_schedulers_blueprint.protect(auth=True, right=OcRight.CONNECTION_EDIT.value)
@handle_oc_errors("updating an Automation!")
def update_oc_scheduler(request_user: CmdbUser, scheduler_id: int) -> Response:
    """
    PUT route to update an OcScheduler.

    Cloud mode:
        - Scheduler ID access validated via cache first, then DG Service Portal
        - Title is mapped/unmapped per tenant

    Raises:
        HTTPException: 403 without ``base.openCelium.connection.edit``; in cloud mode 400 for an Automation outside the
                       subscription; 400 when the body is no object or its title is missing (cloud mode), blank or no
                       text, or the update fails
    """
    try:
        oc_scheduler_manager: OcSchedulerManager = build_scheduler_manager(request_user)

        # In cloud mode, verify the Automation belongs to the requesting user (cache-first)
        assert_scheduler_access(request_user, scheduler_id)

        params: dict[str, Any] = read_scheduler_update_body(request.json, title_required=is_hosted_cloud())

        # Map titles
        if is_hosted_cloud():
            params[OcResponseKey.TITLE.value] = map_oc_name(request_user.database, params[OcResponseKey.TITLE.value])

        updated_oc_scheduler = oc_scheduler_manager.update_scheduler(params, scheduler_id)

        # Unmap for UI
        if is_hosted_cloud():
            unmap_scheduler_titles(updated_oc_scheduler)

        return DefaultResponse(updated_oc_scheduler).make_response()
    except HTTPException as http_err:
        raise http_err
    except OcSchedulerUpdateError as err:
        LOGGER.error("[update_oc_scheduler] %s: %s", type(err), err, exc_info=True)
        abort(400, f"Failed to update the Automation with ID: {scheduler_id}!")

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

@oc_schedulers_blueprint.route('/schedulers/<int:scheduler_id>', methods=['DELETE'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@oc_schedulers_blueprint.protect(auth=True, right=OcRight.CONNECTION_DELETE.value)
@handle_oc_errors("deleting the Automation!")
def delete_oc_scheduler(request_user: CmdbUser, scheduler_id: int) -> Response:
    """
    DELETE route to delete an OcScheduler

    Cloud mode:
        - Validate schedulerId and its connectionId via cache first,
          then Service Portal.
        - Remove deleted IDs from Service Portal.

    Raises:
        HTTPException: 403 without ``base.openCelium.connection.delete``; in cloud mode 400 for an Automation outside
                       the subscription; 500 when a delete fails
    """
    try:
        oc_scheduler_manager: OcSchedulerManager = build_scheduler_manager(request_user)
        oc_connection_manager: OcConnectionManager = build_connection_manager(request_user)

        # Cloud-only collaborators; left None on-premise where the cloud branches are skipped
        dg_sp_manager = None
        cached_user_manager = None

        # FETCH SCHEDULER FIRST (NEEDED TO ACCESS connectionId)
        scheduler = oc_scheduler_manager.get_scheduler(scheduler_id)
        if not scheduler:
            abort(400, f"Automation with ID:{scheduler_id} does not exist!")

        connection_id = int(scheduler[OcResponseKey.CONNECTION.value][OcResponseKey.CONNECTION_ID.value])

        # CLOUD MODE → VALIDATE ID ACCESS (CACHE FIRST)
        if is_hosted_cloud():
            dg_sp_manager = DgServicePortalManager()
            cached_user_manager = get_cached_user_manager()

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
            if is_hosted_cloud():
                dg_sp_manager.delete_scheduler_id(
                    scheduler_id,
                    request_user.email,
                    request_user.database
                )

                cached_user_manager.delete_cached_user(request_user.email)

            # Delete Connection
            oc_connection_manager.delete_connection(connection_id)

            # Cleanup ServicePortal connection entry
            if is_hosted_cloud():
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
