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
`GET /ports/object/<object_id>/cabling` - one ring of the physical layer, over HTTP

The read behind the Cabling View: the focal CmdbObject, every object a cable of its reaches, and the
cables between them. **Every node carries all of its ports**, so a free port is drawn next to a cabled
one and the node's badge is answerable without a second request.

**There is no depth parameter.** Following the cabling outwards is the client asking for the next
object, which is why a NEIGHBOUR's port row has to name the object at its own far end - that is what
makes the port expandable. The seeded topology is the one the mockup draws:

    WEB-01 Gi0/1 --CAT6-001-- PP-01 Front 12 --internal-- PP-01 Rear 12 --CAT6-003-- SW-01 Gi1/0/12
    SW-01 Gi1/0/24 --OM4-001-- NAS-01 e0a
    SW-01 Gi1/0/48 --CAT6-009-- SECRET-01 e0a   (of a type the requesting user may not read)

so opening on WEB-01 answers two nodes, opening on PP-01 answers three, and the walk from one end to
the other is three calls rather than one traversal.
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

from cmdb.framework.port.name_syntax_constants import PortDeviceKind
from cmdb.interface.rest_api.routes.port_routes.port_cabling_constants import (
    CablingEdgeKey,
    CablingEndKey,
    CablingNodeKey,
    PortCablingKey,
)
from cmdb.interface.rest_api.routes.port_routes.port_overview_constants import PortOverviewEntryKey
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_URL: str = '/ports'

TYPE_DEVICE: int = 8610
TYPE_PANEL: int = 8611
TYPE_DENIED: int = 8612

OBJ_WEB: int = 8700
OBJ_PANEL: int = 8701
OBJ_SWITCH: int = 8702
OBJ_NAS: int = 8703
OBJ_LONELY: int = 8704          # has ports, none of them cabled
OBJ_DENIED: int = 8705          # cabled to the switch, of a type the admin group may not read
MISSING_OBJECT: int = 8799

PORT_WEB_1: int = 8800
PORT_WEB_2: int = 8801
PORT_PANEL_F12: int = 8802
PORT_PANEL_R12: int = 8803
PORT_PANEL_F13: int = 8804
PORT_PANEL_R13: int = 8805
PORT_SWITCH_12: int = 8806
PORT_SWITCH_24: int = 8807
PORT_SWITCH_48: int = 8811
PORT_NAS: int = 8808
PORT_LONELY: int = 8809
PORT_DENIED: int = 8810

CONN_WEB_PANEL: int = 8900
CONN_PANEL_PAIR: int = 8901
CONN_PANEL_SWITCH: int = 8902
CONN_PANEL_PAIR_2: int = 8903
CONN_SWITCH_NAS: int = 8904
CONN_SWITCH_DENIED: int = 8905

ALL_TYPE_IDS: list[int] = [TYPE_DEVICE, TYPE_PANEL, TYPE_DENIED]


@pytest.fixture(autouse=True)
def _ipam_licensed(monkeypatch: pytest.MonkeyPatch):
    """Licenses IPAM, which the whole /ports surface is gated behind."""
    monkeypatch.setattr(
        LicenseService, 'has_feature', lambda _self, feature: feature == LicenseFeature.IPAM,
    )


def _denied_acl() -> dict[str, Any]:
    """An ACL granting READ to a group the requesting admin is not in."""
    return {'activated': True, 'groups': {'includes': {'99': ['READ']}}}


def _type_doc(public_id: int, name: str, acl: dict[str, Any] | None = None) -> dict[str, Any]:
    """A port-bearing CmdbType the view can render a node for."""
    return {
        'public_id': public_id,
        'name': name,
        'label': name.title(),
        'author_id': 1,
        'creation_time': datetime.now(timezone.utc),
        'active': True,
        'uses_ports': True,
        'version': '1.0.0',
        'fields': [{'type': 'text', 'name': 'name', 'label': 'Name'}],
        'render_meta': {'icon': 'fa-server', 'sections': [], 'summary': {'fields': ['name']}},
        'ci_explorer_label': 'name',
        'ci_explorer_color': '#1f77b4',
        'acl': acl or {'activated': False, 'groups': {'includes': None}},
    }


