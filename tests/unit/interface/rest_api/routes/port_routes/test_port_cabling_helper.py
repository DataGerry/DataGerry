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
Unit tests for the cabling view's shaping

Pure: no Mongo, no Flask. Everything one call reads is already in the ``CablingRing`` these tests
build by hand, so what is pinned here is the shaping - which objects become nodes, which cables become
edges, and what a node carries when the requesting user may not read it.

The per-port rows themselves are the ports overview's and have their own tests; what this file adds is
the ring around them.
"""
from typing import Any
from unittest.mock import MagicMock

import pytest

from cmdb.framework.port.name_syntax_constants import PortDeviceKind
from cmdb.models.port_connection_model.port_connection_constants import (
    CABLE_VIEW_KEY,
    ConnectionType,
    PortConnectionKey,
)
from cmdb.models.port_model.port_constants import PortKey, PortSide
from cmdb.interface.rest_api.routes.port_routes.port_cabling_constants import (
    CablingEdgeKey,
    CablingEndKey,
    CablingNodeKey,
    PortCablingKey,
)
from cmdb.interface.rest_api.routes.port_routes.port_cabling_helper import (
    CablingRing,
    build_cabling_edges,
    build_cabling_view,
    build_port_expansion,
    collect_neighbour_ids,
    empty_expansion,
    group_ports_by_object,
    read_port_cable,
)
from cmdb.interface.rest_api.routes.port_routes.port_overview_helper import PeerEnds
# -------------------------------------------------------------------------------------------------------------------- #

WEB: int = 100
PANEL: int = 200
SWITCH: int = 300
DENIED: int = 400

TYPE_ID: int = 10


def _port(public_id: int, object_id: int, name: str, side: PortSide = PortSide.SINGLE) -> dict[str, Any]:
    """A stored port reduced to what the shaping reads."""
    return {
        PortKey.PUBLIC_ID.value: public_id,
        PortKey.OBJECT_ID.value: object_id,
        PortKey.SIDE.value: side.value,
        PortKey.NAME.value: name,
        PortKey.PORT_NUMBER.value: None,
    }


def _cable(public_id: int, port_a: int, port_b: int, name: str = 'CAT6-001') -> dict[str, Any]:
    """A CABLE connection carrying its resolved cable block."""
    return {
        PortConnectionKey.PUBLIC_ID.value: public_id,
        PortConnectionKey.ENDPOINTS.value: sorted([port_a, port_b]),
        PortConnectionKey.CONNECTION_TYPE.value: ConnectionType.CABLE.value,
        CABLE_VIEW_KEY: {'name': name},
    }


def _internal(public_id: int, port_a: int, port_b: int) -> dict[str, Any]:
    """An INTERNAL pairing, which joins two ports of one object."""
    return {
        PortConnectionKey.PUBLIC_ID.value: public_id,
        PortConnectionKey.ENDPOINTS.value: sorted([port_a, port_b]),
        PortConnectionKey.CONNECTION_TYPE.value: ConnectionType.INTERNAL.value,
    }


def _object(public_id: int) -> dict[str, Any]:
    """A CmdbObject reduced to what a node reads."""
    return {'public_id': public_id, 'type_id': TYPE_ID, 'fields': []}


def _ring(**overrides: Any) -> CablingRing:
    """The mockup's first ring: WEB-01 -cable- PP-01(front/rear) -cable- SW-01."""
    ports = [
        _port(1, WEB, 'Gi0/1'), _port(2, WEB, 'Gi0/2'),
        _port(3, PANEL, 'Front 12', PortSide.FRONT), _port(4, PANEL, 'Rear 12', PortSide.REAR),
        _port(5, SWITCH, 'Gi1/0/12'),
    ]
    connections = [_cable(101, 1, 3), _internal(102, 3, 4), _cable(103, 4, 5)]
    ring = CablingRing(
        ports_by_object=group_ports_by_object(ports),
        connections=connections,
        objects_by_id={WEB: _object(WEB), PANEL: _object(PANEL)},
        types_by_id={TYPE_ID: {'public_id': TYPE_ID, 'label': 'Device', 'render_meta': {}}},
        neighbour_ids=[PANEL],
        peers=PeerEnds(
            ports_by_id={port[PortKey.PUBLIC_ID.value]: port for port in ports},
            summary_lines={WEB: 'WEB-01', PANEL: 'PP-01'},
            accessible_ids={WEB, PANEL},
        ),
    )

    for key, value in overrides.items():
        setattr(ring, key, value)

    return ring


