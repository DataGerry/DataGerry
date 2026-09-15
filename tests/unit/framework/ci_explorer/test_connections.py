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
Unit tests for cmdb.framework.ci_explorer.connections - the CI-level projection of the physical layer

Pure tests: no Mongo, no Flask. The managers are served by a small in-memory fake rather than by
per-call mocks, because what is under test is a *walk* - several levels deep, each level asking a
question that depends on the previous answer. A MagicMock returning one canned list cannot express
"the panel's ports" and "the next panel's ports" as two different answers, and a test that cannot
express that would pass on a walk that never walks.

Every case ruled in notes/PORT_CONNECTIVITY_PLAN.md §6.2 is pinned here:

  - the ordinary chain, ending on a SINGLE port
  - C1 a chain dying inside the panel, C2 a panel face never paired - both emit nothing
  - C3 chained panels collapsing into one edge
  - C4 the focal object being a panel, which makes it transparent
  - Q36 one connection is one edge, Q39 no self-loops
  - the cycle guard and the hop budget, neither of which any index prevents
"""
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from cmdb.framework.ci_explorer.connections import (
    MAX_PHYSICAL_HOPS,
    ChainWalk,
    ConnectionSourceManagers,
    collect_connection_neighbours,
    index_connections_by_port,
    other_endpoint,
    start_walks,
)
from cmdb.models.port_connection_model.port_connection_constants import ConnectionType
from cmdb.models.port_model.port_constants import PortSide
# -------------------------------------------------------------------------------------------------------------------- #

MODULE_PATH: str = 'cmdb.framework.ci_explorer.connections'

# Objects
SERVER_A: int = 100
SWITCH_B: int = 101
PANEL_P: int = 200
PANEL_P2: int = 201

TYPE_SERVER: int = 10
TYPE_PANEL: int = 11


def _port(public_id: int, object_id: int, side: str = PortSide.SINGLE.value) -> dict[str, Any]:
    """Builds a CmdbPort document reduced to what the walk reads."""
    return {
        'public_id': public_id,
        'object_id': object_id,
        'side': side,
        'name': f'port-{public_id}',
    }


def _connection(public_id: int, port_a: int, port_b: int, connection_type: str) -> dict[str, Any]:
    """Builds a CmdbPortConnection document; endpoints are stored sorted, as the model does."""
    return {
        'public_id': public_id,
        'endpoints': sorted([port_a, port_b]),
        'connection_type': connection_type,
    }


def _cable(public_id: int, port_a: int, port_b: int) -> dict[str, Any]:
    """A CABLE connection between two ports of different objects."""
    return _connection(public_id, port_a, port_b, ConnectionType.CABLE.value)


def _internal(public_id: int, port_a: int, port_b: int) -> dict[str, Any]:
    """An INTERNAL connection pairing the two faces of one patch panel."""
    return _connection(public_id, port_a, port_b, ConnectionType.INTERNAL.value)


def _managers(
    ports: list[dict[str, Any]],
    connections: list[dict[str, Any]],
    objects: list[dict[str, Any]] | None = None,
) -> ConnectionSourceManagers:
    """
    Builds a manager bundle backed by an in-memory store

    ``ports.find`` answers the two criteria shapes the walk issues - by public_id and by object_id -
    and ``get_connections_of_ports`` answers by endpoint membership, which is what the real partial
    index serves. Anything else would be a query the module does not make.
    """
    ports_manager, connections_manager = MagicMock(), MagicMock()
    objects_manager, extendable_options_manager = MagicMock(), MagicMock()

    def _find_ports(criteria: dict[str, Any], **_kwargs: Any) -> list[dict[str, Any]]:
        # .get rather than [] throughout: a real Mongo query simply does not match a document that
        # lacks the field, and some of these tests feed exactly such a document in on purpose
        if 'public_id' in criteria:
            wanted = set(criteria['public_id']['$in'])

            return [port for port in ports if port.get('public_id') in wanted]

        wanted = set(criteria['object_id']['$in'])

        return [port for port in ports if port.get('object_id') in wanted]

    def _connections_of_ports(port_ids: list[int]) -> list[dict[str, Any]]:
        wanted = set(port_ids)

        return [
            connection for connection in connections
            if wanted.intersection(connection['endpoints'])
        ]

    def _find_objects(criteria: dict[str, Any], **_kwargs: Any) -> list[dict[str, Any]]:
        wanted = set(criteria['public_id']['$in'])
        found = [obj for obj in (objects or []) if obj.get('public_id') in wanted]

        if 'type_id' in criteria:
            allowed = set(criteria['type_id']['$in'])
            found = [obj for obj in found if obj['type_id'] in allowed]

        return found

    ports_manager.get_ports_of_object.side_effect = lambda object_id: [
        port for port in ports if port.get('object_id') == object_id
    ]
    ports_manager.find.side_effect = _find_ports
    connections_manager.get_connections_of_ports.side_effect = _connections_of_ports
    objects_manager.find.side_effect = _find_objects

    return ConnectionSourceManagers(
        ports=ports_manager,
        connections=connections_manager,
        objects=objects_manager,
        extendable_options=extendable_options_manager,
    )


def _object(public_id: int, type_id: int = TYPE_SERVER) -> dict[str, Any]:
    """A CmdbObject document reduced to what the source reads."""
    return {'public_id': public_id, 'type_id': type_id, 'fields': []}


def _collect(managers: ConnectionSourceManagers, target_id: int = SERVER_A, **overrides: Any):
    """Runs the collector with the cable-view resolution stubbed out (it has its own tests)."""
    options: dict[str, Any] = {
        'types_filter': frozenset(),
        'remaining': 0,
        'item_limit_active': False,
    }
    options.update(overrides)

    with patch(f'{MODULE_PATH}.attach_cable_views', side_effect=lambda hops, *_args: hops):
        return collect_connection_neighbours(target_id=target_id, managers=managers, **options)


class TestTheOrdinaryChain:
    """A server cabled straight to a switch - no panel involved."""

    def test_the_far_side_ci_becomes_one_neighbour(self) -> None:
        """The whole feature in its simplest form."""
        managers = _managers(
            ports=[_port(1, SERVER_A), _port(2, SWITCH_B)],
            connections=[_cable(900, 1, 2)],
            objects=[_object(SWITCH_B)],
        )

        neighbours, objects = _collect(managers)

        assert [neighbour.neighbour_object_id for neighbour in neighbours] == [SWITCH_B]
        assert set(objects) == {SWITCH_B}

    def test_the_path_carries_the_connection_that_was_collapsed(self) -> None:
        """Case C5: the hidden physical path rides on the edge, not behind a second request."""
        managers = _managers(
            ports=[_port(1, SERVER_A), _port(2, SWITCH_B)],
            connections=[_cable(900, 1, 2)],
            objects=[_object(SWITCH_B)],
        )

        neighbours, _objects = _collect(managers)

        assert [hop['public_id'] for hop in neighbours[0].path] == [900]

    def test_an_uncabled_port_starts_nothing(self) -> None:
        """A port with no CABLE is not a path; it is an empty socket."""
        managers = _managers(ports=[_port(1, SERVER_A)], connections=[], objects=[])

        neighbours, objects = _collect(managers)

        assert not neighbours
        assert not objects

    def test_an_object_without_ports_costs_one_read(self) -> None:
        """The overwhelmingly common case - most CIs have no ports at all - must stay cheap."""
        managers = _managers(ports=[], connections=[], objects=[])

        _collect(managers)

        managers.connections.get_connections_of_ports.assert_not_called()


class TestThePanelIsNeverANode:
    """The four collapse cases, which are the whole of §6.2."""

    def test_a_panel_is_walked_through_and_not_drawn(self) -> None:
        """
        Server A --cable-- P.front --internal-- P.rear --cable-- Switch B

        One edge A -- B, and the panel appears nowhere.
        """
        managers = _managers(
            ports=[
                _port(1, SERVER_A),
                _port(10, PANEL_P, PortSide.FRONT.value),
                _port(11, PANEL_P, PortSide.REAR.value),
                _port(2, SWITCH_B),
            ],
            connections=[_cable(900, 1, 10), _internal(901, 10, 11), _cable(902, 11, 2)],
            objects=[_object(SWITCH_B), _object(PANEL_P, TYPE_PANEL)],
        )

        neighbours, objects = _collect(managers)

        assert [neighbour.neighbour_object_id for neighbour in neighbours] == [SWITCH_B]
        assert PANEL_P not in objects

    def test_the_whole_physical_path_is_carried(self) -> None:
        """Three hops collapse into one edge, and all three stay readable on it."""
        managers = _managers(
            ports=[
                _port(1, SERVER_A),
                _port(10, PANEL_P, PortSide.FRONT.value),
                _port(11, PANEL_P, PortSide.REAR.value),
                _port(2, SWITCH_B),
            ],
            connections=[_cable(900, 1, 10), _internal(901, 10, 11), _cable(902, 11, 2)],
            objects=[_object(SWITCH_B)],
        )

        neighbours, _objects = _collect(managers)

        assert [hop['public_id'] for hop in neighbours[0].path] == [900, 901, 902]

    def test_c1_a_chain_dying_inside_the_panel_draws_nothing(self) -> None:
        """
        The ordinary half-patched state: the rear face is paired but was never cabled

        Server A shows nothing at all, which is indistinguishable from an unpatched server. That was
        ruled explicitly (Q31): the graph is a CI graph, and an incomplete patch belongs on the ports
        tab.
        """
        managers = _managers(
            ports=[
                _port(1, SERVER_A),
                _port(10, PANEL_P, PortSide.FRONT.value),
                _port(11, PANEL_P, PortSide.REAR.value),
            ],
            connections=[_cable(900, 1, 10), _internal(901, 10, 11)],
            objects=[_object(PANEL_P, TYPE_PANEL)],
        )

        neighbours, objects = _collect(managers)

        assert not neighbours
        assert not objects

    def test_c2_a_panel_face_that_was_never_paired_draws_nothing(self) -> None:
        """
        The cable lands on a front port with no INTERNAL at all

        The rule is the strong one - never draw a panel - not the weaker "do not draw a panel the
        path passes through". Nothing is drawn, which is only answerable because the port's `side`
        says it is a panel face even though nothing is paired to it.
        """
        managers = _managers(
            ports=[_port(1, SERVER_A), _port(10, PANEL_P, PortSide.FRONT.value)],
            connections=[_cable(900, 1, 10)],
            objects=[_object(PANEL_P, TYPE_PANEL)],
        )

        neighbours, objects = _collect(managers)

        assert not neighbours
        assert not objects

    def test_c3_chained_panels_collapse_into_one_edge(self) -> None:
        """A -- P1 -- P2 -- B: one drawn edge hiding four connections and two CIs."""
        managers = _managers(
            ports=[
                _port(1, SERVER_A),
                _port(10, PANEL_P, PortSide.FRONT.value),
                _port(11, PANEL_P, PortSide.REAR.value),
                _port(20, PANEL_P2, PortSide.FRONT.value),
                _port(21, PANEL_P2, PortSide.REAR.value),
                _port(2, SWITCH_B),
            ],
            connections=[
                _cable(900, 1, 10), _internal(901, 10, 11), _cable(902, 11, 20),
                _internal(903, 20, 21), _cable(904, 21, 2),
            ],
            objects=[_object(SWITCH_B)],
        )

        neighbours, objects = _collect(managers)

        assert [neighbour.neighbour_object_id for neighbour in neighbours] == [SWITCH_B]
        assert [hop['public_id'] for hop in neighbours[0].path] == [900, 901, 902, 903, 904]
        assert PANEL_P not in objects and PANEL_P2 not in objects

    def test_c4_a_focal_panel_is_transparent(self) -> None:
        """
        Opening the panel itself shows every CI its paths reach, from both of its faces

        Chosen over "its immediate cable peers" because the two differ under C3 and a panel can never
        be a node. The asymmetry is accepted: A's graph draws A -- B, the panel's draws P -- A and
        P -- B.
        """
        managers = _managers(
            ports=[
                _port(1, SERVER_A),
                _port(10, PANEL_P, PortSide.FRONT.value),
                _port(11, PANEL_P, PortSide.REAR.value),
                _port(2, SWITCH_B),
            ],
            connections=[_cable(900, 1, 10), _internal(901, 10, 11), _cable(902, 11, 2)],
            objects=[_object(SERVER_A), _object(SWITCH_B)],
        )

        neighbours, objects = _collect(managers, target_id=PANEL_P)

        assert {neighbour.neighbour_object_id for neighbour in neighbours} == {SERVER_A, SWITCH_B}
        assert set(objects) == {SERVER_A, SWITCH_B}

    def test_c4_reaches_past_a_second_panel(self) -> None:
        """The case where transparency and 'immediate cable peers' actually disagree."""
        managers = _managers(
            ports=[
                _port(1, SERVER_A),
                _port(10, PANEL_P, PortSide.FRONT.value),
                _port(11, PANEL_P, PortSide.REAR.value),
                _port(20, PANEL_P2, PortSide.FRONT.value),
                _port(21, PANEL_P2, PortSide.REAR.value),
                _port(2, SWITCH_B),
            ],
            connections=[
                _cable(900, 1, 10), _internal(901, 10, 11), _cable(902, 11, 20),
                _internal(903, 20, 21), _cable(904, 21, 2),
            ],
            objects=[_object(SERVER_A), _object(SWITCH_B), _object(PANEL_P2, TYPE_PANEL)],
        )

        neighbours, _objects = _collect(managers, target_id=PANEL_P)

        # The immediate cable peer of P's rear face is P2, which is never drawn - B is
        assert {neighbour.neighbour_object_id for neighbour in neighbours} == {SERVER_A, SWITCH_B}


class TestTheEdgeRules:
    """Q36 and Q39, plus the type filter."""

    def test_q36_two_cables_between_the_same_pair_are_two_neighbours(self) -> None:
        """Redundant links and LAGs are ordinary; each connection keeps its own path."""
        managers = _managers(
            ports=[_port(1, SERVER_A), _port(3, SERVER_A), _port(2, SWITCH_B), _port(4, SWITCH_B)],
            connections=[_cable(900, 1, 2), _cable(901, 3, 4)],
            objects=[_object(SWITCH_B)],
        )

        neighbours, objects = _collect(managers)

        assert [neighbour.neighbour_object_id for neighbour in neighbours] == [SWITCH_B, SWITCH_B]
        assert [hop['public_id'] for neighbour in neighbours for hop in neighbour.path] == [900, 901]
        assert set(objects) == {SWITCH_B}

    def test_q39_a_cable_between_two_ports_of_one_object_is_skipped(self) -> None:
        """A real cable, but not an edge anyone can draw."""
        managers = _managers(
            ports=[_port(1, SERVER_A), _port(3, SERVER_A)],
            connections=[_cable(900, 1, 3)],
            objects=[_object(SERVER_A)],
        )

        neighbours, objects = _collect(managers)

        assert not neighbours
        assert not objects

    def test_the_types_filter_applies_to_the_far_side_ci(self) -> None:
        """Q38 - the same rule the relation source follows for its neighbours."""
        managers = _managers(
            ports=[_port(1, SERVER_A), _port(2, SWITCH_B)],
            connections=[_cable(900, 1, 2)],
            objects=[_object(SWITCH_B, TYPE_SERVER)],
        )

        neighbours, objects = _collect(managers, types_filter=frozenset({TYPE_PANEL}))

        assert not neighbours
        assert not objects

    def test_the_item_limit_caps_the_neighbours(self) -> None:
        """The source spends what the earlier branches left, like locations and IPAM do."""
        managers = _managers(
            ports=[_port(1, SERVER_A), _port(3, SERVER_A), _port(2, SWITCH_B), _port(4, SWITCH_B)],
            connections=[_cable(900, 1, 2), _cable(901, 3, 4)],
            objects=[_object(SWITCH_B)],
        )

        neighbours, _objects = _collect(managers, remaining=1, item_limit_active=True)

        assert len(neighbours) == 1

    def test_an_exhausted_budget_reads_nothing_at_all(self) -> None:
        """No slots left means the source must not even look."""
        managers = _managers(
            ports=[_port(1, SERVER_A), _port(2, SWITCH_B)],
            connections=[_cable(900, 1, 2)],
            objects=[_object(SWITCH_B)],
        )

        neighbours, _objects = _collect(managers, remaining=0, item_limit_active=True)

        assert not neighbours
        managers.ports.get_ports_of_object.assert_not_called()


class TestTheWalkTerminates:
    """Neither guard is enforced by an index, so both are the module's own responsibility."""

    def test_a_chain_that_loops_back_is_abandoned(self) -> None:
        """
        Two panels cabled to each other on both faces close the chain into a ring

        Nothing in the data model forbids it: the partial unique indexes allow one CABLE and one
        INTERNAL per port, which is exactly what a ring uses.
        """
        managers = _managers(
            ports=[
                _port(1, SERVER_A),
                _port(10, PANEL_P, PortSide.FRONT.value),
                _port(11, PANEL_P, PortSide.REAR.value),
                _port(20, PANEL_P2, PortSide.FRONT.value),
                _port(21, PANEL_P2, PortSide.REAR.value),
            ],
            connections=[
                _cable(900, 1, 10), _internal(901, 10, 11), _cable(902, 11, 20),
                _internal(903, 20, 21), _cable(904, 21, 10),
            ],
            objects=[],
        )

        neighbours, objects = _collect(managers)

        assert not neighbours
        assert not objects

    def test_the_hop_budget_is_a_module_constant_not_a_request_parameter(self) -> None:
        """C6/Q33 - there is no max_depth on the wire; the budget only protects the database."""
        assert MAX_PHYSICAL_HOPS >= 2


