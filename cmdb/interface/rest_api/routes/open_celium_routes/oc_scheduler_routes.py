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
from cmdb.open_celium import map_oc_name, unmap_oc_name, CachedOcIdType

from cmdb.models.user_model import CmdbUser
from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.route_utils import insert_request_user, verify_api_access, handle_oc_errors
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.rest_api.responses import DefaultResponse

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
@handle_oc_errors("creating an OpenCelium Scheduler!")
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
        dg_sp_manager = DgServicePortalManager()
        cached_user_manager = CachedUserManager(current_app.database_manager)

        params: dict[str, Any] = request.json

        if not params.get("connection"):
            abort(400, "No 'connection' data provided to create the Automation!")

        if not params.get("scheduler"):
            abort(400, "No 'scheduler' data provided to create the Automation!")

        created_connection: dict[str, Any] = None
        conn_data = params["connection"]
        sched_data = params["scheduler"]

        conn_title = conn_data["title"]

        # ------------------------------------------------------------
        # CLOUD MODE → map connection title
        # ------------------------------------------------------------
        if current_app.cloud_mode and not current_app.local_mode:
            conn_title = map_oc_name(request_user.database, conn_title)
            conn_data["title"] = conn_title

        # ------------------------------------------------------------
        # Create connection (scheduler always requires a connection)
        # Reject if connection name already exists
        # ------------------------------------------------------------
        if oc_connection_manager.check_connection_name_exists(conn_title):
            # Unmap for frontend error message
            if current_app.cloud_mode and not current_app.local_mode:
                conn_title = unmap_oc_name(conn_title)

            abort(400, f"The connection name: {conn_title} already exists!")

        # Create connection in OC
        created_connection = oc_connection_manager.create_connection(conn_data)

        # ------------------------------------------------------------
        # CLOUD MODE → save connectionId in DG SP
        # ------------------------------------------------------------
        if current_app.cloud_mode and not current_app.local_mode:
            dg_sp_manager.save_connection_id(
                created_connection["connectionId"],
                request_user.email,
                request_user.database
            )

            # Clear cache because it now contains inconsistent IDs
            cached_user_manager.delete_cached_user(request_user.email)


        # ------------------------------------------------------------
        # Create scheduler
        # ------------------------------------------------------------
        sched_data["connectionId"] = created_connection["connectionId"]

        if current_app.cloud_mode and not current_app.local_mode:
            sched_data["title"] = map_oc_name(request_user.database, sched_data["title"])

        created_scheduler = oc_scheduler_manager.create_scheduler(sched_data)

        # ------------------------------------------------------------
        # CLOUD MODE → save schedulerId in DG SP
        # ------------------------------------------------------------
        if current_app.cloud_mode and not current_app.local_mode:
            dg_sp_manager.save_scheduler_id(
                created_scheduler["schedulerId"],
                request_user.email,
                request_user.database
            )

            cached_user_manager.delete_cached_user(request_user.email)

            # Unmap title for frontend
            created_scheduler["title"] = unmap_oc_name(created_scheduler["title"])

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
# def create_oc_scheduler(request_user: CmdbUser) -> Response:
#     """
#     POST route to create an OcSchedulers in OpenCelium

#     Args:
#         params (dict[str, Any]): the data of the new OcSchedulers
#         request_user (CmdbUser): User requesting this data

#     Returns:
#         dict[str, Any]: The created OcSchedulers
#     """
#     try:
#         oc_scheduler_manager: OcSchedulerManager = OcSchedulerManager()
#         oc_connection_manager: OcConnectionManager = OcConnectionManager()
#         dg_sp_manager: DgServicePortalManager = DgServicePortalManager()

#         params: dict[str, Any] = request.json

#         if not params.get('connection'):
#             abort(400, "No 'connection' data provided to create the Connection of the Automation!")

#         if not params.get('scheduler'):
#             abort(400, "No 'scheduler' data provided to create the Automation!")

#         created_connection: dict[str, Any] = None
#         conn_title: str = params['connection']['title']

#         if current_app.cloud_mode and not current_app.local_mode:
#             conn_title = map_oc_name(request_user.database, conn_title)

#         if not oc_connection_manager.check_connection_name_exists(conn_title):
#             # Map the connection name before it is created
#             if current_app.cloud_mode and not current_app.local_mode:
#                 params['connection']['title'] = conn_title

