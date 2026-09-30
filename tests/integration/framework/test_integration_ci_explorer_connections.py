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
Integration tests for the CI Explorer's port-connectivity source against a real MongoDB

The source rests on one assumption that the code does not enforce and cannot check:

    **a port has at most one CABLE and at most one INTERNAL connection**

That is what makes a port's cable unambiguous - there is no fan-out to choose between. Nothing in
``connections.py`` verifies it; it is held by the two partial unique indexes on ``endpoints``, and a
unit test with a hand-built fixture would satisfy it by construction whether the database did or not.
These tests put the real indexes in front of the real source.

The second thing only a real MongoDB can show is that ``{endpoints: {$in: [...]}}`` is a MULTIKEY
match: it must find a connection whether the port sits at the first or the second position of the
stored array. The endpoints are stored sorted, so which position a given port occupies is decided by
the ids, not by the caller - if the query matched positionally, half of every graph would vanish and
which half would depend on the numbering.

Note the fixture builds the models' declared indexes itself. The test database never goes through
CollectionValidator, so its collections are created by the first write and carry no index but
``_id_``; building them here is what the application does at startup
"""
from datetime import datetime, timezone
from typing import Any

import pytest
from pymongo.errors import DuplicateKeyError

from cmdb.database import MongoDatabaseManager
from cmdb.framework.ci_explorer.connections import (
    ConnectionSourceManagers,
    collect_connection_neighbours,
)
from cmdb.manager.extendable_options_manager import ExtendableOptionsManager
from cmdb.manager.objects_manager import ObjectsManager
from cmdb.manager.port_connections_manager import PortConnectionsManager
from cmdb.manager.ports_manager import PortsManager
from cmdb.models.object_model import CmdbObject
from cmdb.models.port_connection_model import (
    CmdbPortConnection,
    ConnectionType,
    PortConnectionKey,
)
from cmdb.models.port_model import CmdbPort, PortKey, PortSide
# -------------------------------------------------------------------------------------------------------------------- #

# Objects: two devices patched through one panel
SERVER_A: int = 49100
SWITCH_B: int = 49101
PANEL_P: int = 49102

TYPE_DEVICE: int = 49010

# Ports
PORT_A: int = 49200
PORT_B: int = 49201
PORT_FRONT: int = 49202
PORT_REAR: int = 49203
PORT_SPARE: int = 49204

ALL_PORT_IDS: list[int] = [PORT_A, PORT_B, PORT_FRONT, PORT_REAR, PORT_SPARE]
ALL_OBJECT_IDS: list[int] = [SERVER_A, SWITCH_B, PANEL_P]
CONNECTION_IDS: list[int] = [49300, 49301, 49302, 49303]


def _port_doc(public_id: int, object_id: int, side: str) -> dict[str, Any]:
    """A stored CmdbPort document."""
    return {
        PortKey.PUBLIC_ID.value: public_id,
        PortKey.OBJECT_ID.value: object_id,
        PortKey.SIDE.value: side,
        PortKey.NAME.value: f'port-{public_id}',
        PortKey.PORT_NUMBER.value: None,
        PortKey.STATUS.value: None,
        PortKey.PORT_TYPE.value: None,
        PortKey.SPEED.value: None,
        PortKey.DESCRIPTION.value: None,
        PortKey.AUTHOR_ID.value: 1,
        PortKey.CREATION_TIME.value: datetime.now(timezone.utc),
        PortKey.LAST_EDIT_TIME.value: None,
    }


def _connection_doc(public_id: int, endpoints: list[int], connection_type: str) -> dict[str, Any]:
    """A stored CmdbPortConnection; endpoints sorted exactly as the model sorts them on write."""
    return {
        PortConnectionKey.PUBLIC_ID.value: public_id,
        PortConnectionKey.ENDPOINTS.value: sorted(endpoints),
        PortConnectionKey.CONNECTION_TYPE.value: connection_type,
        PortConnectionKey.CABLE_NAME.value: None,
        PortConnectionKey.CABLE_TYPE.value: None,
        PortConnectionKey.CABLE_LENGTH.value: None,
        PortConnectionKey.CABLE_COLOR.value: None,
        PortConnectionKey.CABLE_DESCRIPTION.value: None,
        PortConnectionKey.AUTHOR_ID.value: 1,
        PortConnectionKey.CREATION_TIME.value: datetime.now(timezone.utc),
        PortConnectionKey.LAST_EDIT_TIME.value: None,
    }


def _object_doc(public_id: int) -> dict[str, Any]:
    """A stored CmdbObject the walk can end on."""
    return {
        'public_id': public_id,
        'type_id': TYPE_DEVICE,
        'status': True,
        'active': True,
        'author_id': 1,
        'creation_time': datetime.now(timezone.utc),
        'version': '1.0.0',
        'fields': [{'name': 'name', 'value': f'object-{public_id}'}],
    }


@pytest.fixture(name='collections')
def fixture_collections(database_manager: MongoDatabaseManager, database_name: str):
    """
    Seeds the patched chain with the declared indexes built, and clears it around each test

    ``A --cable-- P.front --internal-- P.rear --cable-- B``, plus one spare panel port that nothing
    is attached to.
    """
    ports = database_manager.get_collection(CmdbPort.COLLECTION, database_name)
    connections = database_manager.get_collection(CmdbPortConnection.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)

    def _purge() -> None:
        ports.delete_many({PortKey.PUBLIC_ID.value: {'$in': ALL_PORT_IDS}})
        connections.delete_many({PortConnectionKey.PUBLIC_ID.value: {'$in': CONNECTION_IDS}})
        objects.delete_many({'public_id': {'$in': ALL_OBJECT_IDS}})

    _purge()
    database_manager.create_indexes(
        CmdbPortConnection.COLLECTION, database_name, CmdbPortConnection.get_index_keys(),
    )
    database_manager.create_indexes(CmdbPort.COLLECTION, database_name, CmdbPort.get_index_keys())

    ports.insert_many([
        _port_doc(PORT_A, SERVER_A, PortSide.SINGLE.value),
        _port_doc(PORT_B, SWITCH_B, PortSide.SINGLE.value),
        _port_doc(PORT_FRONT, PANEL_P, PortSide.FRONT.value),
        _port_doc(PORT_REAR, PANEL_P, PortSide.REAR.value),
        _port_doc(PORT_SPARE, PANEL_P, PortSide.FRONT.value),
    ])
    connections.insert_many([
        _connection_doc(CONNECTION_IDS[0], [PORT_A, PORT_FRONT], ConnectionType.CABLE.value),
        _connection_doc(CONNECTION_IDS[1], [PORT_FRONT, PORT_REAR], ConnectionType.INTERNAL.value),
        _connection_doc(CONNECTION_IDS[2], [PORT_REAR, PORT_B], ConnectionType.CABLE.value),
    ])
    objects.insert_many([_object_doc(object_id) for object_id in ALL_OBJECT_IDS])

    yield connections

    _purge()


@pytest.fixture(name='managers')
def fixture_managers(database_manager: MongoDatabaseManager) -> ConnectionSourceManagers:
    """Real managers backed by the test database - no mock anywhere in these tests."""
    return ConnectionSourceManagers(
        ports=PortsManager(database_manager),
        connections=PortConnectionsManager(database_manager),
        objects=ObjectsManager(database_manager),
        extendable_options=ExtendableOptionsManager(database_manager),
    )


def _collect(managers: ConnectionSourceManagers, target_id: int):
    """Runs the source with no filter and no cap."""
    return collect_connection_neighbours(
        target_id=target_id,
        types_filter=frozenset(),
        remaining=0,
        item_limit_active=False,
        managers=managers,
    )


# -------------------------------------------------------------------------------------------------------------------- #
#                               the assumption the walk rests on is the database's                                     #
# -------------------------------------------------------------------------------------------------------------------- #
def test_a_port_cannot_hold_a_second_cable(collections) -> None:
    """
    The no-fan-out guarantee, refused by the partial unique index rather than by any code

    If it did not hold, ``index_connections_by_port`` would silently keep whichever of the two cables
    it saw last and the walk would follow an arbitrary one of them.
    """
    with pytest.raises(DuplicateKeyError):
        collections.insert_one(
            _connection_doc(CONNECTION_IDS[3], [PORT_A, PORT_SPARE], ConnectionType.CABLE.value),
        )


def test_a_port_may_hold_one_cable_and_one_internal(collections, managers) -> None:
    """
    Both at once is the patch panel itself, so the source depends on this being allowed

    The seeded front port already holds one of each; that the collection accepted it is the
    assertion, and the edge to the panel is the proof it is usable.
    """
    del collections
    neighbours, _objects = _collect(managers, SERVER_A)

    assert [neighbour.neighbour_object_id for neighbour in neighbours] == [PANEL_P]


def test_the_endpoint_query_matches_at_either_position(collections, managers) -> None:
    """
    ``endpoints`` is stored sorted, so a port's position in the array is decided by the ids

    A port at the lower id of its pair and one at the higher must both resolve: a query that only
    matched one position would find a cable from one end and lose it from the other, and which end
    would depend on the numbering.
    """
    del collections
    from_a, _objects_a = _collect(managers, SERVER_A)
    from_b, _objects_b = _collect(managers, SWITCH_B)

    assert [neighbour.neighbour_object_id for neighbour in from_a] == [PANEL_P]
    assert [neighbour.neighbour_object_id for neighbour in from_b] == [PANEL_P]


# -------------------------------------------------------------------------------------------------------------------- #
#                                      the source against real documents                                               #
# -------------------------------------------------------------------------------------------------------------------- #
def test_the_panel_is_a_neighbour_of_both_devices(collections, managers) -> None:
    """The panel owns the two ports in the middle, and is a node on both sides of them."""
    del collections
    _neighbours_a, objects_a = _collect(managers, SERVER_A)
    _neighbours_b, objects_b = _collect(managers, SWITCH_B)

    assert set(objects_a) == {PANEL_P}
    assert set(objects_b) == {PANEL_P}


def test_the_edge_carries_the_one_cable_it_is(collections, managers) -> None:
    """The stored connection the edge is, and only that one."""
    del collections
    neighbours, _objects = _collect(managers, SERVER_A)

    assert [hop[PortConnectionKey.PUBLIC_ID.value] for hop in neighbours[0].path] == [
        CONNECTION_IDS[0],
    ]


def test_each_end_carries_its_own_cable(collections, managers) -> None:
    """The two devices are cabled to the panel by different connections, and each edge names its own."""
    del collections
    from_a, _objects_a = _collect(managers, SERVER_A)
    from_b, _objects_b = _collect(managers, SWITCH_B)

    assert [hop[PortConnectionKey.PUBLIC_ID.value] for hop in from_a[0].path] == [CONNECTION_IDS[0]]
    assert [hop[PortConnectionKey.PUBLIC_ID.value] for hop in from_b[0].path] == [CONNECTION_IDS[2]]


def test_the_focal_panel_reaches_both_ends(collections, managers) -> None:
    """Against real data: opening the panel shows the objects at both ends of its patched pair."""
    del collections
    neighbours, objects = _collect(managers, PANEL_P)

    assert {neighbour.neighbour_object_id for neighbour in neighbours} == {SERVER_A, SWITCH_B}
    assert set(objects) == {SERVER_A, SWITCH_B}


def test_removing_the_rear_cable_leaves_the_front_edge(collections, managers) -> None:
    """
    Against real data: unplug the rear cable and Server A is still cabled to the panel

    The connection is deleted rather than built differently, so what is exercised is the same
    documents in the state an installation reaches by unpatching.
    """
    collections.delete_one({PortConnectionKey.PUBLIC_ID.value: CONNECTION_IDS[2]})

    neighbours, objects = _collect(managers, SERVER_A)

    assert [neighbour.neighbour_object_id for neighbour in neighbours] == [PANEL_P]
    assert set(objects) == {PANEL_P}


def test_removing_the_internal_pairing_leaves_both_cables(collections, managers) -> None:
    """The faces are no longer patched to each other, but both cables are still real edges."""
    collections.delete_one({PortConnectionKey.PUBLIC_ID.value: CONNECTION_IDS[1]})

    from_a, _objects_a = _collect(managers, SERVER_A)
    from_panel, _objects_panel = _collect(managers, PANEL_P)

    assert [neighbour.neighbour_object_id for neighbour in from_a] == [PANEL_P]
    assert {neighbour.neighbour_object_id for neighbour in from_panel} == {SERVER_A, SWITCH_B}


def test_an_internal_pairing_alone_draws_nothing(collections, managers) -> None:
    """Both its ends are ports of the panel, so it is a self-loop whichever way it is read."""
    collections.delete_many({PortConnectionKey.PUBLIC_ID.value: {'$in': [CONNECTION_IDS[0],
                                                                        CONNECTION_IDS[2]]}})

    neighbours, objects = _collect(managers, PANEL_P)

    assert not neighbours
    assert not objects
