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
The rules a CmdbPortConnection has to satisfy that the database can not hold

The collection's two partial unique indexes on ``endpoints`` are the feature's real guarantee: no port
appears in two CABLE connections, no port in two INTERNAL ones, and - thanks to the stored sort - no
pair appears twice. A fourth index gives one cable CI to at most one connection. None of that is
restated here; a read-then-write check would only be a racier copy of it.

What is left over is what this module holds:

  - the endpoints are exactly TWO port ids, canonically SORTED - the sort is what makes the link
    undirected, and it happens on the way in rather than being asserted afterwards
  - **no self-connection**: ``[5, 5]`` dedupes to a single key inside one document, so a unique
    multikey index sees nothing wrong with it
  - both endpoints name REAL ports
  - **the two ends sit on the right devices for the kind of link**: a CABLE joins two different
    CmdbObjects, an INTERNAL pairs two faces of ONE - each is the other's refusal message
  - **cable information is rejected on an INTERNAL connection** - the per-type field rule, the same
    shape as the Rack's occupant_validator: one document holds two kinds of link, so something has to
    say which fields belong to which
  - **the inline cable fields are rejected alongside a cable CI** - a connection describes its cable
    either itself or by reference, never both, so the five values can not be duplicated between a link
    and the asset that IS the cable and then drift apart
  - a ``cable_ci_id`` names an existing CmdbObject of a CABLE SpecialType

