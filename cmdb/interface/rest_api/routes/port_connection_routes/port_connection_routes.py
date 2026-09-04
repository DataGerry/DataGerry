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
Implementation of all API routes for handling CmdbPortConnections

These routes are the only way a connection is written. Four invariants hold across them:

1. **The connection rights alone govern the surface.** A connection spans two CmdbObjects, and unlike
   the /ports routes these do NOT additionally check either endpoint object's ACL - decision Q13,
   taken 2026-09-03, following the Rack-mount precedent for a row that joins two things. The
   trade-off is recorded on `ConnectionRight` rather than hidden: a caller holding these rights can
   cable together two objects they could not open individually.
2. **The endpoints and the connection type are immutable.** An update writes cable information only;
   a re-cable is a delete plus a create. Moving an endpoint would drop the row onto a port whose
   cardinality slot was never checked for it.
3. **The identity and the audit fields are server-owned.** A payload public_id is ignored, and
   `author_id` / `creation_time` / `last_edit_time` are stamped from the request.
4. **The cardinality rules are the DATABASE's.** A port holds at most one cable and at most one
   internal connection, no pair repeats, and a cable CI belongs to one connection - all four held by
   the collection's partial unique indexes. The routes pre-check them for a readable 400 and translate
   the index's duplicate-key error into the same wording, which is what covers two concurrent
   requests, since a pre-check is a read followed by a write.

`§35`'s rule holds by construction: every route here touches exactly the connection it addresses, and
the delete cascades are scoped to the ports actually being removed - resolving or deleting one
connection never removes another.

