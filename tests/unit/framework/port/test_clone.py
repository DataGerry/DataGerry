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
Unit tests for cmdb.framework.port.clone

A clone's port carries its source's side and user-facing fields and nothing of its identity; an INTERNAL
connection between two source ports is remapped onto the two new ports, while a CABLE connection or one reaching
outside the source is left behind. Each batch is recorded in the ledger before it is written, ports first

Pure tests: the managers are mocks
"""
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock

import pytest

from cmdb.framework.port.clone import (
    PortClonePlan,
    clone_ports,
    cloned_connection_documents,
    cloned_port_documents,
    internal_pairs_of,
)
from cmdb.framework.write_ledger import WriteLedger
from cmdb.framework.write_ledger_constants import WriteKind
from cmdb.errors.manager.ports_manager import PortsManagerInsertError
from cmdb.models.port_connection_model import ConnectionType, PortConnectionKey
from cmdb.models.port_model import PortKey, PortSide
# -------------------------------------------------------------------------------------------------------------------- #

SOURCE_OBJECT_ID: int = 7800
TARGET_OBJECT_ID: int = 7801
AUTHOR_ID: int = 4
SOURCE_AUTHOR_ID: int = 9
CREATED_AT: datetime = datetime(2026, 1, 2, tzinfo=timezone.utc)
FRONT_ID: int = 11
REAR_ID: int = 12
OTHER_FRONT_ID: int = 13
OTHER_REAR_ID: int = 14
FOREIGN_PORT_ID: int = 99
NEW_FRONT_ID: int = 511
NEW_REAR_ID: int = 512
NEW_OTHER_FRONT_ID: int = 513
NEW_OTHER_REAR_ID: int = 514
NEW_CONNECTION_IDS: list[int] = [601, 602]


def _port(public_id: int, side: str, name: str, number: int, **values: Any) -> dict[str, Any]:
    """A stored source port."""
    return {
        PortKey.PUBLIC_ID.value: public_id, PortKey.OBJECT_ID.value: SOURCE_OBJECT_ID, PortKey.SIDE.value: side,
        PortKey.NAME.value: name, PortKey.PORT_NUMBER.value: number, PortKey.AUTHOR_ID.value: SOURCE_AUTHOR_ID,
        PortKey.CREATION_TIME.value: datetime(2020, 1, 1, tzinfo=timezone.utc),
        PortKey.LAST_EDIT_TIME.value: datetime(2021, 1, 1, tzinfo=timezone.utc), **values,
    }


def _connection(endpoints: list[int], connection_type: ConnectionType) -> dict[str, Any]:
    """A stored connection."""
    return {PortConnectionKey.ENDPOINTS.value: endpoints,
            PortConnectionKey.CONNECTION_TYPE.value: connection_type.value}


PANEL_PORTS: list[dict[str, Any]] = [
    _port(FRONT_ID, PortSide.FRONT.value, 'F1', 1),
    _port(REAR_ID, PortSide.REAR.value, 'R1', 1),
    _port(OTHER_FRONT_ID, PortSide.FRONT.value, 'F2', 2),
    _port(OTHER_REAR_ID, PortSide.REAR.value, 'R2', 2),
]
NEW_PANEL_IDS: list[int] = [NEW_FRONT_ID, NEW_REAR_ID, NEW_OTHER_FRONT_ID, NEW_OTHER_REAR_ID]


class TestInternalPairsOf:
    """internal_pairs_of"""

    def test_only_internal_connections_inside_the_source_are_kept(self) -> None:
        """A cable and a connection reaching another object stay behind"""
        connections = [
            _connection([FRONT_ID, REAR_ID], ConnectionType.INTERNAL),
            _connection([FRONT_ID, FOREIGN_PORT_ID], ConnectionType.CABLE),
            _connection([OTHER_FRONT_ID, FOREIGN_PORT_ID], ConnectionType.INTERNAL),
            _connection([OTHER_FRONT_ID, OTHER_REAR_ID], ConnectionType.INTERNAL),
        ]

        assert internal_pairs_of({FRONT_ID, REAR_ID, OTHER_FRONT_ID, OTHER_REAR_ID}, connections) == [
            (FRONT_ID, REAR_ID), (OTHER_FRONT_ID, OTHER_REAR_ID)]

    def test_a_cable_between_two_source_ports_is_not_copied(self) -> None:
        """Only a pairing is the device's own structure, whatever a stored cable joins"""
        assert not internal_pairs_of({FRONT_ID, REAR_ID}, [_connection([FRONT_ID, REAR_ID], ConnectionType.CABLE)])

    @pytest.mark.parametrize('endpoints', [None, 'x', [FRONT_ID], [FRONT_ID, REAR_ID, OTHER_REAR_ID]],
                             ids=['none', 'string', 'one-end', 'three-ends'])
    def test_an_unreadable_connection_is_skipped(self, endpoints: Any) -> None:
        """Nothing to remap"""
        connection = {PortConnectionKey.ENDPOINTS.value: endpoints,
                      PortConnectionKey.CONNECTION_TYPE.value: ConnectionType.INTERNAL.value}

        assert not internal_pairs_of({FRONT_ID, REAR_ID, OTHER_REAR_ID}, [connection])