#             created_connection = oc_connection_manager.create_connection(params['connection'])

#             # Save the new connectionId in DG ServicePortal
#             if current_app.cloud_mode and not current_app.local_mode:
#                 dg_sp_manager.save_connection_id(
#                     created_connection['connectionId'],
#                     request_user.email,
#                     request_user.database
#                 )
#         else:
#             abort(400, f"The connection name: {conn_title} already exists!")

#         scheduler_params: dict[str, Any] = params['scheduler']
#         scheduler_params['connectionId'] = created_connection['connectionId']

#         if current_app.cloud_mode and not current_app.local_mode:
#             scheduler_params['title'] = map_oc_name(request_user.database, scheduler_params['title'])

#         created_oc_scheduler: dict[str, Any] = oc_scheduler_manager.create_scheduler(scheduler_params)

#         # Save the new schedulerId in DG ServicePortal
#         if current_app.cloud_mode and not current_app.local_mode:
#             dg_sp_manager.save_scheduler_id(
#                 created_oc_scheduler['schedulerId'],
#                 request_user.email,
#                 request_user.database
#             )

#             created_oc_scheduler['title'] = unmap_oc_name(created_oc_scheduler['title'])

#         return DefaultResponse(created_oc_scheduler).make_response()
#     except HTTPException as http_err:
#         raise http_err
#     except OcConnectionCreateError as err:
#         LOGGER.error("[create_oc_scheduler] %s: %s", type(err).__name__, err, exc_info=True)
#         abort(500, "Failed to create Connection of Automation!")
#     except OcConnectionGetError as err:
#         LOGGER.error("[create_oc_scheduler] %s: %s", type(err).__name__, err, exc_info=True)
#         abort(500, "Failed to check Connection name uniqueness!")
#     except OcSchedulerCreateError as err:
#         LOGGER.error("[create_oc_scheduler] %s: %s", type(err).__name__, err, exc_info=True)
#         abort(500, "Failed to create the Automation!")

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

@oc_schedulers_blueprint.route('/schedulers/<int:scheduler_id>', methods=['GET', 'HEAD'])
@handle_oc_errors("retrieving the OpenCelium Scheduler!")
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
        dg_sp_manager = DgServicePortalManager()
        cached_user_manager = CachedUserManager(current_app.database_manager)

        # ------------------------------------------------------------
        # CLOUD MODE → Validate scheduler access (CACHE FIRST)
        # ------------------------------------------------------------
        if current_app.cloud_mode and not current_app.local_mode:
            cached_user = cached_user_manager.get_cached_user(request_user.email)

            if cached_user:
                is_valid = cached_user_manager.oc_id_exists(
                    cached_user,
                    request_user.database,
                    CachedOcIdType.SCHEDULERS,
                    scheduler_id
                )
            else:
                is_valid = dg_sp_manager.check_scheduler_in_sub(
                    scheduler_id,
                    request_user.email,
                    request_user.database
                )

            if not is_valid:
                abort(400, f"The target Automation with ID:{scheduler_id} was not found!")

        # ------------------------------------------------------------
        # Fetch scheduler
        # ------------------------------------------------------------
        scheduler = oc_scheduler_manager.get_scheduler(scheduler_id)

        # ------------------------------------------------------------
        # CLOUD MODE → Unmap title before sending to frontend
        # ------------------------------------------------------------
        if scheduler and current_app.cloud_mode and not current_app.local_mode:
            scheduler["title"] = unmap_oc_name(scheduler["title"])

        return DefaultResponse(scheduler).make_response()
    except HTTPException as http_err:
        raise http_err
    except OcSchedulerGetError as err:
        LOGGER.error("[get_oc_scheduler] OcSchedulerGetError: %s.", err, exc_info=True)
        abort(500, f"Failed to retrieve OpenCelium Scheduler with ID:{scheduler_id}!")
# def get_oc_scheduler(request_user: CmdbUser, scheduler_id: int) -> Response:
#     """
#     GET/HEAD route to retrive an OcScheduler with the given scheduler_id

#     Args:
#         request_user (CmdbUser): User requesting this data
#         scheduler_id (int): schedulerId of the OcSchedulers

#     Returns:
#         dict[str, Any]: The OcSchedulers from OpenCelium
#     """
#     try:
#         oc_scheduler_manager: OcSchedulerManager = OcSchedulerManager()
#         dg_sp_manager: DgServicePortalManager = DgServicePortalManager()

