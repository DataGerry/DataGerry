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
All API routes for OpenCelium Connections
"""
from logging import Logger, getLogger
from typing import Any

from flask import abort, request, current_app

from werkzeug import Response
from werkzeug.exceptions import HTTPException

from cmdb.manager import (
    OcConnectionManager,
    DgServicePortalManager,
    CachedUserManager,
)

from cmdb.open_celium import map_oc_name, unmap_oc_name, CachedOcIdType

from cmdb.models.user_model import CmdbUser
from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.route_utils import insert_request_user, verify_api_access, handle_oc_errors
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.rest_api.responses import DefaultResponse

from cmdb.errors.open_celium.connection import (
    OcConnectionCreateError,
    OcConnectionGetError,
    OcConnectionUpdateError,
    OcConnectionTestError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

oc_connections_blueprint = APIBlueprint('oc_connections', __name__)

# --------------------------------------------------- CRUD - CREATE -------------------------------------------------- #

@oc_connections_blueprint.route('/connections', methods=['POST'])
@handle_oc_errors("creating an OpenCelium Connection!")
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@oc_connections_blueprint.protect(auth=True, right='base.openCelium.connection.add')
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
        oc_connection_manager: OcConnectionManager = OcConnectionManager(
            current_app.database_manager,
            request_user.database
        )
        dg_sp_manager = DgServicePortalManager()
        cached_user_manager = CachedUserManager(current_app.database_manager)

        params: dict[str, Any] = request.json
        conn_title: str = params["title"]

        # Map title in cloud mode
        if current_app.cloud_mode and not current_app.local_mode:
            mapped_title = map_oc_name(request_user.database, conn_title)
            params["title"] = mapped_title
        else:
            mapped_title = conn_title

        # Check for duplicate
        if oc_connection_manager.check_connection_name_exists(mapped_title):
            if current_app.cloud_mode and not current_app.local_mode:
                conn_title = unmap_oc_name(mapped_title)

            abort(400, f"The connection name '{conn_title}' already exists!")

        # Create in OpenCelium
        created_oc_connection: dict[str, Any] = oc_connection_manager.create_connection(params)
        connection_id = int(created_oc_connection["connectionId"])

        # ------------------------------------------------------
        # Cloud mode: invalidate cache + save ID in Service Portal
        # ------------------------------------------------------
        if current_app.cloud_mode and not current_app.local_mode:
            cached_user_manager.delete_cached_user(request_user.email)

            dg_sp_manager.save_connection_id(
                connection_id,
                request_user.email,
                request_user.database
            )

            # Unmap title for frontend
            created_oc_connection["title"] = unmap_oc_name(created_oc_connection["title"])

        return DefaultResponse(created_oc_connection).make_response()
    except HTTPException as http_err:
        raise http_err
    except OcConnectionCreateError as err:
        LOGGER.error("[create_oc_connection] %s: %s", type(err).__name__, err, exc_info=True)
        abort(400, "Failed to create an OpenCelium Connection!")
# def create_oc_connection(request_user: CmdbUser) -> Response:
#     """
#     **POST** route to create an OcConnection in OpenCelium

#     Args:
#         params (dict[str, Any]): the data of the new OcConnection
#         request_user (CmdbUser): User requesting this data

#     Returns:
#         dict[str, Any]: The created OcConnection
#     """
#     try:
#         oc_connection_manager: OcConnectionManager = OcConnectionManager()
#         dg_sp_manager: DgServicePortalManager = DgServicePortalManager()

#         params: dict[str, Any] = request.json
#         conn_title:str = params['title']

#         if current_app.cloud_mode and not current_app.local_mode:
#             conn_title = map_oc_name(request_user.database, conn_title)
#             params['title'] = conn_title

#         if oc_connection_manager.check_connection_name_exists(conn_title):
#             if current_app.cloud_mode and not current_app.local_mode:
#                 conn_title = unmap_oc_name(conn_title)

#             abort(400, f"The connection name: {conn_title} already exists!")

#         created_oc_connection: dict[str, Any] = oc_connection_manager.create_connection(params)

#         # Save the new connectionId in DG ServicePortal
#         if current_app.cloud_mode and not current_app.local_mode:
#             dg_sp_manager.save_connection_id(
#                 created_oc_connection['connectionId'],
#                 request_user.email,
#                 request_user.database
#             )

#             created_oc_connection['title'] = unmap_oc_name(created_oc_connection['title'])

#         return DefaultResponse(created_oc_connection).make_response()
#     except HTTPException as http_err:
#         raise http_err
#     except OcConnectionCreateError as err:
#         LOGGER.error("[create_oc_connection] %s: %s", type(err).__name__, err, exc_info=True)
#         abort(400, "Failed to create an OpenCelium Connection!")