def _object_doc(public_id: int, type_id: int, display_name: str) -> dict[str, Any]:
    """A CmdbObject with the one field the node title is read from."""
    return {
        'public_id': public_id,
        'type_id': type_id,
        'active': True,
        'author_id': 1,
        'creation_time': datetime.now(timezone.utc),
        'version': '1.0.0',
        'fields': [{'name': 'name', 'value': display_name}],
    }


def _port_doc(public_id: int, object_id: int, name: str, side: str) -> dict[str, Any]:
    """A stored CmdbPort."""
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


def _connection_doc(public_id: int, port_a: int, port_b: int, connection_type: str,
                    cable_name: str = 'CAT6-001') -> dict[str, Any]:
    """A stored CmdbPortConnection; a cable carries its name and length inline."""
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
            'cable_name': cable_name,
            'cable_type': None,
            'cable_length': '15 m',
            'cable_color': 'blue',
            'cable_description': None,
        })

    return document


@pytest.fixture(scope='module', name='connector')
def fixture_connector(database_manager) -> MongoConnector:
    """Shortcut to the underlying MongoConnector for direct collection access."""
    return database_manager.connector


@pytest.fixture(scope='module', autouse=True)
def setup_cabling_fixture(request, connector: MongoConnector, database_name):
    """Seeds the mockup's chain, plus an uncabled object and a neighbour behind an ACL."""
    database = connector.client.get_database(database_name)
    types = database.get_collection(CmdbType.COLLECTION)
    objects = database.get_collection(CmdbObject.COLLECTION)
    ports = database.get_collection(CmdbPort.COLLECTION)
    connections = database.get_collection(CmdbPortConnection.COLLECTION)

    types.insert_many([
        _type_doc(TYPE_DEVICE, 'device'),
        _type_doc(TYPE_PANEL, 'patchpanel'),
        _type_doc(TYPE_DENIED, 'secret', _denied_acl()),
    ])
    objects.insert_many([
        _object_doc(OBJ_WEB, TYPE_DEVICE, 'WEB-01'),
        _object_doc(OBJ_PANEL, TYPE_PANEL, 'PP-01'),
        _object_doc(OBJ_SWITCH, TYPE_DEVICE, 'SW-01'),
        _object_doc(OBJ_NAS, TYPE_DEVICE, 'NAS-01'),
        _object_doc(OBJ_LONELY, TYPE_DEVICE, 'LONE-01'),
        _object_doc(OBJ_DENIED, TYPE_DENIED, 'SECRET-01'),
    ])
    ports.insert_many([
        _port_doc(PORT_WEB_1, OBJ_WEB, 'Gi0/1', PortSide.SINGLE.value),
        _port_doc(PORT_WEB_2, OBJ_WEB, 'Gi0/2', PortSide.SINGLE.value),
        _port_doc(PORT_PANEL_F12, OBJ_PANEL, 'Front 12', PortSide.FRONT.value),
        _port_doc(PORT_PANEL_R12, OBJ_PANEL, 'Rear 12', PortSide.REAR.value),
        _port_doc(PORT_PANEL_F13, OBJ_PANEL, 'Front 13', PortSide.FRONT.value),
        _port_doc(PORT_PANEL_R13, OBJ_PANEL, 'Rear 13', PortSide.REAR.value),
        _port_doc(PORT_SWITCH_12, OBJ_SWITCH, 'Gi1/0/12', PortSide.SINGLE.value),
        _port_doc(PORT_SWITCH_24, OBJ_SWITCH, 'Gi1/0/24', PortSide.SINGLE.value),
        _port_doc(PORT_SWITCH_48, OBJ_SWITCH, 'Gi1/0/48', PortSide.SINGLE.value),
        _port_doc(PORT_NAS, OBJ_NAS, 'e0a', PortSide.SINGLE.value),
        _port_doc(PORT_LONELY, OBJ_LONELY, 'eth0', PortSide.SINGLE.value),
        _port_doc(PORT_DENIED, OBJ_DENIED, 'eth0', PortSide.SINGLE.value),
    ])
    connections.insert_many([
        _connection_doc(CONN_WEB_PANEL, PORT_WEB_1, PORT_PANEL_F12, ConnectionType.CABLE.value),
        _connection_doc(CONN_PANEL_PAIR, PORT_PANEL_F12, PORT_PANEL_R12, ConnectionType.INTERNAL.value),
        _connection_doc(CONN_PANEL_SWITCH, PORT_PANEL_R12, PORT_SWITCH_12,
                        ConnectionType.CABLE.value, 'CAT6-003'),
        _connection_doc(CONN_PANEL_PAIR_2, PORT_PANEL_F13, PORT_PANEL_R13, ConnectionType.INTERNAL.value),
        _connection_doc(CONN_SWITCH_NAS, PORT_SWITCH_24, PORT_NAS, ConnectionType.CABLE.value, 'OM4-001'),
        _connection_doc(CONN_SWITCH_DENIED, PORT_SWITCH_48, PORT_DENIED,
                        ConnectionType.CABLE.value, 'CAT6-009'),
    ])

    def _drop_all() -> None:
        types.drop()
        objects.drop()
        ports.drop()
        connections.drop()

    request.addfinalizer(_drop_all)