class TestClonedPortDocuments:
    """cloned_port_documents"""

    def test_a_clone_carries_the_source_fields_and_its_own_identity(self) -> None:
        """Side, name, number and field values copied; id, owner, author and times its own"""
        source = _port(FRONT_ID, PortSide.SINGLE.value, 'Gi0/1', 1, status=21, port_type=22, speed=23,
                       description='uplink')

        assert cloned_port_documents([source], TARGET_OBJECT_ID, AUTHOR_ID, CREATED_AT) == [{
            PortKey.SIDE.value: PortSide.SINGLE.value, PortKey.NAME.value: 'Gi0/1', PortKey.PORT_NUMBER.value: 1,
            PortKey.STATUS.value: 21, PortKey.PORT_TYPE.value: 22, PortKey.SPEED.value: 23,
            PortKey.DESCRIPTION.value: 'uplink', PortKey.OBJECT_ID.value: TARGET_OBJECT_ID,
            PortKey.AUTHOR_ID.value: AUTHOR_ID, PortKey.CREATION_TIME.value: CREATED_AT,
            PortKey.LAST_EDIT_TIME.value: None,
        }]

    def test_a_key_the_source_lacks_stays_absent(self) -> None:
        """Not written as None"""
        document = cloned_port_documents(
            [{PortKey.PUBLIC_ID.value: FRONT_ID, PortKey.NAME.value: 'p'}], TARGET_OBJECT_ID, AUTHOR_ID, CREATED_AT,
        )[0]

        assert PortKey.PORT_NUMBER.value not in document and PortKey.SIDE.value not in document

    def test_the_order_is_the_source_order(self) -> None:
        """The new ids are matched to the sources by position"""
        documents = cloned_port_documents(PANEL_PORTS, TARGET_OBJECT_ID, AUTHOR_ID, CREATED_AT)

        assert [document[PortKey.NAME.value] for document in documents] == ['F1', 'R1', 'F2', 'R2']


class TestClonedConnectionDocuments:
    """cloned_connection_documents"""

    def test_each_pair_is_remapped_onto_the_new_ports(self) -> None:
        """Sorted endpoints, INTERNAL, the cloner as author"""
        new_ids = {FRONT_ID: NEW_REAR_ID, REAR_ID: NEW_FRONT_ID}

        assert cloned_connection_documents([(FRONT_ID, REAR_ID)], new_ids, AUTHOR_ID, CREATED_AT) == [{
            PortConnectionKey.ENDPOINTS.value: [NEW_FRONT_ID, NEW_REAR_ID],
            PortConnectionKey.CONNECTION_TYPE.value: ConnectionType.INTERNAL.value,
            PortConnectionKey.AUTHOR_ID.value: AUTHOR_ID, PortConnectionKey.CREATION_TIME.value: CREATED_AT,
            PortConnectionKey.LAST_EDIT_TIME.value: None,
        }]


