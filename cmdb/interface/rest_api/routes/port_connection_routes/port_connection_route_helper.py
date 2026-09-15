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
The write guards and lookups the port-connection routes share

Two layers, and the split is deliberate. ``cmdb.framework.port.connection_validator`` holds the pure
rules and reports its reasons; this module is what turns them - and the readable cardinality
pre-checks - into HTTP refusals. Nothing here is the actual guarantee: every cardinality rule is held
by one of the collection's partial unique indexes, because a read followed by a write cannot stop two
concurrent requests. The pre-checks exist so the ORDINARY case gets a message naming the port instead
of a duplicate-key error, and ``duplicate_key_abort`` covers the race with the same wording
"""
from logging import Logger, getLogger
from typing import Any, NoReturn

from flask import abort, request

from cmdb.manager import ObjectsManager, TypesManager
from cmdb.manager.extendable_options_manager import ExtendableOptionsManager
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.manager.port_connections_manager import PortConnectionsManager
from cmdb.manager.ports_manager import PortsManager

from cmdb.models.user_model import CmdbUser

from cmdb.models.object_model.cmdb_object_key_enum import CmdbObjectKey
from cmdb.models.port_connection_model import (
    ConnectionType,
    PortConnectionKey,
    CABLE_FIELD_KEYS,
    sort_endpoints,
)
from cmdb.models.special_type_model.cable_constants import CableField

from cmdb.framework.port.assignable_cables import build_unassigned_cable_rows
from cmdb.framework.port.cable_usage import CableUsage, collect_cable_usage
from cmdb.framework.port.connection_cable_view import attach_cable_view, attach_cable_views
from cmdb.framework.port.connection_validator import (
    cable_ci_blockers,
    coerce_connection_type,
    missing_endpoint_blockers,
    shape_blockers,
    unknown_connection_type_blocker,
)

from cmdb.manager.query_builder.query_builder_constants import SortPipeline
from cmdb.interface.rest_api.responses.response_parameters.response_parameters_constants import ParameterKey

from cmdb.interface.rest_api.routes.port_connection_routes.port_connection_route_constants import (
    CONNECTION_ABORT_PREFIX,
    CONNECTION_CABLE_CI_IN_USE_MESSAGE,
    CONNECTION_DUPLICATE_MESSAGE,
    CONNECTION_FIELD_IMMUTABLE_MESSAGE,
    CONNECTION_NOT_FOUND_MESSAGE,
    CONNECTION_PAIR_EXISTS_MESSAGE,
    CONNECTION_PORT_ALREADY_CABLED_MESSAGE,
    CONNECTION_PORT_ALREADY_PAIRED_MESSAGE,
    CONNECTION_PORT_NOT_FOUND_MESSAGE,
    DUPLICATE_KEY_CABLE_CI_MARKER,
    DUPLICATE_KEY_ENDPOINTS_MARKER,
    CableUsageKey,
    ConnectionRequestKey,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# The message each connection type's occupied-slot refusal uses. Keyed by type rather than branched on,
# so a third type could not silently fall through to the cable wording
OCCUPIED_SLOT_MESSAGES: dict[str, str] = {
    ConnectionType.CABLE.value: CONNECTION_PORT_ALREADY_CABLED_MESSAGE,
    ConnectionType.INTERNAL.value: CONNECTION_PORT_ALREADY_PAIRED_MESSAGE,
}

# -------------------------------------------------------------------------------------------------------------------- #
#                                                      lookups                                                         #
# -------------------------------------------------------------------------------------------------------------------- #

def get_connection_or_abort(
        port_connections_manager: PortConnectionsManager,
        public_id: int) -> dict[str, Any]:
    """
    Reads a CmdbPortConnection or aborts 404

    Args:
        port_connections_manager (PortConnectionsManager): db interface for CmdbPortConnections
        public_id (int): public_id of the CmdbPortConnection

    Raises:
        HTTPException: 404 when no connection with that public_id exists

    Returns:
        dict[str, Any]: The stored connection document
    """
    connection: dict[str, Any] | None = port_connections_manager.get_item(public_id, as_dict=True)

    if not connection:
        abort(404, CONNECTION_NOT_FOUND_MESSAGE.format(public_id=public_id))

    return connection


def get_port_or_abort(ports_manager: PortsManager, port_id: int) -> dict[str, Any]:
    """
    Reads a CmdbPort or aborts 404

    Used by the "all connections of port X" route, so a request naming a port that does not exist is a
    404 rather than an empty list - an empty list means "this port is free", which is a different
    answer

    Args:
        ports_manager (PortsManager): db interface for CmdbPorts
        port_id (int): public_id of the CmdbPort

    Raises:
        HTTPException: 404 when no port with that public_id exists

    Returns:
        dict[str, Any]: The stored port document
    """
    port: dict[str, Any] | None = ports_manager.get_item(port_id, as_dict=True)

    if not port:
        abort(404, CONNECTION_PORT_NOT_FOUND_MESSAGE.format(port_id=port_id))

    return port

# -------------------------------------------------------------------------------------------------------------------- #
#                                                   the read payload                                                   #
# -------------------------------------------------------------------------------------------------------------------- #

def with_cable_views(connections: list[dict[str, Any]], request_user: CmdbUser) -> list[dict[str, Any]]:
    """
    Turns stored connections into the payload the read routes answer with

    Every route that hands a connection back goes through here - the three reads and the create and
    update responses - so a client sees the resolved cable block in the same shape everywhere, and a
    write is answered with exactly what a following read would return

    Args:
        connections (list[dict[str, Any]]): The stored connection documents
        request_user (CmdbUser): CmdbUser requesting this data

    Returns:
        list[dict[str, Any]]: The connections, each with its cable keys replaced by a 'cable' block
    """
    objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
    extendable_options_manager: ExtendableOptionsManager = ManagerProvider.get_manager(
        ManagerType.EXTENDABLE_OPTIONS, request_user)

    return attach_cable_views(connections, objects_manager, extendable_options_manager)


def with_cable_view(connection: dict[str, Any], request_user: CmdbUser) -> dict[str, Any]:
    """
    The single-connection form of with_cable_views

    Args:
        connection (dict[str, Any]): The stored connection document
        request_user (CmdbUser): CmdbUser requesting this data

    Returns:
        dict[str, Any]: The connection with its cable keys replaced by a 'cable' block
    """
    objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
    extendable_options_manager: ExtendableOptionsManager = ManagerProvider.get_manager(
        ManagerType.EXTENDABLE_OPTIONS, request_user)

    return attach_cable_view(connection, objects_manager, extendable_options_manager)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                    write guards                                                      #
# -------------------------------------------------------------------------------------------------------------------- #

def get_requested_connection_type_or_abort(payload: dict[str, Any]) -> str:
    """
    Reads the connection type from a create body, aborting 400 on a missing or unknown value

    Deliberately without a default: the caller always knows whether it is cabling two devices or
    pairing a panel's two faces, and guessing CABLE for a typo would create the wrong kind of link -
    one that then falls under the wrong unique index and gets the wrong cardinality guarantee

    Args:
        payload (dict[str, Any]): The request body

    Raises:
        HTTPException: 400 when the connection type is absent or not a ConnectionType value

    Returns:
        str: The requested ConnectionType value
    """
    raw: Any = payload.get(ConnectionRequestKey.CONNECTION_TYPE.value)
    blocker: str | None = unknown_connection_type_blocker(raw)

    if blocker:
        abort(400, f'{CONNECTION_ABORT_PREFIX}: {blocker}')

    return coerce_connection_type(raw)


def enforce_connection_shape(
        ports_manager: PortsManager,
        objects_manager: ObjectsManager,
        types_manager: TypesManager,
        connection_type: str,
        payload: dict[str, Any]) -> None:
    """
    Aborts 400 with every reason the connection would be refused, in one message

    Runs the pure rules and the two that need a read - both endpoints exist, and the cable CI really
    is a Cable - and reports them together, so a caller fixes one payload instead of discovering the
    rules one request at a time

    Args:
        ports_manager (PortsManager): db interface for CmdbPorts
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        connection_type (str): The ConnectionType value of the connection
        payload (dict[str, Any]): The request body

    Raises:
        HTTPException: 400 when the connection's shape or its references are invalid
    """
    blockers: list[str] = shape_blockers(connection_type, payload)

    blockers.extend(missing_endpoint_blockers(
        ports_manager, payload.get(ConnectionRequestKey.ENDPOINTS.value),
    ))
    blockers.extend(cable_ci_blockers(
        objects_manager, types_manager, payload.get(ConnectionRequestKey.CABLE_CI_ID.value),
    ))

    if blockers:
        abort(400, f'{CONNECTION_ABORT_PREFIX}: {" | ".join(blockers)}')


def enforce_endpoints_free(
        port_connections_manager: PortConnectionsManager,
        connection_type: str,
        endpoints: list[int]) -> None:
    """
    Aborts 400 when either endpoint already holds a connection of this kind

    The readable form of the feature's hard cardinality refusal. Both ends are judged, and the message
    names the port that is occupied - a caller told only "duplicate key" would have to guess which of
    the two it picked is the problem. A pair that is ALREADY connected reports that instead, because
    "these two are already connected" is a different mistake from "this port is in use elsewhere"

    Not the guarantee: the two partial unique indexes are, since this read cannot stop a concurrent
    write. duplicate_key_abort reports the same rules when they do race

    Args:
        port_connections_manager (PortConnectionsManager): db interface for CmdbPortConnections
        connection_type (str): The ConnectionType value being created
        endpoints (list[int]): The two port public_ids, canonically sorted

    Raises:
        HTTPException: 400 when either endpoint's slot of this kind is taken
    """
    for port_id in endpoints:
        existing: dict[str, Any] | None = port_connections_manager.get_connection_of_port_by_type(
            port_id, connection_type,
        )

        if not existing:
            continue

        if sort_endpoints(existing.get(PortConnectionKey.ENDPOINTS.value)) == endpoints:
            abort(400, CONNECTION_PAIR_EXISTS_MESSAGE.format(
                port_id=endpoints[0], peer_id=endpoints[1], connection_type=connection_type,
            ))

        abort(400, OCCUPIED_SLOT_MESSAGES[connection_type].format(port_id=port_id))


def enforce_cable_ci_free(
        port_connections_manager: PortConnectionsManager,
        cable_ci_id: Any,
        exclude_id: int | None = None) -> None:
    """
    Aborts 400 when another connection already claims the cable CI

    One inventoried cable belongs to at most one connection - reusing it on two links is a data-entry
    error. `exclude_id` lets an update re-assert the CI it already holds, so a client that round-trips
    a GET is not punished for sending the field back

    Args:
        port_connections_manager (PortConnectionsManager): db interface for CmdbPortConnections
        cable_ci_id (Any): The requested cable CI, or None when the connection names none
        exclude_id (int | None): public_id of the connection being updated. Defaults to None

    Raises:
        HTTPException: 400 when a different connection already uses that cable CI
    """
    if not isinstance(cable_ci_id, int):
        return

    existing: dict[str, Any] | None = port_connections_manager.get_connection_by_cable_ci(cable_ci_id)

    if not existing or existing.get(PortConnectionKey.PUBLIC_ID.value) == exclude_id:
        return

    abort(400, CONNECTION_CABLE_CI_IN_USE_MESSAGE.format(
        cable_ci_id=cable_ci_id, public_id=existing.get(PortConnectionKey.PUBLIC_ID.value),
    ))


def refuse_identity_change(stored_connection: dict[str, Any], payload: dict[str, Any]) -> None:
    """
    Aborts 400 when an update payload would change what the connection JOINS

    Both the endpoints and the connection type are immutable: a re-cable is a delete plus a create.
    Moving an endpoint would drop the connection onto a port whose cardinality slot was never checked
    for it, and changing the type would move the row between the two partial unique indexes - in both
    cases the guarantee would be decided by whichever index happened to catch it.

    A payload repeating the stored values is fine, since these routes take the whole connection and a
    client that round-trips a GET must not be punished for sending them back

    Args:
        stored_connection (dict[str, Any]): The connection as currently stored
        payload (dict[str, Any]): The request body

    Raises:
        HTTPException: 400 when the endpoints or the connection type differ from the stored values
    """
    requested_endpoints: Any = payload.get(ConnectionRequestKey.ENDPOINTS.value)

    if requested_endpoints is not None and sort_endpoints(requested_endpoints) != sort_endpoints(
            stored_connection.get(PortConnectionKey.ENDPOINTS.value)):
        abort(400, CONNECTION_FIELD_IMMUTABLE_MESSAGE.format(
            field=ConnectionRequestKey.ENDPOINTS.value,
        ))

    requested_type: Any = payload.get(ConnectionRequestKey.CONNECTION_TYPE.value)

    if requested_type is not None and requested_type != stored_connection.get(
            PortConnectionKey.CONNECTION_TYPE.value):
        abort(400, CONNECTION_FIELD_IMMUTABLE_MESSAGE.format(
            field=ConnectionRequestKey.CONNECTION_TYPE.value,
        ))

# -------------------------------------------------------------------------------------------------------------------- #
#                                                  building the row                                                    #
# -------------------------------------------------------------------------------------------------------------------- #

def build_cable_info(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Builds the cable half of a connection document from a request body

    ``cable_ci_id`` is included only when the payload really names one. Writing null instead would put
    every connection without a cable CI into the unique index filtered on that key's PRESENCE, and the
    second such write in the installation would be refused as a duplicate

    Args:
        payload (dict[str, Any]): The request body

    Returns:
        dict[str, Any]: The cable fields, with cable_ci_id absent when none was named
    """
    cable_info: dict[str, Any] = {
        key.value: payload.get(key.value)
        for key in CABLE_FIELD_KEYS
        if key is not PortConnectionKey.CABLE_CI_ID
    }

    cable_ci_id: Any = payload.get(ConnectionRequestKey.CABLE_CI_ID.value)

    if cable_ci_id is not None:
        cable_info[PortConnectionKey.CABLE_CI_ID.value] = cable_ci_id

    return cable_info