class TestThePureHelpers:
    """The three pieces the walk is assembled from."""

    def test_the_far_endpoint_is_found_by_membership(self) -> None:
        """endpoints is stored sorted, so a fixed position means nothing."""
        connection = _cable(900, 7, 3)

        assert other_endpoint(connection, 3) == 7
        assert other_endpoint(connection, 7) == 3

    def test_a_self_connection_leads_nowhere(self) -> None:
        """Both endpoints equal leaves no 'other' side to walk to."""
        assert other_endpoint(_cable(900, 5, 5), 5) is None

    def test_connections_are_indexed_per_port_and_type(self) -> None:
        """A port has at most one of each, which is what makes the index a dict rather than a list."""
        indexed = index_connections_by_port([_cable(900, 1, 2), _internal(901, 2, 3)])

        assert indexed[(1, ConnectionType.CABLE.value)]['public_id'] == 900
        assert indexed[(2, ConnectionType.CABLE.value)]['public_id'] == 900
        assert indexed[(2, ConnectionType.INTERNAL.value)]['public_id'] == 901

    def test_a_walk_starts_on_the_far_side_of_its_cable(self) -> None:
        """The origin port is already visited, so a chain cannot come back through it."""
        walks: list[ChainWalk] = start_walks(
            [_port(1, SERVER_A)], index_connections_by_port([_cable(900, 1, 2)]),
        )

        assert len(walks) == 1
        assert walks[0].current_port_id == 2
        assert walks[0].visited_port_ids == {1, 2}

    @pytest.mark.parametrize('side, is_panel', [
        (PortSide.SINGLE.value, False),
        (PortSide.FRONT.value, True),
        (PortSide.REAR.value, True),
    ])
    def test_panel_ness_comes_from_the_side(self, side: str, is_panel: bool) -> None:
        """The one stored signal the collapse rule can read - see the module docstring."""
        assert PortSide.is_panel_side(side) is is_panel