#         if current_app.cloud_mode and not current_app.local_mode:
#             is_valid_scheduler: bool = dg_sp_manager.check_scheduler_in_sub(
#                 scheduler_id,
#                 request_user.email,
#                 request_user.database
#             )

#             if not is_valid_scheduler:
#                 abort(400, f"The target Automation with ID:{scheduler_id} was not found!")

#         scheduler: dict[str, Any] = oc_scheduler_manager.get_scheduler(scheduler_id)

#         if scheduler and current_app.cloud_mode and not current_app.local_mode:
#             scheduler['title'] = unmap_oc_name(scheduler['title'])

#         # LOGGER.debug(f"scheduler: {scheduler}")

#         return DefaultResponse(scheduler).make_response()
#     except HTTPException as http_err:
#         raise http_err
#     except OcSchedulerGetError as err:
#         LOGGER.error("[get_oc_scheduler] OcSchedulerGetError: %s.", err, exc_info=True)
#         abort(500, f"Failed to retrieve OpenCelium Scheduler with ID:{scheduler_id}!")


@oc_schedulers_blueprint.route('/schedulers', methods=['GET', 'HEAD'])
@handle_oc_errors("retrieving OpenCelium Schedulers!")
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
        dg_sp_manager = DgServicePortalManager()
        cached_user_manager = CachedUserManager(current_app.database_manager)

        # ------------------------------------------------------------
        # CLOUD MODE → Retrieve scheduler IDs (CACHE FIRST)
        # ------------------------------------------------------------
        if current_app.cloud_mode and not current_app.local_mode:

            cached_user = cached_user_manager.get_cached_user(request_user.email)

            if cached_user:
                scheduler_ids = cached_user_manager.get_oc_ids(
                    cached_user,
                    request_user.database,
                    CachedOcIdType.SCHEDULERS
                )
            else:
                scheduler_ids = dg_sp_manager.get_scheduler_ids(
                    request_user.email,
                    request_user.database
                )

            schedulers = None

            if scheduler_ids:
                schedulers = oc_scheduler_manager.get_schedulers_by_ids(scheduler_ids)

                # Unmap for UI
                for sched in schedulers:
                    sched["title"] = unmap_oc_name(sched["title"])


        # ------------------------------------------------------------
        # LOCAL MODE → Retrieve all schedulers
        # ------------------------------------------------------------
        else:
            schedulers = oc_scheduler_manager.get_all_schedulers()

        return DefaultResponse(schedulers).make_response()
    except OcSchedulerGetError as err:
        LOGGER.error("[get_all_oc_schedulers] %s: %s.", type(err).__name__, err, exc_info=True)
        abort(500, "Failed to retrieve OpenCelium Schedulers!")
# def get_all_oc_schedulers(request_user: CmdbUser) -> Response:
#     """
#     **GET**/**HEAD** route for getting multiple OcSchedulers

#     Args:
#         request_user (CmdbUser): User requesting this data

#     Returns:
#         list[dict[str, Any]]: All OcSchedulers from OpenCelium
#     """
#     try:
#         oc_scheduler_manager: OcSchedulerManager = OcSchedulerManager()
#         dg_sp_manager: DgServicePortalManager = DgServicePortalManager()

#         schedulers: list[dict[str, Any]] = None

#         if current_app.cloud_mode and not current_app.local_mode:
#             #Retrieve all corresponding schedulerIds
#             scheduler_ids: list[int] = dg_sp_manager.get_scheduler_ids(request_user.email, request_user.database)
#             schedulers = oc_scheduler_manager.get_schedulers_by_ids(scheduler_ids)

#             for a_scheduler in schedulers:
#                 a_scheduler['title'] = unmap_oc_name(a_scheduler['title'])
#         else:
#             schedulers: list[dict[str, Any]] = oc_scheduler_manager.get_all_schedulers()

#         return DefaultResponse(schedulers).make_response()
#     except OcSchedulerGetError as err:
#         LOGGER.error("[get_all_oc_schedulers] %s: %s.", type(err).__name__, err, exc_info=True)
#         abort(500, "Failed to retrieve OpenCelium Schedulers!")


