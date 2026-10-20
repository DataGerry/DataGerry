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
Integration tests of cloning a CmdbObject's ports against a real MongoDB

With the declared unique indexes built: a cloned patch panel stores one port per source port and its pairing
on the new ports, and when the pairing fails the request's ledger takes every cloned port back - counted in the
collections, not in a return value
"""
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.port_connections_manager import PortConnectionsManager
from cmdb.manager.ports_manager import PortsManager
from cmdb.models.port_connection_model import CmdbPortConnection, ConnectionType, PortConnectionKey
from cmdb.models.port_model import CmdbPort, PortKey, PortSide
from cmdb.framework.port.clone import PortClonePlan, clone_ports, internal_pairs_of
from cmdb.framework.write_ledger import WriteLedger
from cmdb.errors.manager.port_connections_manager import PortConnectionsManagerInsertError
# -------------------------------------------------------------------------------------------------------------------- #

SOURCE_ID: int = 47950
TARGET_ID: int = 47951
AUTHOR_ID: int = 1
FRONT_ID, REAR_ID = 47960, 47961
OBJECT_IDS: list[int] = [SOURCE_ID, TARGET_ID]


@pytest.fixture(name='collections')
def fixture_collections(database_manager: MongoDatabaseManager, database_name: str):
    """Ports and connections with their indexes built; a one-pair panel on the source; cleared around each test"""
    ports = database_manager.get_collection(CmdbPort.COLLECTION, database_name)
    connections = database_manager.get_collection(CmdbPortConnection.COLLECTION, database_name)
    database_manager.create_indexes(CmdbPort.COLLECTION, database_name, CmdbPort.get_index_keys())
    database_manager.create_indexes(
        CmdbPortConnection.COLLECTION, database_name, CmdbPortConnection.get_index_keys(),
    )

    def _purge() -> None:
        port_ids = [row[PortKey.PUBLIC_ID.value]
                    for row in ports.find({PortKey.OBJECT_ID.value: {'$in': OBJECT_IDS}})]
        connections.delete_many({PortConnectionKey.ENDPOINTS.value: {'$in': port_ids}})
        ports.delete_many({PortKey.OBJECT_ID.value: {'$in': OBJECT_IDS}})

    _purge()
    ports.insert_many([
        {PortKey.PUBLIC_ID.value: FRONT_ID, PortKey.OBJECT_ID.value: SOURCE_ID,
         PortKey.SIDE.value: PortSide.FRONT.value, PortKey.NAME.value: 'F1', PortKey.PORT_NUMBER.value: 1},
        {PortKey.PUBLIC_ID.value: REAR_ID, PortKey.OBJECT_ID.value: SOURCE_ID,
         PortKey.SIDE.value: PortSide.REAR.value, PortKey.NAME.value: 'R1', PortKey.PORT_NUMBER.value: 1},
    ])
    connections.insert_one({PortConnectionKey.PUBLIC_ID.value: 47970,
                            PortConnectionKey.ENDPOINTS.value: [FRONT_ID, REAR_ID],
                            PortConnectionKey.CONNECTION_TYPE.value: ConnectionType.INTERNAL.value})

    yield ports, connections

    _purge()


def _plan(ports_manager: PortsManager, connections_manager: PortConnectionsManager) -> PortClonePlan:
    """The source's plan, read the way the hook reads it."""
    ports: list[dict[str, Any]] = ports_manager.get_ports_of_object(SOURCE_ID)
    port_ids: list[int] = [port[PortKey.PUBLIC_ID.value] for port in ports]

    pairs = internal_pairs_of(set(port_ids), connections_manager.get_connections_of_ports(port_ids))

    return PortClonePlan(ports, pairs)


def test_a_panel_is_stored_with_its_pairing(database_manager: MongoDatabaseManager, collections) -> None:
    """Two new ports, one INTERNAL connection between them"""
    ports, connections = collections
    ports_manager, connections_manager = PortsManager(database_manager), PortConnectionsManager(database_manager)

    result = clone_ports(ports_manager, connections_manager, _plan(ports_manager, connections_manager), TARGET_ID,
                         AUTHOR_ID, WriteLedger())

    stored = {row[PortKey.NAME.value]: row[PortKey.PUBLIC_ID.value]
              for row in ports.find({PortKey.OBJECT_ID.value: TARGET_ID})}
    pairing = connections.find_one({PortConnectionKey.PUBLIC_ID.value: result.connection_ids[0]})

    assert sorted(stored.values()) == sorted(result.port_ids) and set(stored) == {'F1', 'R1'}
    assert pairing[PortConnectionKey.ENDPOINTS.value] == sorted([stored['F1'], stored['R1']])


def test_a_failed_pairing_is_undone_by_the_ledger(database_manager: MongoDatabaseManager, collections,
                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    """No cloned port survives; the source is untouched"""
    ports, connections = collections
    ports_manager, connections_manager = PortsManager(database_manager), PortConnectionsManager(database_manager)
    plan = _plan(ports_manager, connections_manager)
    ledger = WriteLedger()

    def _fail(*_args: Any, **_kwargs: Any) -> None:
        raise PortConnectionsManagerInsertError('write failed')

    monkeypatch.setattr(connections_manager, 'insert_many_items', _fail)

    with pytest.raises(PortConnectionsManagerInsertError):
        clone_ports(ports_manager, connections_manager, plan, TARGET_ID, AUTHOR_ID, ledger)

    assert not ledger.undo()
    assert ports.count_documents({PortKey.OBJECT_ID.value: TARGET_ID}) == 0
    assert ports.count_documents({PortKey.OBJECT_ID.value: SOURCE_ID}) == 2
    assert connections.count_documents({PortConnectionKey.ENDPOINTS.value: {'$in': [FRONT_ID, REAR_ID]}}) == 1
