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
Unit tests for cmdb.manager.ports_manager

DB-free: the manager is built against a mocked MongoDatabaseManager, which its __init__ only stores.
PortsManager adds no behaviour of its own - it is a GenericManager bound to CmdbPort - so what is
tested is exactly that binding, plus the two registries a manager is unreachable without. The CRUD
itself is covered once, in test_generic_manager.py
"""
from typing import Any
from unittest.mock import MagicMock

import pytest

from cmdb.manager import PortsManager
from cmdb.manager.generic_manager import GenericManager
from cmdb.manager.manager_provider_model import MANAGER_CLASSES, ManagerType
from cmdb.models.port_model import CmdbPort, PortKey, PortSide
from cmdb.errors.manager import BaseManagerDeleteError, BaseManagerGetError, BaseManagerUpdateError
from cmdb.errors.manager.ports_manager import (
    PORTS_MANAGER_ERRORS,
    PortsManagerDeleteError,
    PortsManagerGetError,
    PortsManagerUpdateError,
)
# -------------------------------------------------------------------------------------------------------------------- #

DB_NAME: str = 'testdb'


@pytest.fixture(name='manager')
def fixture_manager() -> PortsManager:
    """A PortsManager over a mocked database manager (its __init__ performs no I/O)"""
    return PortsManager(MagicMock(name='dbm'), DB_NAME)


class TestTheBinding:
    """What the manager is bound to."""

    def test_is_a_generic_manager(self, manager: PortsManager) -> None:
        """Plain CRUD, so the shared implementation covers it whole"""
        assert isinstance(manager, GenericManager)

    def test_stores_cmdb_ports(self, manager: PortsManager) -> None:
        """The model decides both the collection and how documents are (de)serialised"""
        assert manager.model is CmdbPort
        assert manager.collection == CmdbPort.COLLECTION

    def test_uses_its_own_exception_map(self, manager: PortsManager) -> None:
        """A failure has to surface as a PortsManager error, not another domain's"""
        assert manager.exceptions is PORTS_MANAGER_ERRORS

    def test_targets_the_given_database(self, manager: PortsManager) -> None:
        """The explicit database name is what cloud mode passes per request"""
        assert manager.db_name == DB_NAME

    def test_a_broken_construction_is_not_wrapped(self) -> None:
        """
        Building the manager touches no database: a failure there is a bug, raised as itself (the route's 500),
        never one of the manager's mapped errors, which read like a database failure
        """
        broken = MagicMock(name='dbm')
        type(broken).db_name = property(lambda _self: (_ for _ in ()).throw(RuntimeError('no db')))

        with pytest.raises(RuntimeError):
            PortsManager(broken)


class TestTheRegistration:
    """Without these two entries the manager cannot be obtained by a route."""

    def test_the_manager_type_exists(self) -> None:
        """ManagerType is how a route names the manager it wants"""
        assert ManagerType.PORTS.value == 'PortsManager'

    def test_the_provider_resolves_the_manager_type(self) -> None:
        """Without this entry the route's get_manager call would raise BaseManagerInitError"""
        assert MANAGER_CLASSES[ManagerType.PORTS] is PortsManager


OBJECT_ID: int = 7000
PORT_ID: int = 7001
OTHER_OBJECT_ID: int = 7002
OTHER_PORT_ID: int = 7003
PORT_NAME: str = 'Gi0/1'


class TestGetPortsOfObject:
    """The read every ports panel performs."""

    def test_filters_on_the_owner(self, manager: PortsManager) -> None:
        """One object's ports, nothing else"""
        manager.find = MagicMock(return_value=[])

        manager.get_ports_of_object(OBJECT_ID)

        assert manager.find.call_args.kwargs['criteria'] == {PortKey.OBJECT_ID.value: OBJECT_ID}

    def test_sorts_by_number_then_name(self, manager: PortsManager) -> None:
        """
        A port without a number still needs a stable place, so the name is the tie-break

        The sort matches the declared (object_id, port_number) index, so it is served from it.
        """
        manager.find = MagicMock(return_value=[])

        manager.get_ports_of_object(OBJECT_ID)

        assert manager.find.call_args.kwargs['sort'] == [
            (PortKey.PORT_NUMBER.value, CmdbPort.DAO_ASCENDING),
            (PortKey.NAME.value, CmdbPort.DAO_ASCENDING),
        ]

    def test_wraps_a_read_failure(self, manager: PortsManager) -> None:
        """A BaseManager failure surfaces as the manager's own error type"""
        manager.find = MagicMock(side_effect=BaseManagerGetError('boom'))

        with pytest.raises(PortsManagerGetError):
            manager.get_ports_of_object(OBJECT_ID)


