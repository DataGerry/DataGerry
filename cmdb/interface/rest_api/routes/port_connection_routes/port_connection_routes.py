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

These routes are the only way a connection is written. Five invariants hold across them:

1. **The connection rights alone govern the surface.** A connection spans two CmdbObjects, and unlike
   the /ports routes these do NOT additionally check either endpoint object's ACL - decision Q13,
   taken 2026-09-03, following the Rack-mount precedent for a row that joins two things. The
   trade-off is recorded on `ConnectionRight` rather than hidden: a caller holding these rights can
   cable together two objects they could not open individually.
2. **The endpoints and the connection type are immutable.** An update writes cable information only;
   a re-cable is a delete plus a create. Moving an endpoint would drop the row onto a port whose
   cardinality slot was never checked for it.
3. **The identity and the audit fields are server-owned.** Neither write route's schema declares
   `public_id` or the three audit fields, and the validator purges what it does not declare, so a body
   carrying one never reaches the handler; `author_id` / `creation_time` / `last_edit_time` are stamped
   from the request. The schema types the cable half - before it, a CSV-shaped number reached the
   database as the value of a field the document schema declares a string - while `endpoints` and
   `connection_type` are left untyped for the connection validator, whose messages name what is wrong.
4. **The cardinality rules are the DATABASE's.** A port holds at most one cable and at most one
   internal connection, no pair repeats, and a cable CI belongs to one connection - all four held by
   the collection's partial unique indexes. The routes pre-check them for a readable 400 and translate
   the index's duplicate-key error into the same wording, which is what covers two concurrent
   requests, since a pre-check is a read followed by a write.

5. **A cable is described ONCE, and read as one block.** A connection either carries the five
   `cable_*` values itself or names a Cable CI that owns them - sending both is a 400, so the
   duplication can not exist in stored data. Every response here therefore replaces the flat cable
   keys with a resolved `cable` block (`with_cable_view`), filled from the CI when one is linked and
   from the connection otherwise, so a client renders both storage modes with the same code and never
   reads a value that is null for half the connections. An INTERNAL connection answers `cable: null`.

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
from cmdb.manager.query_builder import BuilderParameters

from cmdb.models.object_model.cmdb_object_key_enum import CmdbObjectKey
from cmdb.models.port_connection_model import PortConnectionKey, sort_endpoints
from cmdb.models.special_type_model.special_type_enum import SpecialType

from cmdb.class_schema.port_connection_model import get_cmdb_port_connection_write_schema
from cmdb.models.user_model import CmdbUser

from cmdb.security.acl.permission import AccessControlPermission

from cmdb.framework.port.assignable_cables import (
    build_cable_name_search_criteria,
    build_unassigned_cable_criteria,
)

from cmdb.errors.security import AccessDeniedError
from cmdb.errors.manager.objects_manager import ObjectsManagerIterationError
from cmdb.errors.manager.ports_manager import PortsManagerGetError
from cmdb.errors.manager.types_manager import TypesManagerGetError
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
    GetMultiResponse,
    GetSingleResponse,
    InsertSingleResponse,
    UpdateSingleResponse,
)
from cmdb.interface.rest_api.responses.response_parameters import CollectionParameters
from cmdb.interface.rest_api.routes.routes_helper import (
    append_criteria_to_filter,
    fetch_only_active_objects,
    request_wants_body,
)

