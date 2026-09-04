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

A port is stored outside its owner's document and a connection outside both of the ports it joins, so
this cascade is the only thing that removes either when the object goes.

The rule these tests exist to pin is the ORDER: a connection is found through its endpoints and a port
does not name its connections, so the ports have to be READ before they are deleted. Getting it the
wrong way round leaves links whose endpoint no longer resolves, and nothing downstream would notice.

Pure tests: the managers are mocks, so what is asserted is that each removal is a single statement,
that it is never skipped for a reason the user cannot see, and that the two halves run in the right
sequence
"""
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from cmdb.manager.manager_provider_model import ManagerType

from cmdb.framework.port.cascade import (
    delete_connections_of_ports,
    delete_connections_of_port,
    delete_interface_links_of_ports,
    delete_interface_links_of_port,
    delete_ports_of_object,
    port_ids_of_object,
)
from cmdb.interface.rest_api.routes.port_routes import port_object_hooks
# -------------------------------------------------------------------------------------------------------------------- #

OBJECT_ID: int = 5000


def _manager(removed: int = 0) -> MagicMock:
    """A PortsManager stand-in reporting the given number of removed ports."""
    manager = MagicMock(name='ports_manager')
    manager.delete_ports_of_object.return_value = removed

    return manager


def _object(public_id: Any = OBJECT_ID) -> dict[str, Any]:
    """A deleted CmdbObject document."""
    return {'public_id': public_id, 'type_id': 42}


PORT_IDS: list[int] = [7101, 7102]


def _connections_manager(removed: int = 0) -> MagicMock:
    """A PortConnectionsManager stand-in reporting the given number of removed connections."""
    manager = MagicMock(name='port_connections_manager')
    manager.delete_connections_of_ports.return_value = removed

    return manager


def _ports_manager_with(port_ids: list[Any], removed: int = 0) -> MagicMock:
    """A PortsManager stand-in whose object read answers with ports carrying the given ids."""
    manager = _manager(removed=removed)
    manager.get_ports_of_object.return_value = [{'public_id': port_id} for port_id in port_ids]

    return manager


def _links_manager(removed: int = 0) -> MagicMock:
    """A PortInterfaceLinksManager stand-in reporting the given number of removed links."""
    manager = MagicMock(name='port_interface_links_manager')
    manager.delete_links_of_ports.return_value = removed

    return manager


def test_removes_the_ports_in_one_statement() -> None:
    """One delete for the whole object, not one per port"""
    manager = _manager(removed=3)

    assert delete_ports_of_object(manager, _object()) == 3
    manager.delete_ports_of_object.assert_called_once_with(OBJECT_ID)


def test_an_object_without_ports_is_a_no_op() -> None:
    """The common case: one indexed delete that matches nothing"""
    manager = _manager(removed=0)

    assert delete_ports_of_object(manager, _object()) == 0


@pytest.mark.parametrize('public_id', [None, 'not-an-int', 1.5], ids=['none', 'string', 'float'])
def test_a_document_without_an_integer_public_id_is_skipped(public_id: Any) -> None:
    """
    A malformed document must not turn into a delete with a garbage filter

    `{'object_id': None}` would match every port whose owner key is missing, which is the kind of
    filter that empties a collection.
    """
    manager = _manager()

    assert delete_ports_of_object(manager, _object(public_id)) == 0
    manager.delete_ports_of_object.assert_not_called()


def test_the_type_flag_is_not_consulted() -> None:
    """
    Cleanup may not depend on `uses_ports`

    The flag can be turned off after the ports were created; gating the cascade on it would orphan
    exactly the rows the cascade exists to remove. The document carries no flag here and the ports go
    anyway.
    """
    manager = _manager(removed=1)

    assert delete_ports_of_object(manager, {'public_id': OBJECT_ID}) == 1


def test_reports_the_removal(caplog) -> None:
    """A cascade that removed rows says so, so an unexpected mass delete is traceable"""
    manager = _manager(removed=7)

    with caplog.at_level('INFO'):
        delete_ports_of_object(manager, _object())

    assert '7 port(s)' in caplog.text


def test_says_nothing_when_there_was_nothing_to_remove(caplog) -> None:
    """Every object deletion runs this; a log line per deletion would be noise"""
    manager = _manager(removed=0)

    with caplog.at_level('INFO'):
        delete_ports_of_object(manager, _object())

    assert caplog.text == ''


# -------------------------------------------------------------------------------------------------------------------- #
#                                       the hook the /objects routes call                                              #
# -------------------------------------------------------------------------------------------------------------------- #
HOOK_PATH: str = 'cmdb.interface.rest_api.routes.port_routes.port_object_hooks'


def test_the_hook_resolves_the_managers_and_delegates() -> None:
    """The hook is request-shaped; the statements themselves live in the cascade"""
    ports_manager = _ports_manager_with(PORT_IDS, removed=2)
    connections_manager = _connections_manager(removed=3)
    links_manager = _links_manager(removed=1)

    with patch(f'{HOOK_PATH}.ManagerProvider.get_manager',
               side_effect=lambda manager_type, _user: {
                   ManagerType.PORTS: ports_manager,
                   ManagerType.PORT_CONNECTIONS: connections_manager,
                   ManagerType.PORT_INTERFACE_LINKS: links_manager,
               }[manager_type]):
        port_object_hooks.handle_object_deleted(MagicMock(), _object())

    ports_manager.delete_ports_of_object.assert_called_once_with(OBJECT_ID)
    connections_manager.delete_connections_of_ports.assert_called_once_with(PORT_IDS)
    links_manager.delete_links_of_ports.assert_called_once_with(PORT_IDS)


@pytest.mark.parametrize('public_id', [None, 'not-an-int'], ids=['none', 'string'])
def test_the_hook_resolves_no_manager_for_a_malformed_document(public_id: Any) -> None:
    """
    Every object deletion runs this hook, so a malformed document must not cost a manager

    ManagerProvider needs an application context; building one for a document that cannot have ports
    would be pure waste on a path that runs for every delete.
    """
    with patch(f'{HOOK_PATH}.ManagerProvider.get_manager') as get_manager:
        port_object_hooks.handle_object_deleted(MagicMock(), _object(public_id))

    get_manager.assert_not_called()


# -------------------------------------------------------------------------------------------------------------------- #
#                                     the connections of one deleted port                                              #
# -------------------------------------------------------------------------------------------------------------------- #
def test_a_deleted_port_takes_its_connections_with_it() -> None:
    """A port may not leave a link pointing at nothing"""
    connections_manager = _connections_manager(removed=2)

    assert delete_connections_of_port(connections_manager, PORT_IDS[0]) == 2
    connections_manager.delete_connections_of_ports.assert_called_once_with([PORT_IDS[0]])


def test_a_free_port_costs_one_statement_and_removes_nothing() -> None:
    """The common case - most ports are connected to nothing"""
    connections_manager = _connections_manager()

    assert delete_connections_of_port(connections_manager, PORT_IDS[0]) == 0


def test_only_the_deleted_ports_connections_are_named() -> None:
    """
    The scope is one port

    A filter that was slightly too wide would silently unpatch a whole rack, which is exactly what
    the rule 'deleting one connection must never delete another' forbids.
    """
    connections_manager = _connections_manager(removed=1)

    delete_connections_of_port(connections_manager, PORT_IDS[1])

    assert connections_manager.delete_connections_of_ports.call_args.args[0] == [PORT_IDS[1]]


# -------------------------------------------------------------------------------------------------------------------- #
#                                the connections of a deleted object's ports                                           #
# -------------------------------------------------------------------------------------------------------------------- #
def test_the_object_cascade_reads_the_ports_before_removing_their_connections() -> None:
    """
    The whole point of this half: the ids have to be collected while the ports still exist

    A connection is found through its endpoints, so once the ports are gone there is no way left to
    reach the links that pointed at them.
    """
    ports_manager = _ports_manager_with(PORT_IDS)
    connections_manager = _connections_manager(removed=3)

    assert delete_connections_of_ports(connections_manager, port_ids_of_object(ports_manager, OBJECT_ID)) == 3

    ports_manager.get_ports_of_object.assert_called_once_with(OBJECT_ID)
    connections_manager.delete_connections_of_ports.assert_called_once_with(PORT_IDS)


def test_an_object_without_ports_costs_no_delete() -> None:
    """The common case on every object deletion - most objects have no ports at all"""
    ports_manager = _ports_manager_with([])
    connections_manager = _connections_manager()

    assert delete_connections_of_ports(connections_manager, port_ids_of_object(ports_manager, OBJECT_ID)) == 0
    connections_manager.delete_connections_of_ports.assert_not_called()


def test_a_port_document_without_a_usable_id_is_skipped() -> None:
    """A drifted row must not put a null into the $in and take unrelated connections with it"""
    ports_manager = _ports_manager_with([PORT_IDS[0], None, 'not-an-int'])
    connections_manager = _connections_manager(removed=1)

    delete_connections_of_ports(connections_manager, port_ids_of_object(ports_manager, OBJECT_ID))

    assert connections_manager.delete_connections_of_ports.call_args.args[0] == [PORT_IDS[0]]


def test_the_object_cascade_reports_the_removal(caplog) -> None:
    """An operator has to be able to see what a deletion took with it"""
    ports_manager = _ports_manager_with(PORT_IDS)
    connections_manager = _connections_manager(removed=3)

    with caplog.at_level('INFO'):
        delete_connections_of_ports(connections_manager, port_ids_of_object(ports_manager, OBJECT_ID))

    assert 'removed 3 connection(s)' in caplog.text


# -------------------------------------------------------------------------------------------------------------------- #
#                              the hook runs both halves, connections first                                            #
# -------------------------------------------------------------------------------------------------------------------- #
def test_the_hook_removes_everything_referencing_the_ports_before_the_ports() -> None:
    """
    The ordering the whole cascade depends on, asserted as an ordering rather than as three calls

    A connection is found through its endpoints and a link through its port_id; a port names neither.
    Deleting the ports first would therefore leave both behind with nothing left to reach them by, and
    every statement would still report success.
    """
    calls: list[str] = []

    ports_manager = _ports_manager_with(PORT_IDS)
    ports_manager.get_ports_of_object.side_effect = lambda _object_id: (
        calls.append('read ports') or [{'public_id': port_id} for port_id in PORT_IDS]
    )
    ports_manager.delete_ports_of_object.side_effect = lambda _object_id: calls.append('delete ports') or 2

    connections_manager = _connections_manager(removed=3)
    connections_manager.delete_connections_of_ports.side_effect = (
        lambda _port_ids: calls.append('delete connections') or 3
    )

    links_manager = _links_manager(removed=1)
    links_manager.delete_links_of_ports.side_effect = (
        lambda _port_ids: calls.append('delete links') or 1
    )

    with patch(f'{HOOK_PATH}.ManagerProvider.get_manager',
               side_effect=lambda manager_type, _user: {
                   ManagerType.PORTS: ports_manager,
                   ManagerType.PORT_CONNECTIONS: connections_manager,
                   ManagerType.PORT_INTERFACE_LINKS: links_manager,
               }[manager_type]):
        port_object_hooks.handle_object_deleted(MagicMock(), _object())

    # The ports are read ONCE and the ids shared: both cascades answer the same question, so a second
    # read would cost a query on every object deletion for no new information
    assert calls == ['read ports', 'delete connections', 'delete links', 'delete ports']


# -------------------------------------------------------------------------------------------------------------------- #
#                                      the interface links of a deleted port                                           #
# -------------------------------------------------------------------------------------------------------------------- #
def test_a_deleted_port_takes_its_interface_links_with_it() -> None:
    """
    The port half of a link is a HARD reference

    A link without its port is a row nothing can reach and nothing can repair - unlike the interface
    half, which is soft precisely so a vanished row can be reported.
    """
    links_manager = _links_manager(removed=2)

    assert delete_interface_links_of_port(links_manager, PORT_IDS[0]) == 2
    links_manager.delete_links_of_ports.assert_called_once_with([PORT_IDS[0]])


def test_a_port_without_links_removes_nothing() -> None:
    """Most ports are not linked to an interface at all"""
    assert delete_interface_links_of_port(_links_manager(), PORT_IDS[0]) == 0


def test_the_object_cascade_removes_the_links_of_every_port() -> None:
    """The ids are read while the ports still exist, exactly as for the connections"""
    ports_manager = _ports_manager_with(PORT_IDS)
    links_manager = _links_manager(removed=3)

    assert delete_interface_links_of_ports(links_manager, port_ids_of_object(ports_manager, OBJECT_ID)) == 3
    links_manager.delete_links_of_ports.assert_called_once_with(PORT_IDS)


def test_an_object_without_ports_removes_no_links() -> None:
    """The common case on every object deletion"""
    links_manager = _links_manager()

    assert delete_interface_links_of_ports(links_manager, port_ids_of_object(_ports_manager_with([]), OBJECT_ID)) == 0
    links_manager.delete_links_of_ports.assert_not_called()


def test_the_link_cascade_reports_the_removal(caplog) -> None:
    """An operator has to be able to see what a deletion took with it"""
    with caplog.at_level('INFO'):
        delete_interface_links_of_port(_links_manager(removed=2), PORT_IDS[0])

    assert 'removed 2 interface link(s)' in caplog.text


# -------------------------------------------------------------------------------------------------------------------- #
#                                          the shared port-id read                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
def test_the_port_ids_of_an_object_are_read_once() -> None:
    """
    The read both cascades start from, extracted so they cannot disagree about what a port id is

    Reading only the ids is what keeps a device with many ports at one query rather than one per port.
    """
    ports_manager = _ports_manager_with(PORT_IDS)

    assert port_ids_of_object(ports_manager, OBJECT_ID) == PORT_IDS
    ports_manager.get_ports_of_object.assert_called_once_with(OBJECT_ID)


def test_a_port_row_without_a_usable_id_is_dropped() -> None:
    """A drifted row must not put a null into the following $in and take unrelated rows with it"""
    ports_manager = _ports_manager_with([PORT_IDS[0], None, 'not-an-int'])

    assert port_ids_of_object(ports_manager, OBJECT_ID) == [PORT_IDS[0]]
