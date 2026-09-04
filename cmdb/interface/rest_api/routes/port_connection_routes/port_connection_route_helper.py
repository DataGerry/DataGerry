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

from flask import abort

from cmdb.manager import ObjectsManager, TypesManager
from cmdb.manager.port_connections_manager import PortConnectionsManager
from cmdb.manager.ports_manager import PortsManager

from cmdb.models.port_connection_model import (
    ConnectionType,
    PortConnectionKey,
    CABLE_FIELD_KEYS,
    sort_endpoints,
)

from cmdb.framework.port.connection_validator import (
    cable_ci_blockers,
    coerce_connection_type,
    missing_endpoint_blockers,
    shape_blockers,
    unknown_connection_type_blocker,
)

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