@oc_schedulers_blueprint.route('/schedulers/execute/<int:scheduler_id>', methods=['GET', 'HEAD'])
@handle_oc_errors("executing the OpenCelium Scheduler!")
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
        dg_sp_manager = DgServicePortalManager()
        cached_user_manager = CachedUserManager(current_app.database_manager)

        # ------------------------------------------------------------
        # CLOUD MODE → Validate scheduler access (CACHE FIRST)
        # ------------------------------------------------------------
        if current_app.cloud_mode and not current_app.local_mode:

            cached_user = cached_user_manager.get_cached_user(request_user.email)

            if cached_user:
                is_valid = cached_user_manager.oc_id_exists(
                    cached_user,
                    request_user.database,
                    CachedOcIdType.SCHEDULERS,
                    scheduler_id
                )
            else:
                is_valid = dg_sp_manager.check_scheduler_in_sub(
                    scheduler_id,
                    request_user.email,
                    request_user.database
                )

            if not is_valid:
                abort(400, f"The target Automation with ID:{scheduler_id} was not found!")

        # ------------------------------------------------------------
        # Execute Scheduler
        # ------------------------------------------------------------
        scheduler_result = oc_scheduler_manager.execute_scheduler(scheduler_id)

        return DefaultResponse(scheduler_result).make_response()
    except HTTPException as http_err:
        raise http_err
    except OcSchedulerGetError as err:
        LOGGER.error("[execute_oc_scheduler] %s: %s.", type(err).__name__, err, exc_info=True)
        abort(500, f"Failed to execute OpenCelium Scheduler with ID: {scheduler_id}!")
# def execute_oc_scheduler(request_user: CmdbUser, scheduler_id: int) -> Response:
#     """
#     **GET**/**HEAD** route to execute an OC Scheduler with given scheduler_id

#     Args:
#         request_user (CmdbUser): User requesting this data
#         scheduler_id (int): schedulerId of the OpenCelium Scheduler which schuld be executed

#     Returns:
#         dict[str, Any]: Result of the Scheduler execution
#     """
#     try:
#         oc_scheduler_manager: OcSchedulerManager = OcSchedulerManager()
#         dg_sp_manager: DgServicePortalManager = DgServicePortalManager()

#         if current_app.cloud_mode and not current_app.local_mode:
#             is_valid_scheduler: bool = dg_sp_manager.check_scheduler_in_sub(
#                 scheduler_id,
#                 request_user.email,
#                 request_user.database
#             )

#             if not is_valid_scheduler:
#                 abort(400, f"The target Automation with ID:{scheduler_id} was not found!")

#         scheduler_result: dict[str, Any] = oc_scheduler_manager.execute_scheduler(scheduler_id)

#         return DefaultResponse(scheduler_result).make_response()
#     except HTTPException as http_err:
#         raise http_err
#     except OcSchedulerGetError as err:
#         LOGGER.error("[execute_oc_scheduler] %s: %s.", type(err).__name__, err, exc_info=True)
#         abort(500, f"Failed to execute OpenCelium Scheduler with ID: {scheduler_id}!")

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

@oc_schedulers_blueprint.route('/schedulers/<int:scheduler_id>', methods=['PUT'])
@handle_oc_errors("updating an OpenCelium Scheduler!")
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
def update_oc_scheduler(request_user: CmdbUser, scheduler_id: int) -> Response:
    """
    PUT route to update an OcScheduler.

    Cloud mode:
        - Scheduler ID access validated via cache first, then DG Service Portal.
        - Title is mapped/unmapped per tenant.
    """
    try:
        oc_scheduler_manager = OcSchedulerManager(
            current_app.database_manager,
            request_user.database
        )
        dg_sp_manager = DgServicePortalManager()
        cached_user_manager = CachedUserManager(current_app.database_manager)

        # ------------------------------------------------------------
        # CLOUD MODE → Validate scheduler access (CACHE FIRST)
        # ------------------------------------------------------------
        if current_app.cloud_mode and not current_app.local_mode:

            cached_user = cached_user_manager.get_cached_user(request_user.email)

            if cached_user:
                is_valid = cached_user_manager.oc_id_exists(
                    cached_user,
                    request_user.database,
                    CachedOcIdType.SCHEDULERS,
                    scheduler_id
                )
            else:
                is_valid = dg_sp_manager.check_scheduler_in_sub(
                    scheduler_id,
                    request_user.email,
                    request_user.database
                )

            if not is_valid:
                abort(400, f"The target Automation with ID:{scheduler_id} was not found!")

        # ------------------------------------------------------------
        # UPDATE PARAMS
        # ------------------------------------------------------------
        params: dict[str, Any] = request.json

        # Map title per tenant
        if current_app.cloud_mode and not current_app.local_mode:
            params["title"] = map_oc_name(request_user.database, params["title"])

        # ------------------------------------------------------------
        # UPDATE OPERATION
        # ------------------------------------------------------------
        updated_oc_scheduler = oc_scheduler_manager.update_scheduler(params, scheduler_id)

        # Unmap for UI
        if current_app.cloud_mode and not current_app.local_mode:
            updated_oc_scheduler["title"] = unmap_oc_name(updated_oc_scheduler["title"])

        return DefaultResponse(updated_oc_scheduler).make_response()
    except HTTPException as http_err:
        raise http_err
    except OcSchedulerUpdateError as err:
        LOGGER.error("[update_oc_scheduler] %s: %s", type(err), err, exc_info=True)
        abort(400, f"Failed to update the Automation with ID: {scheduler_id}!")
