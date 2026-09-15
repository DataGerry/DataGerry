# DATAGERRY - OpenSource Enterprise CMDB
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
Port-connectivity grafting for the CI Explorer - the CI-level projection of the physical layer

Step 14 of the Port Connectivity plan, built to the contract closed in its §6.2. The physical layer
is ports, cables and patch panels; the CI Explorer draws **objects**. So this module walks the
physical chain and reports only what it ends at:

    Server A --cable-- P.F07 --internal-- P.R07 --cable-- Switch B      becomes      A ---- B

**A patch panel is never a node.** Hiding it is the point of the feature, not a refinement of it
(Q8, Option B). The concept's §29 projection therefore ships in v1 rather than after a port-level
first pass.

**Panel-ness is read from the port's ``side``.** It is the one stored signal for it - D3 made
``side`` explicit precisely so a panel is derivable without a "kind" field and without parsing port
names, which the concept forbids (§7-§17). A port on FRONT or REAR belongs to a patch panel; a
SINGLE port belongs to an ordinary device. Note this is a *different* question from "is the next hop
INTERNAL": a panel face that has not been paired yet still carries FRONT/REAR, which is exactly what
makes case C2 below answerable at all.

What the walk emits, case by case (all ruled 2026-09-15):

  - **the ordinary case** - the chain ends on a SINGLE port: one edge to that port's owner
  - **C1** - the chain dies inside the panel (a paired rear with no cable): **nothing**
  - **C2** - the cable lands on a panel face that was never paired: **nothing**. There is no far-side
    CI, and the panel itself is not a node
  - **C3** - chained panels: they collapse together, one edge between the two ends
  - **C4** - the focal object is itself a panel: it is transparent. Every one of its ports is walked
    outwards independently, so its graph shows every CI its paths reach. The graph is deliberately
    not symmetric as a result: A's graph draws ``A -- B``, while the panel's draws ``P -- A`` and
    ``P -- B``
  - **Q39** - both ends on the same object: skipped, no self-loop is drawn

**One CI hop, like every other source** (C6/Q33). There is no ``max_depth`` on the wire: the walk
runs until the chain ends, and what bounds it is ``MAX_PHYSICAL_HOPS`` plus a visited-port set - a
cable and an internal pairing can close a chain into a cycle, which no unique index forbids.

