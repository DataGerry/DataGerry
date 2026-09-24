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
Assembly of the cabling view - one ring of the physical layer

The focal CmdbObject, every object a cable of its reaches, and the cables between them. **Every node
carries all of its ports**, the focal one and the neighbours alike, so the client can show a free port
next to a cabled one and count them for the node's badge without a second request.

**There is no depth parameter, and no traversal.** Following the cabling outwards is the client asking
for the next object: a neighbour's port row carries the object at ITS far end, so "expand this port"
is this same route on that id. One ring per call, like the CI Explorer.

**Cost: a fixed handful of queries, whatever the ring holds.** The ports of the focal object, their
connections, the ports at the far ends, the objects owning them, every port of those objects, the
connections of THOSE ports (which is what lets a neighbour's row point one step further), the far
objects of that second ring, the types, and the option labels. Each is one indexed read for the whole
ring - never one per node and never one per port.
"""
from dataclasses import dataclass, field
from logging import Logger, getLogger
from typing import Any

from cmdb.framework.ci_explorer.nodes import build_type_info, resolve_title
from cmdb.framework.port.cable_hops import collect_cable_hops
from cmdb.framework.port.connected import project_connected
from cmdb.framework.port.connection_cable_view import attach_cable_views
from cmdb.manager import ExtendableOptionsManager, ObjectsManager, TypesManager
from cmdb.manager.port_connections_manager import PortConnectionsManager
from cmdb.manager.port_interface_links_manager import PortInterfaceLinksManager
from cmdb.manager.ports_manager import PortsManager

from cmdb.models.object_model.cmdb_object_key_enum import CmdbObjectKey
from cmdb.models.port_connection_model.port_connection_constants import (
    CABLE_VIEW_KEY,
    ConnectionType,
    PortConnectionKey,
)
from cmdb.models.port_model import PortKey
from cmdb.models.user_model import CmdbUser
from cmdb.security.acl.permission import AccessControlPermission

from cmdb.interface.rest_api.routes.port_routes.port_cabling_constants import (
    CablingEdgeKey,
    CablingEndKey,
    CablingNodeKey,
    PortCablingKey,
)
from cmdb.interface.rest_api.routes.port_routes.port_interface_link_helper import with_interface_links
from cmdb.interface.rest_api.routes.port_routes.port_overview_constants import PortOverviewKey
from cmdb.interface.rest_api.routes.port_routes.port_overview_helper import (
    PeerEnds,
    build_port_overview,
    load_port_option_labels,
)
from cmdb.interface.rest_api.routes.port_routes.port_route_constants import PORT_CONNECTED_KEY
from cmdb.interface.rest_api.routes.port_routes.port_route_helper import collect_port_ids, current_port_kind
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

TYPE_ID_KEY: str = 'type_id'


@dataclass(frozen=True)
class CablingManagers:
    """
    The managers the cabling view reads through

    Bundled for the same reason ``ConnectionSourceManagers`` is: the collector takes one argument
    instead of six, and a test names only what its scenario touches

    Attributes:
        ports (PortsManager): db interface for CmdbPorts
        connections (PortConnectionsManager): db interface for CmdbPortConnections
        objects (ObjectsManager): db interface for CmdbObjects
        types (TypesManager): db interface for CmdbTypes, read for a node's presentation
        interface_links (PortInterfaceLinksManager): db interface for the port/interface links
        extendable_options (ExtendableOptionsManager): db interface for the select labels
    """
    ports: PortsManager
    connections: PortConnectionsManager
    objects: ObjectsManager
    types: TypesManager
    interface_links: PortInterfaceLinksManager
    extendable_options: ExtendableOptionsManager


@dataclass
class CablingRing:
    """
    Everything one call reads, before any of it is shaped into a response

    Attributes:
        ports_by_object: Every port of every object in the ring, grouped by its owner
        connections: The connections of all those ports, with their cable blocks resolved
        objects_by_id: The CmdbObjects the user may read, by public_id
        types_by_id: Their CmdbTypes, by public_id
        neighbour_ids: The objects one cable away from the focal one, in the order they were reached
        peers: The far ends of every cable in the ring, for the per-port rows
        option_labels: {option_type: {public_id: value}} for the three select fields
    """
    ports_by_object: dict[int, list[dict[str, Any]]] = field(default_factory=dict)
    connections: list[dict[str, Any]] = field(default_factory=list)
    objects_by_id: dict[int, dict[str, Any]] = field(default_factory=dict)
    types_by_id: dict[int, dict[str, Any]] = field(default_factory=dict)
    neighbour_ids: list[int] = field(default_factory=list)
    peers: PeerEnds = field(default_factory=PeerEnds)
    option_labels: dict[str, dict[int, str]] = field(default_factory=dict)


def group_ports_by_object(ports: list[dict[str, Any]]) -> dict[int, list[dict[str, Any]]]:
    """
    Groups port documents by the CmdbObject that owns them

    Args:
        ports (list[dict[str, Any]]): Port documents, in the order they were read

    Returns:
        dict[int, list[dict[str, Any]]]: {object public_id: its ports, order preserved}
    """
    grouped: dict[int, list[dict[str, Any]]] = {}

    for port in ports:
        owner_id: Any = port.get(PortKey.OBJECT_ID.value)

        if isinstance(owner_id, int):
            grouped.setdefault(owner_id, []).append(port)

    return grouped


def collect_neighbour_ids(
        focal_ports: list[dict[str, Any]],
        connections: list[dict[str, Any]],
        owner_by_port: dict[int, int],
        focal_object_id: int) -> list[int]:
    """
    Reports the objects one cable away from the focal one, in the order their ports appear

    A cable whose far end is another port of the focal object reaches no neighbour, and neither does
    one whose far port could not be read - both are skipped rather than yielding a node with no
    content

    Args:
        focal_ports (list[dict[str, Any]]): The focal object's ports
        connections (list[dict[str, Any]]): The connections of those ports
        owner_by_port (dict[int, int]): Owner object of every far port
        focal_object_id (int): public_id of the focal CmdbObject

    Returns:
        list[int]: The neighbour object public_ids, each once
    """
    focal_port_ids: set[int] = set(collect_port_ids(focal_ports))
    neighbours: dict[int, None] = {}

    for _connection, far_port_id in collect_cable_hops(connections, focal_port_ids):
        owner_id: int | None = owner_by_port.get(far_port_id)

        if owner_id is not None and owner_id != focal_object_id:
            neighbours[owner_id] = None

    return list(neighbours)


def build_cabling_node(
        object_id: int,
        ring: CablingRing,
        managers: CablingManagers) -> dict[str, Any]:
    """
    Builds one node: an object, how it is presented, and every one of its ports

    A node the requesting user may not read carries its id and ``restricted`` alone. The cable that
    reaches it stays visible - a user who may read this object's ports may know it is cabled to
    something - but what sits at the far end is not described

    Args:
        object_id (int): public_id of the CmdbObject this node stands for
        ring (CablingRing): Everything the call read
        managers (CablingManagers): The managers, for the interface-link resolution

    Returns:
        dict[str, Any]: The node
    """
    linked_object: dict[str, Any] | None = ring.objects_by_id.get(object_id)

    if linked_object is None:
        return {
            CablingNodeKey.OBJECT_ID.value: object_id,
            CablingNodeKey.RESTRICTED.value: True,
        }

    type_doc: dict[str, Any] = ring.types_by_id.get(linked_object.get(TYPE_ID_KEY)) or {}
    ports: list[dict[str, Any]] = ring.ports_by_object.get(object_id) or []

    # The links are resolved against the node's OWN object, which is the only place an interface may
    # live - so the rows carry their addresses without a read per port
    with_interface_links(managers.interface_links, managers.objects, ports, linked_object)

    # Projected from the connections the ring already holds rather than re-read per node: the flag is
    # every connection of the port, an INTERNAL pairing included, so a panel face reads connected
    # while carrying no cable. What this view draws a port's state from is its row's `cable`
    project_connected(ports, ring.connections, PORT_CONNECTED_KEY)

    overview: dict[str, Any] = build_port_overview(
        ports,
        ring.connections,
        current_port_kind(ports),
        ring.option_labels,
        ring.peers,
    )

    return {
        CablingNodeKey.OBJECT_ID.value: object_id,
        CablingNodeKey.TITLE.value: resolve_title(linked_object, type_doc),
        CablingNodeKey.TYPE_INFO.value: build_type_info(type_doc),
        CablingNodeKey.DEVICE_KIND.value: overview[PortOverviewKey.DEVICE_KIND.value],
        CablingNodeKey.PORT_COUNT.value: len(ports),
        CablingNodeKey.ROWS.value: overview[PortOverviewKey.ROWS.value],
        CablingNodeKey.RESTRICTED.value: False,
    }


def build_cabling_edges(
        connections: list[dict[str, Any]],
        owner_by_port: dict[int, int],
        ports_by_id: dict[int, dict[str, Any]],
        drawn_object_ids: set[int],
        accessible_ids: set[int]) -> list[dict[str, Any]]:
    """
    Builds one edge per cable, between the two ports it joins

    Only CABLE connections become edges: an INTERNAL pairing joins two ports of one object and is
    drawn inside the node, not between two of them. A cable is emitted once - the stored ``endpoints``
    pair is sorted, so the same cable yields the same edge whichever of its ends the view opened on -
    and only when **both** of its objects are nodes of this ring, so no edge points at nothing

    Args:
        connections (list[dict[str, Any]]): Every connection read, with its cable block
        owner_by_port (dict[int, int]): Owner object of every port in the ring
        ports_by_id (dict[int, dict[str, Any]]): Every port in the ring, by public_id
        drawn_object_ids (set[int]): The objects this response carries as nodes
        accessible_ids (set[int]): The objects the requesting user may read

    Returns:
        list[dict[str, Any]]: The edges, one per cable
    """
    edges: list[dict[str, Any]] = []
    seen: set[int] = set()

    for connection in connections:
        if connection.get(PortConnectionKey.CONNECTION_TYPE.value) != ConnectionType.CABLE.value:
            continue

        connection_id: Any = connection.get(PortConnectionKey.PUBLIC_ID.value)

        if connection_id in seen:
            continue

        endpoints: list[Any] = connection.get(PortConnectionKey.ENDPOINTS.value) or []

        if len(endpoints) != 2:
            continue

        owners: list[int | None] = [owner_by_port.get(endpoint) for endpoint in endpoints]

        if any(owner not in drawn_object_ids for owner in owners):
            continue

        seen.add(connection_id)
        edges.append({
            CablingEdgeKey.CONNECTION_ID.value: connection_id,
            CablingEdgeKey.FROM_END.value: build_cabling_end(
                endpoints[0], owners[0], ports_by_id, accessible_ids,
            ),
            CablingEdgeKey.TO_END.value: build_cabling_end(
                endpoints[1], owners[1], ports_by_id, accessible_ids,
            ),
            CablingEdgeKey.CABLE.value: connection.get(CABLE_VIEW_KEY),
        })

    return edges


def build_cabling_end(
        port_id: int,
        object_id: int | None,
        ports_by_id: dict[int, dict[str, Any]],
        accessible_ids: set[int]) -> dict[str, Any]:
    """
    Names one end of an edge: which port of which object the cable lands on

    An end on an object the requesting user may not read keeps its ids and loses its name and side:
    ``GET /ports/<public_id>`` answers 403 for that port, so the graph may not hand its name out
    either. The ids stay, because the cable the user is allowed to see already names them

    Args:
        port_id (int): public_id of the port at this end
        object_id (int | None): public_id of the object owning it
        ports_by_id (dict[int, dict[str, Any]]): Every port in the ring, by public_id
        accessible_ids (set[int]): The objects the requesting user may read

    Returns:
        dict[str, Any]: The end
    """
    port: dict[str, Any] = ports_by_id.get(port_id) or {}
    readable: bool = object_id in accessible_ids

    return {
        CablingEndKey.OBJECT_ID.value: object_id,
        CablingEndKey.PORT_ID.value: port_id,
        CablingEndKey.PORT_NAME.value: port.get(PortKey.NAME.value) if readable else None,
        CablingEndKey.SIDE.value: port.get(PortKey.SIDE.value) if readable else None,
    }


def load_ring_peer_ports(
        ring_ports: list[dict[str, Any]],
        ring_connections: list[dict[str, Any]],
        managers: CablingManagers) -> dict[int, dict[str, Any]]:
    """
    Reads every port the ring's cables touch, including the ones one step beyond it

    The ports outside the ring are what let a NEIGHBOUR's row name the object at its own far end -
    which is how the client knows that port can be expanded, without that object being a node here

    Args:
        ring_ports (list[dict[str, Any]]): The ports of the focal object and its neighbours
        ring_connections (list[dict[str, Any]]): The connections of those ports
        managers (CablingManagers): The managers to read through

    Returns:
        dict[int, dict[str, Any]]: {port public_id: port document}
    """
    ring_port_ids: set[int] = set(collect_port_ids(ring_ports))
    outward_port_ids: list[int] = sorted({
        far_port_id for _connection, far_port_id
        in collect_cable_hops(ring_connections, ring_port_ids)
    } - ring_port_ids)

    return {
        port[PortKey.PUBLIC_ID.value]: port
        for port in ring_ports + managers.ports.get_ports_by_ids(outward_port_ids)
        if isinstance(port.get(PortKey.PUBLIC_ID.value), int)
    }


def load_ring_objects(
        focal_object_id: int,
        neighbour_ids: list[int],
        peer_ports: dict[int, dict[str, Any]],
        managers: CablingManagers,
        request_user: CmdbUser) -> list[dict[str, Any]]:
    """
    Reads every CmdbObject the ring names, ACL-scoped, in one query

    The read is scoped, so an object the requesting user may not read simply does not come back -
    which is what makes it reportable as a restricted node rather than described from a document they
    have no access to

    Args:
        focal_object_id (int): public_id of the CmdbObject the view opened on
        neighbour_ids (list[int]): The objects one cable away from it
        peer_ports (dict[int, dict[str, Any]]): Every port the ring's cables touch
        managers (CablingManagers): The managers to read through
        request_user (CmdbUser): CmdbUser requesting this data

    Returns:
        list[dict[str, Any]]: The objects the user may read
    """
    object_ids: list[int] = sorted(
        {focal_object_id, *neighbour_ids}
        | {port[PortKey.OBJECT_ID.value] for port in peer_ports.values()
           if isinstance(port.get(PortKey.OBJECT_ID.value), int)}
    )

    return managers.objects.find_objects(
        criteria={CmdbObjectKey.PUBLIC_ID.value: {'$in': object_ids}},
        as_dict=True,
        user=request_user,
        permission=AccessControlPermission.READ,
    )


def read_far_port_owners(
        focal_ports: list[dict[str, Any]],
        focal_connections: list[dict[str, Any]],
        managers: CablingManagers) -> dict[int, int]:
    """
    Reads which CmdbObject owns each port the focal object's cables land on

    One indexed read for the whole ring, which is what turns "these cables lead somewhere" into
    "these objects are the neighbours"

    Args:
        focal_ports (list[dict[str, Any]]): The focal object's ports
        focal_connections (list[dict[str, Any]]): The connections of those ports
        managers (CablingManagers): The managers to read through

    Returns:
        dict[int, int]: {far port public_id: owner object public_id}
    """
    far_port_ids: list[int] = sorted({
        far_port_id for _connection, far_port_id
        in collect_cable_hops(focal_connections, set(collect_port_ids(focal_ports)))
    })

    return {
        port[PortKey.PUBLIC_ID.value]: port[PortKey.OBJECT_ID.value]
        for port in managers.ports.get_ports_by_ids(far_port_ids)
        if isinstance(port.get(PortKey.OBJECT_ID.value), int)
    }


def read_cabling_ring(
        focal_object_id: int,
        focal_object: dict[str, Any],
        managers: CablingManagers,
        request_user: CmdbUser,
        with_neighbours: bool = True) -> CablingRing:
    """
    Reads everything one ring of the cabling view needs, in a fixed number of queries

    The reads are ordered by what the next one depends on: the focal ports decide which connections
    to read, those decide which far ports, those decide which objects are neighbours, and those decide
    the second ring of ports whose own connections let a neighbour's row point one step further.
    Every step is one indexed read for the WHOLE ring.

    ``with_neighbours=False`` reads the focal object ALONE - its ports, and enough of the cabling to
    resolve their rows. That is what an expansion needs: the user asked for one object, and pulling in
    everything IT is cabled to would drag a 48-port switch's whole neighbourhood onto the canvas
    behind their back

    Args:
        focal_object_id (int): public_id of the CmdbObject the view opened on
        focal_object (dict[str, Any]): That object, already read for the ACL check
        managers (CablingManagers): The managers to read through
        request_user (CmdbUser): CmdbUser requesting this data
        with_neighbours (bool): Whether the objects one cable away become nodes too

    Returns:
        CablingRing: Everything the response is shaped from
    """
    focal_ports: list[dict[str, Any]] = managers.ports.get_ports_of_object(focal_object_id)
    focal_connections: list[dict[str, Any]] = managers.connections.get_connections_of_ports(
        collect_port_ids(focal_ports),
    )

    neighbour_ids: list[int] = collect_neighbour_ids(
        focal_ports, focal_connections,
        read_far_port_owners(focal_ports, focal_connections, managers),
        focal_object_id,
    ) if with_neighbours else []

    # Every port of every neighbour, and their connections: the first is what a node shows, the second
    # is what lets a neighbour's row name the object one step further out
    neighbour_ports: list[dict[str, Any]] = managers.ports.get_ports_of_objects(neighbour_ids)
    ring_ports: list[dict[str, Any]] = focal_ports + neighbour_ports
    ring_connections: list[dict[str, Any]] = attach_cable_views(
        managers.connections.get_connections_of_ports(collect_port_ids(ring_ports)),
        managers.objects,
        managers.extendable_options,
    )

    peer_ports: dict[int, dict[str, Any]] = load_ring_peer_ports(
        ring_ports, ring_connections, managers,
    )
    readable_objects: list[dict[str, Any]] = load_ring_objects(
        focal_object_id, neighbour_ids, peer_ports, managers, request_user,
    )
    objects_by_id: dict[int, dict[str, Any]] = {
        document[CmdbObjectKey.PUBLIC_ID.value]: document for document in readable_objects
    }

    # The focal object was already read for the ACL check, so it is put back whatever the scoped read
    # returned. An EXPANSION passes nothing here on purpose: whether its object may be read is exactly
    # what the scoped read above answers, and a denied one has to stay absent to become a restricted
    # node rather than an empty one
    if focal_object:
        objects_by_id[focal_object_id] = focal_object

    return CablingRing(
        ports_by_object=group_ports_by_object(ring_ports),
        connections=ring_connections,
        objects_by_id=objects_by_id,
        types_by_id=load_ring_types(objects_by_id, managers),
        neighbour_ids=neighbour_ids,
        peers=PeerEnds(
            ports_by_id=peer_ports,
            summary_lines=managers.objects.get_summary_lines_lookup(
                list(objects_by_id), object_docs=readable_objects,
            ),
            accessible_ids=set(objects_by_id),
        ),
        option_labels=load_port_option_labels(managers.extendable_options),
    )


def load_ring_types(
        objects_by_id: dict[int, dict[str, Any]],
        managers: CablingManagers) -> dict[int, dict[str, Any]]:
    """
    Bulk-fetches the CmdbType of every object in the ring in a single ``$in``

    The type documents rather than the model instances: a node's presentation is built by the CI
    Explorer's own composers, which read the document

    Args:
        objects_by_id (dict[int, dict[str, Any]]): The objects the ring carries
        managers (CablingManagers): The managers to read through

    Returns:
        dict[int, dict[str, Any]]: {public_id: CmdbType document}
    """
    type_ids: set[int] = {
        document[TYPE_ID_KEY] for document in objects_by_id.values()
        if isinstance(document.get(TYPE_ID_KEY), int)
    }

    if not type_ids:
        return {}

    return {
        type_doc[CmdbObjectKey.PUBLIC_ID.value]: type_doc
        for type_doc in managers.types.find(
            criteria={CmdbObjectKey.PUBLIC_ID.value: {'$in': sorted(type_ids)}},
        )
        if isinstance(type_doc.get(CmdbObjectKey.PUBLIC_ID.value), int)
    }


def build_port_expansion(
        port: dict[str, Any],
        connection: dict[str, Any],
        far_port_id: int,
        far_object_id: int,
        ring: CablingRing,
        managers: CablingManagers) -> dict[str, Any]:
    """
    Shapes what following ONE port outwards reveals: a single node and the cable that reached it

    The same envelope the initial ring answers with, carrying one node and one edge - so a client
    merges both responses with one function and never has to tell them apart. ``focal_object_id`` is
    the object the clicked port belongs to: the expansion's origin, not the node it revealed, because
    that is the node the client already has on the canvas to attach the edge to.

    The revealed node carries ALL of its ports, and each of their rows names the object at its own far
    end - which is what makes the next port expandable in turn

    Args:
        port (dict[str, Any]): The port that was followed
        connection (dict[str, Any]): Its cable, with the resolved cable block
        far_port_id (int): public_id of the port at the other end
        far_object_id (int): public_id of the object owning that port
        ring (CablingRing): What was read for the revealed object
        managers (CablingManagers): The managers, for the interface-link resolution

    Returns:
        dict[str, Any]: ``{focal_object_id, nodes, edges}`` with one of each
    """
    owner_by_port: dict[int, int] = {
        port_id: known[PortKey.OBJECT_ID.value]
        for port_id, known in ring.peers.ports_by_id.items()
        if isinstance(known.get(PortKey.OBJECT_ID.value), int)
    }

    edge: dict[str, Any] = {
        CablingEdgeKey.CONNECTION_ID.value: connection.get(PortConnectionKey.PUBLIC_ID.value),
        CablingEdgeKey.FROM_END.value: build_cabling_end(
            port[PortKey.PUBLIC_ID.value], port.get(PortKey.OBJECT_ID.value), {
                port[PortKey.PUBLIC_ID.value]: port,
            },
            {port.get(PortKey.OBJECT_ID.value)},
        ),
        CablingEdgeKey.TO_END.value: build_cabling_end(
            far_port_id, owner_by_port.get(far_port_id, far_object_id), ring.peers.ports_by_id,
            ring.peers.accessible_ids,
        ),
        CablingEdgeKey.CABLE.value: connection.get(CABLE_VIEW_KEY),
    }

    return {
        PortCablingKey.FOCAL_OBJECT_ID.value: port.get(PortKey.OBJECT_ID.value),
        PortCablingKey.NODES.value: [build_cabling_node(far_object_id, ring, managers)],
        PortCablingKey.EDGES.value: [edge],
    }


def empty_expansion(port: dict[str, Any]) -> dict[str, Any]:
    """
    The answer for a port that leads nowhere a graph can draw

    A free port, and a cable whose far end is another port of the same object (Q39), both reveal no
    node. That is an empty answer rather than a refusal: the port exists and the client asked a fair
    question about it

    Args:
        port (dict[str, Any]): The port that was followed

    Returns:
        dict[str, Any]: The envelope, with nothing in it
    """
    return {
        PortCablingKey.FOCAL_OBJECT_ID.value: port.get(PortKey.OBJECT_ID.value),
        PortCablingKey.NODES.value: [],
        PortCablingKey.EDGES.value: [],
    }


def read_port_cable(
        port: dict[str, Any],
        managers: CablingManagers) -> tuple[dict[str, Any], int] | None:
    """
    Reads the cable of one port and the port at its other end

    Args:
        port (dict[str, Any]): The port being followed
        managers (CablingManagers): The managers to read through

    Returns:
        tuple[dict[str, Any], int] | None: The connection with its resolved cable block and the far
            port's public_id, or None when the port carries no cable that leads elsewhere
    """
    port_id: int = port[PortKey.PUBLIC_ID.value]
    hops: list[tuple[dict[str, Any], int]] = collect_cable_hops(
        managers.connections.get_connections_of_ports([port_id]), {port_id},
    )

    if not hops:
        return None

    connection, far_port_id = hops[0]

    return attach_cable_views([connection], managers.objects, managers.extendable_options)[0], far_port_id


def build_cabling_view(
        focal_object_id: int,
        ring: CablingRing,
        managers: CablingManagers) -> dict[str, Any]:
    """
    Shapes one ring into the cabling-view response

    Args:
        focal_object_id (int): public_id of the CmdbObject the view opened on
        ring (CablingRing): Everything the call read
        managers (CablingManagers): The managers, for the interface-link resolution

    Returns:
        dict[str, Any]: ``{focal_object_id, nodes, edges}``
    """
    drawn_ids: list[int] = [focal_object_id, *ring.neighbour_ids]
    nodes: list[dict[str, Any]] = [
        build_cabling_node(object_id, ring, managers) for object_id in drawn_ids
    ]

    owner_by_port: dict[int, int] = {
        port_id: port[PortKey.OBJECT_ID.value]
        for port_id, port in ring.peers.ports_by_id.items()
        if isinstance(port.get(PortKey.OBJECT_ID.value), int)
    }

    return {
        PortCablingKey.FOCAL_OBJECT_ID.value: focal_object_id,
        PortCablingKey.NODES.value: nodes,
        PortCablingKey.EDGES.value: build_cabling_edges(
            ring.connections, owner_by_port, ring.peers.ports_by_id, set(drawn_ids),
            ring.peers.accessible_ids,
        ),
    }