def _view(ring: CablingRing, focal: int = WEB) -> dict[str, Any]:
    """Shapes a ring, with the interface-link resolution stubbed out (it has its own tests)."""
    managers = MagicMock()
    managers.interface_links.get_links_of_ports.return_value = []

    return build_cabling_view(focal, ring, managers)


def _node(view: dict[str, Any], object_id: int) -> dict[str, Any]:
    """One node of a shaped view."""
    return next(
        node for node in view[PortCablingKey.NODES.value]
        if node[CablingNodeKey.OBJECT_ID.value] == object_id
    )


# -------------------------------------------------------------------------------------------------------------------- #
#                                                    what a ring holds                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
def test_ports_are_grouped_by_their_owner() -> None:
    """A node shows its own ports, so the read is grouped once rather than filtered per node"""
    grouped = group_ports_by_object([_port(1, WEB, 'a'), _port(2, PANEL, 'b'), _port(3, WEB, 'c')])

    assert sorted(grouped) == [WEB, PANEL]
    assert [port[PortKey.PUBLIC_ID.value] for port in grouped[WEB]] == [1, 3]


def test_a_port_without_an_owner_is_not_grouped() -> None:
    """`object_id` is server-owned, so a port without one is a broken document"""
    assert group_ports_by_object([{PortKey.PUBLIC_ID.value: 1}]) == {}


def test_the_neighbours_are_the_objects_one_cable_away() -> None:
    """One ring: what a cable of the focal object reaches, and nothing further"""
    focal_ports = [_port(1, WEB, 'Gi0/1')]
    neighbours = collect_neighbour_ids(
        focal_ports, [_cable(101, 1, 3)], {3: PANEL}, WEB,
    )

    assert neighbours == [PANEL]


def test_a_cable_back_onto_the_focal_object_reaches_no_neighbour() -> None:
    """Two ports of one object cabled together is a real cable, but not a second node"""
    focal_ports = [_port(1, WEB, 'Gi0/1'), _port(2, WEB, 'Gi0/2')]

    assert not collect_neighbour_ids(focal_ports, [_cable(101, 1, 2)], {2: WEB}, WEB)


def test_each_neighbour_appears_once() -> None:
    """Two cables into the same object draw two edges but one node"""
    focal_ports = [_port(1, WEB, 'Gi0/1'), _port(2, WEB, 'Gi0/2')]
    connections = [_cable(101, 1, 3), _cable(102, 2, 4)]

    assert collect_neighbour_ids(focal_ports, connections, {3: PANEL, 4: PANEL}, WEB) == [PANEL]


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       the nodes                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
def test_the_focal_object_and_its_neighbours_are_the_nodes() -> None:
    """The initial state of the view: the object it opened on, plus one ring"""
    view = _view(_ring())

    assert view[PortCablingKey.FOCAL_OBJECT_ID.value] == WEB
    assert [node[CablingNodeKey.OBJECT_ID.value] for node in view[PortCablingKey.NODES.value]] == [
        WEB, PANEL,
    ]


def test_every_node_carries_all_of_its_ports() -> None:
    """Including the free ones - a node shows a free port next to a cabled one"""
    view = _view(_ring())

    assert _node(view, WEB)[CablingNodeKey.PORT_COUNT.value] == 2
    assert len(_node(view, WEB)[CablingNodeKey.ROWS.value]) == 2


def test_the_port_count_counts_ports_not_rows() -> None:
    """A panel's row is a front/rear PAIR, so the badge and the row count differ by two"""
    panel = _node(_view(_ring()), PANEL)

    assert panel[CablingNodeKey.PORT_COUNT.value] == 2
    assert len(panel[CablingNodeKey.ROWS.value]) == 1


