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
The port-connectivity source of GET /ci_explorer/items (Port Connectivity step 14)

Drives the real route against a real patch-panel fixture:

    Server A --cable-- P.front-1 --internal-- P.rear-1 --cable-- Switch B

plus a half-patched second path (C1) and an unpaired third one (C2), which are the states an
installation is actually in most of the time.

The unit tests in tests/unit/framework/ci_explorer/test_connections.py own the walk's branches. What
these own is the contract over HTTP: the flag, the bucket the collapsed edge lands in, the metadata
the frontend branches on, and the two refusals that are not refusals - an unlicensed instance and a
parents-only request both get an empty source rather than an error.
"""
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database.mongo_connector import MongoConnector
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.models.object_model import CmdbObject
from cmdb.models.port_connection_model import CmdbPortConnection, ConnectionType
from cmdb.models.port_model import CmdbPort, PortSide
from cmdb.models.type_model import CmdbType
from cmdb.security.license.license_constants import LicenseFeature
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_URL: str = '/ci_explorer/items'

# Types
TYPE_DEVICE: int = 8210
TYPE_PANEL: int = 8211

# Objects
OBJ_SERVER_A: int = 8300
OBJ_SWITCH_B: int = 8301
OBJ_PANEL_P: int = 8302
OBJ_SERVER_C: int = 8303      # cabled into a half-patched panel face (C1)
OBJ_SERVER_D: int = 8304      # cabled to a panel face that was never paired (C2)

# Ports
PORT_A1: int = 8400           # Server A
PORT_B1: int = 8401           # Switch B
PORT_P_FRONT_1: int = 8402    # Panel, front, patched through to the rear
PORT_P_REAR_1: int = 8403     # Panel, rear, cabled onward to Switch B
PORT_C1: int = 8404           # Server C
PORT_P_FRONT_2: int = 8405    # Panel, front, paired to a rear face that is not cabled (C1)
PORT_P_REAR_2: int = 8406     # Panel, rear, no cable
PORT_D1: int = 8407           # Server D
PORT_P_FRONT_3: int = 8408    # Panel, front, never paired at all (C2)

# Connections
CONN_A_TO_PANEL: int = 8500
CONN_PANEL_PAIR_1: int = 8501
CONN_PANEL_TO_B: int = 8502
CONN_C_TO_PANEL: int = 8503
CONN_PANEL_PAIR_2: int = 8504
CONN_D_TO_PANEL: int = 8505


@pytest.fixture(autouse=True)
def _ipam_licensed(monkeypatch: pytest.MonkeyPatch):
    """Licenses IPAM, without which the source deliberately yields nothing (Q40)."""
    monkeypatch.setattr(
        LicenseService, 'has_feature', lambda _self, feature: feature == LicenseFeature.IPAM,
    )


def _make_type(public_id: int, name: str) -> dict[str, Any]:
    """A port-bearing CmdbType the CI Explorer can render a node for."""
    return {
        'public_id': public_id,
        'name': name,
        'label': name.title(),
        'author_id': 1,
        'creation_time': datetime.now(timezone.utc),
        'active': True,
        'uses_ports': True,
        'fields': [{'type': 'text', 'name': 'name', 'label': 'Name'}],
        'render_meta': {'icon': 'fa-server', 'sections': [], 'summary': {'fields': ['name']}},
        'ci_explorer_label': 'name',
        'ci_explorer_color': '#1f77b4',
        'acl': {'activated': False, 'groups': {'includes': None}},
        'version': '1.0.0',
    }


def _make_object(public_id: int, type_id: int, display_name: str) -> dict[str, Any]:
    """A CmdbObject with the one field the CI Explorer renders as its title."""
    return {
        'public_id': public_id,
        'type_id': type_id,
        'status': True,
        'active': True,
        'author_id': 1,
        'creation_time': datetime.now(timezone.utc),
        'version': '1.0.0',
        'fields': [{'name': 'name', 'value': display_name}],
    }


def _make_port(public_id: int, object_id: int, name: str, side: str) -> dict[str, Any]:
    """A CmdbPort; `side` is what the collapse rule reads panel-ness from."""
    return {
        'public_id': public_id,
        'object_id': object_id,
        'side': side,
        'name': name,
        'port_number': None,
        'status': None,
        'port_type': None,
        'speed': None,
        'description': None,
        'author_id': 1,
        'creation_time': datetime.now(timezone.utc),
        'last_edit_time': None,
    }


def _make_connection(public_id: int, port_a: int, port_b: int, connection_type: str) -> dict[str, Any]:
    """A CmdbPortConnection; endpoints are stored sorted, which is what makes it undirected."""
    document: dict[str, Any] = {
        'public_id': public_id,
        'endpoints': sorted([port_a, port_b]),
        'connection_type': connection_type,
        'author_id': 1,
        'creation_time': datetime.now(timezone.utc),
        'last_edit_time': None,
    }

    if connection_type == ConnectionType.CABLE.value:
        document.update({
            'cable_name': f'cable-{public_id}',
            'cable_type': None,
            'cable_length': '3m',
            'cable_color': 'blue',
            'cable_description': None,
        })

    return document


@pytest.fixture(scope='module', name='connector')
def fixture_connector(database_manager) -> MongoConnector:
    """Shortcut to the underlying MongoConnector for direct collection access."""
    return database_manager.connector


@pytest.fixture(scope='module', autouse=True)
def setup_connection_fixture(request, connector: MongoConnector, database_name):
    """Seeds the patched, half-patched and unpaired paths through one patch panel."""
    database = connector.client.get_database(database_name)
    types = database.get_collection(CmdbType.COLLECTION)
    objects = database.get_collection(CmdbObject.COLLECTION)
    ports = database.get_collection(CmdbPort.COLLECTION)
    connections = database.get_collection(CmdbPortConnection.COLLECTION)

    types.insert_many([
        _make_type(TYPE_DEVICE, 'device'),
        _make_type(TYPE_PANEL, 'panel'),
    ])

    objects.insert_many([
        _make_object(OBJ_SERVER_A, TYPE_DEVICE, 'server-a'),
        _make_object(OBJ_SWITCH_B, TYPE_DEVICE, 'switch-b'),
        _make_object(OBJ_PANEL_P, TYPE_PANEL, 'panel-p'),
        _make_object(OBJ_SERVER_C, TYPE_DEVICE, 'server-c'),
        _make_object(OBJ_SERVER_D, TYPE_DEVICE, 'server-d'),
    ])

    ports.insert_many([
        _make_port(PORT_A1, OBJ_SERVER_A, 'eth0', PortSide.SINGLE.value),
        _make_port(PORT_B1, OBJ_SWITCH_B, 'Gi0/1', PortSide.SINGLE.value),
        _make_port(PORT_P_FRONT_1, OBJ_PANEL_P, 'F01', PortSide.FRONT.value),
        _make_port(PORT_P_REAR_1, OBJ_PANEL_P, 'R01', PortSide.REAR.value),
        _make_port(PORT_C1, OBJ_SERVER_C, 'eth0', PortSide.SINGLE.value),
        _make_port(PORT_P_FRONT_2, OBJ_PANEL_P, 'F02', PortSide.FRONT.value),
        _make_port(PORT_P_REAR_2, OBJ_PANEL_P, 'R02', PortSide.REAR.value),
        _make_port(PORT_D1, OBJ_SERVER_D, 'eth0', PortSide.SINGLE.value),
        _make_port(PORT_P_FRONT_3, OBJ_PANEL_P, 'F03', PortSide.FRONT.value),
    ])

    connections.insert_many([
        # The fully patched path: A -- P -- B
        _make_connection(CONN_A_TO_PANEL, PORT_A1, PORT_P_FRONT_1, ConnectionType.CABLE.value),
        _make_connection(CONN_PANEL_PAIR_1, PORT_P_FRONT_1, PORT_P_REAR_1, ConnectionType.INTERNAL.value),
        _make_connection(CONN_PANEL_TO_B, PORT_P_REAR_1, PORT_B1, ConnectionType.CABLE.value),
        # C1: paired inside the panel, but the rear face was never cabled onward
        _make_connection(CONN_C_TO_PANEL, PORT_C1, PORT_P_FRONT_2, ConnectionType.CABLE.value),
        _make_connection(CONN_PANEL_PAIR_2, PORT_P_FRONT_2, PORT_P_REAR_2, ConnectionType.INTERNAL.value),
        # C2: cabled to a front face that has no internal pairing at all
        _make_connection(CONN_D_TO_PANEL, PORT_D1, PORT_P_FRONT_3, ConnectionType.CABLE.value),
    ])

    def _drop_all() -> None:
        types.drop()
        objects.drop()
        ports.drop()
        connections.drop()

    request.addfinalizer(_drop_all)


def _get(rest_api, target_id: int, **params: Any):
    """Issues one /ci_explorer/items request with the connection source switched on."""
    query = '&'.join(f'{key}={value}' for key, value in params.items())

    return rest_api.get(f'{ROUTE_URL}?target_id={target_id}&with_port_connections=true&{query}')


def _child_ids(body: dict[str, Any]) -> set[int]:
    """The public_ids in the children bucket."""
    return {node['linked_object']['public_id'] for node in body['children_nodes']}


def _connection_edges(body: dict[str, Any]) -> list[dict[str, Any]]:
    """Only the edges the port-connectivity source produced."""
    return [
        edge for edge in body['child_edges']
        if edge.get('metadata', {}).get('source') == 'port_connection'
    ]


class TestThePanelIsCollapsedAway:
    """The feature's whole point: the graph shows the two CIs, not the panel between them."""

    def test_the_far_side_ci_is_drawn(self, rest_api) -> None:
        """A -- P -- B is answered as A -- B."""
        response = _get(rest_api, OBJ_SERVER_A, target_type='CHILD')

        assert response.status_code == HTTPStatus.OK
        assert OBJ_SWITCH_B in _child_ids(response.get_json())

    def test_the_panel_is_not_drawn(self, rest_api) -> None:
        """Not as a node, and not as the far end of an edge."""
        body = _get(rest_api, OBJ_SERVER_A, target_type='CHILD').get_json()

        assert OBJ_PANEL_P not in _child_ids(body)
        assert OBJ_PANEL_P not in {edge['to'] for edge in body['child_edges']}

    def test_the_edge_carries_the_collapsed_physical_path(self, rest_api) -> None:
        """
        Case C5: all three hops ride on the edge, focal end first

        Which is what lets the frontend answer "show me the physical path" without a second request.
        """
        body = _get(rest_api, OBJ_SERVER_A, target_type='CHILD').get_json()
        edge = next(edge for edge in _connection_edges(body) if edge['to'] == OBJ_SWITCH_B)

        assert [hop['public_id'] for hop in edge['metadata']['path']] == [
            CONN_A_TO_PANEL, CONN_PANEL_PAIR_1, CONN_PANEL_TO_B,
        ]
        assert [hop['connection_type'] for hop in edge['metadata']['path']] == [
            ConnectionType.CABLE.value, ConnectionType.INTERNAL.value, ConnectionType.CABLE.value,
        ]

    def test_each_hop_carries_the_resolved_cable_block(self, rest_api) -> None:
        """
        The same shape the /port_connections reads answer with

        The flat cable_* keys are replaced by one block, so a client never has to know whether the
        cable is inline or an inventoried CI.
        """
        body = _get(rest_api, OBJ_SERVER_A, target_type='CHILD').get_json()
        edge = next(edge for edge in _connection_edges(body) if edge['to'] == OBJ_SWITCH_B)
        first_hop = edge['metadata']['path'][0]

        assert 'cable' in first_hop
        assert 'cable_name' not in first_hop

    def test_the_edge_is_undirected_and_tagged(self, rest_api) -> None:
        """The two metadata flags the frontend branches on."""
        body = _get(rest_api, OBJ_SERVER_A, target_type='CHILD').get_json()
        edge = next(edge for edge in _connection_edges(body) if edge['to'] == OBJ_SWITCH_B)

        assert edge['metadata']['undirected'] is True
        assert edge['metadata']['source'] == 'port_connection'
        assert edge['metadata']['relation_id'] is None