class TestGetPortsOfObjects:
    """The ports of several objects in one read."""

    def test_no_ids_read_nothing(self, manager: PortsManager) -> None:
        """An empty list answers at once, without a query"""
        manager.find = MagicMock()

        assert not manager.get_ports_of_objects([])
        manager.find.assert_not_called()

    def test_reads_every_owner_in_one_query_sorted_by_owner(self, manager: PortsManager) -> None:
        """One '$in' over the owners; each object's ports stay together, in their panel order"""
        manager.find = MagicMock(return_value=[])

        manager.get_ports_of_objects([OBJECT_ID, OTHER_OBJECT_ID])

        assert manager.find.call_args.kwargs == {
            'criteria': {PortKey.OBJECT_ID.value: {'$in': [OBJECT_ID, OTHER_OBJECT_ID]}},
            'sort': [
                (PortKey.OBJECT_ID.value, CmdbPort.DAO_ASCENDING),
                (PortKey.PORT_NUMBER.value, CmdbPort.DAO_ASCENDING),
                (PortKey.NAME.value, CmdbPort.DAO_ASCENDING),
            ],
        }

    def test_wraps_a_read_failure(self, manager: PortsManager) -> None:
        """A BaseManager failure surfaces as the manager's own error type"""
        failure = BaseManagerGetError('boom')
        manager.find = MagicMock(side_effect=failure)

        with pytest.raises(PortsManagerGetError) as caught:
            manager.get_ports_of_objects([OBJECT_ID])

        assert caught.value.args[0] is failure


class TestGetPortsByIds:
    """Several ports by their own ids in one read."""

    def test_no_ids_read_nothing(self, manager: PortsManager) -> None:
        """An empty list answers at once, without a query"""
        manager.find = MagicMock()

        assert not manager.get_ports_by_ids([])
        manager.find.assert_not_called()

    def test_reads_every_port_in_one_query(self, manager: PortsManager) -> None:
        """One '$in' over the port ids"""
        manager.find = MagicMock(return_value=[])

        manager.get_ports_by_ids([PORT_ID, OTHER_PORT_ID])

        assert manager.find.call_args.kwargs == {
            'criteria': {PortKey.PUBLIC_ID.value: {'$in': [PORT_ID, OTHER_PORT_ID]}},
        }

    def test_wraps_a_read_failure(self, manager: PortsManager) -> None:
        """A BaseManager failure surfaces as the manager's own error type"""
        failure = BaseManagerGetError('boom')
        manager.find = MagicMock(side_effect=failure)

        with pytest.raises(PortsManagerGetError) as caught:
            manager.get_ports_by_ids([PORT_ID])

        assert caught.value.args[0] is failure


class TestGetPortByName:
    """The read behind the readable duplicate-name refusal."""

    def test_looks_up_the_identity_triple(self, manager: PortsManager) -> None:
        """
        Keyed on (object_id, side, name), exactly like the unique index

        Leaving the side out would report a panel's rear port as a clash with its front port.
        """
        manager.get_one_by = MagicMock(return_value=None)

        manager.get_port_by_name(OBJECT_ID, PortSide.FRONT.value, PORT_NAME)

        assert manager.get_one_by.call_args.args[0] == {
            PortKey.OBJECT_ID.value: OBJECT_ID,
            PortKey.SIDE.value: PortSide.FRONT.value,
            PortKey.NAME.value: PORT_NAME,
        }

    def test_returns_none_when_the_name_is_free(self, manager: PortsManager) -> None:
        """The common case"""
        manager.get_one_by = MagicMock(return_value=None)

        assert manager.get_port_by_name(OBJECT_ID, PortSide.SINGLE.value, PORT_NAME) is None

    def test_wraps_a_read_failure(self, manager: PortsManager) -> None:
        """A BaseManager failure surfaces as the manager's own error type"""
        manager.get_one_by = MagicMock(side_effect=BaseManagerGetError('boom'))

        with pytest.raises(PortsManagerGetError):
            manager.get_port_by_name(OBJECT_ID, PortSide.SINGLE.value, PORT_NAME)


class TestGetPortKindsOfObject:
    """The projected read behind the kind guards and the object cascade's port ids."""

    def test_reads_only_id_owner_and_side(self, manager: PortsManager) -> None:
        """One object's ports, three keys each - never the whole documents"""
        manager.find = MagicMock(return_value=[])

        manager.get_port_kinds_of_object(OBJECT_ID)

        assert manager.find.call_args.kwargs == {
            'criteria': {PortKey.OBJECT_ID.value: OBJECT_ID},
            'projection': {PortKey.PUBLIC_ID.value: 1, PortKey.OBJECT_ID.value: 1, PortKey.SIDE.value: 1, '_id': 0},
        }


class TestSnapshotPorts:
    """The ledger's snapshot of the ports a delete removes."""

    def test_no_ids_read_nothing(self, manager: PortsManager) -> None:
        """An empty selection costs no query"""
        manager.find = MagicMock()

        assert not manager.snapshot_ports([])
        manager.find.assert_not_called()

    def test_reads_the_whole_documents_mongo_id_included(self, manager: PortsManager) -> None:
        """projection=None keeps `_id`, which the undo re-inserts each port under"""
        manager.find = MagicMock(return_value=[])

        manager.snapshot_ports([PORT_ID, OTHER_PORT_ID])

        assert manager.find.call_args.kwargs == {
            'criteria': {PortKey.PUBLIC_ID.value: {'$in': [PORT_ID, OTHER_PORT_ID]}}, 'projection': None,
        }