# def update_oc_scheduler(request_user: CmdbUser, scheduler_id: int) -> Response:
#     """
#     **PUT** route to update an OcSchedulers

#     Args:
#         params (dict[str, Any]): new data of the OcSchedulers
#         request_user (CmdbUser): User requesting this data
#         scheduler_id (int): the schedulerId of the OcSchedulers

#     Returns:
#         dict[str, Any]: The updated OcSchedulers
#     """
#     try:
#         oc_scheduler_manager: OcSchedulerManager = OcSchedulerManager()
#         dg_sp_manager: DgServicePortalManager = DgServicePortalManager()

#         if current_app.cloud_mode and not current_app.local_mode:
#             is_valid_scheduler: bool = dg_sp_manager.check_scheduler_in_sub(
#                 scheduler_id,
#                 request_user.email,
#                 request_user.database
#             )

#             if not is_valid_scheduler:
#                 abort(400, f"The target Automation with ID:{scheduler_id} was not found!")

#         params: dict[str, Any] = request.json

#         if current_app.cloud_mode and not current_app.local_mode:
#             params['title'] = map_oc_name(request_user.database, params['title'])

#         updated_oc_scheduler: dict[str, Any] = oc_scheduler_manager.update_scheduler(params, scheduler_id)

#         if current_app.cloud_mode and not current_app.local_mode:
#             updated_oc_scheduler['title'] = unmap_oc_name(updated_oc_scheduler['title'])

#         return DefaultResponse(updated_oc_scheduler).make_response()
#     except HTTPException as http_err:
#         raise http_err
#     except OcSchedulerUpdateError as err:
#         LOGGER.error("[update_oc_scheduler] %s: %s", type(err), err, exc_info=True)
#         abort(400, f"Failed to update the Automation with ID: {scheduler_id}!")

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