class TestTheIncompletePaths:
    """C1 and C2 - the states a half-rolled-out panel is actually in."""

    def test_c1_a_chain_dying_inside_the_panel_shows_nothing(self, rest_api) -> None:
        """
        Server C is cabled and patched, but the rear face leads nowhere yet

        Accepted explicitly (Q31): its graph is indistinguishable from an unpatched server's.
        """
        body = _get(rest_api, OBJ_SERVER_C, target_type='CHILD').get_json()

        assert not _connection_edges(body)
        assert _child_ids(body) == set()

    def test_c2_an_unpaired_panel_face_shows_nothing(self, rest_api) -> None:
        """Server D's cable lands on a front port with no internal pairing at all."""
        body = _get(rest_api, OBJ_SERVER_D, target_type='CHILD').get_json()

        assert not _connection_edges(body)
        assert _child_ids(body) == set()


class TestTheFocalPanelIsTransparent:
    """C4 - opening the panel itself."""

    def test_it_shows_the_cis_its_paths_reach(self, rest_api) -> None:
        """Both ends of the patched path, from the panel's two faces."""
        body = _get(rest_api, OBJ_PANEL_P, target_type='CHILD').get_json()

        assert {OBJ_SERVER_A, OBJ_SWITCH_B}.issubset(_child_ids(body))

    def test_it_still_shows_nothing_for_its_incomplete_paths(self, rest_api) -> None:
        """
        The panel's own half-patched faces follow the same rules

        Server C's cable reaches the panel, but walking outward from the panel's F02 face ends on an
        uncabled rear - and walking from F03 ends nowhere at all.
        """
        body = _get(rest_api, OBJ_PANEL_P, target_type='CHILD').get_json()

        assert OBJ_SERVER_C in _child_ids(body)     # reached directly from F02's own cable
        assert OBJ_SERVER_D in _child_ids(body)     # reached directly from F03's own cable
        assert OBJ_PANEL_P not in _child_ids(body)