def _cabling(rest_api, object_id: int):
    """Issues one initial-ring request."""
    return rest_api.get(f'{ROUTE_URL}/object/{object_id}/cabling')


def _follow(rest_api, port_id: int):
    """Issues one expansion request: what following this port reveals."""
    return rest_api.get(f'{ROUTE_URL}/{port_id}/cabling')


def _node_ids(body: dict[str, Any]) -> list[int]:
    """The public_ids of the nodes, in the order they were answered."""
    return [node[CablingNodeKey.OBJECT_ID.value] for node in body[PortCablingKey.NODES.value]]


def _node(body: dict[str, Any], object_id: int) -> dict[str, Any]:
    """One node of the answer."""
    return next(
        node for node in body[PortCablingKey.NODES.value]
        if node[CablingNodeKey.OBJECT_ID.value] == object_id
    )


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  THE INITIAL STATE                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
class TestTheInitialState:
    """Opening the view on an object: itself, and everything one cable away."""

    def test_the_focal_object_and_its_neighbours_are_the_nodes(self, rest_api) -> None:
        """WEB-01 is cabled only to the panel, so the first ring is two nodes"""
        response = _cabling(rest_api, OBJ_WEB)

        assert response.status_code == HTTPStatus.OK
        body = response.get_json()
        assert body[PortCablingKey.FOCAL_OBJECT_ID.value] == OBJ_WEB
        assert _node_ids(body) == [OBJ_WEB, OBJ_PANEL]

    def test_what_is_behind_the_panel_is_not_in_the_first_ring(self, rest_api) -> None:
        """One ring per call - SW-01 is reached by expanding, not by opening"""
        assert OBJ_SWITCH not in _node_ids(_cabling(rest_api, OBJ_WEB).get_json())

    def test_the_focal_node_carries_all_of_its_ports(self, rest_api) -> None:
        """Including the free Gi0/2, which the mockup draws greyed out"""
        node = _node(_cabling(rest_api, OBJ_WEB).get_json(), OBJ_WEB)

        assert node[CablingNodeKey.PORT_COUNT.value] == 2
        assert len(node[CablingNodeKey.ROWS.value]) == 2

    def test_a_neighbour_carries_all_of_its_ports_too(self, rest_api) -> None:
        """The panel has four ports and only one pair is in use"""
        node = _node(_cabling(rest_api, OBJ_WEB).get_json(), OBJ_PANEL)

        assert node[CablingNodeKey.PORT_COUNT.value] == 4
        assert node[CablingNodeKey.DEVICE_KIND.value] == PortDeviceKind.PATCH_PANEL.value

    def test_a_panel_node_is_shaped_as_front_rear_pairs(self, rest_api) -> None:
        """Four ports, two rows - which is why the badge counts ports and not rows"""
        node = _node(_cabling(rest_api, OBJ_WEB).get_json(), OBJ_PANEL)

        assert len(node[CablingNodeKey.ROWS.value]) == 2
        assert set(node[CablingNodeKey.ROWS.value][0]) == {'front', 'rear', 'paired'}

    def test_a_node_carries_its_presentation(self, rest_api) -> None:
        """Title and type_info come from the CI Explorer's own composers, so both graphs agree"""
        node = _node(_cabling(rest_api, OBJ_WEB).get_json(), OBJ_WEB)

        assert node[CablingNodeKey.TITLE.value] == 'WEB-01'
        assert node[CablingNodeKey.TYPE_INFO.value]['type_id'] == TYPE_DEVICE

    def test_an_object_with_no_cables_is_one_node(self, rest_api) -> None:
        """It has a port; nothing is plugged into it"""
        body = _cabling(rest_api, OBJ_LONELY).get_json()

        assert _node_ids(body) == [OBJ_LONELY]
        assert body[PortCablingKey.EDGES.value] == []