class TestUpdatePorts:
    """The bulk edit's one write."""

    def test_no_ids_write_nothing(self, manager: PortsManager) -> None:
        """An empty selection costs no write"""
        manager.update_many = MagicMock()

        manager.update_ports([], {PortKey.NAME.value: PORT_NAME})

        manager.update_many.assert_not_called()

    def test_sets_the_values_on_the_whole_selection(self, manager: PortsManager) -> None:
        """One statement for every selected port"""
        manager.update_many = MagicMock()
        values = {PortKey.NAME.value: PORT_NAME}

        manager.update_ports([PORT_ID, OTHER_PORT_ID], values)

        manager.update_many.assert_called_once_with(
            criteria={PortKey.PUBLIC_ID.value: {'$in': [PORT_ID, OTHER_PORT_ID]}}, update=values,
        )


class TestDeletePortsByIds:
    """The last statement of every port delete."""

    def test_no_ids_delete_nothing(self, manager: PortsManager) -> None:
        """An empty selection costs no statement"""
        manager.delete_many = MagicMock()

        assert manager.delete_ports_by_ids([]) == 0
        manager.delete_many.assert_not_called()

    def test_deletes_the_selection_in_one_call(self, manager: PortsManager) -> None:
        """One '$in' over the port ids"""
        manager.delete_many = MagicMock(return_value=MagicMock(deleted_count=4))

        assert manager.delete_ports_by_ids([PORT_ID, OTHER_PORT_ID]) == 4
        manager.delete_many.assert_called_once_with({PortKey.PUBLIC_ID.value: {'$in': [PORT_ID, OTHER_PORT_ID]}})


# Every narrowed arm: the call, the delegate it makes, the typed error that delegate raises, and the manager's own
NARROWED_ARMS: list[tuple[Any, str, type[Exception], type[Exception]]] = [
    (lambda manager: manager.get_ports_of_object(OBJECT_ID), 'find', BaseManagerGetError, PortsManagerGetError),
    (lambda manager: manager.get_ports_of_objects([OBJECT_ID]), 'find', BaseManagerGetError, PortsManagerGetError),
    (lambda manager: manager.get_ports_by_ids([PORT_ID]), 'find', BaseManagerGetError, PortsManagerGetError),
    (lambda manager: manager.get_port_by_name(OBJECT_ID, PortSide.SINGLE.value, PORT_NAME), 'get_one_by',
     BaseManagerGetError, PortsManagerGetError),
    (lambda manager: manager.get_port_kinds_of_object(OBJECT_ID), 'find', BaseManagerGetError,
     PortsManagerGetError),
    (lambda manager: manager.snapshot_ports([PORT_ID]), 'find', BaseManagerGetError, PortsManagerGetError),
    (lambda manager: manager.update_ports([PORT_ID], {PortKey.NAME.value: PORT_NAME}), 'update_many',
     BaseManagerUpdateError, PortsManagerUpdateError),
    (lambda manager: manager.delete_ports_by_ids([PORT_ID]), 'delete_many', BaseManagerDeleteError,
     PortsManagerDeleteError),
]
ARM_IDS: list[str] = [
    'get_ports_of_object', 'get_ports_of_objects', 'get_ports_by_ids', 'get_port_by_name',
    'get_port_kinds_of_object', 'snapshot_ports', 'update_ports', 'delete_ports_by_ids',
]


class TestNarrowedArms:
    """Each method wraps the typed error its delegate raises, and nothing else."""

    @pytest.mark.parametrize('call_method, delegate, typed, wrapped', NARROWED_ARMS, ids=ARM_IDS)
    def test_the_typed_failure_is_wrapped_carrying_it(self, manager: PortsManager, call_method: Any, delegate: str,
                                                      typed: type[Exception], wrapped: type[Exception]) -> None:
        """The route's 400 - and the original error stays reachable as args[0]"""
        failure = typed('the database failed')
        setattr(manager, delegate, MagicMock(side_effect=failure))

        with pytest.raises(wrapped) as caught:
            call_method(manager)

        assert caught.value.args[0] is failure

    @pytest.mark.parametrize('call_method, delegate, typed, wrapped', NARROWED_ARMS, ids=ARM_IDS)
    def test_a_programming_error_propagates(self, manager: PortsManager, call_method: Any, delegate: str,
                                            typed: type[Exception], wrapped: type[Exception]) -> None:
        """A bug reaches the route's 500 as itself, not as a failed read or write"""
        del typed, wrapped
        setattr(manager, delegate, MagicMock(side_effect=RuntimeError('a bug')))

        with pytest.raises(RuntimeError):
            call_method(manager)