class TestADanglingReference:
    """A connection naming a port that is gone must degrade, not crash."""

    def test_a_missing_port_abandons_only_its_own_path(self) -> None:
        """Half a graph is more useful than none, which is the rule the whole package follows."""
        managers = _managers(
            ports=[_port(1, SERVER_A), _port(3, SERVER_A), _port(4, SWITCH_B)],
            connections=[_cable(900, 1, 99), _cable(901, 3, 4)],
            objects=[_object(SWITCH_B)],
        )

        neighbours, _objects = _collect(managers)

        assert [neighbour.neighbour_object_id for neighbour in neighbours] == [SWITCH_B]


class TestTheDefensivePaths:
    """
    Malformed documents and the hop budget

    None of these are reachable through the write routes - the schemas and the validators refuse a
    self-connection and the model stamps every port with a public_id. They are reachable through a
    hand-edited database, a partially applied migration, or a future writer, and the walk has to
    degrade rather than raise on any of them.
    """

    def test_a_port_without_a_public_id_starts_no_walk(self) -> None:
        """It cannot be an endpoint of anything, so there is nothing to follow."""
        managers = _managers(
            ports=[{'object_id': SERVER_A, 'side': PortSide.SINGLE.value}],
            connections=[],
            objects=[],
        )

        neighbours, _objects = _collect(managers)

        assert not neighbours

    def test_a_self_cable_on_the_focal_port_starts_no_walk(self) -> None:
        """
        A cable whose two endpoints are the same port

        The validator refuses it on write and the multikey index cannot (both entries dedupe to one
        key inside a single document), so it is the one cardinality case stored data could carry.
        """
        managers = _managers(
            ports=[_port(1, SERVER_A)],
            connections=[_cable(900, 1, 1)],
            objects=[],
        )

        neighbours, _objects = _collect(managers)

        assert not neighbours

    def test_a_self_internal_inside_a_panel_ends_the_walk(self) -> None:
        """The same shape one hop further in, where it would pair a panel face with itself."""
        managers = _managers(
            ports=[_port(1, SERVER_A), _port(10, PANEL_P, PortSide.FRONT.value)],
            connections=[_cable(900, 1, 10), _internal(901, 10, 10)],
            objects=[],
        )

        neighbours, _objects = _collect(managers)

        assert not neighbours

    def test_a_self_cable_beyond_the_panel_ends_the_walk(self) -> None:
        """And once more on the cable leaving the panel's rear face."""
        managers = _managers(
            ports=[
                _port(1, SERVER_A),
                _port(10, PANEL_P, PortSide.FRONT.value),
                _port(11, PANEL_P, PortSide.REAR.value),
            ],
            connections=[_cable(900, 1, 10), _internal(901, 10, 11), _cable(902, 11, 11)],
            objects=[],
        )

        neighbours, _objects = _collect(managers)

        assert not neighbours

    def test_a_port_without_an_owner_object_resolves_to_nothing(self) -> None:
        """The chain ends on a SINGLE port that names no object, so there is no CI to draw."""
        managers = _managers(
            ports=[_port(1, SERVER_A), {'public_id': 2, 'side': PortSide.SINGLE.value}],
            connections=[_cable(900, 1, 2)],
            objects=[],
        )

        neighbours, _objects = _collect(managers)

        assert not neighbours

    def test_a_malformed_endpoint_is_not_indexed(self) -> None:
        """A non-integer endpoint or a missing connection_type cannot key the index."""
        indexed = index_connections_by_port([
            {'public_id': 900, 'endpoints': ['not-an-id', 2], 'connection_type': 'CABLE'},
            {'public_id': 901, 'endpoints': [3, 4], 'connection_type': None},
        ])

        assert indexed == {(2, ConnectionType.CABLE.value): {
            'public_id': 900, 'endpoints': ['not-an-id', 2], 'connection_type': 'CABLE',
        }}

    def test_a_chain_longer_than_the_hop_budget_is_abandoned(self) -> None:
        """
        The second guard, for a chain that is long rather than circular

        The visited-port set cannot stop this one: every port is new. Built here as a straight line
        of panels, which is what a badly modelled cabling import would produce.
        """
        panel_count: int = MAX_PHYSICAL_HOPS  # two physical hops each, so comfortably over budget
        ports: list[dict[str, Any]] = [_port(1, SERVER_A)]
        connections: list[dict[str, Any]] = []
        previous_port: int = 1

        for index in range(panel_count):
            front, rear = 100 + index * 2, 101 + index * 2
            panel_id = 1000 + index
            ports.append(_port(front, panel_id, PortSide.FRONT.value))
            ports.append(_port(rear, panel_id, PortSide.REAR.value))
            connections.append(_cable(2000 + index, previous_port, front))
            connections.append(_internal(3000 + index, front, rear))
            previous_port = rear

        managers = _managers(ports=ports, connections=connections, objects=[])

        neighbours, _objects = _collect(managers)

        assert not neighbours
        assert managers.ports.find.call_count <= MAX_PHYSICAL_HOPS