class TestTheRequestContract:
    """The flag, the direction rule and the licence rule."""

    def test_the_source_is_off_by_default(self, rest_api) -> None:
        """Every other client keeps the response it has today."""
        body = rest_api.get(f'{ROUTE_URL}?target_id={OBJ_SERVER_A}&target_type=CHILD').get_json()

        assert not _connection_edges(body)

    def test_a_parents_only_request_gets_no_connections(self, rest_api) -> None:
        """Q37 - an undirected edge has no parent side, so the source is not consulted."""
        body = _get(rest_api, OBJ_SERVER_A, target_type='PARENT').get_json()

        assert 'child_edges' not in body
        assert body['parent_nodes'] == []

    def test_an_unlicensed_instance_yields_nothing_rather_than_403(
        self, rest_api, monkeypatch,
    ) -> None:
        """
        Q40 - the graph is a shared read surface

        Refusing the whole request would break a graph that is perfectly valid for every other
        source, so the flag simply produces no connections.
        """
        monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, _feature: False)

        response = _get(rest_api, OBJ_SERVER_A, target_type='CHILD')

        assert response.status_code == HTTPStatus.OK
        assert _connection_edges(response.get_json()) == []

    def test_the_types_filter_applies_to_the_far_side_ci(self, rest_api) -> None:
        """Q38 - the same rule the relation source follows."""
        body = _get(
            rest_api, OBJ_SERVER_A, target_type='CHILD', types_filter=f'[{TYPE_PANEL}]',
        ).get_json()

        assert OBJ_SWITCH_B not in _child_ids(body)

    def test_an_object_with_no_ports_is_unaffected(self, rest_api) -> None:
        """The flag must be free for the overwhelming majority of CIs, which have no ports."""
        response = rest_api.get(
            f'{ROUTE_URL}?target_id={OBJ_SWITCH_B}&with_port_connections=true&target_type=PARENT',
        )

        assert response.status_code == HTTPStatus.OK
