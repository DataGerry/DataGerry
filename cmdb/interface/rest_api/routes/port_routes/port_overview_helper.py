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
Assembly of the ports overview

The panel of an object view asks one question - "show me this object's ports the way they are wired" -
and the answer needs four things the stored port does not carry: the labels behind its three option
ids, the cable on it, the CI that cable ends on, and, on a patch panel, the port it is paired with.

**Every one of those is resolved for the whole object at once.** The cost is a fixed handful of
queries whatever the port count, which is the reason this exists as a route at all: assembled in the
client it is one read per port for the peer port and another for its object - just under a hundred
requests for a 48-port switch.

The functions below are split so each answers one of those questions and can be tested without a
database; `build_port_overview` is the only one that talks to a manager.
"""
from dataclasses import dataclass, field
from logging import Logger, getLogger
from typing import Any

from cmdb.manager.objects_manager import ObjectsManager
from cmdb.manager.ports_manager import PortsManager
from cmdb.manager.extendable_options_manager import ExtendableOptionsManager

from cmdb.models.user_model import CmdbUser
from cmdb.models.object_model.cmdb_object_key_enum import CmdbObjectKey
from cmdb.models.port_model.port_constants import PORT_SELECT_FIELD_OPTION_TYPES, PortKey, PortSide
from cmdb.models.port_connection_model.port_connection_constants import (
    CABLE_VIEW_KEY,
    ConnectionType,
    PortConnectionKey,
)
from cmdb.security.acl.permission import AccessControlPermission

from cmdb.framework.port.cable_hops import other_endpoint
from cmdb.framework.port.name_syntax_constants import PortDeviceKind

from cmdb.interface.rest_api.routes.port_routes.port_route_constants import PORT_CONNECTED_KEY
from cmdb.interface.rest_api.routes.port_routes.port_interface_link_constants import PORT_INTERFACE_LINKS_KEY
from cmdb.interface.rest_api.routes.port_routes.port_overview_constants import (
    ConnectedObjectKey,
    ConnectedPortKey,
    PortOverviewEntryKey,
    PortOverviewKey,
    PortOverviewOptionKey,
    PortOverviewRowKey,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #

def index_connections_by_kind(
        connections: list[dict[str, Any]],
        connection_type: ConnectionType) -> dict[int, dict[str, Any]]:
    """
    Indexes connections of one kind by each of the two ports they join

    Both endpoints are indexed because the stored pair is sorted ascending - neither position carries
    meaning, so a reader may arrive from either side

    Args:
        connections (list[dict[str, Any]]): The connections of the object's ports
        connection_type (ConnectionType): Which kind to index; the other kind is skipped

    Returns:
        dict[int, dict[str, Any]]: {port_id: connection} for every port taking part in one
    """
    by_port: dict[int, dict[str, Any]] = {}

    for connection in connections:
        if connection.get(PortConnectionKey.CONNECTION_TYPE.value) != connection_type.value:
            continue

        for port_id in connection.get(PortConnectionKey.ENDPOINTS.value) or []:
            by_port[port_id] = connection

    return by_port


def collect_peer_port_ids(ports: list[dict[str, Any]], cable_by_port: dict[int, dict[str, Any]]) -> list[int]:
    """
    Collects the ports at the far end of the object's cables

    The ports of the object itself are excluded: a cable between two ports of one object names a peer
    that is already in hand, and reading it again would be a query for nothing

    Args:
        ports (list[dict[str, Any]]): The object's ports
        cable_by_port (dict[int, dict[str, Any]]): Cable connections indexed by port

    Returns:
        list[int]: The distinct peer port public_ids, in the order their ports appear
    """
    own_ids: set[int] = {port.get(PortKey.PUBLIC_ID.value) for port in ports}
    peer_ids: dict[int, None] = {}

    for port in ports:
        port_id = port.get(PortKey.PUBLIC_ID.value)
        peer = other_endpoint(cable_by_port.get(port_id), port_id)

        if peer is not None and peer not in own_ids:
            peer_ids[peer] = None

    return list(peer_ids)


def build_option_view(option_id: Any, labels: dict[int, str]) -> dict[str, Any]:
    """
    Resolves one stored option reference into what the panel shows it as

    An id whose option is gone keeps its id and answers a label of None: the port still holds that
    value, and reporting no id would read as "nothing selected"

    Args:
        option_id (Any): The stored CmdbExtendableOption public_id, or None
        labels (dict[int, str]): {public_id: value} of the list this field draws from

    Returns:
        dict[str, Any]: The {id, label} pair, both None when the port holds no value
    """
    return {
        PortOverviewOptionKey.ID.value: option_id,
        PortOverviewOptionKey.LABEL.value: labels.get(option_id) if option_id is not None else None,
    }


@dataclass
class PeerEnds:
    """
    The far ends of an object's cables, resolved once for the whole overview

    Holds what the peer reads produced: the port documents the cables land on, the summary lines of the
    objects owning them, and which of those objects the requesting user may read. A user names a
    connection port first and device second, so both halves are answered - and an object outside
    ACCESSIBLE_IDS was filtered out by the ACL-scoped read, which is what makes it reportable as
    restricted rather than by a label composed from a document the user has no access to
    """
    ports_by_id: dict[int, dict[str, Any]] = field(default_factory=dict)
    summary_lines: dict[int, str] = field(default_factory=dict)
    accessible_ids: set[int] = field(default_factory=set)

    def connected_port(self, peer_id: int | None) -> dict[str, Any] | None:
        """
        Names the port at the other end of a cable

        Enough for the connection dialog to render that end without reading it again, which is two
        requests per connection saved - the port documents were already read to find their owners.

        **A port whose owner the user may not read is reported by id alone.** `GET /ports/<public_id>`
        answers 403 for exactly that port, so its name is not something this response may hand out -
        the id is, because the connection the user is allowed to read already names it

        Args:
            peer_id (int | None): The port at the far end, or None when the port carries no cable

        Returns:
            dict[str, Any] | None: The far port, or None when there is none to name
        """
        peer_port: dict[str, Any] | None = self.ports_by_id.get(peer_id) if peer_id is not None else None

        if peer_port is None:
            return None

        readable: bool = peer_port.get(PortKey.OBJECT_ID.value) in self.accessible_ids

        return {
            ConnectedPortKey.PORT_ID.value: peer_port.get(PortKey.PUBLIC_ID.value),
            ConnectedPortKey.NAME.value: peer_port.get(PortKey.NAME.value) if readable else None,
            ConnectedPortKey.SIDE.value: peer_port.get(PortKey.SIDE.value) if readable else None,
        }

    def connected_object(self, peer_id: int | None) -> dict[str, Any] | None:
        """
        Names the CI at the other end of a port's cable

        One cable hop, never a chain: the connected CI owns the port this cable ends on, so a device
        cabled into a patch panel reports the panel rather than whatever the panel's rear reaches

        Args:
            peer_id (int | None): The port at the far end, or None when the port carries no cable

        Returns:
            dict[str, Any] | None: The connected CI, or None when nothing is cabled to the port
        """
        peer_port: dict[str, Any] | None = self.ports_by_id.get(peer_id) if peer_id is not None else None
        object_id: int | None = (peer_port or {}).get(PortKey.OBJECT_ID.value)

        if object_id is None:
            return None

        restricted: bool = object_id not in self.accessible_ids

        return {
            ConnectedObjectKey.OBJECT_ID.value: object_id,
            ConnectedObjectKey.LABEL.value: None if restricted else self.summary_lines.get(object_id),
            ConnectedObjectKey.RESTRICTED.value: restricted,
        }


def build_port_entry(
        port: dict[str, Any],
        option_labels: dict[str, dict[int, str]],
        cable_by_port: dict[int, dict[str, Any]],
        peers: PeerEnds) -> dict[str, Any]:
    """
    Builds one port of an overview row

    Args:
        port (dict[str, Any]): The stored port, already carrying its connected flag and links
        option_labels (dict[str, dict[int, str]]): {option_type: {public_id: value}} of the three lists
        cable_by_port (dict[int, dict[str, Any]]): Cable connections indexed by port
        peers (PeerEnds): The far ends of the object's cables

    Returns:
        dict[str, Any]: The port as the overview presents it
    """
    port_id: int = port.get(PortKey.PUBLIC_ID.value)
    cable_connection: dict[str, Any] | None = cable_by_port.get(port_id)

    entry: dict[str, Any] = {
        PortOverviewEntryKey.PORT_ID.value: port_id,
        PortOverviewEntryKey.SIDE.value: port.get(PortKey.SIDE.value),
        PortOverviewEntryKey.PORT_NUMBER.value: port.get(PortKey.PORT_NUMBER.value),
        PortOverviewEntryKey.NAME.value: port.get(PortKey.NAME.value),
        PortOverviewEntryKey.DESCRIPTION.value: port.get(PortKey.DESCRIPTION.value),
        PortOverviewEntryKey.CONNECTED.value: bool(port.get(PORT_CONNECTED_KEY)),
        PortOverviewEntryKey.CABLE.value: (cable_connection or {}).get(CABLE_VIEW_KEY),
        PortOverviewEntryKey.CABLE_CONNECTION_ID.value: (
            cable_connection.get(PortConnectionKey.PUBLIC_ID.value) if cable_connection else None
        ),
        PortOverviewEntryKey.CONNECTED_PORT.value: peers.connected_port(
            other_endpoint(cable_connection, port_id),
        ),
        PortOverviewEntryKey.CONNECTED_OBJECT.value: peers.connected_object(
            other_endpoint(cable_connection, port_id),
        ),
        PortOverviewEntryKey.INTERFACE_LINKS.value: port.get(PORT_INTERFACE_LINKS_KEY) or [],
    }

    for field_key, option_type in PORT_SELECT_FIELD_OPTION_TYPES.items():
        entry[field_key.value] = build_option_view(
            port.get(field_key.value), option_labels.get(option_type.value, {}),
        )

    return entry


def build_standard_rows(ports: list[dict[str, Any]], entry_builder: Any) -> list[dict[str, Any]]:
    """
    Builds the rows of an ordinary device: one per port, in the order the ports were read

    Args:
        ports (list[dict[str, Any]]): The object's ports
        entry_builder (Any): Callable turning one port into its overview entry

    Returns:
        list[dict[str, Any]]: One row per port
    """
    return [{PortOverviewRowKey.PORT.value: entry_builder(port)} for port in ports]


def build_panel_rows(
        ports: list[dict[str, Any]],
        internal_by_port: dict[int, dict[str, Any]],
        entry_builder: Any) -> list[dict[str, Any]]:
    """
    Builds the rows of a patch panel: one per front/rear pairing

    **The INTERNAL connection is the pairing**, never the names - the same rule the bulk creation
    writes it by. Front faces lead, each pulling in the rear it is paired with; a rear that no front
    claims follows, alone in its row. Both halves of D3: a face whose counterpart is missing is listed
    with the other slot empty rather than hidden, because a half-built panel has to be visible to be
    fixable

    Args:
        ports (list[dict[str, Any]]): The panel's ports
        internal_by_port (dict[int, dict[str, Any]]): INTERNAL connections indexed by port
        entry_builder (Any): Callable turning one port into its overview entry

    Returns:
        list[dict[str, Any]]: One row per pairing, front faces first
    """
    ports_by_id: dict[int, dict[str, Any]] = {port.get(PortKey.PUBLIC_ID.value): port for port in ports}
    rows: list[dict[str, Any]] = []
    claimed_rear_ids: set[int] = set()

    for port in ports:
        if port.get(PortKey.SIDE.value) != PortSide.FRONT.value:
            continue

        port_id = port.get(PortKey.PUBLIC_ID.value)
        rear: dict[str, Any] | None = ports_by_id.get(other_endpoint(internal_by_port.get(port_id), port_id))

        if rear is not None:
            claimed_rear_ids.add(rear.get(PortKey.PUBLIC_ID.value))

        rows.append({
            PortOverviewRowKey.FRONT.value: entry_builder(port),
            PortOverviewRowKey.REAR.value: entry_builder(rear) if rear else None,
            PortOverviewRowKey.PAIRED.value: rear is not None,
        })

    for port in ports:
        if port.get(PortKey.SIDE.value) != PortSide.REAR.value:
            continue

        if port.get(PortKey.PUBLIC_ID.value) in claimed_rear_ids:
            continue

        rows.append({
            PortOverviewRowKey.FRONT.value: None,
            PortOverviewRowKey.REAR.value: entry_builder(port),
            PortOverviewRowKey.PAIRED.value: False,
        })

    return rows


def build_port_overview(
        ports: list[dict[str, Any]],
        connections: list[dict[str, Any]],
        device_kind: str | None,
        option_labels: dict[str, dict[int, str]],
        peers: PeerEnds) -> dict[str, Any]:
    """
    Builds the whole overview payload from everything that was read for it

    Pure: every read the answer depends on has already happened, which is what lets the two row shapes
    be tested without a database

    Args:
        ports (list[dict[str, Any]]): The object's ports, with their connected flag and links
        connections (list[dict[str, Any]]): The connections of those ports, with their cable blocks
        device_kind (str | None): The object's PortDeviceKind, None when it holds no ports
        option_labels (dict[str, dict[int, str]]): {option_type: {public_id: value}}
        peers (PeerEnds): The far ends of the object's cables

    Returns:
        dict[str, Any]: The overview response
    """
    cable_by_port: dict[int, dict[str, Any]] = index_connections_by_kind(connections, ConnectionType.CABLE)
    internal_by_port: dict[int, dict[str, Any]] = index_connections_by_kind(connections, ConnectionType.INTERNAL)

    def entry_builder(port: dict[str, Any]) -> dict[str, Any]:
        """Builds one port entry against everything resolved for this response."""
        return build_port_entry(port, option_labels, cable_by_port, peers)

    if device_kind == PortDeviceKind.PATCH_PANEL.value:
        rows: list[dict[str, Any]] = build_panel_rows(ports, internal_by_port, entry_builder)
    else:
        rows = build_standard_rows(ports, entry_builder)

    return {
        PortOverviewKey.DEVICE_KIND.value: device_kind,
        PortOverviewKey.ROWS.value: rows,
        PortOverviewKey.TOTAL.value: len(rows),
    }


def load_peer_objects(
        ports_manager: PortsManager,
        objects_manager: ObjectsManager,
        peer_ids: list[int],
        request_user: CmdbUser) -> PeerEnds:
    """
    Resolves the CIs the object's cables end on, for the whole page at once

    Three batched reads at most, and none at all when nothing is cabled outwards: the peer ports, the
    objects owning them, and the summary lines of those objects. The object read is ACL-scoped, so an
    object the user may not read simply does not come back - which is what makes it reportable as
    restricted rather than by a label composed from a document they have no access to

    Args:
        ports_manager (PortsManager): db interface for CmdbPorts
        objects_manager (ObjectsManager): db interface for CmdbObjects
        peer_ids (list[int]): The ports at the far end of the object's cables
        request_user (CmdbUser): CmdbUser requesting this data

    Returns:
        PeerEnds: The far port documents, the summary lines of the readable owners, and which owners
            those are
    """
    if not peer_ids:
        return PeerEnds()

    ports_by_id: dict[int, dict[str, Any]] = {
        port[PortKey.PUBLIC_ID.value]: port
        for port in ports_manager.get_ports_by_ids(peer_ids)
        if port.get(PortKey.PUBLIC_ID.value) is not None
    }

    object_ids: list[int] = list(dict.fromkeys(
        port[PortKey.OBJECT_ID.value] for port in ports_by_id.values()
        if port.get(PortKey.OBJECT_ID.value) is not None
    ))

    if not object_ids:
        return PeerEnds(ports_by_id=ports_by_id)

    accessible_objects: list[dict[str, Any]] = objects_manager.find_objects(
        criteria={CmdbObjectKey.PUBLIC_ID.value: {'$in': object_ids}},
        as_dict=True,
        user=request_user,
        permission=AccessControlPermission.READ,
    )

    accessible_object_ids: set[int] = {
        document[CmdbObjectKey.PUBLIC_ID.value] for document in accessible_objects
    }

    summary_lines: dict[int, str] = objects_manager.get_summary_lines_lookup(
        list(accessible_object_ids), object_docs=accessible_objects,
    )

    return PeerEnds(
        ports_by_id=ports_by_id,
        summary_lines=summary_lines,
        accessible_ids=accessible_object_ids,
    )


def load_port_option_labels(extendable_options_manager: ExtendableOptionsManager) -> dict[str, dict[int, str]]:
    """
    Reads the labels behind a port's three select fields in one query

    The panel would otherwise resolve them itself, which is the one remaining read it needs before it
    can draw a row

    Args:
        extendable_options_manager (ExtendableOptionsManager): db interface for CmdbExtendableOptions

    Returns:
        dict[str, dict[int, str]]: {option_type: {public_id: value}}
    """
    return extendable_options_manager.get_option_values_by_id(
        [option_type.value for option_type in PORT_SELECT_FIELD_OPTION_TYPES.values()]
    )
