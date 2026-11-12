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
Integration tests: the CI Explorer's port source cuts ``item_limit`` deterministically, against a real MongoDB

A switch is cabled to three devices - the lowest-id one twice - and the cables are STORED in reverse id order, so
the connection read's natural order is the opposite of the id order:

  - under a cap of two, the two lowest-id neighbours are drawn, on every request
  - under a cap of one, the lowest neighbour is drawn with BOTH its cables - a slot is a neighbour, not a cable
  - only the drawn neighbours are answered
"""
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.framework.ci_explorer.connections import ConnectionSourceManagers, collect_connection_neighbours
from cmdb.framework.ci_explorer.type_scope import NeighbourTypeScope
from cmdb.manager.extendable_options_manager import ExtendableOptionsManager
from cmdb.manager.objects_manager import ObjectsManager
from cmdb.manager.port_connections_manager import PortConnectionsManager
from cmdb.manager.ports_manager import PortsManager
from cmdb.models.object_model import CmdbObject
from cmdb.models.port_connection_model import CmdbPortConnection, PortConnectionKey
from cmdb.models.port_model import CmdbPort, PortKey
from tests.utils.port_doc_builders import cable_doc, device_doc, port_doc
# -------------------------------------------------------------------------------------------------------------------- #

TYPE_DEVICE: int = 48010
SWITCH: int = 48100
LOW: int = 48101
MID: int = 48102
HIGH: int = 48103
OBJECT_IDS: list[int] = [SWITCH, LOW, MID, HIGH]
# Switch ports 48201-48204; one far port per device, a second on the lowest
SWITCH_PORTS: list[int] = [48201, 48202, 48203, 48204]
FAR_PORTS: dict[int, int] = {48211: LOW, 48212: MID, 48213: HIGH, 48214: LOW}
PORT_IDS: list[int] = SWITCH_PORTS + list(FAR_PORTS)
# (connection id, switch port, far port), stored highest id first
CABLES: list[tuple[int, int, int]] = [(48304, 48204, 48214), (48303, 48203, 48213), (48302, 48202, 48212),
                                      (48301, 48201, 48211)]
CONNECTION_IDS: list[int] = [cable[0] for cable in CABLES]
MONGO_ID_INDEX: str = '_id_'


@pytest.fixture(name='managers')
def fixture_managers(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[ConnectionSourceManagers]:
    """The switch and its cabling behind the declared indexes; documents and indexes built here removed after"""
    ports = database_manager.get_collection(CmdbPort.COLLECTION, database_name)
    connections = database_manager.get_collection(CmdbPortConnection.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)

    def _purge() -> None:
        ports.delete_many({PortKey.PUBLIC_ID.value: {'$in': PORT_IDS}})
        connections.delete_many({PortConnectionKey.PUBLIC_ID.value: {'$in': CONNECTION_IDS}})
        objects.delete_many({'public_id': {'$in': OBJECT_IDS}})

    _purge()
    had_indexes: dict[Any, set[str]] = {collection: set(collection.index_information())
                                        for collection in (ports, connections)}
    database_manager.create_indexes(CmdbPortConnection.COLLECTION, database_name, CmdbPortConnection.get_index_keys())
    database_manager.create_indexes(CmdbPort.COLLECTION, database_name, CmdbPort.get_index_keys())

    ports.insert_many([port_doc(port_id, SWITCH) for port_id in SWITCH_PORTS]
                      + [port_doc(port_id, owner) for port_id, owner in FAR_PORTS.items()])
    connections.insert_many([cable_doc(connection_id, [near, far]) for connection_id, near, far in CABLES])
    objects.insert_many([device_doc(object_id, TYPE_DEVICE) for object_id in OBJECT_IDS])

    yield ConnectionSourceManagers(
        ports=PortsManager(database_manager), connections=PortConnectionsManager(database_manager),
        objects=ObjectsManager(database_manager), extendable_options=ExtendableOptionsManager(database_manager),
    )

    _purge()

    for collection, existing in had_indexes.items():
        for index_name in set(collection.index_information()) - existing - {MONGO_ID_INDEX}:
            collection.drop_index(index_name)


def _collect(managers: ConnectionSourceManagers, remaining: int) -> tuple[list[tuple[int, int]], list[int]]:
    """(neighbour, connection) per drawn edge, and the answered objects"""
    neighbours, objects = collect_connection_neighbours(
        target_id=SWITCH, type_scope=NeighbourTypeScope(), remaining=remaining, item_limit_active=True,
        managers=managers,
    )

    return [(neighbour.neighbour_object_id, neighbour.path[0][PortConnectionKey.PUBLIC_ID.value])
            for neighbour in neighbours], list(objects)


def test_the_lowest_neighbours_are_drawn_on_every_request(managers: ConnectionSourceManagers) -> None:
    """The read answers the highest cable first; the cut does not follow it"""
    first = _collect(managers, remaining=2)

    assert first == ([(LOW, 48301), (LOW, 48304), (MID, 48302)], [LOW, MID])
    assert _collect(managers, remaining=2) == first


def test_a_slot_is_a_neighbour_not_a_cable(managers: ConnectionSourceManagers) -> None:
    """Doubled cabling to the lowest neighbour: one node, both cables"""
    assert _collect(managers, remaining=1) == ([(LOW, 48301), (LOW, 48304)], [LOW])
