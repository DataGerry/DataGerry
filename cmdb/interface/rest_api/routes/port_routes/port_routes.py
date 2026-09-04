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
Implementation of all API routes for handling CmdbPorts

These routes are the only way a port is written. Four invariants hold across them:

1. **The owner CmdbObject's ACL is checked on every route.** A port is stored outside the object's
   document, so nothing about it inherits the object's access control - each route resolves the owner
   through `objects_manager.get_object`, which runs `verify_access` and refuses with 403. The port
   rights guard the port surface; they are not a substitute for that.
2. **The owner's CmdbType must declare `uses_ports`.** A port on a type that does not use ports would
   be invisible in the UI, so creating one is refused with 400 rather than stored.
3. **The identity, the owner, the side and the audit fields are server-owned.** A payload public_id is
   ignored, `object_id` and `side` are immutable after creation, and `author_id` / `creation_time` /
   `last_edit_time` are stamped from the request.
4. **A port name is unique within one face of one object.** The routes pre-check it for a readable
   400, and translate the unique index's duplicate-key error into the same 400 - which is what covers
   two concurrent requests, since the pre-check is a read followed by a write.

The whole surface is gated behind the licensed IPAM feature (see init_rest_api), like the /racks
surface: `uses_ports` cannot be turned on without that licence either.

