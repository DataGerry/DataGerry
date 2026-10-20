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
Unit tests for cmdb.framework.ci_explorer.connections - the physical layer as CI edges

Pure tests: no Mongo, no Flask. The managers are served by a small in-memory fake rather than by
per-call mocks, because the source asks three questions in sequence - the focal object's ports, their
connections, and the owners of the ports at the far ends - and each answer decides the next.

**Every object a cable reaches is a node, a patch panel included.** What is pinned here:

  - one cable is one edge, to the owner of the port at the other end
  - a patch panel is an ordinary neighbour: expanding a switch shows the panel, expanding the panel
    shows both switches
  - an INTERNAL pairing draws nothing - it joins two ports of one object
  - a half-patched or never-paired face still draws its cable, because the cable is real
  - Q36 one connection is one edge, Q39 no self-loops
"""
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from cmdb.framework.port.cable_hops import collect_cable_hops, other_endpoint
from cmdb.framework.ci_explorer.connections import (
    ConnectionSourceManagers,
    collect_connection_neighbours,
    index_ports_by_id,
    load_far_port_owners,
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
    """Builds a CmdbPort document reduced to what the source reads."""
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
    """A CABLE connection between two ports."""
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

    ``get_ports_of_object`` and ``get_ports_by_ids`` answer the two port reads the source makes, and
    ``get_connections_of_ports`` answers by endpoint membership, which is what the real partial index
    serves. Anything else would be a query the module does not make.
    """
    ports_manager, connections_manager = MagicMock(), MagicMock()
    objects_manager, extendable_options_manager = MagicMock(), MagicMock()

    def _ports_by_ids(port_ids: list[int]) -> list[dict[str, Any]]:
        # .get rather than [] throughout: a real Mongo query simply does not match a document that
        # lacks the field, and some of these tests feed exactly such a document in on purpose
        wanted = set(port_ids)

        return [port for port in ports if port.get('public_id') in wanted]

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
    ports_manager.get_ports_by_ids.side_effect = _ports_by_ids
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


def _neighbour_ids(neighbours) -> list[int]:
    """The objects the collected edges point at."""
    return sorted(neighbour.neighbour_object_id for neighbour in neighbours)


# -------------------------------------------------------------------------------------------------------------------- #
#                                            A DIRECT CABLE BETWEEN TWO CIs                                            #
# -------------------------------------------------------------------------------------------------------------------- #
class TestADirectCable:
    """The ordinary case: two devices cabled to each other."""

    def test_the_far_side_ci_becomes_one_neighbour(self) -> None:
        """One cable, one edge, to the owner of the port at the other end"""
        managers = _managers(
            ports=[_port(1, SERVER_A), _port(2, SWITCH_B)],
            connections=[_cable(10, 1, 2)],
            objects=[_object(SWITCH_B)],
        )

        neighbours, objects = _collect(managers)

        assert _neighbour_ids(neighbours) == [SWITCH_B]
        assert set(objects) == {SWITCH_B}

    def test_the_path_carries_the_cable(self) -> None:
        """One entry, because an edge is exactly one cable - it is what names it on the wire"""
        managers = _managers(
            ports=[_port(1, SERVER_A), _port(2, SWITCH_B)],
            connections=[_cable(10, 1, 2)],
            objects=[_object(SWITCH_B)],
        )

        neighbours, _objects = _collect(managers)

        assert [hop['public_id'] for hop in neighbours[0].path] == [10]

    def test_an_uncabled_port_reaches_nothing(self) -> None:
        """A port with no connection at all"""
        managers = _managers(ports=[_port(1, SERVER_A)], connections=[], objects=[])

        assert _collect(managers) == ([], {})

    def test_an_object_without_ports_costs_one_read(self) -> None:
        """The common case on every object view that does not use ports"""
        managers = _managers(ports=[], connections=[], objects=[])

        assert _collect(managers) == ([], {})
        managers.connections.get_connections_of_ports.assert_not_called()