# -------------------------------------------------------------------------------------------------------------------- #
#                                                     THE EDGES                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
class TestTheEdges:
    """One cable, one edge, between the two ports it joins."""

    def test_the_edge_names_both_ports_and_its_cable(self, rest_api) -> None:
        """The canvas draws between port rows, and labels the line with the cable"""
        body = _cabling(rest_api, OBJ_WEB).get_json()
        edge = body[PortCablingKey.EDGES.value][0]

        assert edge[CablingEdgeKey.CONNECTION_ID.value] == CONN_WEB_PANEL
        assert {edge[CablingEdgeKey.FROM_END.value][CablingEndKey.PORT_NAME.value],
                edge[CablingEdgeKey.TO_END.value][CablingEndKey.PORT_NAME.value]} == {'Gi0/1', 'Front 12'}
        assert edge[CablingEdgeKey.CABLE.value]['name'] == 'CAT6-001'
        assert edge[CablingEdgeKey.CABLE.value]['length'] == '15 m'

    def test_an_internal_pairing_is_not_an_edge(self, rest_api) -> None:
        """It joins two ports of the panel and is drawn inside the node"""
        body = _cabling(rest_api, OBJ_PANEL).get_json()
        connection_ids = [edge[CablingEdgeKey.CONNECTION_ID.value]
                          for edge in body[PortCablingKey.EDGES.value]]

        assert CONN_PANEL_PAIR not in connection_ids
        assert CONN_PANEL_PAIR_2 not in connection_ids

    def test_a_cable_leaving_the_ring_is_not_drawn(self, rest_api) -> None:
        """Opening on WEB-01, the panel's onward cable has no node at its far end yet"""
        body = _cabling(rest_api, OBJ_WEB).get_json()

        assert [edge[CablingEdgeKey.CONNECTION_ID.value]
                for edge in body[PortCablingKey.EDGES.value]] == [CONN_WEB_PANEL]