**Cost.** Level-synchronous, never per port: two queries to start (the focal object's ports and
their connections) and one more per level walked. The common case - a server cabled straight to a
switch - is three queries, and each additional panel in the chain adds two. The far-side objects and
their types are loaded by the orchestrator's existing bulk reads, not here
"""
from dataclasses import dataclass, field
from logging import Logger, getLogger
from typing import Any

from cmdb.framework.port.connection_cable_view import attach_cable_views
from cmdb.manager import ExtendableOptionsManager, ObjectsManager
from cmdb.manager.port_connections_manager import PortConnectionsManager
from cmdb.manager.ports_manager import PortsManager
from cmdb.models.port_connection_model.port_connection_constants import ConnectionType, PortConnectionKey
from cmdb.models.port_model import PortKey
from cmdb.models.port_model.port_constants import PortSide
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

#: Wire tag distinguishing a collapsed physical edge from a CmdbRelation or IPAM one, like 'ipam'
PORT_CONNECTION_METADATA_SOURCE: str = 'port_connection'

#: The fixed presentation of a collapsed edge - no CmdbRelation backs it, so nothing is configurable
PORT_CONNECTION_RELATION_NAME: str = 'Port connection'
PORT_CONNECTION_RELATION_LABEL: str = 'connected'
PORT_CONNECTION_RELATION_ICON: str = 'fas fa-ethernet'
PORT_CONNECTION_RELATION_COLOR: str = '#8E44AD'

#: Safety bound on one chain walk, counted in physical hops rather than drawn edges. A cabled and
#: internally paired chain can close into a cycle, which no index forbids, and the visited-port set
#: already stops that - this is the second guard, against a pathologically long patch chain
MAX_PHYSICAL_HOPS: int = 50

PUBLIC_ID_KEY: str = 'public_id'
TYPE_ID_KEY: str = 'type_id'


@dataclass(frozen=True)
class ConnectionSourceManagers:
    """
    The four managers the connection walk reads through

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
    One CI the focal object is physically connected to, and the path that was collapsed to say so

    Attributes:
        neighbour_object_id: public_id of the CmdbObject at the far end of the chain
        path: The physical hops, ordered from the focal end outwards. Each entry is a stored
            CmdbPortConnection carrying its resolved cable block and its two endpoint ports
    """
    neighbour_object_id: int
    path: list[dict[str, Any]]


@dataclass
class ChainWalk:
    """
    One in-flight physical path, from a port of the focal object outwards

    Attributes:
        hops: The connections traversed so far, focal end first
        current_port_id: The port the walk has arrived at and has not yet resolved
        visited_port_ids: Every port this particular path has already touched, so a chain that loops
            back on itself is abandoned instead of walked forever
    """
    hops: list[dict[str, Any]] = field(default_factory=list)
    current_port_id: int = 0
    visited_port_ids: set[int] = field(default_factory=set)


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


def index_connections_by_port(connections: list[dict[str, Any]]) -> dict[tuple[int, str], dict[str, Any]]:
    """
    Indexes connections by (port_id, connection_type), which is a unique key by construction

    A port has at most one CABLE and at most one INTERNAL connection - the two partial unique indexes
    on ``endpoints`` guarantee it - so there is no fan-out at a port and every physical path is a
    simple chain. That is what lets the walk ask a dict rather than branch

    Args:
        connections (list[dict[str, Any]]): CmdbPortConnection documents

    Returns:
        dict[tuple[int, str], dict[str, Any]]: {(port public_id, connection type): connection}
    """
    indexed: dict[tuple[int, str], dict[str, Any]] = {}

    for connection in connections:
        connection_type: Any = connection.get(PortConnectionKey.CONNECTION_TYPE.value)

        for endpoint in connection.get(PortConnectionKey.ENDPOINTS.value) or []:
            if isinstance(endpoint, int) and isinstance(connection_type, str):
                indexed[(endpoint, connection_type)] = connection

    return indexed


def other_endpoint(connection: dict[str, Any], port_id: int) -> int | None:
    """
    Returns the endpoint of a connection that is not the given port

    ``endpoints`` is stored sorted, so a fixed position means nothing: the question can only ever be
    asked as membership. A self-connection (both endpoints equal) answers None, since it leads nowhere

    Args:
        connection (dict[str, Any]): The CmdbPortConnection document
        port_id (int): The endpoint the walk arrived from

    Returns:
        int | None: The far endpoint, or None when the connection does not name exactly one other port
    """
    endpoints: list[Any] = connection.get(PortConnectionKey.ENDPOINTS.value) or []
    far_endpoints: list[int] = [
        endpoint for endpoint in endpoints if isinstance(endpoint, int) and endpoint != port_id
    ]

    return far_endpoints[0] if len(far_endpoints) == 1 else None


def start_walks(
        focal_ports: list[dict[str, Any]],
        connections_by_port: dict[tuple[int, str], dict[str, Any]]) -> list[ChainWalk]:
    """
    Opens one walk per cabled port of the focal object

    Every port is a starting point, the focal object's own panel faces included - that is what makes
    a panel transparent when it is the focal object (C4). A port with no CABLE starts nothing: an
    INTERNAL pairing on its own connects the object to itself

    Args:
        focal_ports (list[dict[str, Any]]): Every CmdbPort of the focal object
        connections_by_port (dict[tuple[int, str], dict[str, Any]]): The focal ports' connections

    Returns:
        list[ChainWalk]: One walk per cabled port, each already standing on the far side of its cable
    """
    walks: list[ChainWalk] = []

    for port in focal_ports:
        port_id: Any = port.get(PortKey.PUBLIC_ID.value)

        if not isinstance(port_id, int):
            continue

        cable: dict[str, Any] | None = connections_by_port.get((port_id, ConnectionType.CABLE.value))

        if cable is None:
            continue

        far_port_id: int | None = other_endpoint(cable, port_id)

        if far_port_id is None:
            continue

        walks.append(ChainWalk(
            hops=[cable],
            current_port_id=far_port_id,
            visited_port_ids={port_id, far_port_id},
        ))

    return walks


def advance_walk(
        walk: ChainWalk,
        connections_by_port: dict[tuple[int, str], dict[str, Any]]) -> ChainWalk | None:
    """
    Walks one chain through a patch panel, or abandons it

    Called only for a walk standing on a panel face. Two of the ruled cases end here: an unpaired
    face (C2) and a paired one whose far side was never cabled (C1) both abandon the walk, because
    neither reaches a CI and the panel itself is never drawn

    Args:
        walk (ChainWalk): The walk standing on the panel face
        connections_by_port (dict[tuple[int, str], dict[str, Any]]): Connections of the panel's ports

    Returns:
        ChainWalk | None: The walk advanced to the next port, or None when the chain ends here
    """
    internal: dict[str, Any] | None = connections_by_port.get(
        (walk.current_port_id, ConnectionType.INTERNAL.value),
    )

    if internal is None:
        # C2 - a panel face that was never paired. No path through anything, and no panel node
        return None

    paired_port_id: int | None = other_endpoint(internal, walk.current_port_id)

    if paired_port_id is None:
        return None

    cable: dict[str, Any] | None = connections_by_port.get((paired_port_id, ConnectionType.CABLE.value))

    if cable is None:
        # C1 - the ordinary half-patched state: the chain dies inside the panel
        return None

    next_port_id: int | None = other_endpoint(cable, paired_port_id)

    if next_port_id is None or next_port_id in walk.visited_port_ids:
        if next_port_id is not None:
            LOGGER.warning(
                "[ci_explorer] Port %s revisited while walking a physical chain - path abandoned",
                next_port_id,
            )

        return None

    return ChainWalk(
        hops=[*walk.hops, internal, cable],
        current_port_id=next_port_id,
        visited_port_ids={*walk.visited_port_ids, paired_port_id, next_port_id},
    )


def resolve_walks(
        walks: list[ChainWalk],
        managers: ConnectionSourceManagers) -> list[tuple[ChainWalk, int]]:
    """
    Runs every open walk to its end, one level at a time

    Level-synchronous rather than depth-first: all walks standing on a port ask for their port
    documents in one query and for the connections of the panels they landed on in one more, so the
    number of round trips follows the length of the chain and never the number of ports

    Args:
        walks (list[ChainWalk]): The walks opened at the focal object's cabled ports
        managers (ConnectionSourceManagers): The managers to read through

    Returns:
        list[tuple[ChainWalk, int]]: Each finished walk with the public_id of the CmdbObject it
            ended on; walks that reached no CI are not in the list
    """
    resolved: list[tuple[ChainWalk, int]] = []
    hops_walked: int = 1

    while walks and hops_walked <= MAX_PHYSICAL_HOPS:
        ports_by_id: dict[int, dict[str, Any]] = index_ports_by_id(managers.ports.find(
            criteria={PortKey.PUBLIC_ID.value: {'$in': [walk.current_port_id for walk in walks]}},
        ))

        panel_walks: list[tuple[ChainWalk, dict[str, Any]]] = []

        for walk in walks:
            port: dict[str, Any] | None = ports_by_id.get(walk.current_port_id)

            if port is None:
                LOGGER.warning(
                    "[ci_explorer] Connection names the missing Port %s - path abandoned",
                    walk.current_port_id,
                )
                continue

            if PortSide.is_panel_side(port.get(PortKey.SIDE.value)):
                panel_walks.append((walk, port))
                continue

            owner_id: Any = port.get(PortKey.OBJECT_ID.value)

            if isinstance(owner_id, int):
                resolved.append((walk, owner_id))

        walks = advance_panel_walks(panel_walks, managers)
        hops_walked += 2

    if walks:
        LOGGER.warning(
            "[ci_explorer] %s physical chain(s) exceeded the %s hop budget and were abandoned",
            len(walks), MAX_PHYSICAL_HOPS,
        )

    return resolved


def advance_panel_walks(
        panel_walks: list[tuple[ChainWalk, dict[str, Any]]],
        managers: ConnectionSourceManagers) -> list[ChainWalk]:
    """
    Advances every walk that landed on a panel face, in one batched read

    The paired face and the cable leaving it both belong to the panel, so one query for the
    connections of all the landed panels' ports carries the whole level

    Args:
        panel_walks (list[tuple[ChainWalk, dict[str, Any]]]): The walks standing on a panel face,
            each with that face's CmdbPort document
        managers (ConnectionSourceManagers): The managers to read through

    Returns:
        list[ChainWalk]: The walks that continue past the panel
    """
    if not panel_walks:
        return []

    panel_object_ids: list[int] = sorted({
        port[PortKey.OBJECT_ID.value] for _walk, port in panel_walks
        if isinstance(port.get(PortKey.OBJECT_ID.value), int)
    })

    panel_ports: list[dict[str, Any]] = managers.ports.find(
        criteria={PortKey.OBJECT_ID.value: {'$in': panel_object_ids}},
    ) if panel_object_ids else []

    connections_by_port: dict[tuple[int, str], dict[str, Any]] = index_connections_by_port(
        managers.connections.get_connections_of_ports(sorted(index_ports_by_id(panel_ports).keys())),
    )

    advanced: list[ChainWalk] = []

    for walk, port in panel_walks:
        del port  # Read by the caller to decide panel-ness and to batch; the advance needs only ids
        next_walk: ChainWalk | None = advance_walk(walk, connections_by_port)

        if next_walk is not None:
            advanced.append(next_walk)

    return advanced


def collect_connection_neighbours(
        target_id: int,
        types_filter: frozenset[int],
        remaining: int,
        item_limit_active: bool,
        managers: ConnectionSourceManagers) -> tuple[list[ConnectionNeighbour], dict[int, dict[str, Any]]]:
    """
    Returns the CIs the focal object is physically connected to, and those CmdbObjects

    The whole source in one call: open a walk at every cabled port of the focal object, run them all
    to their ends, drop what the rules say is not drawn, and resolve the surviving far ends into
    CmdbObjects. The cable block of every hop is resolved the same way the /port_connections reads
    resolve it, so the frontend reads one cable shape everywhere

    Args:
        target_id (int): public_id of the focal CmdbObject
        types_filter (frozenset[int]): Allowed neighbour type_ids; empty disables filtering
        remaining (int): Neighbour slots left by the earlier sources
        item_limit_active (bool): Whether a cap applies at all
        managers (ConnectionSourceManagers): The managers to read through

    Returns:
        tuple[list[ConnectionNeighbour], dict[int, dict[str, Any]]]: The neighbours with their
            collapsed paths, and the far-side CmdbObjects by public_id
    """
    if item_limit_active and remaining <= 0:
        return [], {}

    focal_ports: list[dict[str, Any]] = managers.ports.get_ports_of_object(target_id)

    if not focal_ports:
        return [], {}

    focal_connections: list[dict[str, Any]] = managers.connections.get_connections_of_ports(
        sorted(index_ports_by_id(focal_ports).keys()),
    )

    resolved: list[tuple[ChainWalk, int]] = resolve_walks(
        start_walks(focal_ports, index_connections_by_port(focal_connections)), managers,
    )

    # Q39: both ends on the focal object itself is a real cable, but not an edge anyone can draw
    reachable: list[tuple[ChainWalk, int]] = [
        (walk, owner_id) for walk, owner_id in resolved if owner_id != target_id
    ]

    if not reachable:
        return [], {}

    neighbour_objects: dict[int, dict[str, Any]] = load_neighbour_objects(
        sorted({owner_id for _walk, owner_id in reachable}), types_filter, managers,
    )

    neighbours: list[ConnectionNeighbour] = []

    for walk, owner_id in reachable:
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
            path=attach_cable_views(walk.hops, managers.objects, managers.extendable_options),
        ))

    return neighbours, neighbour_objects


def load_neighbour_objects(
        neighbour_ids: list[int],
        types_filter: frozenset[int],
        managers: ConnectionSourceManagers) -> dict[int, dict[str, Any]]:
    """
    Bulk-loads the far-side CmdbObjects, applying the caller's type filter in the same query

    Args:
        neighbour_ids (list[int]): public_ids of the objects the walks ended on
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
