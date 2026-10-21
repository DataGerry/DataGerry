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
Unit tests for cmdb.manager.port_interface_links_manager

DB-free: the manager is built against a mocked MongoDatabaseManager, which its __init__ only stores.
What is tested is the binding, the two registries a manager is unreachable without, and the reads and
the delete it adds - in particular that each read matches one of the declared indexes, since the two
directions (a port's interfaces, and the links pointing into one object) are what the index pair exists
for. The CRUD itself is covered once, in test_generic_manager.py
"""
from typing import Any
from unittest.mock import MagicMock

import pytest

from cmdb.manager import PortInterfaceLinksManager
from cmdb.manager.generic_manager import GenericManager
from cmdb.manager.manager_provider_model import MANAGER_CLASSES, ManagerType
from cmdb.models.port_interface_link_model import CmdbPortInterfaceLink, PortInterfaceLinkKey
from cmdb.errors.manager import BaseManagerDeleteError, BaseManagerGetError
from cmdb.errors.manager.port_interface_links_manager import (
    PORT_INTERFACE_LINKS_MANAGER_ERRORS,
    PortInterfaceLinksManagerDeleteError,
    PortInterfaceLinksManagerGetError,
)
# -------------------------------------------------------------------------------------------------------------------- #

DB_NAME: str = 'testdb'

PORT_ID: int = 8200
OTHER_PORT_ID: int = 8201
LINK_ID: int = 8400


@pytest.fixture(name='manager')
def fixture_manager() -> PortInterfaceLinksManager:
    """A PortInterfaceLinksManager over a mocked database manager (its __init__ performs no I/O)"""
    return PortInterfaceLinksManager(MagicMock(name='dbm'), DB_NAME)


class TestTheBinding:
    """What the manager is bound to."""

    def test_is_a_generic_manager(self, manager: PortInterfaceLinksManager) -> None:
        """The CRUD is plain, so the shared implementation covers it"""
        assert isinstance(manager, GenericManager)

    def test_stores_port_interface_links(self, manager: PortInterfaceLinksManager) -> None:
        """The model decides both the collection and how documents are (de)serialised"""
        assert manager.model is CmdbPortInterfaceLink
        assert manager.collection == CmdbPortInterfaceLink.COLLECTION

    def test_uses_its_own_exception_map(self, manager: PortInterfaceLinksManager) -> None:
        """A failure has to surface as this manager's error, not another domain's"""
        assert manager.exceptions is PORT_INTERFACE_LINKS_MANAGER_ERRORS

    def test_a_broken_construction_is_not_wrapped(self) -> None:
        """
        Building the manager touches no database: a failure there is a bug, raised as itself (the route's 500),
        never one of the manager's mapped errors, which read like a database failure
        """
        broken = MagicMock(name='dbm')
        type(broken).db_name = property(lambda _self: (_ for _ in ()).throw(RuntimeError('no db')))

        with pytest.raises(RuntimeError):
            PortInterfaceLinksManager(broken)


class TestTheRegistration:
    """Without these two entries the manager cannot be obtained by a route."""

    def test_the_manager_type_exists(self) -> None:
        """ManagerType is how a route names the manager it wants"""
        assert ManagerType.PORT_INTERFACE_LINKS.value == 'PortInterfaceLinksManager'

    def test_the_provider_resolves_the_manager_type(self) -> None:
        """Without this entry the route's get_manager call would raise BaseManagerInitError"""
        assert MANAGER_CLASSES[ManagerType.PORT_INTERFACE_LINKS] is PortInterfaceLinksManager


class TestGetLinksOfPort:
    """'Which interfaces does this port carry' - one indexed predicate."""

    def test_filters_on_the_port(self, manager: PortInterfaceLinksManager) -> None:
        """Served by the declared port_id index"""
        manager.find = MagicMock(return_value=[])

        manager.get_links_of_port(PORT_ID)

        assert manager.find.call_args.kwargs['criteria'] == {
            PortInterfaceLinkKey.PORT_ID.value: PORT_ID,
        }

    def test_returns_every_link_of_the_port(self, manager: PortInterfaceLinksManager) -> None:
        """A port legitimately has several - a bond member plus VLAN sub-interfaces"""
        found = [{'public_id': 1}, {'public_id': 2}]
        manager.find = MagicMock(return_value=found)

        assert manager.get_links_of_port(PORT_ID) == found

    def test_wraps_a_read_failure(self, manager: PortInterfaceLinksManager) -> None:
        """A BaseManager failure surfaces as the manager's own error type"""
        manager.find = MagicMock(side_effect=BaseManagerGetError('boom'))

        with pytest.raises(PortInterfaceLinksManagerGetError):
            manager.get_links_of_port(PORT_ID)


class TestGetLinksOfPorts:
    """The batched read a whole page of ports would use."""

    def test_reads_every_port_in_one_query(self, manager: PortInterfaceLinksManager) -> None:
        """One round trip however many ports a response lists"""
        manager.find = MagicMock(return_value=[])

        manager.get_links_of_ports([PORT_ID, OTHER_PORT_ID])

        assert manager.find.call_args.kwargs['criteria'] == {
            PortInterfaceLinkKey.PORT_ID.value: {'$in': [PORT_ID, OTHER_PORT_ID]},
        }

    def test_an_empty_page_costs_no_query(self, manager: PortInterfaceLinksManager) -> None:
        """An object with no ports is the common case"""
        manager.find = MagicMock(return_value=[])

        assert manager.get_links_of_ports([]) == []
        manager.find.assert_not_called()

    def test_wraps_a_read_failure(self, manager: PortInterfaceLinksManager) -> None:
        """A BaseManager failure surfaces as the manager's own error type"""
        manager.find = MagicMock(side_effect=BaseManagerGetError('boom'))

        with pytest.raises(PortInterfaceLinksManagerGetError):
            manager.get_links_of_ports([PORT_ID])


class TestGetAllLinkReferences:
    """The repair report's first read: every link's address, nothing more."""

    def test_reads_the_whole_collection_projected_to_the_address(self, manager: PortInterfaceLinksManager) -> None:
        """
        An unfiltered read, which is what the report needs and what nothing else may use - but only the id and the
        interface row triple come back, since whether a link dangles is decided by them alone
        """
        manager.find = MagicMock(return_value=[])

        manager.get_all_link_references()

        assert manager.find.call_args.kwargs == {'projection': {
            PortInterfaceLinkKey.PUBLIC_ID.value: 1,
            PortInterfaceLinkKey.INTERFACE_OBJECT_ID.value: 1,
            PortInterfaceLinkKey.INTERFACE_SECTION_ID.value: 1,
            PortInterfaceLinkKey.INTERFACE_MULTI_DATA_ID.value: 1,
            '_id': 0,
        }}


class TestGetLinksByIds:
    """The repair report's second read: the dangling links in full."""

    def test_reads_the_selection_in_one_query(self, manager: PortInterfaceLinksManager) -> None:
        """One '$in' over the link ids"""
        manager.find = MagicMock(return_value=[])

        manager.get_links_by_ids([LINK_ID, LINK_ID + 1])

        assert manager.find.call_args.kwargs == {
            'criteria': {PortInterfaceLinkKey.PUBLIC_ID.value: {'$in': [LINK_ID, LINK_ID + 1]}},
        }

    def test_no_ids_read_nothing(self, manager: PortInterfaceLinksManager) -> None:
        """Nothing dangling costs no second query"""
        manager.find = MagicMock()

        assert not manager.get_links_by_ids([])
        manager.find.assert_not_called()


class TestSnapshotLinksOfPorts:
    """The ledger's snapshot of the links a port delete removes."""

    def test_reads_the_whole_documents_mongo_id_included(self, manager: PortInterfaceLinksManager) -> None:
        """projection=None keeps `_id`, which the undo re-inserts each link under"""
        manager.find = MagicMock(return_value=[])

        manager.snapshot_links_of_ports([PORT_ID, OTHER_PORT_ID])

        assert manager.find.call_args.kwargs == {
            'criteria': {PortInterfaceLinkKey.PORT_ID.value: {'$in': [PORT_ID, OTHER_PORT_ID]}}, 'projection': None,
        }

    def test_no_ports_read_nothing(self, manager: PortInterfaceLinksManager) -> None:
        """An empty selection costs no query"""
        manager.find = MagicMock()

        assert not manager.snapshot_links_of_ports([])
        manager.find.assert_not_called()


class TestDeleteLinksOfPorts:
    """A link must not outlive its port."""

    def test_deletes_the_links_of_every_doomed_port_in_one_call(
            self, manager: PortInterfaceLinksManager) -> None:
        """One statement rather than a per-port loop"""
        manager.delete_many = MagicMock(return_value=MagicMock(deleted_count=4))

        assert manager.delete_links_of_ports([PORT_ID, OTHER_PORT_ID]) == 4
        manager.delete_many.assert_called_once_with({
            PortInterfaceLinkKey.PORT_ID.value: {'$in': [PORT_ID, OTHER_PORT_ID]},
        })

    def test_no_ports_deletes_nothing(self, manager: PortInterfaceLinksManager) -> None:
        """An object without ports is the common case on every object deletion"""
        manager.delete_many = MagicMock()

        assert manager.delete_links_of_ports([]) == 0
        manager.delete_many.assert_not_called()

    def test_nothing_is_deleted_by_the_interface_side(self, manager: PortInterfaceLinksManager) -> None:
        """
        The asymmetry that defines the feature: only the PORT reference cascades

        There is deliberately no delete_links_of_interface_object - a vanished interface row leaves its
        link in place to be reported and repaired.
        """
        assert not hasattr(manager, 'delete_links_of_interface_object')

    def test_wraps_a_delete_failure(self, manager: PortInterfaceLinksManager) -> None:
        """A BaseManager failure surfaces as the manager's own error type"""
        manager.delete_many = MagicMock(side_effect=BaseManagerDeleteError('boom'))

        with pytest.raises(PortInterfaceLinksManagerDeleteError):
            manager.delete_links_of_ports([PORT_ID])


# Every narrowed arm: the call, the delegate it makes, the typed error that delegate raises, and the manager's own
NARROWED_ARMS: list[tuple[Any, str, type[Exception], type[Exception]]] = [
    (lambda manager: manager.get_links_of_port(PORT_ID), 'find', BaseManagerGetError,
     PortInterfaceLinksManagerGetError),
    (lambda manager: manager.get_links_of_ports([PORT_ID]), 'find', BaseManagerGetError,
     PortInterfaceLinksManagerGetError),
    (lambda manager: manager.get_all_link_references(), 'find', BaseManagerGetError,
     PortInterfaceLinksManagerGetError),
    (lambda manager: manager.get_links_by_ids([LINK_ID]), 'find', BaseManagerGetError,
     PortInterfaceLinksManagerGetError),
    (lambda manager: manager.snapshot_links_of_ports([PORT_ID]), 'find', BaseManagerGetError,
     PortInterfaceLinksManagerGetError),
    (lambda manager: manager.delete_links_of_ports([PORT_ID]), 'delete_many', BaseManagerDeleteError,
     PortInterfaceLinksManagerDeleteError),
]
ARM_IDS: list[str] = [
    'get_links_of_port', 'get_links_of_ports', 'get_all_link_references', 'get_links_by_ids',
    'snapshot_links_of_ports', 'delete_links_of_ports',
]


class TestNarrowedArms:
    """Each method wraps the typed error its delegate raises, and nothing else."""

    @pytest.mark.parametrize('call_method, delegate, typed, wrapped', NARROWED_ARMS, ids=ARM_IDS)
    def test_the_typed_failure_is_wrapped_carrying_it(self, manager: PortInterfaceLinksManager, call_method: Any,
                                                      delegate: str, typed: type[Exception],
                                                      wrapped: type[Exception]) -> None:
        """The route's 400 - and the original error stays reachable as args[0]"""
        failure = typed('the database failed')
        setattr(manager, delegate, MagicMock(side_effect=failure))

        with pytest.raises(wrapped) as caught:
            call_method(manager)

        assert caught.value.args[0] is failure

    @pytest.mark.parametrize('call_method, delegate, typed, wrapped', NARROWED_ARMS, ids=ARM_IDS)
    def test_a_programming_error_propagates(self, manager: PortInterfaceLinksManager, call_method: Any,
                                            delegate: str, typed: type[Exception], wrapped: type[Exception]) -> None:
        """A bug reaches the route's 500 as itself, not as a failed read or delete"""
        del typed, wrapped
        setattr(manager, delegate, MagicMock(side_effect=RuntimeError('a bug')))

        with pytest.raises(RuntimeError):
            call_method(manager)
