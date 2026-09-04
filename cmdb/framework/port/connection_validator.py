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
  - **cable information is rejected on an INTERNAL connection** - the per-type field rule, the same
    shape as the Rack's occupant_validator: one document holds two kinds of link, so something has to
    say which fields belong to which
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


def missing_endpoint_blockers(ports_manager: PortsManager, raw_endpoints: Any) -> list[str]:
    """
    Judges whether both ends name a CmdbPort that really exists

    One batched read for both ids rather than one per endpoint. Unusable endpoints are not reported
    again here - endpoint_blockers has already said so, and repeating it would give the caller the
    same problem twice under two different messages

    Args:
        ports_manager (PortsManager): db interface for CmdbPorts
        raw_endpoints (Any): The raw endpoints value from the request

    Returns:
        list[str]: One reason per endpoint that names no port; empty when both exist
    """
    endpoints: list[int] | None = sort_endpoints(raw_endpoints)

    if endpoints is None:
        return []

    found: list[dict[str, Any]] = ports_manager.find(
        criteria={PortKey.PUBLIC_ID.value: {'$in': endpoints}},
    )
    existing: set[Any] = {port.get(PortKey.PUBLIC_ID.value) for port in found}

    return [
        PortConnectionError.ENDPOINT_NOT_FOUND.format(port_id=port_id)
        for port_id in endpoints
        if port_id not in existing
    ]

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

    return blockers