The whole surface is gated behind the licensed IPAM feature (see init_rest_api), like /ports and
/racks: `uses_ports` cannot be turned on without that licence either
"""
from logging import Logger, getLogger
from datetime import datetime, timezone
from typing import Any

from flask import request, abort
from werkzeug import Response
from werkzeug.exceptions import HTTPException

from cmdb.manager import ObjectsManager, TypesManager
from cmdb.manager.port_connections_manager import PortConnectionsManager
from cmdb.manager.ports_manager import PortsManager
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType

from cmdb.models.port_connection_model import PortConnectionKey, sort_endpoints
from cmdb.models.user_model import CmdbUser

from cmdb.errors.manager.port_connections_manager import (
    PortConnectionsManagerDeleteError,
    PortConnectionsManagerGetError,
    PortConnectionsManagerInsertError,
    PortConnectionsManagerUpdateError,
)

from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.route_utils import insert_request_user, verify_api_access
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.rest_api.responses import (
    DefaultResponse,
    DeleteSingleResponse,
    GetSingleResponse,
    InsertSingleResponse,
    UpdateSingleResponse,
)

from cmdb.interface.rest_api.routes.port_connection_routes.port_connection_route_constants import (
    ConnectionRequestKey,
    ConnectionRight,
)
from cmdb.interface.rest_api.routes.port_connection_routes.port_connection_route_helper import (
    build_cable_info,
    build_connection_candidate,
    duplicate_key_abort,
    enforce_cable_ci_free,
    enforce_connection_shape,
    enforce_endpoints_free,
    get_connection_or_abort,
    get_port_or_abort,
    get_requested_connection_type_or_abort,
    refuse_identity_change,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

port_connection_blueprint = APIBlueprint('port_connections', __name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                   CRUD - CREATE                                                      #
# -------------------------------------------------------------------------------------------------------------------- #

@port_connection_blueprint.route('/', methods=['POST'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@port_connection_blueprint.protect(auth=True, right=ConnectionRight.ADD.value)
def insert_cmdb_port_connection(request_user: CmdbUser) -> Response:
    """
    HTTP `POST` route to create a CmdbPortConnection between two CmdbPorts

    The endpoints are stored canonically sorted, which is what makes the link undirected: 'A to B' and
    'B to A' are the same document, so neither end is a source and a duplicate pair cannot exist

    Args:
        request_user (CmdbUser): CmdbUser requesting this operation

    Raises:
        HTTPException: 400 when the shape is invalid, an endpoint's slot of this kind is taken, or the
                       cable CI is already used; 404 when the created connection cannot be read back;
                       500 on an unexpected error

    Returns:
        InsertSingleResponse: The new CmdbPortConnection and its public_id
    """
    payload: dict[str, Any] = {}
    connection_type: str = ''
    endpoints: list[int] | None = None

    try:
        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
        types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)
        ports_manager: PortsManager = ManagerProvider.get_manager(ManagerType.PORTS, request_user)
        port_connections_manager: PortConnectionsManager = ManagerProvider.get_manager(
            ManagerType.PORT_CONNECTIONS, request_user)

        payload = request.get_json(silent=True) or {}

        connection_type = get_requested_connection_type_or_abort(payload)
        enforce_connection_shape(ports_manager, objects_manager, types_manager, connection_type, payload)

        # Sorted only after the shape check passed, so an unusable value was already refused with its
        # own message rather than reaching here as None
        endpoints = sort_endpoints(payload.get(ConnectionRequestKey.ENDPOINTS.value))

        enforce_endpoints_free(port_connections_manager, connection_type, endpoints)
        enforce_cable_ci_free(
            port_connections_manager, payload.get(ConnectionRequestKey.CABLE_CI_ID.value),
        )

        candidate: dict[str, Any] = build_connection_candidate(endpoints, connection_type, payload)
        candidate[PortConnectionKey.AUTHOR_ID.value] = request_user.get_public_id()
        candidate[PortConnectionKey.CREATION_TIME.value] = datetime.now(timezone.utc)
        candidate[PortConnectionKey.LAST_EDIT_TIME.value] = None

        new_id: int = port_connections_manager.insert_item(candidate)

        created: dict[str, Any] | None = port_connections_manager.get_item(new_id, as_dict=True)

        if not created:
            abort(404, 'Could not retrieve the created Port connection from the database!')

        return InsertSingleResponse(created, new_id).make_response()
    except HTTPException as http_err:
        raise http_err
    except PortConnectionsManagerInsertError as err:
        # The partial unique indexes are what stop two concurrent creates, and they are the only thing
        # that can: every check above is a read followed by a write
        LOGGER.error("[insert_cmdb_port_connection] PortConnectionsManagerInsertError: %s", err, exc_info=True)
        duplicate_key_abort(err, connection_type, endpoints)
    except Exception as err:
        LOGGER.error("[insert_cmdb_port_connection] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, 'An internal server error occured while creating the Port connection!')

# -------------------------------------------------------------------------------------------------------------------- #
#                                                    CRUD - READ                                                       #
# -------------------------------------------------------------------------------------------------------------------- #

@port_connection_blueprint.route('/<int:public_id>', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@port_connection_blueprint.protect(auth=True, right=ConnectionRight.VIEW.value)
def get_cmdb_port_connection(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route to retrieve a single CmdbPortConnection

    Args:
        public_id (int): public_id of the CmdbPortConnection
        request_user (CmdbUser): CmdbUser requesting this data

    Raises:
        HTTPException: 404 when the connection does not exist; 500 on an unexpected error

    Returns:
        GetSingleResponse: The requested CmdbPortConnection
    """
    try:
        port_connections_manager: PortConnectionsManager = ManagerProvider.get_manager(
            ManagerType.PORT_CONNECTIONS, request_user)

        connection: dict[str, Any] = get_connection_or_abort(port_connections_manager, public_id)

        return GetSingleResponse(connection, body=request.method == 'HEAD').make_response()
    except HTTPException as http_err:
        raise http_err
    except PortConnectionsManagerGetError as err:
        LOGGER.error("[get_cmdb_port_connection] PortConnectionsManagerGetError: %s", err, exc_info=True)
        abort(400, f'Failed to retrieve the Port connection with ID: {public_id} from the database!')
    except Exception as err:
        LOGGER.error("[get_cmdb_port_connection] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f'An internal server error occured while retrieving the Port connection ID: {public_id}!')


@port_connection_blueprint.route('/port/<int:port_id>', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@port_connection_blueprint.protect(auth=True, right=ConnectionRight.VIEW.value)
def get_cmdb_port_connections_of_port(port_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route to retrieve every CmdbPortConnection one CmdbPort takes part in

    One indexed predicate finds the port at either end, because the two ids share one array field. A
    panel port legitimately answers with two: its cable and its internal pairing. A port that is
    connected to nothing answers with an empty list - "free" is a normal state, not a 404. The PORT
    not existing is a 404, because that is a different answer

    Args:
        port_id (int): public_id of the CmdbPort
        request_user (CmdbUser): CmdbUser requesting this data

    Raises:
        HTTPException: 404 when the port does not exist; 500 on an unexpected error

    Returns:
        DefaultResponse: The port's CmdbPortConnections as a list
    """
    try:
        ports_manager: PortsManager = ManagerProvider.get_manager(ManagerType.PORTS, request_user)
        port_connections_manager: PortConnectionsManager = ManagerProvider.get_manager(
            ManagerType.PORT_CONNECTIONS, request_user)

        get_port_or_abort(ports_manager, port_id)

        return DefaultResponse(
            port_connections_manager.get_connections_of_port(port_id),
        ).make_response()
    except HTTPException as http_err:
        raise http_err
    except PortConnectionsManagerGetError as err:
        LOGGER.error("[get_cmdb_port_connections_of_port] PortConnectionsManagerGetError: %s", err, exc_info=True)
        abort(400, f'Failed to retrieve the Port connections of Port ID: {port_id} from the database!')
    except Exception as err:
        LOGGER.error("[get_cmdb_port_connections_of_port] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f'An internal server error occured while retrieving the connections of Port ID: {port_id}!')

# -------------------------------------------------------------------------------------------------------------------- #
#                                                   CRUD - UPDATE                                                      #
# -------------------------------------------------------------------------------------------------------------------- #

@port_connection_blueprint.route('/<int:public_id>', methods=['PUT', 'PATCH'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@port_connection_blueprint.protect(auth=True, right=ConnectionRight.EDIT.value)
def update_cmdb_port_connection(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `PUT`/`PATCH` route to update the cable information of a single CmdbPortConnection

    **Cable information only.** The endpoints and the connection type are immutable - a payload naming
    different ones is refused rather than ignored, so a client can not discover that its edit did
    nothing. A re-cable is a delete plus a create.

    A cable CI the body omits is REMOVED, not kept: these routes take the whole connection, and the
    key has to be unset rather than nulled because the index that guarantees one CI per connection is
    filtered on the key's presence

    Args:
        public_id (int): public_id of the CmdbPortConnection to update
        request_user (CmdbUser): CmdbUser requesting this operation

    Raises:
        HTTPException: 400 when the payload changes an immutable field, the cable CI is already used,
                       or a cable field is set on an INTERNAL connection; 404 when the connection does
                       not exist; 500 on an unexpected error

    Returns:
        UpdateSingleResponse: The new data of the CmdbPortConnection
    """
    try:
        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
        types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)
        port_connections_manager: PortConnectionsManager = ManagerProvider.get_manager(
            ManagerType.PORT_CONNECTIONS, request_user)

        payload: dict[str, Any] = request.get_json(silent=True) or {}

        stored: dict[str, Any] = get_connection_or_abort(port_connections_manager, public_id)

        refuse_identity_change(stored, payload)

        # The stored type decides which fields are allowed, not the payload's: the type is immutable,
        # so a body that omits it must be judged by what the connection actually IS
        connection_type: str = stored.get(PortConnectionKey.CONNECTION_TYPE.value)

        enforce_connection_shape(
            ManagerProvider.get_manager(ManagerType.PORTS, request_user),
            objects_manager, types_manager, connection_type,
            {**payload, ConnectionRequestKey.ENDPOINTS.value: stored.get(PortConnectionKey.ENDPOINTS.value)},
        )
        enforce_cable_ci_free(
            port_connections_manager, payload.get(ConnectionRequestKey.CABLE_CI_ID.value),
            exclude_id=public_id,
        )

        cable_info: dict[str, Any] = build_cable_info(payload)
        cable_info[PortConnectionKey.LAST_EDIT_TIME.value] = datetime.now(timezone.utc)

        port_connections_manager.replace_connection(public_id, cable_info)

        updated: dict[str, Any] = get_connection_or_abort(port_connections_manager, public_id)

        return UpdateSingleResponse(updated).make_response()
    except HTTPException as http_err:
        raise http_err
    except PortConnectionsManagerUpdateError as err:
        LOGGER.error("[update_cmdb_port_connection] PortConnectionsManagerUpdateError: %s", err, exc_info=True)
        abort(400, f'Failed to update the Port connection with ID: {public_id}!')
    except Exception as err:
        LOGGER.error("[update_cmdb_port_connection] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f'An internal server error occured while updating the Port connection ID: {public_id}!')

# -------------------------------------------------------------------------------------------------------------------- #
#                                                   CRUD - DELETE                                                      #
# -------------------------------------------------------------------------------------------------------------------- #

@port_connection_blueprint.route('/<int:public_id>', methods=['DELETE'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@port_connection_blueprint.protect(auth=True, right=ConnectionRight.DELETE.value)
def delete_cmdb_port_connection(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `DELETE` route to delete a single CmdbPortConnection

    Resolving a connection removes exactly this one row and nothing else - the concept's rule that
    resolving or deleting one connection must never delete another. A patch-panel pair holds a front
    connection, a rear connection and an internal pairing, and each is addressed and resolved on its
    own. Neither endpoint port is touched: they simply become free again, which needs no write because
    `connected` is computed on read

    Args:
        public_id (int): public_id of the CmdbPortConnection to delete
        request_user (CmdbUser): CmdbUser requesting this operation

    Raises:
        HTTPException: 404 when the connection does not exist; 500 on an unexpected error

    Returns:
        DeleteSingleResponse: The deleted CmdbPortConnection data
    """
    try:
        port_connections_manager: PortConnectionsManager = ManagerProvider.get_manager(
            ManagerType.PORT_CONNECTIONS, request_user)

        connection: dict[str, Any] = get_connection_or_abort(port_connections_manager, public_id)

        port_connections_manager.delete_item(public_id)

        return DeleteSingleResponse(connection).make_response()
    except HTTPException as http_err:
        raise http_err
    except PortConnectionsManagerDeleteError as err:
        LOGGER.error("[delete_cmdb_port_connection] PortConnectionsManagerDeleteError: %s", err, exc_info=True)
        abort(400, f'Failed to delete the Port connection with ID: {public_id}!')
    except Exception as err:
        LOGGER.error("[delete_cmdb_port_connection] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f'An internal server error occured while deleting the Port connection ID: {public_id}!')