oc_connections_blueprint.route('/connections/test/<int:channel_id>', methods=['POST'])
@handle_oc_errors("testing an OpenCelium Connection!")
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@oc_connections_blueprint.protect(auth=True, right='base.openCelium.connection.add')
def test_oc_connection(request_user: CmdbUser, channel_id: int) -> Response:
    """
    **POST** route to create an OcConnection in OpenCelium

    Args:
        request_user (CmdbUser): User requesting this data
        channel_id (int): ID of the channel

    Returns:
        dict[str, Any]: The created OcConnection
    """
    try:
        oc_connection_manager: OcConnectionManager = OcConnectionManager(
            current_app.database_manager,
            request_user.database
        )

        connection: dict[str, Any] = request.json

        test_response: dict[str, Any] = oc_connection_manager.test_connection(connection, channel_id)

        return DefaultResponse(test_response).make_response()
    except HTTPException as http_err:
        raise http_err
    except OcConnectionTestError as err:
        LOGGER.error("[create_oc_connection] %s: %s", type(err).__name__, err, exc_info=True)
        abort(400, "Failed to test the OpenCelium Connection!")


oc_connections_blueprint.route('/connections/remote_api', methods=['POST'])
@handle_oc_errors("sending to remote API!")
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@oc_connections_blueprint.protect(auth=True, right='base.openCelium.connection.add')
def oc_send_to_remote_api(request_user: CmdbUser) -> Response:
    """
    **POST** route to call remote API

    Args:
        request_user (CmdbUser): User requesting this data

    Returns:
        dict[str, Any]: The response from remote API
    """
    try:
        oc_connection_manager: OcConnectionManager = OcConnectionManager(
            current_app.database_manager,
            request_user.database
        )

        payload: dict[str, Any] = request.json

        remote_api_response: dict[str, Any] = oc_connection_manager.send_to_remote_api(payload)

        return DefaultResponse(remote_api_response).make_response()
    except HTTPException as http_err:
        raise http_err
    except OcConnectionTestError as err:
        LOGGER.error("[oc_send_to_remote_api] %s: %s", type(err).__name__, err, exc_info=True)
        abort(400, "Failed to send payload to remote API!")

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

@oc_connections_blueprint.route('/connections/<int:connection_id>', methods=['GET', 'HEAD'])
@handle_oc_errors("retrieving the OpenCelium Connection!")
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@oc_connections_blueprint.protect(auth=True, right='base.openCelium.connection.view')
def get_oc_connection(request_user: CmdbUser, connection_id: int) -> Response:
    """
    GET/HEAD route to retrieve an OcConnection by its connection_id.

    Behavior:
    - In cloud mode, validates that the connection belongs to the user's subscription
      using cache first, then Service Portal fallback.
    - The title is unmapped for UI if cloud mode.
    - Local mode retrieves the connection directly from OpenCelium.

    Args:
        request_user (CmdbUser): User requesting this data.
        connection_id (int): The ID of the OcConnection.

    Returns:
        Response: The OcConnection object.
    """
    try:
        oc_connection_manager: OcConnectionManager = OcConnectionManager(
            current_app.database_manager,
            request_user.database
        )
        dg_sp_manager = DgServicePortalManager()
        cached_user_manager = CachedUserManager(current_app.database_manager)

        # ---------------------------
        # Cloud mode: validate connection exists in subscription
        # ---------------------------
        if current_app.cloud_mode and not current_app.local_mode:
            cached_user = cached_user_manager.get_cached_user(request_user.email)

            if cached_user:
                is_valid = cached_user_manager.oc_id_exists(
                    cached_user,
                    request_user.database,
                    CachedOcIdType.CONNECTIONS,
                    connection_id
                )
            else:
                is_valid = dg_sp_manager.check_connection_in_sub(
                    connection_id,
                    request_user.email,
                    request_user.database
                )

            if not is_valid:
                abort(400, f"The target Connection with ID:{connection_id} was not found!")

        # ---------------------------
        # Retrieve connection from OpenCelium
        # ---------------------------
        connection: dict[str, Any] = oc_connection_manager.get_connection(connection_id)

        # Unmap title for cloud mode
        if connection and current_app.cloud_mode and not current_app.local_mode:
            connection["title"] = unmap_oc_name(connection["title"])

        return DefaultResponse(connection).make_response()
    except HTTPException as http_err:
        raise http_err
    except OcConnectionGetError as err:
        LOGGER.error("[get_oc_connection] %s: %s", type(err).__name__, err, exc_info=True)
        abort(500, f"Failed to retrieve OpenCelium Connection with ID:{connection_id}!")
# def get_oc_connection(request_user: CmdbUser, connection_id: int) -> Response:
#     """
#     GET/HEAD route to retrive an OcConnection with the given connection_id

#     Args:
#         request_user (CmdbUser): User requesting this data
#         connection_id (int): connectionId of the OcConnection

#     Returns:
#         dict[str, Any]: The OcConnection from OpenCelium
#     """
#     try:
#         oc_connection_manager: OcConnectionManager = OcConnectionManager()
#         dg_sp_manager: DgServicePortalManager = DgServicePortalManager()

