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
Unit tests for cmdb.framework.port.cascade

A port is stored outside its owner's document and a connection outside both of the ports it joins, so this cascade
is the only thing that removes either when the ports go.

Two rules are pinned. The ORDER: a connection is found through its endpoints and a link through its port_id, and a
port names neither, so connections and links go before the ports. And ALL OR NOTHING: each delete is recorded in the
caller's WriteLedger with the documents it removes before it runs, so a failure part-way is undone.

Pure tests: the managers are mocks; one test runs the real WriteLedger undo against them
"""
from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest

from cmdb.manager.manager_provider_model import ManagerType

from cmdb.framework.port.cascade import (
    PortCascadeResult,
    PortStoreManagers,
    delete_ports_with_dependents,
    port_ids_of_object,
)
from cmdb.framework.port.cascade_constants import CascadeLedgerDescription
from cmdb.framework.write_ledger import WriteLedger
from cmdb.interface.rest_api.routes.port_routes import port_object_hooks

from cmdb.errors.manager.ports_manager import PortsManagerDeleteError
# -------------------------------------------------------------------------------------------------------------------- #

OBJECT_ID: int = 5000
PORT_IDS: list[int] = [7102, 7101]
SORTED_PORT_IDS: str = str(sorted(PORT_IDS))

# Distinct counts per collection, so a swapped count fails
REMOVED_CONNECTIONS: int = 3
REMOVED_LINKS: int = 5
REMOVED_PORTS: int = 2

CONNECTION_SNAPSHOT: list[dict[str, Any]] = [{'_id': 'c1', 'public_id': 61, 'endpoints': [7101, 9001]}]
LINK_SNAPSHOT: list[dict[str, Any]] = [{'_id': 'l1', 'public_id': 71, 'port_id': 7101}]
PORT_SNAPSHOT: list[dict[str, Any]] = [{'_id': 'p1', 'public_id': 7101}, {'_id': 'p2', 'public_id': 7102}]

HOOK_PATH: str = 'cmdb.interface.rest_api.routes.port_routes.port_object_hooks'


def _managers(calls: list[str] | None = None) -> PortStoreManagers:
    """Three manager stand-ins answering the snapshots and counts above, recording their calls in order"""
    recorded: list[str] = calls if calls is not None else []

    def _answer(name: str, value: Any) -> Any:
        return lambda *_args, **_kwargs: recorded.append(name) or value

    ports = MagicMock(name='ports_manager', collection='framework.ports')
    ports.snapshot_ports.side_effect = _answer('snapshot ports', PORT_SNAPSHOT)
    ports.delete_ports_by_ids.side_effect = _answer('delete ports', REMOVED_PORTS)
    ports.get_port_kinds_of_object.side_effect = _answer(
        'read port ids', [{'public_id': port_id} for port_id in PORT_IDS],
    )

    connections = MagicMock(name='port_connections_manager', collection='framework.portConnections')
    connections.snapshot_connections_of_ports.side_effect = _answer('snapshot connections', CONNECTION_SNAPSHOT)
    connections.delete_connections_of_ports.side_effect = _answer('delete connections', REMOVED_CONNECTIONS)

    links = MagicMock(name='port_interface_links_manager', collection='framework.portInterfaceLinks')
    links.snapshot_links_of_ports.side_effect = _answer('snapshot links', LINK_SNAPSHOT)
    links.delete_links_of_ports.side_effect = _answer('delete links', REMOVED_LINKS)

    return PortStoreManagers(ports=ports, connections=connections, interface_links=links)


def _object(public_id: Any = OBJECT_ID) -> dict[str, Any]:
    """A deleted CmdbObject document"""
    return {'public_id': public_id, 'type_id': 42}

# -------------------------------------------------------------------------------------------------------------------- #
#                                                  port_ids_of_object                                                  #
# -------------------------------------------------------------------------------------------------------------------- #

def test_the_port_ids_of_an_object_are_read_once_through_the_projected_read() -> None:
    """Only ids, sides and the owner are read - never the whole port documents"""
    managers = _managers()

    assert port_ids_of_object(managers.ports, OBJECT_ID) == PORT_IDS
    managers.ports.get_port_kinds_of_object.assert_called_once_with(OBJECT_ID)
    managers.ports.get_ports_of_object.assert_not_called()


def test_a_port_row_without_a_usable_id_is_dropped() -> None:
    """A null would otherwise reach the following $in"""
    ports = MagicMock()
    ports.get_port_kinds_of_object.return_value = [{'public_id': 7101}, {'public_id': None}, {}, {'public_id': 'x'}]

    assert port_ids_of_object(ports, OBJECT_ID) == [7101]

# -------------------------------------------------------------------------------------------------------------------- #
#                                             delete_ports_with_dependents                                             #
# -------------------------------------------------------------------------------------------------------------------- #

def test_dependents_go_first_and_each_is_snapshotted_before_its_delete() -> None:
    """Connections, then links, then ports - each read whole before the statement that removes it"""
    calls: list[str] = []

    delete_ports_with_dependents(_managers(calls), PORT_IDS, MagicMock())

    assert calls == ['snapshot connections', 'delete connections', 'snapshot links', 'delete links',
                     'snapshot ports', 'delete ports']


def test_each_delete_is_one_statement_for_the_whole_selection() -> None:
    """The same id list reaches every read and every delete"""
    managers = _managers()

    delete_ports_with_dependents(managers, PORT_IDS, MagicMock())

    managers.connections.snapshot_connections_of_ports.assert_called_once_with(PORT_IDS)
    managers.connections.delete_connections_of_ports.assert_called_once_with(PORT_IDS)
    managers.interface_links.snapshot_links_of_ports.assert_called_once_with(PORT_IDS)
    managers.interface_links.delete_links_of_ports.assert_called_once_with(PORT_IDS)
    managers.ports.snapshot_ports.assert_called_once_with(PORT_IDS)
    managers.ports.delete_ports_by_ids.assert_called_once_with(PORT_IDS)


def test_the_ledger_records_each_snapshot_with_its_manager_and_name() -> None:
    """What the undo will put back, and what a residue report will call it"""
    managers = _managers()
    ledger = MagicMock()

    delete_ports_with_dependents(managers, PORT_IDS, ledger)

    assert ledger.deleted_many.call_args_list == [
        call(managers.connections, CONNECTION_SNAPSHOT,
             CascadeLedgerDescription.CONNECTIONS.value.format(port_ids=SORTED_PORT_IDS)),
        call(managers.interface_links, LINK_SNAPSHOT,
             CascadeLedgerDescription.INTERFACE_LINKS.value.format(port_ids=SORTED_PORT_IDS)),
        call(managers.ports, PORT_SNAPSHOT, CascadeLedgerDescription.PORTS.value.format(port_ids=SORTED_PORT_IDS)),
    ]


def test_the_result_counts_each_collection() -> None:
    """Distinct counts per collection, so a swap fails"""
    assert delete_ports_with_dependents(_managers(), PORT_IDS, MagicMock()) == PortCascadeResult(
        connections=REMOVED_CONNECTIONS, interface_links=REMOVED_LINKS, ports=REMOVED_PORTS,
    )


def test_no_ports_reads_and_records_nothing() -> None:
    """An object without ports costs no query at all"""
    managers = _managers()
    ledger = MagicMock()

    assert delete_ports_with_dependents(managers, [], ledger) == PortCascadeResult(0, 0, 0)
    managers.connections.snapshot_connections_of_ports.assert_not_called()
    managers.ports.delete_ports_by_ids.assert_not_called()
    ledger.deleted_many.assert_not_called()


def test_a_failing_last_step_has_recorded_every_earlier_delete() -> None:
    """The ports' delete fails: connections and links are already in the ledger, so the undo can restore them"""
    managers = _managers()
    managers.ports.delete_ports_by_ids.side_effect = PortsManagerDeleteError('gone')
    ledger = MagicMock()

    with pytest.raises(PortsManagerDeleteError):
        delete_ports_with_dependents(managers, PORT_IDS, ledger)

    assert [entry.args[0] for entry in ledger.deleted_many.call_args_list] == [
        managers.connections, managers.interface_links, managers.ports,
    ]


