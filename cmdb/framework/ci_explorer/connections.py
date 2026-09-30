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
Port-connectivity grafting for the CI Explorer - one cable, one edge

**Every CmdbObject a cable reaches is a node**, a patch panel included: a panel is an object like any
other, so the graph draws it. The source is therefore one hop wide - for each port of the focal
object, follow its CABLE connection to the port at the other end and draw an edge to that port's
owner:

    Switch A --cable-- P.F01     draws     A ---- P
    P.R01 --cable-- Switch B     draws     P ---- B

Expanding A shows the panel; expanding the panel shows A and B. The graph is symmetric: every
object's view of a cable is the same cable.

**An INTERNAL pairing draws nothing.** A panel's front-to-rear pairing joins two ports of the SAME
object, so it is a self-loop - and which face is patched to which is port-level detail the ports panel
of the object view answers, not a relation between CIs. The same rule covers a cable between two ports
of one object (Q39).

**A half-patched panel is visible.** A cable landing on a face that was never paired, or on one whose
rear is not cabled onward, is still a cable between two objects and is still drawn - what stops at the
panel is the *path*, not the edge.

**Cost.** Four reads, whatever the port count and whatever the topology: the focal object's ports,
their connections, the ports at the far ends of those cables, and the CmdbObjects owning them. The
far side's types are loaded by the orchestrator's existing bulk reads, not here
"""
from dataclasses import dataclass
from logging import Logger, getLogger
from typing import Any

from cmdb.framework.port.cable_hops import collect_cable_hops
from cmdb.framework.port.connection_cable_view import attach_cable_views
from cmdb.manager import ExtendableOptionsManager, ObjectsManager
from cmdb.manager.port_connections_manager import PortConnectionsManager
from cmdb.manager.ports_manager import PortsManager
from cmdb.models.port_model import PortKey
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

#: Wire tag distinguishing a physical edge from a CmdbRelation or IPAM one, like 'ipam'
PORT_CONNECTION_METADATA_SOURCE: str = 'port_connection'

#: The fixed presentation of a physical edge - no CmdbRelation backs it, so nothing is configurable
PORT_CONNECTION_RELATION_NAME: str = 'Port connection'
PORT_CONNECTION_RELATION_LABEL: str = 'connected'
PORT_CONNECTION_RELATION_ICON: str = 'fas fa-ethernet'
PORT_CONNECTION_RELATION_COLOR: str = '#8E44AD'

PUBLIC_ID_KEY: str = 'public_id'
TYPE_ID_KEY: str = 'type_id'


@dataclass(frozen=True)
class ConnectionSourceManagers:
    """
    The four managers the connection source reads through

    Bundled for the same reason ``CiExplorerManagers`` is: the collector takes one argument instead
    of four, and a test names only what its scenario touches

    Attributes:
        ports (PortsManager): db interface for CmdbPorts
        connections (PortConnectionsManager): db interface for CmdbPortConnections
        objects (ObjectsManager): db interface for CmdbObjects, used to resolve Cable CIs
        extendable_options (ExtendableOptionsManager): db interface for the CABLE_TYPE labels
    """
    ports: PortsManager
    connections: PortConnectionsManager
    objects: ObjectsManager
    extendable_options: ExtendableOptionsManager


@dataclass(frozen=True)
class ConnectionNeighbour:
    """
    One CI the focal object is cabled to, and the cable that says so

    Attributes:
        neighbour_object_id: public_id of the CmdbObject owning the port at the far end
        path: The cable, as a one-entry list - the stored CmdbPortConnection carrying its resolved
            cable block. It is a list because the edge's ``metadata.path`` is one, and because a
            reader of the wire format should not have to care that it is always one long
    """
    neighbour_object_id: int
    path: list[dict[str, Any]]


def index_ports_by_id(ports: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    """
    Indexes CmdbPort documents by public_id, skipping any without a usable one

    Args:
        ports (list[dict[str, Any]]): CmdbPort documents

    Returns:
        dict[int, dict[str, Any]]: {public_id: port document}
    """
    return {
        port[PortKey.PUBLIC_ID.value]: port
        for port in ports if isinstance(port.get(PortKey.PUBLIC_ID.value), int)
    }


def load_far_port_owners(
        far_port_ids: list[int],
        managers: ConnectionSourceManagers) -> dict[int, int]:
    """
    Reads which CmdbObject owns each port at the far end of a cable, in one query

    Args:
        far_port_ids (list[int]): public_ids of the ports the cables land on
        managers (ConnectionSourceManagers): The managers to read through

    Returns:
        dict[int, int]: {port public_id: owner object public_id}
    """
    if not far_port_ids:
        return {}

    return {
        port[PortKey.PUBLIC_ID.value]: port[PortKey.OBJECT_ID.value]
        for port in managers.ports.get_ports_by_ids(far_port_ids)
        if isinstance(port.get(PortKey.OBJECT_ID.value), int)
    }


def collect_connection_neighbours(
        target_id: int,
        types_filter: frozenset[int],
        remaining: int,
        item_limit_active: bool,
        managers: ConnectionSourceManagers) -> tuple[list[ConnectionNeighbour], dict[int, dict[str, Any]]]:
    """
    Returns the CIs the focal object is cabled to, and those CmdbObjects

    The whole source in one call: read the focal object's ports and their connections, take one hop
    along every cable, resolve the far ports into the objects that own them and load those. The cable
    block of every edge is resolved the same way the /port_connections reads resolve it, so the
    frontend reads one cable shape everywhere

    Args:
        target_id (int): public_id of the focal CmdbObject
        types_filter (frozenset[int]): Allowed neighbour type_ids; empty disables filtering
        remaining (int): Neighbour slots left by the earlier sources
        item_limit_active (bool): Whether a cap applies at all
        managers (ConnectionSourceManagers): The managers to read through

    Returns:
        tuple[list[ConnectionNeighbour], dict[int, dict[str, Any]]]: The neighbours with their cable,
            and the far-side CmdbObjects by public_id
    """
    if item_limit_active and remaining <= 0:
        return [], {}

    focal_ports: list[dict[str, Any]] = managers.ports.get_ports_of_object(target_id)

    if not focal_ports:
        return [], {}

    focal_port_ids: set[int] = set(index_ports_by_id(focal_ports))

    focal_connections: list[dict[str, Any]] = managers.connections.get_connections_of_ports(
        sorted(focal_port_ids),
    )

    hops: list[tuple[dict[str, Any], int]] = collect_cable_hops(focal_connections, focal_port_ids)

    if not hops:
        return [], {}

    owner_by_port: dict[int, int] = load_far_port_owners(
        sorted({far_port_id for _connection, far_port_id in hops}), managers,
    )

    # A far end on the focal object itself is a real cable, but not an edge anyone can draw (Q39)
    reachable: list[tuple[dict[str, Any], int]] = [
        (connection, owner_by_port[far_port_id])
        for connection, far_port_id in hops
        if owner_by_port.get(far_port_id) not in (None, target_id)
    ]

    if not reachable:
        return [], {}

    neighbour_objects: dict[int, dict[str, Any]] = load_neighbour_objects(
        sorted({owner_id for _connection, owner_id in reachable}), types_filter, managers,
    )

    neighbours: list[ConnectionNeighbour] = []

    for connection, owner_id in reachable:
        if owner_id not in neighbour_objects:
            continue

        if item_limit_active and len(neighbours) >= remaining:
            LOGGER.warning(
                "[ci_explorer] Graph of object %s truncated: the item_limit cut its port connections",
                target_id,
            )
            break

        neighbours.append(ConnectionNeighbour(
            neighbour_object_id=owner_id,
            path=attach_cable_views([connection], managers.objects, managers.extendable_options),
        ))

    return neighbours, neighbour_objects


def load_neighbour_objects(
        neighbour_ids: list[int],
        types_filter: frozenset[int],
        managers: ConnectionSourceManagers) -> dict[int, dict[str, Any]]:
    """
    Bulk-loads the far-side CmdbObjects, applying the caller's type filter in the same query

    Args:
        neighbour_ids (list[int]): public_ids of the objects the cables reach
        types_filter (frozenset[int]): Allowed neighbour type_ids; empty disables filtering
        managers (ConnectionSourceManagers): The managers to read through

    Returns:
        dict[int, dict[str, Any]]: {public_id: CmdbObject document}
    """
    criteria: dict[str, Any] = {PUBLIC_ID_KEY: {'$in': neighbour_ids}}

    if types_filter:
        criteria[TYPE_ID_KEY] = {'$in': sorted(types_filter)}

    return {
        neighbour[PUBLIC_ID_KEY]: neighbour
        for neighbour in managers.objects.find(criteria=criteria, sort=[(PUBLIC_ID_KEY, 1)])
        if isinstance(neighbour.get(PUBLIC_ID_KEY), int)
    }