# -------------------------------------------------------------------------------------------------------------------- #
#                                            FOLLOWING THE CABLING OUTWARDS                                            #
# -------------------------------------------------------------------------------------------------------------------- #
class TestFollowingTheCabling:
    """Expanding a port is this same route on the object that port leads to."""

    def test_a_neighbours_port_names_the_object_beyond_it(self, rest_api) -> None:
        """Which is what makes the port expandable - without it the client could not follow"""
        panel = _node(_cabling(rest_api, OBJ_WEB).get_json(), OBJ_PANEL)
        paired_row = next(row for row in panel[CablingNodeKey.ROWS.value] if row['paired'])

        assert paired_row['rear'][PortOverviewEntryKey.CONNECTED_OBJECT.value]['object_id'] == OBJ_SWITCH

    def test_opening_on_the_panel_answers_both_of_its_sides(self, rest_api) -> None:
        """The mockup's next step: clicking Rear 12 opens PP-01 and reveals SW-01"""
        body = _cabling(rest_api, OBJ_PANEL).get_json()

        assert set(_node_ids(body)) == {OBJ_PANEL, OBJ_WEB, OBJ_SWITCH}

    def test_the_chain_is_walked_one_call_at_a_time(self, rest_api) -> None:
        """WEB-01 -> PP-01 -> SW-01 -> NAS-01, each ring answered by its own request"""
        from_switch = _cabling(rest_api, OBJ_SWITCH).get_json()

        assert OBJ_NAS in _node_ids(from_switch)
        assert OBJ_WEB not in _node_ids(from_switch)

    def test_an_object_cabled_to_several_objects_shows_them_all(self, rest_api) -> None:
        """SW-01 reaches the panel, the NAS and the object behind the ACL"""
        body = _cabling(rest_api, OBJ_SWITCH).get_json()

        assert {OBJ_PANEL, OBJ_NAS, OBJ_DENIED}.issubset(set(_node_ids(body)))


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       ACCESS                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class TestAccess:
    """The owner's ACL, the neighbours' ACL, and the existence check."""

    def test_a_neighbour_the_user_may_not_read_is_restricted(self, rest_api) -> None:
        """Its cable stays visible; what sits at the far end does not"""
        node = _node(_cabling(rest_api, OBJ_SWITCH).get_json(), OBJ_DENIED)

        assert node[CablingNodeKey.RESTRICTED.value] is True
        assert CablingNodeKey.ROWS.value not in node
        assert CablingNodeKey.TITLE.value not in node

    def test_a_missing_object_is_404(self, rest_api) -> None:
        """The view is asked for an object, so a missing one is not an empty graph"""
        assert _cabling(rest_api, MISSING_OBJECT).status_code == HTTPStatus.NOT_FOUND

    def test_an_owner_the_user_may_not_read_is_403(self, rest_api) -> None:
        """A port inherits no ACL from its owner, so the owner is checked explicitly"""
        assert _cabling(rest_api, OBJ_DENIED).status_code == HTTPStatus.FORBIDDEN

    def test_an_unlicensed_instance_is_refused(self, rest_api, monkeypatch) -> None:
        """The whole /ports surface is gated behind the IPAM licence"""
        monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, _feature: False)

        assert _cabling(rest_api, OBJ_WEB).status_code == HTTPStatus.FORBIDDEN