def build_connection_candidate(
        endpoints: list[int],
        connection_type: str,
        payload: dict[str, Any]) -> dict[str, Any]:
    """
    Builds the connection document a create writes, from the request body

    Only the keys a request owns are read: the identity and the audit fields are filled in by the
    caller from the request user, never from the payload

    Args:
        endpoints (list[int]): The two port public_ids, canonically sorted
        connection_type (str): The ConnectionType value of the connection
        payload (dict[str, Any]): The request body

    Returns:
        dict[str, Any]: The connection document without its identity and audit fields
    """
    return {
        PortConnectionKey.ENDPOINTS.value: endpoints,
        PortConnectionKey.CONNECTION_TYPE.value: connection_type,
        **build_cable_info(payload),
    }

# -------------------------------------------------------------------------------------------------------------------- #
#                                              the database's own refusal                                              #
# -------------------------------------------------------------------------------------------------------------------- #

def duplicate_key_abort(
        error: Exception,
        connection_type: str,
        endpoints: list[int] | None) -> NoReturn:
    """
    Turns the database's duplicate-key refusal into the same message the pre-check would have given

    This is the arm that actually holds under concurrency: the pre-checks above are reads followed by
    writes, so two simultaneous requests both pass them and one of the unique indexes stops the second.
    Reporting that as a raw driver error would tell the loser nothing it could act on.

    The driver names the violated index's key PATTERN, not its name, so the two endpoint indexes are
    indistinguishable here - which costs nothing, because the route knows which connection_type it was
    writing and the message follows from that. An unrecognised duplicate falls back to a message
    stating all three rules rather than guessing one

    Args:
        error (Exception): The manager error wrapping the duplicate-key failure
        connection_type (str): The ConnectionType value that was being written
        endpoints (list[int] | None): The canonically sorted endpoints, when they are known

    Raises:
        HTTPException: 400, always
    """
    reason: str = str(error)

    if DUPLICATE_KEY_CABLE_CI_MARKER in reason:
        abort(400, CONNECTION_DUPLICATE_MESSAGE)

    if DUPLICATE_KEY_ENDPOINTS_MARKER in reason and endpoints:
        abort(400, OCCUPIED_SLOT_MESSAGES.get(
            connection_type, CONNECTION_DUPLICATE_MESSAGE,
        ).format(port_id=endpoints[0]))

    abort(400, CONNECTION_DUPLICATE_MESSAGE)