def test_a_panel_node_keeps_its_pair_shape() -> None:
    """The ports overview's PATCH_PANEL rows, unchanged - which is what the mockup draws"""
    panel = _node(_view(_ring()), PANEL)

    assert panel[CablingNodeKey.DEVICE_KIND.value] == PortDeviceKind.PATCH_PANEL.value
    assert set(panel[CablingNodeKey.ROWS.value][0]) == {'front', 'rear', 'paired'}


def test_a_neighbour_the_user_may_not_read_is_a_restricted_node() -> None:
    """The cable that reaches it stays visible; what sits at the far end does not"""
    ring = _ring(neighbour_ids=[PANEL, DENIED])

    denied = _node(_view(ring), DENIED)

    assert denied[CablingNodeKey.RESTRICTED.value] is True
    assert CablingNodeKey.ROWS.value not in denied


def test_an_object_with_no_ports_is_still_its_own_node() -> None:
    """Opening the view on an uncabled object answers one node and no edges"""
    ring = CablingRing(objects_by_id={WEB: _object(WEB)},
                       types_by_id={TYPE_ID: {'public_id': TYPE_ID}})

    view = _view(ring)

    assert len(view[PortCablingKey.NODES.value]) == 1
    assert view[PortCablingKey.EDGES.value] == []


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       the edges                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
def test_one_cable_is_one_edge_between_two_ports() -> None:
    """Named by the ports it joins, not by the nodes - which is what the canvas draws between"""
    edges = build_cabling_edges(
        [_cable(101, 1, 3)], {1: WEB, 3: PANEL},
        {1: _port(1, WEB, 'Gi0/1'), 3: _port(3, PANEL, 'Front 12', PortSide.FRONT)},
        {WEB, PANEL}, {WEB, PANEL},
    )

    assert len(edges) == 1
    assert edges[0][CablingEdgeKey.FROM_END.value][CablingEndKey.PORT_NAME.value] == 'Gi0/1'
    assert edges[0][CablingEdgeKey.TO_END.value][CablingEndKey.SIDE.value] == PortSide.FRONT.value
    assert edges[0][CablingEdgeKey.CABLE.value] == {'name': 'CAT6-001'}


def test_an_internal_pairing_is_not_an_edge() -> None:
    """It joins two ports of one object and is drawn inside the node"""
    edges = build_cabling_edges(
        [_internal(102, 3, 4)], {3: PANEL, 4: PANEL},
        {3: _port(3, PANEL, 'Front 12'), 4: _port(4, PANEL, 'Rear 12')}, {PANEL}, {PANEL},
    )

    assert not edges


def test_a_cable_is_emitted_once() -> None:
    """Both of its ports are in the ring, and the endpoints are stored sorted"""
    connections = [_cable(101, 1, 3), _cable(101, 1, 3)]

    edges = build_cabling_edges(
        connections, {1: WEB, 3: PANEL},
        {1: _port(1, WEB, 'a'), 3: _port(3, PANEL, 'b')}, {WEB, PANEL}, {WEB, PANEL},
    )

    assert len(edges) == 1


def test_a_cable_leaving_the_ring_is_not_an_edge() -> None:
    """Its far object is not a node here, so the edge would point at nothing"""
    edges = build_cabling_edges(
        [_cable(103, 4, 5)], {4: PANEL, 5: SWITCH},
        {4: _port(4, PANEL, 'Rear 12'), 5: _port(5, SWITCH, 'Gi1/0/12')}, {WEB, PANEL}, {WEB, PANEL},
    )

    assert not edges


@pytest.mark.parametrize('endpoints', [[1], [1, 2, 3], []], ids=repr)
def test_a_connection_naming_the_wrong_number_of_ports_is_skipped(endpoints: list[int]) -> None:
    """`endpoints` holds exactly two, which only the write path enforces"""
    connection = {
        PortConnectionKey.PUBLIC_ID.value: 101,
        PortConnectionKey.ENDPOINTS.value: endpoints,
        PortConnectionKey.CONNECTION_TYPE.value: ConnectionType.CABLE.value,
    }

    assert not build_cabling_edges([connection], {1: WEB}, {}, {WEB}, {WEB})