# -------------------------------------------------------------------------------------------------------------------- #
#                                               A PANEL IS AN ORDINARY NODE                                            #
# -------------------------------------------------------------------------------------------------------------------- #
class TestAPanelIsANode:
    """A patch panel is a CmdbObject, so the graph draws it like any other."""

    @staticmethod
    def _patched_through() -> ConnectionSourceManagers:
        """A --cable-- P.F01 --internal-- P.R01 --cable-- B."""
        return _managers(
            ports=[
                _port(1, SERVER_A),
                _port(2, PANEL_P, PortSide.FRONT.value),
                _port(3, PANEL_P, PortSide.REAR.value),
                _port(4, SWITCH_B),
            ],
            connections=[_cable(10, 1, 2), _internal(11, 2, 3), _cable(12, 3, 4)],
            objects=[_object(SERVER_A), _object(SWITCH_B), _object(PANEL_P, TYPE_PANEL)],
        )

    def test_the_switch_sees_the_panel_and_not_what_is_behind_it(self) -> None:
        """The reported scenario: expanding the switch shows the panel it is cabled to"""
        neighbours, _objects = _collect(self._patched_through(), target_id=SERVER_A)

        assert _neighbour_ids(neighbours) == [PANEL_P]

    def test_the_panel_sees_both_sides(self) -> None:
        """Expanding the panel shows the objects at both ends of its patched pair"""
        neighbours, _objects = _collect(self._patched_through(), target_id=PANEL_P)

        assert _neighbour_ids(neighbours) == [SERVER_A, SWITCH_B]

    def test_the_far_switch_sees_the_panel_too(self) -> None:
        """The graph is symmetric: every object's view of a cable is the same cable"""
        neighbours, _objects = _collect(self._patched_through(), target_id=SWITCH_B)

        assert _neighbour_ids(neighbours) == [PANEL_P]

    def test_an_internal_pairing_draws_nothing(self) -> None:
        """It joins two ports of ONE object, so it is a self-loop - which face is patched to which is
        port-level detail the ports panel answers"""
        managers = _managers(
            ports=[_port(2, PANEL_P, PortSide.FRONT.value), _port(3, PANEL_P, PortSide.REAR.value)],
            connections=[_internal(11, 2, 3)],
            objects=[_object(PANEL_P, TYPE_PANEL)],
        )

        assert _collect(managers, target_id=PANEL_P) == ([], {})

    def test_a_cable_into_a_never_paired_face_is_still_drawn(self) -> None:
        """The cable is real, so the edge is real - what stops at the panel is the path, not the edge"""
        managers = _managers(
            ports=[_port(1, SERVER_A), _port(2, PANEL_P, PortSide.FRONT.value)],
            connections=[_cable(10, 1, 2)],
            objects=[_object(PANEL_P, TYPE_PANEL)],
        )

        neighbours, _objects = _collect(managers, target_id=SERVER_A)

        assert _neighbour_ids(neighbours) == [PANEL_P]

    def test_a_half_patched_pair_is_still_drawn(self) -> None:
        """Paired inside the panel but not cabled onward - visible, where collapsing hid it entirely"""
        managers = _managers(
            ports=[
                _port(1, SERVER_A),
                _port(2, PANEL_P, PortSide.FRONT.value),
                _port(3, PANEL_P, PortSide.REAR.value),
            ],
            connections=[_cable(10, 1, 2), _internal(11, 2, 3)],
            objects=[_object(PANEL_P, TYPE_PANEL)],
        )

        neighbours, _objects = _collect(managers, target_id=SERVER_A)

        assert _neighbour_ids(neighbours) == [PANEL_P]

    def test_chained_panels_are_each_their_own_node(self) -> None:
        """A -- P1 -- P2 -- B: expanding A shows P1, and expanding P1 shows A and P2"""
        managers = _managers(
            ports=[
                _port(1, SERVER_A),
                _port(2, PANEL_P, PortSide.FRONT.value),
                _port(3, PANEL_P, PortSide.REAR.value),
                _port(4, PANEL_P2, PortSide.FRONT.value),
                _port(5, PANEL_P2, PortSide.REAR.value),
                _port(6, SWITCH_B),
            ],
            connections=[
                _cable(10, 1, 2), _internal(11, 2, 3), _cable(12, 3, 4),
                _internal(13, 4, 5), _cable(14, 5, 6),
            ],
            objects=[
                _object(SERVER_A), _object(SWITCH_B),
                _object(PANEL_P, TYPE_PANEL), _object(PANEL_P2, TYPE_PANEL),
            ],
        )

        from_a, _objects = _collect(managers, target_id=SERVER_A)
        from_p1, _objects = _collect(managers, target_id=PANEL_P)

        assert _neighbour_ids(from_a) == [PANEL_P]
        assert _neighbour_ids(from_p1) == [SERVER_A, PANEL_P2]