#         if current_app.cloud_mode and not current_app.local_mode:
#             is_valid_connection: bool = dg_sp_manager.check_connection_in_sub(
#                 connection_id,
#                 request_user.email,
#                 request_user.database
#             )

#             if not is_valid_connection:
#                 abort(400, f"The target Connection with ID:{is_valid_connection} was not found!")

#         connection: dict[str, Any] = oc_connection_manager.get_connection(connection_id)

#         if connection and current_app.cloud_mode and not current_app.local_mode:
#             connection['title'] = unmap_oc_name(connection['title'])
#         # LOGGER.debug(f"connection: {connection}")

#         return DefaultResponse(connection).make_response()
#     except HTTPException as http_err:
#         raise http_err
#     except OcConnectionGetError as err:
#         LOGGER.error("[get_oc_connection] %s: %s", type(err).__name__, err, exc_info=True)
#         abort(500, f"Failed to retrieve OpenCelium Connection with ID:{connection_id}!")

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

@oc_connections_blueprint.route('/connections/<int:connection_id>', methods=['PUT'])
@handle_oc_errors("updating an OpenCelium Connection!")
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@oc_connections_blueprint.protect(auth=True, right='base.openCelium.connection.edit')
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
        oc_connection_manager: OcConnectionManager = OcConnectionManager(
            current_app.database_manager,
            request_user.database
        )
        dg_sp_manager = DgServicePortalManager()
        cached_user_manager = CachedUserManager(current_app.database_manager)

        params: dict[str, Any] = request.json

        # ------------------------------------------------------
        # Cloud mode: validate connection exists
        # ------------------------------------------------------
        if current_app.cloud_mode and not current_app.local_mode:
            cached_user = cached_user_manager.get_cached_user(request_user.email)

            if cached_user:
                is_valid = cached_user_manager.oc_id_exists(
                    cached_user,
                    request_user.database,
                    CachedOcIdType.CONNECTIONS,
                    connection_id
                )
            else:
                is_valid = dg_sp_manager.check_connection_in_sub(
                    connection_id,
                    request_user.email,
                    request_user.database
                )

            if not is_valid:
                abort(400, f"The target Connection with ID:{connection_id} was not found!")

            # Map title for tenant
            if "title" in params:
                params["title"] = map_oc_name(request_user.database, params["title"])

        # ------------------------------------------------------
        # Update connection in OpenCelium
        # ------------------------------------------------------
        updated_oc_connection: dict[str, Any] = oc_connection_manager.update_connection(params, connection_id)

        # Invalidate cache after update
        if current_app.cloud_mode and not current_app.local_mode:
            # Unmap title for frontend
            if "title" in updated_oc_connection:
                updated_oc_connection["title"] = unmap_oc_name(updated_oc_connection["title"])

        return DefaultResponse(updated_oc_connection).make_response()
    except HTTPException as http_err:
        raise http_err
    except OcConnectionUpdateError as err:
        LOGGER.error("[update_oc_connection] %s: %s", type(err), err, exc_info=True)
        abort(400, f"Failed to update the OpenCelium Connection with ID: {connection_id}!")
# def update_oc_connection(request_user: CmdbUser, connection_id: int) -> Response:
#     """
#     **PUT** route to update an OcConnection

#     Args:
#         params (dict[str, Any]): new data of the OcConnection
#         request_user (CmdbUser): User requesting this data
#         connection_id (int): the connection_id of the OcConnection

#     Returns:
#         dict[str, Any]: The updated OcConnection
#     """
#     try:
#         oc_connection_manager: OcConnectionManager = OcConnectionManager()
#         dg_sp_manager: DgServicePortalManager = DgServicePortalManager()

#         if current_app.cloud_mode and not current_app.local_mode:
#             is_valid_connection: bool = dg_sp_manager.check_connection_in_sub(
#                 connection_id,
#                 request_user.email,
#                 request_user.database
#             )

#             if not is_valid_connection:
#                 abort(400, f"The target Connection with ID:{connection_id} was not found!")

#         params: dict[str, Any] = request.json

#         if current_app.cloud_mode and not current_app.local_mode:
#             params['title'] = map_oc_name(request_user.database, params['title'])

#         updated_oc_connection: dict[str, Any] = oc_connection_manager.update_connection(params, connection_id)

#         if current_app.cloud_mode and not current_app.local_mode:
#             updated_oc_connection['title'] = unmap_oc_name(updated_oc_connection['title'])

#         return DefaultResponse(updated_oc_connection).make_response()
#     except HTTPException as http_err:
#         raise http_err
#     except OcConnectionUpdateError as err:
#         LOGGER.error("[update_oc_connection] %s: %s", type(err), err, exc_info=True)
#         abort(400, f"Failed to update the OpenCelium Connection with ID: {connection_id}!")