def test_the_view_carries_the_edges_of_its_ring() -> None:
    """The cable into the panel, but not the one leaving it - that one belongs to the next ring"""
    view = _view(_ring())

    assert [edge[CablingEdgeKey.CONNECTION_ID.value] for edge in view[PortCablingKey.EDGES.value]] == [101]


# -------------------------------------------------------------------------------------------------------------------- #
#                                             following ONE port outwards                                              #
# -------------------------------------------------------------------------------------------------------------------- #
def _expansion_ring() -> CablingRing:
    """What is read for an expansion: the revealed object ALONE, with no ring of its own."""
    revealed_ports = [_port(5, SWITCH, 'Gi1/0/12'), _port(6, SWITCH, 'Gi1/0/24')]

    return CablingRing(
        ports_by_object=group_ports_by_object(revealed_ports),
        connections=[_cable(103, 4, 5)],
        objects_by_id={SWITCH: _object(SWITCH)},
        types_by_id={TYPE_ID: {'public_id': TYPE_ID, 'label': 'Device', 'render_meta': {}}},
        neighbour_ids=[],
        peers=PeerEnds(
            ports_by_id={port[PortKey.PUBLIC_ID.value]: port for port in revealed_ports},
            summary_lines={SWITCH: 'SW-01'},
            accessible_ids={SWITCH},
        ),
    )


def _expansion(ring: CablingRing | None = None) -> dict[str, Any]:
    """Follows PP-01's Rear 12, which the mockup's user clicks to reach SW-01."""
    managers = MagicMock()
    managers.interface_links.get_links_of_ports.return_value = []

    return build_port_expansion(
        _port(4, PANEL, 'Rear 12', PortSide.REAR), _cable(103, 4, 5, 'CAT6-003'),
        5, SWITCH, ring or _expansion_ring(), managers,
    )


def test_following_a_port_reveals_exactly_one_node() -> None:
    """Which is the whole reason this is a route of its own - the object route answers a ring"""
    view = _expansion()

    assert [node[CablingNodeKey.OBJECT_ID.value] for node in view[PortCablingKey.NODES.value]] == [SWITCH]


def test_the_expansion_is_the_same_envelope_as_the_initial_ring() -> None:
    """So a client merges both answers with one function and never tells them apart"""
    assert sorted(_expansion()) == sorted(_view(_ring()))


def test_the_focal_id_is_where_the_expansion_started() -> None:
    """The node already on the canvas, which the new edge attaches to - not the revealed one"""
    assert _expansion()[PortCablingKey.FOCAL_OBJECT_ID.value] == PANEL


def test_the_revealed_node_carries_all_of_its_ports() -> None:
    """Including the ones the cable did not arrive on, so it can be expanded from in turn"""
    node = _expansion()[PortCablingKey.NODES.value][0]

    assert node[CablingNodeKey.PORT_COUNT.value] == 2
    assert len(node[CablingNodeKey.ROWS.value]) == 2


def test_the_expansion_carries_the_one_cable_that_was_followed() -> None:
    """One node, one edge - labelled by the resolved cable block"""
    view = _expansion()
    edge = view[PortCablingKey.EDGES.value][0]

    assert len(view[PortCablingKey.EDGES.value]) == 1
    assert edge[CablingEdgeKey.CONNECTION_ID.value] == 103
    assert edge[CablingEdgeKey.CABLE.value] == {'name': 'CAT6-003'}


def test_both_ends_of_the_edge_name_their_port_and_owner() -> None:
    """The mockup draws the line between two port rows, not between two node boxes"""
    edge = _expansion()[PortCablingKey.EDGES.value][0]

    assert edge[CablingEdgeKey.FROM_END.value] == {
        CablingEndKey.OBJECT_ID.value: PANEL,
        CablingEndKey.PORT_ID.value: 4,
        CablingEndKey.PORT_NAME.value: 'Rear 12',
        CablingEndKey.SIDE.value: PortSide.REAR.value,
    }
    assert edge[CablingEdgeKey.TO_END.value][CablingEndKey.PORT_ID.value] == 5
    assert edge[CablingEdgeKey.TO_END.value][CablingEndKey.OBJECT_ID.value] == SWITCH