from cmdb.interface.rest_api.routes.port_connection_routes.port_connection_route_constants import (
    ConnectionParam,
    ConnectionRequestKey,
    ConnectionRight,
)
from cmdb.interface.rest_api.routes.port_routes.port_route_helper import (
    collect_port_ids,
    get_accessible_owner_or_abort,
)
from cmdb.interface.rest_api.routes.port_connection_routes.port_connection_route_helper import (
    build_cable_info,
    build_cable_usage_payload,
    build_connection_candidate,
    collect_claimed_cable_ci_ids,
    duplicate_key_abort,
    enforce_cable_ci_free,
    enforce_connection_shape,
    enforce_endpoints_free,
    get_connection_or_abort,
    get_port_or_abort,
    get_requested_connection_type_or_abort,
    refuse_identity_change,
    resolve_cable_sort,
    shape_unassigned_cable_page,
    with_cable_view,
    with_cable_views,
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
@port_connection_blueprint.validate(get_cmdb_port_connection_write_schema())
def insert_cmdb_port_connection(data: dict[str, Any], request_user: CmdbUser) -> Response:
    """
    HTTP `POST` route to create a CmdbPortConnection between two CmdbPorts

    The endpoints are stored canonically sorted, which is what makes the link undirected: 'A to B' and
    'B to A' are the same document, so neither end is a source and a duplicate pair cannot exist

    **The cable is described once.** A body carrying a `cable_ci_id` may not also carry the inline
    cable fields - the CI owns them, and storing both would duplicate five values between the link and
    the asset that IS the cable, to drift apart the moment either is edited.

    Args:
        data (dict[str, Any]): The request body, validated against the write schema
        request_user (CmdbUser): CmdbUser requesting this operation

    Raises:
        HTTPException: 400 when the body fails the schema, the shape is invalid, an endpoint's slot of
                       this kind is taken, the cable CI is already used, or the body describes its
                       cable both inline and by reference; 404 when the created connection cannot be
                       read back; 500 on an unexpected error

    Returns:
        InsertSingleResponse: The new CmdbPortConnection, with its resolved cable block, and its
            public_id
    """
    # Both are read by the duplicate-key arm below, which the write can reach before either is set
    connection_type: str = ''
    endpoints: list[int] | None = None

    try:
        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
        types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)
        ports_manager: PortsManager = ManagerProvider.get_manager(ManagerType.PORTS, request_user)
        port_connections_manager: PortConnectionsManager = ManagerProvider.get_manager(
            ManagerType.PORT_CONNECTIONS, request_user)

        connection_type = get_requested_connection_type_or_abort(data)
        enforce_connection_shape(ports_manager, objects_manager, types_manager, connection_type, data)

        # Sorted only after the shape check passed, so an unusable value was already refused with its
        # own message rather than reaching here as None
        endpoints = sort_endpoints(data.get(ConnectionRequestKey.ENDPOINTS.value))

        enforce_endpoints_free(port_connections_manager, connection_type, endpoints)
        enforce_cable_ci_free(
            port_connections_manager, data.get(ConnectionRequestKey.CABLE_CI_ID.value),
        )

        candidate: dict[str, Any] = build_connection_candidate(endpoints, connection_type, data)
        candidate[PortConnectionKey.AUTHOR_ID.value] = request_user.get_public_id()
        candidate[PortConnectionKey.CREATION_TIME.value] = datetime.now(timezone.utc)
        candidate[PortConnectionKey.LAST_EDIT_TIME.value] = None

        new_id: int = port_connections_manager.insert_item(candidate)

        created: dict[str, Any] | None = port_connections_manager.get_item(new_id, as_dict=True)

        if not created:
            abort(404, 'Could not retrieve the created Port connection from the database!')

        return InsertSingleResponse(with_cable_view(created, request_user), new_id).make_response()
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
        GetSingleResponse: The requested CmdbPortConnection, with its resolved cable block
    """
    try:
        port_connections_manager: PortConnectionsManager = ManagerProvider.get_manager(
            ManagerType.PORT_CONNECTIONS, request_user)

        connection: dict[str, Any] = get_connection_or_abort(port_connections_manager, public_id)

        return GetSingleResponse(
            with_cable_view(connection, request_user), body=request_wants_body(),
        ).make_response()
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
        DefaultResponse: The port's CmdbPortConnections as a list, each with its resolved cable block
    """
    try:
        ports_manager: PortsManager = ManagerProvider.get_manager(ManagerType.PORTS, request_user)
        port_connections_manager: PortConnectionsManager = ManagerProvider.get_manager(
            ManagerType.PORT_CONNECTIONS, request_user)

        get_port_or_abort(ports_manager, port_id)

        return DefaultResponse(
            with_cable_views(port_connections_manager.get_connections_of_port(port_id), request_user),
        ).make_response()
    except HTTPException as http_err:
        raise http_err
    except PortConnectionsManagerGetError as err:
        LOGGER.error("[get_cmdb_port_connections_of_port] PortConnectionsManagerGetError: %s", err, exc_info=True)
        abort(400, f'Failed to retrieve the Port connections of Port ID: {port_id} from the database!')
    except Exception as err:
        LOGGER.error("[get_cmdb_port_connections_of_port] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f'An internal server error occured while retrieving the connections of Port ID: {port_id}!')

@port_connection_blueprint.route('/object/<int:object_id>', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@port_connection_blueprint.protect(auth=True, right=ConnectionRight.VIEW.value)
def get_cmdb_port_connections_of_object(object_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route to retrieve every CmdbPortConnection of one CmdbObject's CmdbPorts

    What an object view needs to show the cabling of a device in one request. Without it a client had
    to read the object's ports and then ask per port, so a 48-port switch cost 49 round trips for a
    question two indexed reads answer.

    An object with no ports, or with none of them connected, answers with an empty list - "nothing is
    cabled here" is a normal state. The OBJECT not existing is a 404, because that is a different
    answer.

    **Each connection appears once**, even the internal pairing of a patch panel, whose two endpoints
    are both ports of this object: they are one document, matched once by the `$in`.

    **On the ACL**: this route is keyed by an object, so the object's own READ permission is checked
    exactly as `/ports/object/<id>` checks it - the caller is asking what is attached to *that device*.
    What decision Q13 governs is the PEER end: the returned connections may name ports of objects the
    caller cannot read, and their ids are not filtered out, because a connection is a fact about the
    cabling rather than about either device

    Args:
        object_id (int): public_id of the owner CmdbObject
        request_user (CmdbUser): CmdbUser requesting this data

    Raises:
        HTTPException: 403 when the object's ACL denies it; 404 when the object does not exist;
                       400 when the ports or the connections could not be read;
                       500 on an unexpected error

    Returns:
        DefaultResponse: The CmdbPortConnections of the object's CmdbPorts as a list, each with its
            resolved cable block. The Cable CIs and cable-type labels are resolved in two batched
            reads for the whole list, so a 48-port switch costs two extra queries rather than ninety-six
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

        return DefaultResponse(
            with_cable_views(
                port_connections_manager.get_connections_of_ports(collect_port_ids(ports)), request_user,
            ),
        ).make_response()
    except HTTPException as http_err:
        raise http_err
    except AccessDeniedError as err:
        LOGGER.error("[get_cmdb_port_connections_of_object] AccessDeniedError: %s", err, exc_info=True)
        abort(403, str(err))
    except PortsManagerGetError as err:
        LOGGER.error("[get_cmdb_port_connections_of_object] PortsManagerGetError: %s", err, exc_info=True)
        abort(400, f'Failed to retrieve the Ports of CmdbObject ID: {object_id} from the database!')
    except PortConnectionsManagerGetError as err:
        LOGGER.error("[get_cmdb_port_connections_of_object] PortConnectionsManagerGetError: %s", err,
                     exc_info=True)
        abort(400, f'Failed to retrieve the Port connections of CmdbObject ID: {object_id}!')
    except Exception as err:
        LOGGER.error("[get_cmdb_port_connections_of_object] Exception: %s. Type: %s", err, type(err),
                     exc_info=True)
        abort(500,
              f'An internal server error occured while retrieving the connections of CmdbObject ID: {object_id}!')

@port_connection_blueprint.route('/cable_usage/<int:object_id>', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@port_connection_blueprint.protect(auth=True, right=ConnectionRight.VIEW.value)
def get_cable_usage_of_object(object_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route to answer whether a Cable CI is still used by a CmdbPortConnection

    The pre-check for the delete guard: deleting a Cable CI a connection still names is refused with a
    400 (the connection describes a physical patch and outlives the inventory record - see
    `cmdb.framework.port.cable_usage`), so a client asks here first and can say *why* the delete is
    unavailable instead of offering it and reporting an error. The same relationship
    `/types/uses_ports_usage/<id>` has with the uses_ports guard.

    ``in_use: false`` means the object may be deleted as far as its cable role is concerned - the other
    delete guards (IPAM, locations, ACL) are independent of this answer. An object that is not a Cable
    CI at all answers ``in_use: false`` too: it uses the same lookup, and "no connection names this
    object as its cable" is the true answer for it

    Args:
        object_id (int): public_id of the CmdbObject to inspect
        request_user (CmdbUser): CmdbUser requesting this data

    Raises:
        HTTPException: 403 when the object's ACL denies it; 404 when the object does not exist;
                       400 when the connections could not be read; 500 on an unexpected error

    Returns:
        DefaultResponse: { in_use: bool, connection_id: int | None, endpoints: list[int] | None } -
            connection_id and endpoints name what to resolve first, and are null when the cable is free
    """
    try:
        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
        port_connections_manager: PortConnectionsManager = ManagerProvider.get_manager(
            ManagerType.PORT_CONNECTIONS, request_user)

        get_accessible_owner_or_abort(
            objects_manager, object_id, request_user, AccessControlPermission.READ,
        )

        return DefaultResponse(
            build_cable_usage_payload(port_connections_manager, object_id),
        ).make_response()
    except HTTPException as http_err:
        raise http_err
    except AccessDeniedError as err:
        LOGGER.error("[get_cable_usage_of_object] AccessDeniedError: %s", err, exc_info=True)
        abort(403, str(err))
    except PortConnectionsManagerGetError as err:
        LOGGER.error("[get_cable_usage_of_object] PortConnectionsManagerGetError: %s", err, exc_info=True)
        abort(400, f'Failed to determine the Port connection usage of the Cable with ID: {object_id}!')
    except Exception as err:
        LOGGER.error("[get_cable_usage_of_object] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, 'An internal server error occured while determining the Port connection usage of the '
                   f'Cable with ID: {object_id}!')

@port_connection_blueprint.route('/cables/unassigned/', methods=['GET', 'HEAD'])
@port_connection_blueprint.parse_collection_parameters()
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@port_connection_blueprint.protect(auth=True, right=ConnectionRight.VIEW.value)
def get_unassigned_cables(params: CollectionParameters, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route to list the Cable CIs that can still be assigned to a CmdbPortConnection

    The picker behind a connection's ``cable_ci_id``. Two rules decide it: the CmdbObject's type must
    carry the CABLE marker, and a cable another connection already uses is out - `cable_ci_id` holds a
    partial unique index, so offering a claimed cable would only produce a refusal. Both are appended
    behind the caller's own `?filter=`, which can narrow the candidates but never widen them past the
    rules

    ``?connection_id=`` names the connection being edited and keeps ITS cable in the list, so an edit
    form can preselect the value it already holds. ``?search=`` matches the cable name as a literal,
    case-insensitive substring. Ordering, paging and filtering are the standard collection parameters,
    except that `sort` defaults to the cable name instead of the public_id

    Guarded by the connection view right, like every read here: this is a question, not a change. The
    candidates' own ACLs are not applied - Q13's rule for this surface, and the same trade-off the
    Rack's assignable-objects picker documents

    Args:
        params (CollectionParameters): Filtering, sorting and pagination parameters
        request_user (CmdbUser): CmdbUser requesting this data

    Raises:
        HTTPException: 404 when ``?connection_id=`` names no connection; 400 when a read fails;
                       500 on an unexpected error

    Returns:
        GetMultiResponse: One picker row per assignable Cable CI of the requested page
    """
    try:
        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
        types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)
        port_connections_manager: PortConnectionsManager = ManagerProvider.get_manager(
            ManagerType.PORT_CONNECTIONS, request_user)

        claimed_cable_ci_ids: list[int] = collect_claimed_cable_ci_ids(
            port_connections_manager,
            request.args.get(ConnectionParam.CONNECTION_ID.value, type=int),
        )

        criteria: dict[str, Any] = build_unassigned_cable_criteria(
            types_manager.get_type_ids_of_special_type(SpecialType.CABLE),
            claimed_cable_ci_ids,
        )

        params.filter = append_criteria_to_filter(params.filter, criteria)

        search_criteria: dict[str, Any] = build_cable_name_search_criteria(
            request.args.get(ConnectionParam.SEARCH.value, type=str),
        )

        if search_criteria:
            params.filter.append({'$match': search_criteria})

        if fetch_only_active_objects():
            params.filter.append({'$match': {CmdbObjectKey.ACTIVE.value: {'$eq': True}}})

        params.sort = resolve_cable_sort(params.sort)

        builder_params = BuilderParameters(**CollectionParameters.get_builder_params(params))

        # The raw aggregation documents, not hydrated CmdbObjects: a picker row is nine keys read out
        # of the document, so building a model per candidate only to project it away is wasted work
        object_docs, total = objects_manager.iterate_query(builder_params)

        return GetMultiResponse(
            shape_unassigned_cable_page(types_manager, object_docs),
            total=total,
            params=params,
            url=request.url,
            body=request_wants_body(),
        ).make_response()
    except HTTPException as http_err:
        raise http_err
    except PortConnectionsManagerGetError as err:
        LOGGER.error("[get_unassigned_cables] PortConnectionsManagerGetError: %s", err, exc_info=True)
        abort(400, 'Failed to retrieve the Cables already used by a Port connection!')
    except ObjectsManagerIterationError as err:
        LOGGER.error("[get_unassigned_cables] ObjectsManagerIterationError: %s", err, exc_info=True)
        abort(400, 'Failed to retrieve the Cables assignable to a Port connection!')
    except TypesManagerGetError as err:
        LOGGER.error("[get_unassigned_cables] TypesManagerGetError: %s", err, exc_info=True)
        abort(400, 'Failed to retrieve the Cable types!')
    except Exception as err:
        LOGGER.error("[get_unassigned_cables] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, 'An internal server error occured while listing the assignable Cables!')


# -------------------------------------------------------------------------------------------------------------------- #
#                                                   CRUD - UPDATE                                                      #
# -------------------------------------------------------------------------------------------------------------------- #

@port_connection_blueprint.route('/<int:public_id>', methods=['PUT', 'PATCH'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@port_connection_blueprint.protect(auth=True, right=ConnectionRight.EDIT.value)
@port_connection_blueprint.validate(get_cmdb_port_connection_write_schema())
def update_cmdb_port_connection(public_id: int, data: dict[str, Any], request_user: CmdbUser) -> Response:
    """
    HTTP `PUT`/`PATCH` route to update the cable information of a single CmdbPortConnection

    **Cable information only.** The endpoints and the connection type are immutable - a payload naming
    different ones is refused rather than ignored, so a client can not discover that its edit did
    nothing. A re-cable is a delete plus a create.

    A cable CI the body omits is REMOVED, not kept: these routes take the whole connection, and the
    key has to be unset rather than nulled because the index that guarantees one CI per connection is
    filtered on the key's presence

    **Switching between the two ways of describing a cable is one write.** A body naming a
    `cable_ci_id` and no inline fields hands the values over to the CI; a body carrying the inline
    fields and no `cable_ci_id` takes them back. Carrying both is refused

    Args:
        public_id (int): public_id of the CmdbPortConnection to update
        data (dict[str, Any]): The request body, validated against the write schema
        request_user (CmdbUser): CmdbUser requesting this operation

    Raises:
        HTTPException: 400 when the body fails the schema, the payload changes an immutable field, the
                       cable CI is already used, a cable field is set on an INTERNAL connection, or the
                       body describes its cable both inline and by reference; 404 when the connection
                       does not exist; 500 on an unexpected error

    Returns:
        UpdateSingleResponse: The new data of the CmdbPortConnection, with its resolved cable block
    """
    try:
        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
        types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)
        port_connections_manager: PortConnectionsManager = ManagerProvider.get_manager(
            ManagerType.PORT_CONNECTIONS, request_user)

        stored: dict[str, Any] = get_connection_or_abort(port_connections_manager, public_id)

        refuse_identity_change(stored, data)

        # The stored type decides which fields are allowed, not the payload's: the type is immutable,
        # so a body that omits it must be judged by what the connection actually IS
        connection_type: str = stored.get(PortConnectionKey.CONNECTION_TYPE.value)

        enforce_connection_shape(
            ManagerProvider.get_manager(ManagerType.PORTS, request_user),
            objects_manager, types_manager, connection_type,
            {**data, ConnectionRequestKey.ENDPOINTS.value: stored.get(PortConnectionKey.ENDPOINTS.value)},
        )
        enforce_cable_ci_free(
            port_connections_manager, data.get(ConnectionRequestKey.CABLE_CI_ID.value),
            exclude_id=public_id,
        )

        cable_info: dict[str, Any] = build_cable_info(data)
        cable_info[PortConnectionKey.LAST_EDIT_TIME.value] = datetime.now(timezone.utc)

        port_connections_manager.replace_connection(public_id, cable_info)

        updated: dict[str, Any] = get_connection_or_abort(port_connections_manager, public_id)

        return UpdateSingleResponse(with_cable_view(updated, request_user)).make_response()
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