def test_the_real_ledger_restores_what_was_deleted_before_the_failure() -> None:
    """WriteLedger.undo re-inserts the snapshots no longer stored - here the connections and links"""
    managers = _managers()
    managers.ports.delete_ports_by_ids.side_effect = PortsManagerDeleteError('gone')

    for manager, snapshot in ((managers.connections, CONNECTION_SNAPSHOT), (managers.interface_links, LINK_SNAPSHOT),
                              (managers.ports, PORT_SNAPSHOT)):
        manager.find.return_value = []
        manager.count_documents.return_value = len(snapshot)

    managers.ports.find.return_value = [{'_id': snapshot['_id']} for snapshot in PORT_SNAPSHOT]
    ledger = WriteLedger()

    with pytest.raises(PortsManagerDeleteError):
        delete_ports_with_dependents(managers, PORT_IDS, ledger)

    assert not ledger.undo()
    managers.connections.insert_many.assert_called_once_with(CONNECTION_SNAPSHOT, skip_public=True)
    managers.interface_links.insert_many.assert_called_once_with(LINK_SNAPSHOT, skip_public=True)
    managers.ports.insert_many.assert_not_called()


def test_the_removal_is_logged(caplog) -> None:
    """One line naming the three counts"""
    with caplog.at_level('INFO'):
        delete_ports_with_dependents(_managers(), PORT_IDS, MagicMock())

    assert f'deleted {REMOVED_PORTS} port(s), {REMOVED_CONNECTIONS} connection(s), {REMOVED_LINKS}' in caplog.text