# -------------------------------------------------------------------------------------------------------------------- #
#                                                    THE EDGE RULES                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
class TestTheEdgeRules:
    """What is drawn once, what is not drawn at all, and what the caller's budget does."""

    def test_q36_two_cables_between_the_same_pair_are_two_neighbours(self) -> None:
        """One connection is one edge; the frontend decides whether to bundle them"""
        managers = _managers(
            ports=[_port(1, SERVER_A), _port(2, SERVER_A), _port(3, SWITCH_B), _port(4, SWITCH_B)],
            connections=[_cable(10, 1, 3), _cable(11, 2, 4)],
            objects=[_object(SWITCH_B)],
        )

        neighbours, _objects = _collect(managers)

        assert _neighbour_ids(neighbours) == [SWITCH_B, SWITCH_B]

    def test_q39_a_cable_between_two_ports_of_one_object_is_skipped(self) -> None:
        """A real cable, but not an edge anyone can draw"""
        managers = _managers(
            ports=[_port(1, SERVER_A), _port(2, SERVER_A)],
            connections=[_cable(10, 1, 2)],
            objects=[_object(SERVER_A)],
        )

        assert _collect(managers) == ([], {})

    def test_the_types_filter_applies_to_the_far_side_ci(self) -> None:
        """A panel filtered out of the graph drops its edge with it"""
        managers = _managers(
            ports=[_port(1, SERVER_A), _port(2, PANEL_P, PortSide.FRONT.value)],
            connections=[_cable(10, 1, 2)],
            objects=[_object(PANEL_P, TYPE_PANEL)],
        )

        neighbours, objects = _collect(managers, types_filter=frozenset({TYPE_SERVER}))

        assert neighbours == []
        assert objects == {}

    def test_the_item_limit_caps_the_neighbours(self) -> None:
        """The cap is the caller's remaining budget, not a property of the walk"""
        managers = _managers(
            ports=[_port(1, SERVER_A), _port(2, SERVER_A), _port(3, SWITCH_B), _port(4, PANEL_P)],
            connections=[_cable(10, 1, 3), _cable(11, 2, 4)],
            objects=[_object(SWITCH_B), _object(PANEL_P, TYPE_PANEL)],
        )

        neighbours, _objects = _collect(managers, remaining=1, item_limit_active=True)

        assert len(neighbours) == 1

    def test_an_exhausted_budget_reads_nothing_at_all(self) -> None:
        """Not one query: the source is skipped before it starts"""
        managers = _managers(ports=[_port(1, SERVER_A)], connections=[], objects=[])

        assert _collect(managers, remaining=0, item_limit_active=True) == ([], {})
        managers.ports.get_ports_of_object.assert_not_called()