# -------------------------------------------------------------------------------------------------------------------- #
#                                        FOLLOWING ONE PORT: GET /ports/<id>/cabling                                   #
# -------------------------------------------------------------------------------------------------------------------- #
class TestFollowingOnePort:
    """
    The expansion half - deliberately a route of its own

    The initial call reveals every object the focal one is cabled to; this reveals exactly ONE. Doing
    it through the object route instead would answer that object's whole neighbourhood, which for a
    switch is every other object it is patched to.
    """

    def test_one_port_reveals_exactly_one_node(self, rest_api) -> None:
        """The mockup's step: clicking PP-01's Rear 12 brings back SW-01 and nothing else"""
        response = _follow(rest_api, PORT_PANEL_R12)

        assert response.status_code == HTTPStatus.OK
        body = response.get_json()
        assert _node_ids(body) == [OBJ_SWITCH]

    def test_the_object_route_would_have_answered_more(self, rest_api) -> None:
        """Which is the whole reason this is a second route"""
        expanded = _node_ids(_follow(rest_api, PORT_PANEL_R12).get_json())
        through_the_object = _node_ids(_cabling(rest_api, OBJ_SWITCH).get_json())

        assert expanded == [OBJ_SWITCH]
        assert len(through_the_object) > len(expanded)

    def test_the_revealed_node_carries_all_of_its_ports(self, rest_api) -> None:
        """So the user can keep following from it without another call"""
        node = _follow(rest_api, PORT_PANEL_R12).get_json()[PortCablingKey.NODES.value][0]

        assert node[CablingNodeKey.PORT_COUNT.value] == 3
        assert node[CablingNodeKey.TITLE.value] == 'SW-01'

    def test_the_revealed_rows_name_the_next_objects(self, rest_api) -> None:
        """Which is what makes the next port expandable in turn"""
        node = _follow(rest_api, PORT_PANEL_R12).get_json()[PortCablingKey.NODES.value][0]
        reached = {
            (row['port'][PortOverviewEntryKey.CONNECTED_OBJECT.value] or {}).get('object_id')
            for row in node[CablingNodeKey.ROWS.value]
        }

        assert OBJ_NAS in reached

    def test_the_answer_carries_the_one_cable(self, rest_api) -> None:
        """One node, one edge - the cable that was followed"""
        body = _follow(rest_api, PORT_PANEL_R12).get_json()
        edge = body[PortCablingKey.EDGES.value][0]

        assert len(body[PortCablingKey.EDGES.value]) == 1
        assert edge[CablingEdgeKey.CONNECTION_ID.value] == CONN_PANEL_SWITCH
        assert edge[CablingEdgeKey.FROM_END.value][CablingEndKey.PORT_ID.value] == PORT_PANEL_R12
        assert edge[CablingEdgeKey.TO_END.value][CablingEndKey.PORT_ID.value] == PORT_SWITCH_12
        assert edge[CablingEdgeKey.CABLE.value]['name'] == 'CAT6-003'

    def test_the_focal_id_is_where_the_expansion_started(self, rest_api) -> None:
        """The node already on the canvas, which the new edge attaches to"""
        body = _follow(rest_api, PORT_PANEL_R12).get_json()

        assert body[PortCablingKey.FOCAL_OBJECT_ID.value] == OBJ_PANEL

    def test_a_free_port_reveals_nothing(self, rest_api) -> None:
        """200 with an empty envelope: the port exists and the question was fair"""
        response = _follow(rest_api, PORT_WEB_2)

        assert response.status_code == HTTPStatus.OK
        assert response.get_json()[PortCablingKey.NODES.value] == []
        assert response.get_json()[PortCablingKey.EDGES.value] == []

    def test_an_internally_paired_face_reveals_nothing(self, rest_api) -> None:
        """A pairing joins two ports of one object, so following it leaves no node to draw"""
        body = _follow(rest_api, PORT_PANEL_F13).get_json()

        assert body[PortCablingKey.NODES.value] == []

    def test_a_revealed_object_the_user_may_not_read_is_restricted(self, rest_api) -> None:
        """The cable is still returned - what sits at its end is not described"""
        body = _follow(rest_api, PORT_SWITCH_48).get_json()
        node = body[PortCablingKey.NODES.value][0]

        assert node[CablingNodeKey.OBJECT_ID.value] == OBJ_DENIED
        assert node[CablingNodeKey.RESTRICTED.value] is True
        assert len(body[PortCablingKey.EDGES.value]) == 1

    def test_the_edge_into_a_restricted_object_carries_no_port_name(self, rest_api) -> None:
        """The cable is visible; the Port it lands on is a 403 through every other route"""
        edge = _follow(rest_api, PORT_SWITCH_48).get_json()[PortCablingKey.EDGES.value][0]

        assert edge[CablingEdgeKey.TO_END.value][CablingEndKey.PORT_ID.value] == PORT_DENIED
        assert edge[CablingEdgeKey.TO_END.value][CablingEndKey.PORT_NAME.value] is None
        assert edge[CablingEdgeKey.TO_END.value][CablingEndKey.SIDE.value] is None

    def test_a_missing_port_is_404(self, rest_api) -> None:
        """The route is asked about a port, so a missing one is not an empty answer"""
        assert _follow(rest_api, 8899).status_code == HTTPStatus.NOT_FOUND

    def test_a_port_whose_owner_is_denied_is_403(self, rest_api) -> None:
        """A port inherits no ACL from its owner, so the owner is checked explicitly"""
        assert _follow(rest_api, PORT_DENIED).status_code == HTTPStatus.FORBIDDEN