def _managers(port_ids: list[int]) -> tuple[MagicMock, MagicMock]:
    """A ports manager answering `port_ids` and a connections manager answering two connection ids."""
    ports_manager = MagicMock()
    ports_manager.insert_many_items.return_value = port_ids
    connections_manager = MagicMock()
    connections_manager.insert_many_items.return_value = NEW_CONNECTION_IDS

    return ports_manager, connections_manager


class TestClonePorts:
    """clone_ports"""

    def test_a_panel_gets_its_ports_then_its_pairing(self) -> None:
        """The pairs joined by the new ids; the ledger names both batches before they run"""
        ports_manager, connections_manager = _managers(NEW_PANEL_IDS)
        ledger = WriteLedger()
        plan = PortClonePlan(PANEL_PORTS, [(FRONT_ID, REAR_ID), (OTHER_FRONT_ID, OTHER_REAR_ID)])

        result = clone_ports(ports_manager, connections_manager, plan, TARGET_OBJECT_ID, AUTHOR_ID, ledger)

        written = connections_manager.insert_many_items.call_args.args[0]
        assert [row[PortConnectionKey.ENDPOINTS.value] for row in written] == [
            [NEW_FRONT_ID, NEW_REAR_ID], [NEW_OTHER_FRONT_ID, NEW_OTHER_REAR_ID]]
        assert result.port_ids == NEW_PANEL_IDS and result.connection_ids == NEW_CONNECTION_IDS
        assert [(entry.kind, entry.manager, entry.criteria) for entry in ledger.entries] == [
            (WriteKind.INSERT_BATCH, ports_manager, {PortKey.OBJECT_ID.value: TARGET_OBJECT_ID}),
            (WriteKind.INSERT_BATCH, connections_manager, {
                PortConnectionKey.ENDPOINTS.value: {'$in': NEW_PANEL_IDS},
                PortConnectionKey.CONNECTION_TYPE.value: ConnectionType.INTERNAL.value}),
        ]

    def test_a_device_without_pairs_writes_no_connection(self) -> None:
        """One batch"""
        ports_manager, connections_manager = _managers([NEW_FRONT_ID])
        ledger = WriteLedger()

        result = clone_ports(ports_manager, connections_manager, PortClonePlan(PANEL_PORTS[:1], []),
                             TARGET_OBJECT_ID, AUTHOR_ID, ledger)

        connections_manager.insert_many_items.assert_not_called()
        assert result.connection_ids == [] and len(ledger.entries) == 1

    def test_no_port_writes_nothing(self) -> None:
        """Not even a ledger entry"""
        ports_manager, connections_manager = _managers([])
        ledger = WriteLedger()

        result = clone_ports(ports_manager, connections_manager, PortClonePlan([], []), TARGET_OBJECT_ID,
                             AUTHOR_ID, ledger)

        ports_manager.insert_many_items.assert_not_called()
        assert result.port_ids == [] and not ledger.entries

    def test_a_failed_port_batch_is_recorded_before_it_raised(self) -> None:
        """The undo can still reach what an unordered batch stored"""
        ports_manager, connections_manager = _managers([])
        ports_manager.insert_many_items.side_effect = PortsManagerInsertError('write failed')
        ledger = WriteLedger()

        with pytest.raises(PortsManagerInsertError):
            clone_ports(ports_manager, connections_manager, PortClonePlan(PANEL_PORTS, []), TARGET_OBJECT_ID,
                        AUTHOR_ID, ledger)

        assert [entry.criteria for entry in ledger.entries] == [{PortKey.OBJECT_ID.value: TARGET_OBJECT_ID}]