# -------------------------------------------------------------------------------------------------------------------- #
#                                             the unassigned-cable picker                                              #
# -------------------------------------------------------------------------------------------------------------------- #

# Sort key of the picker's default order: the cable's name, which lives inside the object's 'fields'
# array and is therefore addressed through the query builder's fields.<name> sort form
CABLE_NAME_SORT: str = f'{SortPipeline.FIELDS_PREFIX}{CableField.NAME.value}'


def collect_claimed_cable_ci_ids(
        port_connections_manager: PortConnectionsManager,
        connection_id: int | None) -> list[int]:
    """
    Reads the Cable CIs the picker has to hide, keeping the edited connection's own cable

    Every cable some connection already uses is hidden, because `cable_ci_id` holds a partial unique
    index and offering a claimed cable would only produce a refusal. ``?connection_id=`` names the
    connection being edited, and its cable is kept in the list - otherwise an edit form could not
    preselect the value it already holds. A connection_id naming nothing is a 404 rather than a
    silently ignored parameter: the caller asked a question about a connection that does not exist

    Args:
        port_connections_manager (PortConnectionsManager): db interface for CmdbPortConnections
        connection_id (int | None): public_id of the connection being edited, or None when the picker
            is filling a new connection

    Raises:
        HTTPException: 404 when connection_id names no CmdbPortConnection

    Returns:
        list[int]: public_ids of the Cable CIs to exclude
    """
    claimed: list[int] = port_connections_manager.get_assigned_cable_ci_ids()

    if connection_id is None:
        return claimed

    connection: dict[str, Any] = get_connection_or_abort(port_connections_manager, connection_id)
    own_cable_ci_id: Any = connection.get(PortConnectionKey.CABLE_CI_ID.value)

    if not isinstance(own_cable_ci_id, int):
        return claimed

    return [cable_ci_id for cable_ci_id in claimed if cable_ci_id != own_cable_ci_id]