# -------------------------------------------------------------------------------------------------------------------- #
#                                         the hook the /objects routes call                                            #
# -------------------------------------------------------------------------------------------------------------------- #

def _provider(managers: PortStoreManagers) -> Any:
    """ManagerProvider.get_manager answering the three stand-ins"""
    return lambda manager_type, _user: {
        ManagerType.PORTS: managers.ports,
        ManagerType.PORT_CONNECTIONS: managers.connections,
        ManagerType.PORT_INTERFACE_LINKS: managers.interface_links,
    }[manager_type]


def test_the_hook_reads_the_ids_once_then_runs_the_cascade() -> None:
    """The ids first, then the whole cascade in its order"""
    calls: list[str] = []
    managers = _managers(calls)

    with patch(f'{HOOK_PATH}.ManagerProvider.get_manager', side_effect=_provider(managers)):
        port_object_hooks.handle_object_deleted(MagicMock(), _object())

    assert calls == ['read port ids', 'snapshot connections', 'delete connections', 'snapshot links',
                     'delete links', 'snapshot ports', 'delete ports']
    managers.ports.delete_ports_by_ids.assert_called_once_with(PORT_IDS)


def test_the_hook_uses_the_managers_it_is_given() -> None:
    """The bulk object delete resolves the three managers once and passes them in"""
    managers = _managers()

    with patch(f'{HOOK_PATH}.ManagerProvider.get_manager') as get_manager:
        port_object_hooks.handle_object_deleted(
            MagicMock(), _object(), managers.ports, managers.connections, managers.interface_links,
        )

    get_manager.assert_not_called()
    managers.ports.delete_ports_by_ids.assert_called_once_with(PORT_IDS)


@pytest.mark.parametrize('public_id', [None, 'not-an-int'], ids=['none', 'string'])
def test_the_hook_resolves_no_manager_for_a_malformed_document(public_id: Any) -> None:
    """Every object deletion runs this hook, so a malformed document must not cost a manager"""
    with patch(f'{HOOK_PATH}.ManagerProvider.get_manager') as get_manager:
        port_object_hooks.handle_object_deleted(MagicMock(), _object(public_id))

    get_manager.assert_not_called()


def test_the_hook_undoes_a_cascade_that_fails_part_way_and_raises_the_error() -> None:
    """The error reaches the object route as before, after the connections and links are put back"""
    managers = _managers()
    managers.ports.delete_ports_by_ids.side_effect = PortsManagerDeleteError('gone')

    for manager, snapshot in ((managers.connections, CONNECTION_SNAPSHOT), (managers.interface_links, LINK_SNAPSHOT),
                              (managers.ports, PORT_SNAPSHOT)):
        manager.find.return_value = []
        manager.count_documents.return_value = len(snapshot)

    with pytest.raises(PortsManagerDeleteError):
        port_object_hooks.handle_object_deleted(
            MagicMock(), _object(), managers.ports, managers.connections, managers.interface_links,
        )

    managers.connections.insert_many.assert_called_once_with(CONNECTION_SNAPSHOT, skip_public=True)
    managers.interface_links.insert_many.assert_called_once_with(LINK_SNAPSHOT, skip_public=True)