Note the object's ports are read at `GET /ports/object/<object_id>` rather than under /objects: the
child resource owns its URLs, as `/object_relations/tabs/<object_id>` does, and a route living under
/objects while being IPAM-gated and port-righted would read as part of the (ungated) objects API
"""
from logging import Logger, getLogger
from datetime import datetime, timezone
from typing import Any

from flask import request, abort
from werkzeug import Response
from werkzeug.exceptions import HTTPException

from cmdb.manager import ExtendableOptionsManager, ObjectsManager, TypesManager
from cmdb.manager.port_connections_manager import PortConnectionsManager
from cmdb.manager.port_interface_links_manager import PortInterfaceLinksManager
from cmdb.manager.ports_manager import PortsManager
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType

from cmdb.models.object_model.cmdb_object_key_enum import CmdbObjectKey
from cmdb.models.port_model import PortKey
from cmdb.models.user_model import CmdbUser

from cmdb.security.acl.permission import AccessControlPermission

from cmdb.errors.security import AccessDeniedError
from cmdb.errors.manager.ports_manager import (
    PortsManagerDeleteError,
    PortsManagerGetError,
    PortsManagerInsertError,
    PortsManagerUpdateError,
)

from cmdb.framework.port.cascade import delete_connections_of_port, delete_interface_links_of_port

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

from cmdb.interface.rest_api.routes.port_routes.port_route_constants import (
    PORT_NAME_TAKEN_MESSAGE,
    PortRequestKey,
    PortRight,
)
from cmdb.interface.rest_api.routes.port_routes.port_route_helper import (
    build_port_candidate,
    with_connected_flag,
    enforce_port_name_available,
    enforce_select_values,
    enforce_type_uses_ports,
    get_accessible_owner_or_abort,
    get_port_or_abort,
    get_requested_name_or_abort,
    get_requested_side_or_abort,
    refuse_owner_change,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

port_blueprint = APIBlueprint('ports', __name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                   CRUD - CREATE                                                      #
# -------------------------------------------------------------------------------------------------------------------- #

@port_blueprint.route('/', methods=['POST'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@port_blueprint.protect(auth=True, right=PortRight.ADD.value)
def insert_cmdb_port(request_user: CmdbUser) -> Response:
    """
    HTTP `POST` route to create a CmdbPort on a CmdbObject

    The owner comes from the body, because a port is created against an object rather than under one.
    The name must be free on the requested face of that object, and every select value must belong to
    the CmdbExtendableOption list its field draws from

    Args:
        request_user (CmdbUser): CmdbUser requesting this operation

    Raises:
        HTTPException: 400 when the owner's Type does not use ports, the name is taken, or a value is
                       invalid; 403 when the owner's ACL denies it; 404 when the owner does not exist;
                       500 on an unexpected error

    Returns:
        InsertSingleResponse: The new CmdbPort and its public_id
    """
    try:
        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
        types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)
        ports_manager: PortsManager = ManagerProvider.get_manager(ManagerType.PORTS, request_user)
        extendable_options_manager: ExtendableOptionsManager = ManagerProvider.get_manager(
            ManagerType.EXTENDABLE_OPTIONS, request_user)

        payload: dict[str, Any] = request.get_json(silent=True) or {}

        owner: dict[str, Any] = get_accessible_owner_or_abort(
            objects_manager, payload.get(PortRequestKey.OBJECT_ID.value), request_user,
            AccessControlPermission.UPDATE,
        )
        enforce_type_uses_ports(types_manager, owner)

        # Taken from the resolved owner, not read from the payload a second time: whatever the body
        # said, the port belongs to the object whose ACL was just checked
        object_id: int = owner[CmdbObjectKey.PUBLIC_ID]
        side: str = get_requested_side_or_abort(payload)
        name: str = get_requested_name_or_abort(payload)

        enforce_select_values(extendable_options_manager, payload)
        enforce_port_name_available(ports_manager, object_id, side, name)

        candidate: dict[str, Any] = build_port_candidate(object_id, side, name, payload)
        candidate[PortKey.AUTHOR_ID.value] = request_user.get_public_id()
        candidate[PortKey.CREATION_TIME.value] = datetime.now(timezone.utc)
        candidate[PortKey.LAST_EDIT_TIME.value] = None

        new_id: int = ports_manager.insert_item(candidate)

        created_port: dict[str, Any] | None = ports_manager.get_item(new_id, as_dict=True)

        if not created_port:
            abort(404, 'Could not retrieve the created Port from the database!')

        return InsertSingleResponse(created_port, new_id).make_response()
    except HTTPException as http_err:
        raise http_err
    except AccessDeniedError as err:
        LOGGER.error("[insert_cmdb_port] AccessDeniedError: %s", err, exc_info=True)
        abort(403, str(err))
    except PortsManagerInsertError as err:
        # The unique (object_id, side, name) index is what stops two concurrent creates, and it is the
        # only thing that can: the pre-check above is a read followed by a write. Reported as the same
        # readable 400 rather than as a database error
        LOGGER.error("[insert_cmdb_port] PortsManagerInsertError: %s", err, exc_info=True)
        abort(400, PORT_NAME_TAKEN_MESSAGE.format(
            name=payload.get(PortRequestKey.NAME.value),
            side=payload.get(PortRequestKey.SIDE.value),
            object_id=payload.get(PortRequestKey.OBJECT_ID.value),
        ))
    except Exception as err:
        LOGGER.error("[insert_cmdb_port] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, 'An internal server error occured while creating the Port!')

# -------------------------------------------------------------------------------------------------------------------- #
#                                                    CRUD - READ                                                       #
# -------------------------------------------------------------------------------------------------------------------- #

@port_blueprint.route('/<int:public_id>', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@port_blueprint.protect(auth=True, right=PortRight.VIEW.value)
def get_cmdb_port(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route to retrieve a single CmdbPort

    The owner object is resolved even though it is not returned: reading a port means reading part of
    that object, so the object's ACL decides whether the caller may.

    The response carries the derived `connected` flag, which is computed here and never stored - see
    cmdb.framework.port.connected

    Args:
        public_id (int): public_id of the CmdbPort
        request_user (CmdbUser): CmdbUser requesting this data

    Raises:
        HTTPException: 403 when the owner's ACL denies it; 404 when the port or its owner does not
                       exist; 500 on an unexpected error

    Returns:
        GetSingleResponse: The requested CmdbPort, carrying its derived `connected` flag
    """
    try:
        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
        ports_manager: PortsManager = ManagerProvider.get_manager(ManagerType.PORTS, request_user)
        port_connections_manager: PortConnectionsManager = ManagerProvider.get_manager(
            ManagerType.PORT_CONNECTIONS, request_user)

        port: dict[str, Any] = get_port_or_abort(ports_manager, public_id)

        get_accessible_owner_or_abort(
            objects_manager, port.get(PortKey.OBJECT_ID.value), request_user, AccessControlPermission.READ,
        )

        with_connected_flag(port_connections_manager, [port])

        return GetSingleResponse(port, body=request.method == 'HEAD').make_response()
    except HTTPException as http_err:
        raise http_err
    except AccessDeniedError as err:
        LOGGER.error("[get_cmdb_port] AccessDeniedError: %s", err, exc_info=True)
        abort(403, str(err))
    except PortsManagerGetError as err:
        LOGGER.error("[get_cmdb_port] PortsManagerGetError: %s", err, exc_info=True)
        abort(400, f'Failed to retrieve the Port with ID: {public_id} from the database!')
    except Exception as err:
        LOGGER.error("[get_cmdb_port] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f'An internal server error occured while retrieving the Port with ID: {public_id}!')


@port_blueprint.route('/object/<int:object_id>', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@port_blueprint.protect(auth=True, right=PortRight.VIEW.value)
def get_cmdb_ports_of_object(object_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route to retrieve every CmdbPort of one CmdbObject

    The route the ports panel of an object view loads. Ordered by port number and then by name, so a
    port without a number still has a stable place. An object with no ports answers with an empty
    list, not a 404 - "this object has no ports yet" is a normal state.

    Every port carries its derived `connected` flag, resolved for the WHOLE page in one batched query
    rather than one per port - a 48-port switch costs two reads in total

    Args:
        object_id (int): public_id of the owner CmdbObject
        request_user (CmdbUser): CmdbUser requesting this data

    Raises:
        HTTPException: 403 when the object's ACL denies it; 404 when the object does not exist;
                       500 on an unexpected error

    Returns:
        DefaultResponse: The object's CmdbPorts as a list, each carrying its `connected` flag
    """
    try:
        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
        ports_manager: PortsManager = ManagerProvider.get_manager(ManagerType.PORTS, request_user)
        port_connections_manager: PortConnectionsManager = ManagerProvider.get_manager(
            ManagerType.PORT_CONNECTIONS, request_user)

        get_accessible_owner_or_abort(
            objects_manager, object_id, request_user, AccessControlPermission.READ,
        )

        ports: list[dict[str, Any]] = ports_manager.get_ports_of_object(object_id)

        return DefaultResponse(with_connected_flag(port_connections_manager, ports)).make_response()
    except HTTPException as http_err:
        raise http_err
    except AccessDeniedError as err:
        LOGGER.error("[get_cmdb_ports_of_object] AccessDeniedError: %s", err, exc_info=True)
        abort(403, str(err))
    except PortsManagerGetError as err:
        LOGGER.error("[get_cmdb_ports_of_object] PortsManagerGetError: %s", err, exc_info=True)
        abort(400, f'Failed to retrieve the Ports of CmdbObject ID: {object_id} from the database!')
    except Exception as err:
        LOGGER.error("[get_cmdb_ports_of_object] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f'An internal server error occured while retrieving the Ports of CmdbObject ID: {object_id}!')

# -------------------------------------------------------------------------------------------------------------------- #
#                                                   CRUD - UPDATE                                                      #
# -------------------------------------------------------------------------------------------------------------------- #

@port_blueprint.route('/<int:public_id>', methods=['PUT', 'PATCH'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@port_blueprint.protect(auth=True, right=PortRight.EDIT.value)
def update_cmdb_port(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `PUT`/`PATCH` route to update a single CmdbPort

    The owner and the side are immutable: a payload naming a different one is refused rather than
    ignored, so a client can not discover that its edit did nothing. Everything else the body carries
    replaces the stored value, since the routes take the whole port

    Args:
        public_id (int): public_id of the CmdbPort to update
        request_user (CmdbUser): CmdbUser requesting this operation

    Raises:
        HTTPException: 400 when the payload changes an immutable field, the name is taken, or a value
                       is invalid; 403 when the owner's ACL denies it; 404 when the port or its owner
                       does not exist; 500 on an unexpected error

    Returns:
        UpdateSingleResponse: The new data of the CmdbPort
    """
    try:
        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
        ports_manager: PortsManager = ManagerProvider.get_manager(ManagerType.PORTS, request_user)
        extendable_options_manager: ExtendableOptionsManager = ManagerProvider.get_manager(
            ManagerType.EXTENDABLE_OPTIONS, request_user)

        payload: dict[str, Any] = request.get_json(silent=True) or {}

        stored_port: dict[str, Any] = get_port_or_abort(ports_manager, public_id)
        object_id: Any = stored_port.get(PortKey.OBJECT_ID.value)

        get_accessible_owner_or_abort(
            objects_manager, object_id, request_user, AccessControlPermission.UPDATE,
        )

        refuse_owner_change(stored_port, payload)

        name: str = get_requested_name_or_abort(payload)
        side: str = stored_port.get(PortKey.SIDE.value)

        enforce_select_values(extendable_options_manager, payload)
        enforce_port_name_available(ports_manager, object_id, side, name, exclude_id=public_id)

        candidate: dict[str, Any] = build_port_candidate(object_id, side, name, payload)
        candidate[PortKey.PUBLIC_ID.value] = public_id
        candidate[PortKey.AUTHOR_ID.value] = stored_port.get(PortKey.AUTHOR_ID.value)
        candidate[PortKey.CREATION_TIME.value] = stored_port.get(PortKey.CREATION_TIME.value)
        candidate[PortKey.LAST_EDIT_TIME.value] = datetime.now(timezone.utc)

        ports_manager.update_item(public_id, candidate)

        return UpdateSingleResponse(candidate).make_response()
    except HTTPException as http_err:
        raise http_err
    except AccessDeniedError as err:
        LOGGER.error("[update_cmdb_port] AccessDeniedError: %s", err, exc_info=True)
        abort(403, str(err))
    except PortsManagerUpdateError as err:
        LOGGER.error("[update_cmdb_port] PortsManagerUpdateError: %s", err, exc_info=True)
        abort(400, f'Failed to update the Port with ID: {public_id}!')
    except Exception as err:
        LOGGER.error("[update_cmdb_port] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f'An internal server error occured while updating the Port with ID: {public_id}!')

# -------------------------------------------------------------------------------------------------------------------- #
#                                                   CRUD - DELETE                                                      #
# -------------------------------------------------------------------------------------------------------------------- #

@port_blueprint.route('/<int:public_id>', methods=['DELETE'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@port_blueprint.protect(auth=True, right=PortRight.DELETE.value)
def delete_cmdb_port(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `DELETE` route to delete a single CmdbPort

    Deleting a port never touches the owner CmdbObject, but it does take the port's CONNECTIONS and
    its INTERFACE LINKS with it - neither may be left pointing at nothing. Both go first, because each
    is found through the port and a deleted port can no longer be looked up. The peers at the other
    ends simply become free, nothing about them is rewritten since `connected` is computed on read, and
    no CmdbObject's interface rows are touched - a link's interface half is a soft reference

    Args:
        public_id (int): public_id of the CmdbPort to delete
        request_user (CmdbUser): CmdbUser requesting this operation

    Raises:
        HTTPException: 403 when the owner's ACL denies it; 404 when the port or its owner does not
                       exist; 500 on an unexpected error

    Returns:
        DeleteSingleResponse: The deleted CmdbPort data
    """
    try:
        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
        ports_manager: PortsManager = ManagerProvider.get_manager(ManagerType.PORTS, request_user)
        port_connections_manager: PortConnectionsManager = ManagerProvider.get_manager(
            ManagerType.PORT_CONNECTIONS, request_user)
        port_interface_links_manager: PortInterfaceLinksManager = ManagerProvider.get_manager(
            ManagerType.PORT_INTERFACE_LINKS, request_user)

        port: dict[str, Any] = get_port_or_abort(ports_manager, public_id)

        get_accessible_owner_or_abort(
            objects_manager, port.get(PortKey.OBJECT_ID.value), request_user,
            AccessControlPermission.UPDATE,
        )

        # Deliberately NOT guarded by the connection rights: this is cleanup that follows from an
        # operation the caller was already allowed to perform, and refusing it would leave the
        # dangling rows the cascade exists to prevent
        delete_connections_of_port(port_connections_manager, public_id)
        delete_interface_links_of_port(port_interface_links_manager, public_id)

        ports_manager.delete_item(public_id)

        return DeleteSingleResponse(port).make_response()
    except HTTPException as http_err:
        raise http_err
    except AccessDeniedError as err:
        LOGGER.error("[delete_cmdb_port] AccessDeniedError: %s", err, exc_info=True)
        abort(403, str(err))
    except PortsManagerDeleteError as err:
        LOGGER.error("[delete_cmdb_port] PortsManagerDeleteError: %s", err, exc_info=True)
        abort(400, f'Failed to delete the Port with ID: {public_id}!')
    except Exception as err:
        LOGGER.error("[delete_cmdb_port] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f'An internal server error occured while deleting the Port with ID: {public_id}!')