def resolve_cable_sort(requested_sort: str) -> str:
    """
    Answers with the sort key the picker should use

    The pager defaults ``sort`` to 'public_id' for every collection route, which for a cable picker
    means "creation order" - so this route defaults to the cable's name instead. The default only
    applies when the caller sent no ``?sort=`` at all: an explicit `?sort=public_id` is a choice and
    is kept, which is why the query string is consulted rather than the parsed value alone

    Args:
        requested_sort (str): The sort key the pager parsed

    Returns:
        str: The sort key to query with
    """
    if ParameterKey.SORT.value in request.args:
        return requested_sort

    return CABLE_NAME_SORT


def shape_unassigned_cable_page(
        types_manager: TypesManager,
        object_docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Resolves one page of Cable CIs into the rows the picker draws

    One bulk read for the CmdbType labels actually present on the page - scoping it to the page rather
    than to every CABLE type keeps an installation with many cable types from paying for labels it
    does not render. The cable values themselves need no read: they are in the documents already

    Args:
        types_manager (TypesManager): db interface for CmdbTypes
        object_docs (list[dict[str, Any]]): The candidate Cable CI documents of one page

    Returns:
        list[dict[str, Any]]: One picker row per document, in input order
    """
    type_ids: list[int] = [
        doc[CmdbObjectKey.TYPE_ID.value]
        for doc in object_docs
        if isinstance(doc.get(CmdbObjectKey.TYPE_ID.value), int)
    ]

    type_labels: dict[int, str] = {
        type_id: cmdb_type.label
        for type_id, cmdb_type in types_manager.get_types_lookup(list(set(type_ids))).items()
    } if type_ids else {}

    return build_unassigned_cable_rows(object_docs, type_labels)


def build_cable_usage_payload(port_connections_manager: PortConnectionsManager, object_id: int) -> dict[str, Any]:
    """
    Builds the pre-check answer for one Cable CI: is a CmdbPortConnection still using it?

    The read behind ``GET /port_connections/cable_usage/<object_id>``, so a client can tell BEFORE it
    offers the delete what the delete guard would refuse - the same relationship
    ``/types/uses_ports_usage/<id>`` has with the uses_ports guard. A cable is used at most once
    (``cable_ci_id`` carries a partial unique index), which is why the answer names one connection
    instead of a list

    Args:
        port_connections_manager (PortConnectionsManager): db interface for CmdbPortConnections
        object_id (int): public_id of the CmdbObject to inspect

    Raises:
        PortConnectionsManagerGetError: If the connection lookup fails

    Returns:
        dict[str, Any]: { in_use: bool, connection_id: int | None, endpoints: list[int] | None } -
            the last two are null when the cable is free (and for any object that is not a Cable CI)
    """
    usages: list[CableUsage] = collect_cable_usage(port_connections_manager, [object_id])

    if not usages:
        return {
            CableUsageKey.IN_USE.value: False,
            CableUsageKey.CONNECTION_ID.value: None,
            CableUsageKey.ENDPOINTS.value: None,
        }

    usage: CableUsage = usages[0]

    return {
        CableUsageKey.IN_USE.value: True,
        CableUsageKey.CONNECTION_ID.value: usage.connection_id,
        CableUsageKey.ENDPOINTS.value: list(usage.endpoints),
    }