# -------------------------------------------------------------------------------------------------------------------- #
#                                                    THE PURE HELPERS                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
class TestThePureHelpers:
    """Each answers one question, without a manager."""

    def test_the_far_endpoint_is_found_by_membership(self) -> None:
        """`endpoints` is stored sorted, so a fixed position means nothing"""
        connection = _cable(10, 7, 3)

        assert other_endpoint(connection, 3) == 7
        assert other_endpoint(connection, 7) == 3

    def test_a_self_connection_leads_nowhere(self) -> None:
        """Both endpoints equal names no other port"""
        assert other_endpoint({'endpoints': [5, 5]}, 5) is None

    def test_ports_are_indexed_by_public_id(self) -> None:
        """A port without a usable public_id could never match a connection endpoint"""
        indexed = index_ports_by_id([_port(1, SERVER_A), {'object_id': SERVER_A}])

        assert set(indexed) == {1}

    def test_only_cables_become_hops(self) -> None:
        """An INTERNAL pairing is skipped before the far-side read, not filtered out after it"""
        hops = collect_cable_hops([_cable(10, 1, 2), _internal(11, 1, 3)], focal_port_ids={1})

        assert [(connection['public_id'], far) for connection, far in hops] == [(10, 2)]

    def test_a_cable_that_ends_on_the_focal_object_is_not_a_hop(self) -> None:
        """Q39, applied where it costs nothing"""
        assert collect_cable_hops([_cable(10, 1, 2)], focal_port_ids={1, 2}) == []

    def test_a_cable_naming_no_focal_port_is_not_a_hop(self) -> None:
        """Defensive: the read is by endpoint membership, so this cannot normally happen"""
        assert collect_cable_hops([_cable(10, 8, 9)], focal_port_ids={1}) == []

    def test_the_far_owners_are_read_in_one_query(self) -> None:
        """One '$in' for the whole page of cables"""
        managers = _managers(ports=[_port(2, PANEL_P), _port(3, SWITCH_B)], connections=[])

        assert load_far_port_owners([2, 3], managers) == {2: PANEL_P, 3: SWITCH_B}
        managers.ports.get_ports_by_ids.assert_called_once_with([2, 3])

    def test_nothing_to_resolve_costs_no_query(self) -> None:
        """An object whose every cable was skipped"""
        managers = _managers(ports=[], connections=[])

        assert load_far_port_owners([], managers) == {}
        managers.ports.get_ports_by_ids.assert_not_called()


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  THE DEFENSIVE PATHS                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
class TestTheDefensivePaths:
    """Documents that should not exist, which the source must not raise on."""

    def test_a_port_at_the_far_end_that_no_longer_exists_drops_its_edge(self) -> None:
        """A dangling endpoint names no object, and inventing one would be worse than nothing"""
        managers = _managers(
            ports=[_port(1, SERVER_A)],
            connections=[_cable(10, 1, 999)],
            objects=[_object(SWITCH_B)],
        )

        assert _collect(managers) == ([], {})

    def test_a_far_port_without_an_owner_drops_its_edge(self) -> None:
        """`object_id` is server-owned, so a port without one is a broken document"""
        managers = _managers(
            ports=[_port(1, SERVER_A), {'public_id': 2, 'side': PortSide.SINGLE.value}],
            connections=[_cable(10, 1, 2)],
            objects=[_object(SWITCH_B)],
        )

        assert _collect(managers) == ([], {})

    def test_a_far_object_that_no_longer_exists_drops_its_edge(self) -> None:
        """The port resolves, its object does not"""
        managers = _managers(
            ports=[_port(1, SERVER_A), _port(2, SWITCH_B)],
            connections=[_cable(10, 1, 2)],
            objects=[],
        )

        neighbours, objects = _collect(managers)

        assert neighbours == []
        assert objects == {}

    @pytest.mark.parametrize('endpoints', [[1], [1, 2, 3], []], ids=repr)
    def test_a_connection_naming_the_wrong_number_of_ports_is_skipped(self, endpoints: list[int]) -> None:
        """`endpoints` holds exactly two, which only the write path enforces"""
        connection = {'public_id': 10, 'endpoints': endpoints,
                      'connection_type': ConnectionType.CABLE.value}

        assert collect_cable_hops([connection], focal_port_ids={1}) == []