Pure and free of Flask: every function reports its reasons and the routes decide whether to abort. The
two that need the database take managers and still only report - so the same cores can back a write
and a dry-run pre-check without either being able to accept what the other refuses
"""
from logging import Logger, getLogger
from typing import Any

from cmdb.manager.objects_manager import ObjectsManager
from cmdb.manager.ports_manager import PortsManager
from cmdb.manager.types_manager import TypesManager

from cmdb.models.object_model.cmdb_object_key_enum import CmdbObjectKey
from cmdb.models.port_model.port_constants import PortKey
from cmdb.models.port_connection_model.port_connection_constants import (
    ConnectionType,
    PortConnectionKey,
    CABLE_FIELD_KEYS,
    ENDPOINT_COUNT,
    INLINE_CABLE_FIELD_KEYS,
)
from cmdb.models.port_connection_model.port_connection_helpers import (
    coerce_endpoints,
    is_self_connection,
    sort_endpoints,
)
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.type_model import TypeSchemaKey

from cmdb.framework.port.connection_constants import PortConnectionError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                  connection type                                                     #
# -------------------------------------------------------------------------------------------------------------------- #

def coerce_connection_type(raw_connection_type: Any) -> str | None:
    """
    Reads the connection type out of a request

    Deliberately WITHOUT a default, unlike the Rack row's kind: a connection is either a cable or a
    panel's internal pairing, the caller always knows which, and defaulting a missing value to CABLE
    would let a typo create the wrong kind of link - one that then falls under the wrong unique index
    and gets the wrong cardinality guarantee

    Args:
        raw_connection_type (Any): The raw connection_type value from the request

    Returns:
        str | None: The ConnectionType value, or None when the value is not a known type
    """
    if isinstance(raw_connection_type, str) and ConnectionType.is_valid(raw_connection_type):
        return raw_connection_type

    return None


def unknown_connection_type_blocker(raw_connection_type: Any) -> str | None:
    """
    Judges whether a request names a connection type that exists

    Args:
        raw_connection_type (Any): The raw connection_type value from the request

    Returns:
        str | None: The reason the connection type is unusable, or None when it is fine
    """
    if coerce_connection_type(raw_connection_type) is not None:
        return None

    return PortConnectionError.UNKNOWN_CONNECTION_TYPE.format(
        connection_type=raw_connection_type,
        allowed=', '.join(member.value for member in ConnectionType),
    )

# -------------------------------------------------------------------------------------------------------------------- #
#                                                     endpoints                                                        #
# -------------------------------------------------------------------------------------------------------------------- #

def endpoint_blockers(raw_endpoints: Any) -> list[str]:
    """
    Judges the two ends a request names, without asking the database

    Reports every reason at once rather than the first, so a caller fixes one payload instead of
    discovering the rules one request at a time

    Args:
        raw_endpoints (Any): The raw endpoints value from the request

    Returns:
        list[str]: The reasons the endpoints are refused; empty when they are usable
    """
    if coerce_endpoints(raw_endpoints) is None:
        return [PortConnectionError.INVALID_ENDPOINTS.format(count=ENDPOINT_COUNT)]

    if is_self_connection(raw_endpoints):
        return [PortConnectionError.SELF_CONNECTION.value]

    return []


def read_endpoint_ports(ports_manager: PortsManager, raw_endpoints: Any) -> dict[int, dict[str, Any]]:
    """
    Reads the CmdbPorts a request names as its endpoints, keyed by public_id

    **One batched read for both ids**, and one for the whole validation: two rules ask about these
    documents - do they exist, and do they belong to the same CmdbObject - so they are read here once
    and judged by pure functions afterwards

    Args:
        ports_manager (PortsManager): db interface for CmdbPorts
        raw_endpoints (Any): The raw endpoints value from the request

    Returns:
        dict[int, dict[str, Any]]: The ports that exist, keyed by public_id; empty when the endpoints
            are unusable, which endpoint_blockers has already reported
    """
    endpoints: list[int] | None = sort_endpoints(raw_endpoints)

    if endpoints is None:
        return {}

    found: list[dict[str, Any]] = ports_manager.find(
        criteria={PortKey.PUBLIC_ID.value: {'$in': endpoints}},
    )

    return {
        port[PortKey.PUBLIC_ID.value]: port for port in found
        if isinstance(port.get(PortKey.PUBLIC_ID.value), int)
    }


def missing_endpoint_blockers(
        endpoint_ports: dict[int, dict[str, Any]],
        raw_endpoints: Any) -> list[str]:
    """
    Judges whether both ends name a CmdbPort that really exists

    Pure: it judges the documents `read_endpoint_ports` fetched. Unusable endpoints are not reported
    again here - endpoint_blockers has already said so, and repeating it would give the caller the
    same problem twice under two different messages

    Args:
        endpoint_ports (dict[int, dict[str, Any]]): The endpoint ports that exist, keyed by public_id
        raw_endpoints (Any): The raw endpoints value from the request

    Returns:
        list[str]: One reason per endpoint that names no port; empty when both exist
    """
    endpoints: list[int] | None = sort_endpoints(raw_endpoints)

    if endpoints is None:
        return []

    return [
        PortConnectionError.ENDPOINT_NOT_FOUND.format(port_id=port_id)
        for port_id in endpoints
        if port_id not in endpoint_ports
    ]


def same_object_blockers(
        endpoint_ports: dict[int, dict[str, Any]],
        connection_type: str,
        raw_endpoints: Any) -> list[str]:
    """
    Judges the two ends against the devices they sit on, which the connection type decides

    **The two kinds of connection are the two sides of one rule**, and each is the other's refusal
    message:

      - a **CABLE** joins two devices. Two ports of the same CmdbObject cabled together is a patch
        panel's pairing written the wrong way, or a mis-click; either way the graph would draw a
        device linked to itself
      - an **INTERNAL** pairs two faces of ONE device - a panel's front port and its rear port. Across
        two objects it is not a pairing at all, and the CI Explorer's collapse rule (a port-bearing
        intermediate is walked THROUGH, never drawn) would follow it into the wrong device

    Silent when either port is missing: `missing_endpoint_blockers` already speaks for that, and a
    rule about two owners cannot be judged with one of them unknown

    Args:
        endpoint_ports (dict[int, dict[str, Any]]): The endpoint ports, keyed by public_id
        connection_type (str): The ConnectionType value of the connection
        raw_endpoints (Any): The raw endpoints value from the request

    Returns:
        list[str]: The one reason the pairing is refused, or empty when it is allowed
    """
    endpoints: list[int] | None = sort_endpoints(raw_endpoints)

    if endpoints is None:
        return []

    ports: list[dict[str, Any]] = [
        endpoint_ports[port_id] for port_id in endpoints if port_id in endpoint_ports
    ]

    if len(ports) != ENDPOINT_COUNT:
        return []

    first_object_id: Any = ports[0].get(PortKey.OBJECT_ID.value)
    second_object_id: Any = ports[1].get(PortKey.OBJECT_ID.value)
    same_object: bool = first_object_id == second_object_id

    if connection_type == ConnectionType.INTERNAL:
        if same_object:
            return []

        return [PortConnectionError.CROSS_OBJECT_INTERNAL.format(
            first_port_id=endpoints[0], first_object_id=first_object_id,
            second_port_id=endpoints[1], second_object_id=second_object_id,
        )]

    if same_object:
        return [PortConnectionError.SAME_OBJECT_CABLE.format(
            first_port_id=endpoints[0], second_port_id=endpoints[1], object_id=first_object_id,
        )]

    return []

# -------------------------------------------------------------------------------------------------------------------- #
#                                             per-type field rule (cable info)                                         #
# -------------------------------------------------------------------------------------------------------------------- #

def cable_field_blockers(connection_type: str, payload: dict[str, Any]) -> list[str]:
    """
    Judges the cable information a request carries against the kind of link it is creating

    A patch panel's internal pairing has no cable, so none of the cable fields belong on it - including
    ``cable_ci_id``. Only keys the payload actually carries are judged, which is what lets the same
    core back a partial update that names a single field

    Args:
        connection_type (str): The ConnectionType value of the connection
        payload (dict[str, Any]): The request body

    Returns:
        list[str]: The reasons the request is refused; empty when its shape is valid
    """
    if connection_type != ConnectionType.INTERNAL:
        return []

    return [
        PortConnectionError.CABLE_FIELD_ON_INTERNAL.format(
            field=key.value, connection_type=connection_type,
        )
        for key in CABLE_FIELD_KEYS
        if payload.get(key.value) is not None
    ]

def cable_duplication_blockers(payload: dict[str, Any]) -> list[str]:
    """
    Judges a request that describes its cable twice - inline AND by reference

    A connection carries the five cable values itself OR names a Cable CI that owns them, never both.
    Storing both would duplicate five values between a link and the asset that IS the cable, and the
    two copies would then drift apart silently the moment someone edits the CI - which is the
    inconsistency a CMDB exists to prevent. The same shape as the per-type field rule above: one
    document can describe a cable in two ways, so something has to say which one is in use.

    Only keys the payload actually carries are judged, and an explicit null is not a value - clearing
    a field the CI does not own is not an attempt to own it here

    Args:
        payload (dict[str, Any]): The request body

    Returns:
        list[str]: One reason per inline cable field sent alongside a cable CI; empty when the request
            uses exactly one of the two ways
    """
    cable_ci_id: Any = payload.get(PortConnectionKey.CABLE_CI_ID.value)

    if cable_ci_id is None:
        return []

    return [
        PortConnectionError.CABLE_FIELD_WITH_CABLE_CI.format(
            field=key.value, cable_ci_id=cable_ci_id,
        )
        for key in INLINE_CABLE_FIELD_KEYS
        if payload.get(key.value) is not None
    ]

# -------------------------------------------------------------------------------------------------------------------- #
#                                                     cable CI                                                         #
# -------------------------------------------------------------------------------------------------------------------- #

def cable_ci_blockers(
        objects_manager: ObjectsManager,
        types_manager: TypesManager,
        cable_ci_id: Any) -> list[str]:
    """
    Judges whether a cable CI reference names an inventoried cable

    Two reasons, checked in the order a caller can act on them: the object has to exist, and its
    CmdbType has to carry the CABLE SpecialType marker - a ``cable_ci_id`` pointing at an arbitrary
    object would otherwise be stored and rendered as a cable.

    That no OTHER connection already claims the same CI is deliberately NOT checked here: the partial
    unique index on ``cable_ci_id`` holds that one, so it survives two concurrent requests. And a CI
    that is DELETED later does not cascade - the reference is soft, tolerated on read and reported

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        cable_ci_id (Any): The raw cable_ci_id value from the request; None means no CI is named

    Returns:
        list[str]: The reasons the reference is refused; empty when it is fine or absent
    """
    if cable_ci_id is None:
        return []

    cable_ci: dict[str, Any] | None = objects_manager.get_object(cable_ci_id)

    if not cable_ci:
        return [PortConnectionError.CABLE_CI_NOT_FOUND.format(cable_ci_id=cable_ci_id)]

    type_doc: dict[str, Any] | None = types_manager.get_type(cable_ci.get(CmdbObjectKey.TYPE_ID.value))

    if not type_doc or type_doc.get(TypeSchemaKey.SPECIAL_TYPE) != SpecialType.CABLE:
        return [PortConnectionError.CABLE_CI_NOT_A_CABLE.format(cable_ci_id=cable_ci_id)]

    return []

# -------------------------------------------------------------------------------------------------------------------- #
#                                                    the aggregate                                                     #
# -------------------------------------------------------------------------------------------------------------------- #

def shape_blockers(connection_type: str, payload: dict[str, Any]) -> list[str]:
    """
    Every shape reason a connection would be refused, in one call, without touching the database

    The pure half of the write guard: the endpoints and the per-type field rule. The two reads - do
    both ports exist, is the cable CI a Cable - stay separate calls, so a caller that has already
    resolved either does not pay for it twice

    Args:
        connection_type (str): The ConnectionType value of the connection
        payload (dict[str, Any]): The request body

    Returns:
        list[str]: The reasons the connection is refused; empty when its shape is valid
    """
    blockers: list[str] = endpoint_blockers(payload.get(PortConnectionKey.ENDPOINTS.value))

    blockers.extend(cable_field_blockers(connection_type, payload))
    blockers.extend(cable_duplication_blockers(payload))

    return blockers
