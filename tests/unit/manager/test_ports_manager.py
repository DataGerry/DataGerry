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
from unittest.mock import MagicMock

import pytest

from cmdb.manager import PortsManager
from cmdb.manager.generic_manager import GenericManager
from cmdb.manager.manager_provider_model import ManagerType
from cmdb.manager.manager_provider_model.manager_provider import ManagerProvider
from cmdb.models.port_model import CmdbPort, PortKey, PortSide
from cmdb.errors.manager import BaseManagerDeleteError, BaseManagerGetError
from cmdb.errors.manager.ports_manager import (
    PORTS_MANAGER_ERRORS,
    PortsManagerDeleteError,
    PortsManagerGetError,
    PortsManagerInitError,
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

    def test_an_init_failure_raises_the_managers_own_error(self) -> None:
        """The 'init' entry of the exception map is what a broken construction reports"""
        broken = MagicMock(name='dbm')
        type(broken).db_name = property(lambda _self: (_ for _ in ()).throw(RuntimeError('no db')))

        with pytest.raises(PortsManagerInitError):
            PortsManager(broken)


class TestTheRegistration:
    """Without these two entries the manager cannot be obtained by a route."""

    def test_the_manager_type_exists(self) -> None:
        """ManagerType is how a route names the manager it wants"""
        assert ManagerType.PORTS.value == 'PortsManager'

    def test_the_provider_resolves_the_manager_type(self) -> None:
        """A ManagerType missing from the provider map raises BaseManagerInitError at request time"""
        # pylint: disable=protected-access
        assert ManagerProvider._ManagerProvider__get_manager_class(ManagerType.PORTS) is PortsManager


OBJECT_ID: int = 7000
PORT_ID: int = 7001
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


class TestDeletePortsOfObject:
    """The delete cascade's single statement."""

    def test_deletes_every_port_of_the_object_in_one_call(self, manager: PortsManager) -> None:
        """One statement rather than a per-port loop"""
        manager.delete_many = MagicMock(return_value=MagicMock(deleted_count=4))

        assert manager.delete_ports_of_object(OBJECT_ID) == 4
        manager.delete_many.assert_called_once_with({PortKey.OBJECT_ID.value: OBJECT_ID})

    def test_wraps_a_delete_failure(self, manager: PortsManager) -> None:
        """A BaseManager failure surfaces as the manager's own error type"""
        manager.delete_many = MagicMock(side_effect=BaseManagerDeleteError('boom'))

        with pytest.raises(PortsManagerDeleteError):
            manager.delete_ports_of_object(OBJECT_ID)