def test_a_revealed_object_the_user_may_not_read_is_restricted() -> None:
    """The cable is still drawn - what sits at its far end is not described"""
    ring = _expansion_ring()
    ring.objects_by_id = {}
    ring.peers.accessible_ids = set()

    view = build_port_expansion(
        _port(4, PANEL, 'Rear 12', PortSide.REAR), _cable(103, 4, 5), 5, DENIED, ring, MagicMock(),
    )
    node = view[PortCablingKey.NODES.value][0]

    assert node == {CablingNodeKey.OBJECT_ID.value: DENIED, CablingNodeKey.RESTRICTED.value: True}
    assert len(view[PortCablingKey.EDGES.value]) == 1


def test_an_empty_expansion_is_the_envelope_with_nothing_in_it() -> None:
    """A free port leads nowhere a graph can draw, which is an answer rather than a refusal"""
    view = empty_expansion(_port(2, WEB, 'Gi0/2'))

    assert view == {
        PortCablingKey.FOCAL_OBJECT_ID.value: WEB,
        PortCablingKey.NODES.value: [],
        PortCablingKey.EDGES.value: [],
    }


# -------------------------------------------------------------------------------------------------------------------- #
#                                            reading the cable of one port                                             #
# -------------------------------------------------------------------------------------------------------------------- #
def _read(connections: list[dict[str, Any]]) -> Any:
    """Reads the cable of PP-01's Rear 12 out of whatever its ports carry."""
    managers = MagicMock()
    managers.connections.get_connections_of_ports.return_value = connections

    return read_port_cable(_port(4, PANEL, 'Rear 12', PortSide.REAR), managers)


def test_the_cable_of_a_port_is_read_with_its_far_end() -> None:
    """Both halves of the question at once, since neither is answerable without the other"""
    connection, far_port_id = _read([_cable(103, 4, 5)])

    assert connection[PortConnectionKey.PUBLIC_ID.value] == 103
    assert far_port_id == 5


def test_a_free_port_carries_no_cable() -> None:
    """None rather than an empty pair, so the caller answers an empty expansion"""
    assert _read([]) is None


def test_an_internal_pairing_is_not_a_cable() -> None:
    """It joins two ports of ONE object, so following it reveals nothing to draw"""
    assert _read([_internal(102, 3, 4)]) is None


def test_an_edge_end_on_an_unreadable_object_loses_its_port_name() -> None:
    """`GET /ports/<id>` answers 403 for that port, so the graph may not hand its name out either"""
    ports = {1: _port(1, WEB, 'Gi0/1'), 9: _port(9, DENIED, 'eth0')}
    edge = build_cabling_edges(
        [_cable(101, 1, 9)], {1: WEB, 9: DENIED}, ports, {WEB, DENIED}, {WEB},
    )[0]

    assert edge[CablingEdgeKey.FROM_END.value][CablingEndKey.PORT_NAME.value] == 'Gi0/1'
    assert edge[CablingEdgeKey.TO_END.value] == {
        CablingEndKey.OBJECT_ID.value: DENIED,
        CablingEndKey.PORT_ID.value: 9,
        CablingEndKey.PORT_NAME.value: None,
        CablingEndKey.SIDE.value: None,
    }


def test_the_expansion_masks_the_far_end_the_same_way() -> None:
    """Both halves of the view answer one rule, or the graph leaks through whichever is cheaper"""
    ring = _expansion_ring()
    ring.objects_by_id = {}
    ring.peers.accessible_ids = set()

    edge = build_port_expansion(
        _port(4, PANEL, 'Rear 12', PortSide.REAR), _cable(103, 4, 5), 5, DENIED, ring, MagicMock(),
    )[PortCablingKey.EDGES.value][0]

    assert edge[CablingEdgeKey.FROM_END.value][CablingEndKey.PORT_NAME.value] == 'Rear 12'
    assert edge[CablingEdgeKey.TO_END.value][CablingEndKey.PORT_NAME.value] is None