@oc_schedulers_blueprint.route('/schedulers/<int:scheduler_id>', methods=['DELETE'])
@handle_oc_errors("deleting the OpenCelium Scheduler!")
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
def delete_oc_scheduler(request_user: CmdbUser, scheduler_id: int) -> Response:
    """
    DELETE route to delete an OcScheduler.

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
        dg_sp_manager = DgServicePortalManager()
        cached_user_manager = CachedUserManager(current_app.database_manager)

        # ------------------------------------------------------------
        # FETCH SCHEDULER FIRST (NEEDED TO ACCESS connectionId)
        # ------------------------------------------------------------
        scheduler = oc_scheduler_manager.get_scheduler(scheduler_id)
        if not scheduler:
            abort(400, f"Automation with ID:{scheduler_id} does not exist!")

        connection_id = int(scheduler["connection"]["connectionId"])

        # ------------------------------------------------------------
        # CLOUD MODE → VALIDATE ID ACCESS (CACHE FIRST)
        # ------------------------------------------------------------
        if current_app.cloud_mode and not current_app.local_mode:

            cached_user = cached_user_manager.get_cached_user(request_user.email)

            # Validate schedulerId
            if cached_user:
                valid_scheduler = cached_user_manager.oc_id_exists(
                    cached_user,
                    request_user.database,
                    CachedOcIdType.SCHEDULERS,
                    scheduler_id
                )
            else:
                valid_scheduler = dg_sp_manager.check_scheduler_in_sub(
                    scheduler_id,
                    request_user.email,
                    request_user.database
                )

            if not valid_scheduler:
                abort(400, f"The target Automation with ID:{scheduler_id} was not found!")

            # Validate connectionId
            if cached_user:
                valid_conn = cached_user_manager.oc_id_exists(
                    cached_user,
                    request_user.database,
                    CachedOcIdType.CONNECTIONS,
                    connection_id
                )
            else:
                valid_conn = dg_sp_manager.check_connection_in_sub(
                    connection_id,
                    request_user.email,
                    request_user.database
                )

            if not valid_conn:
                abort(400, f"The target Connection with ID:{connection_id} was not found!")

        # ------------------------------------------------------------
        # DELETE CONNECTION FIRST (OC logic requirement)
        # ------------------------------------------------------------
        oc_connection_manager.delete_connection(connection_id)

        # Cleanup ServicePortal entry
        if current_app.cloud_mode and not current_app.local_mode:
            dg_sp_manager.delete_connection_id(
                connection_id,
                request_user.email,
                request_user.database
            )

            cached_user_manager.delete_cached_user(request_user.email)

        # ------------------------------------------------------------
        # DELETE SCHEDULER
        # ------------------------------------------------------------
        deleted_scheduler: bool = oc_scheduler_manager.delete_scheduler(scheduler_id)

        # Cleanup ServicePortal entry
        if current_app.cloud_mode and not current_app.local_mode:
            dg_sp_manager.delete_scheduler_id(
                scheduler_id,
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
# def delete_oc_scheduler(request_user: CmdbUser, scheduler_id: int) -> Response:
#     """
#     **DELETE** route to delete an OcSchedulers

#     Args:
#         request_user (CmdbUser): User requesting this data
#         scheduler_id (int): the schedulerId of the OcSchedulers

#     Returns:
#         bool: True if deletion was a success else False
#     """
#     try:
#         oc_scheduler_manager: OcSchedulerManager = OcSchedulerManager()
#         oc_conection_manager: OcConnectionManager = OcConnectionManager()
#         dg_sp_manager: DgServicePortalManager = DgServicePortalManager()

#         to_delete_scheduler: dict[str, Any] = oc_scheduler_manager.get_scheduler(scheduler_id)

#         # Check is scheduler_id and connectionId are part of the users subscription
#         if current_app.cloud_mode and not current_app.local_mode:
#             is_valid_conn: bool = dg_sp_manager.check_connection_in_sub(
#                 to_delete_scheduler['connection']['connectionId'],
#                 request_user.email,
#                 request_user.database
#             )

#             if not is_valid_conn:
#                 abort(400, f"The target Automation with ID:{scheduler_id} was not found!")

#             is_valid_scheduler: bool = dg_sp_manager.check_scheduler_in_sub(
#                 scheduler_id,
#                 request_user.email,
#                 request_user.database
#             )

#             if not is_valid_scheduler:
#                 abort(400, f"The target Automation with ID:{scheduler_id} was not found!")

#         # LOGGER.debug(f"[delete_oc_scheduler] to_delete_scheduler: {to_delete_scheduler}")

#         # First delete the connection
#         target_connection = to_delete_scheduler['connection']['connectionId']
#         oc_conection_manager.delete_connection(target_connection)

#         if current_app.cloud_mode and not current_app.local_mode:
#             dg_sp_manager.delete_connection_id(
#                 target_connection,
#                 request_user.email,
#                 request_user.database,
#             )

#         # Then delete scheduler
#         deleted_oc_scheduler: bool = oc_scheduler_manager.delete_scheduler(scheduler_id)

#         if current_app.cloud_mode and not current_app.local_mode:
#             dg_sp_manager.delete_scheduler_id(
#                 scheduler_id,
#                 request_user.email,
#                 request_user.database,
#             )

#         return DefaultResponse(deleted_oc_scheduler).make_response()
#     except HTTPException as http_err:
#         raise http_err
#     except OcSchedulerDeleteError as err:
#         LOGGER.error("[delete_oc_scheduler] %s: %s", type(err), err, exc_info=True)
#         abort(500, f"Failed to delete the OpenCelium Scheduler with ID: {scheduler_id}!")
