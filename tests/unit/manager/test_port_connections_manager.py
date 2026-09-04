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
Unit tests for cmdb.manager.port_connections_manager

DB-free: the manager is built against a mocked MongoDatabaseManager, which its __init__ only stores.
What is tested is the binding, the two registries a manager is unreachable without, and the three
reads/deletes it adds - in particular that all of them query the single 'endpoints' array rather than
an $or over two scalar fields, which is the whole reason the endpoints are one array. The CRUD itself
is covered once, in test_generic_manager.py
"""
from unittest.mock import MagicMock

import pytest

from cmdb.manager import PortConnectionsManager
from cmdb.manager.generic_manager import GenericManager
from cmdb.manager.manager_provider_model import ManagerType
from cmdb.manager.manager_provider_model.manager_provider import ManagerProvider
from cmdb.models.port_connection_model import CmdbPortConnection, PortConnectionKey
from cmdb.models.port_connection_model import ConnectionType
from cmdb.errors.manager import BaseManagerDeleteError, BaseManagerGetError, BaseManagerUpdateError
from cmdb.errors.manager.port_connections_manager import (
    PORT_CONNECTIONS_MANAGER_ERRORS,
    PortConnectionsManagerDeleteError,
    PortConnectionsManagerGetError,
    PortConnectionsManagerInitError,
    PortConnectionsManagerUpdateError,
)
# -------------------------------------------------------------------------------------------------------------------- #

DB_NAME: str = 'testdb'

PORT_A: int = 3
PORT_B: int = 10
CONNECTION_ID: int = 55
CABLE_CI_ID: int = 77


@pytest.fixture(name='manager')
def fixture_manager() -> PortConnectionsManager:
    """A PortConnectionsManager over a mocked database manager (its __init__ performs no I/O)"""
    return PortConnectionsManager(MagicMock(name='dbm'), DB_NAME)


class TestTheBinding:
    """What the manager is bound to."""

    def test_is_a_generic_manager(self, manager: PortConnectionsManager) -> None:
        """The CRUD is plain, so the shared implementation covers it"""
        assert isinstance(manager, GenericManager)

    def test_stores_cmdb_port_connections(self, manager: PortConnectionsManager) -> None:
        """The model decides both the collection and how documents are (de)serialised"""
        assert manager.model is CmdbPortConnection
        assert manager.collection == CmdbPortConnection.COLLECTION

    def test_uses_its_own_exception_map(self, manager: PortConnectionsManager) -> None:
        """A failure has to surface as a PortConnectionsManager error, not another domain's"""
        assert manager.exceptions is PORT_CONNECTIONS_MANAGER_ERRORS

    def test_targets_the_given_database(self, manager: PortConnectionsManager) -> None:
        """The explicit database name is what cloud mode passes per request"""
        assert manager.db_name == DB_NAME

    def test_an_init_failure_raises_the_managers_own_error(self) -> None:
        """The 'init' entry of the exception map is what a broken construction reports"""
        broken = MagicMock(name='dbm')
        type(broken).db_name = property(lambda _self: (_ for _ in ()).throw(RuntimeError('no db')))

        with pytest.raises(PortConnectionsManagerInitError):
            PortConnectionsManager(broken)


class TestTheRegistration:
    """Without these two entries the manager cannot be obtained by a route."""

    def test_the_manager_type_exists(self) -> None:
        """ManagerType is how a route names the manager it wants"""
        assert ManagerType.PORT_CONNECTIONS.value == 'PortConnectionsManager'

    def test_the_provider_resolves_the_manager_type(self) -> None:
        """A ManagerType missing from the provider map raises BaseManagerInitError at request time"""
        # pylint: disable=protected-access
        assert ManagerProvider._ManagerProvider__get_manager_class(
            ManagerType.PORT_CONNECTIONS) is PortConnectionsManager


class TestGetConnectionsOfPort:
    """'What is this port connected to' - one indexed predicate."""

    def test_matches_the_port_at_either_end(self, manager: PortConnectionsManager) -> None:
        """
        A plain equality against the array, NOT an $or over two scalar fields

        Mongo matches an array element with the same predicate, which is why storing the two ids in
        one field makes this - and the batched read below - a single indexed lookup.
        """
        manager.find = MagicMock(return_value=[])

        manager.get_connections_of_port(PORT_A)

        assert manager.find.call_args.kwargs['criteria'] == {
            PortConnectionKey.ENDPOINTS.value: PORT_A,
        }

    def test_returns_every_connection_of_the_port(self, manager: PortConnectionsManager) -> None:
        """A panel port legitimately has two: its cable and its internal pairing"""
        found = [{'public_id': 1}, {'public_id': 2}]
        manager.find = MagicMock(return_value=found)

        assert manager.get_connections_of_port(PORT_A) == found

    def test_wraps_a_read_failure(self, manager: PortConnectionsManager) -> None:
        """A BaseManager failure surfaces as the manager's own error type"""
        manager.find = MagicMock(side_effect=BaseManagerGetError('boom'))

        with pytest.raises(PortConnectionsManagerGetError):
            manager.get_connections_of_port(PORT_A)


class TestGetConnectionsOfPorts:
    """The batched read the computed 'connected' flag is served by."""

    def test_reads_a_whole_page_of_ports_in_one_query(self, manager: PortConnectionsManager) -> None:
        """One round trip however many ports a response lists, rather than one query per port"""
        manager.find = MagicMock(return_value=[])

        manager.get_connections_of_ports([PORT_A, PORT_B])

        assert manager.find.call_args.kwargs['criteria'] == {
            PortConnectionKey.ENDPOINTS.value: {'$in': [PORT_A, PORT_B]},
        }

    def test_an_empty_page_costs_no_query(self, manager: PortConnectionsManager) -> None:
        """An object with no ports is the common case on every list response"""
        manager.find = MagicMock(return_value=[])

        assert manager.get_connections_of_ports([]) == []
        manager.find.assert_not_called()

    def test_wraps_a_read_failure(self, manager: PortConnectionsManager) -> None:
        """A BaseManager failure surfaces as the manager's own error type"""
        manager.find = MagicMock(side_effect=BaseManagerGetError('boom'))

        with pytest.raises(PortConnectionsManagerGetError):
            manager.get_connections_of_ports([PORT_A])


class TestDeleteConnectionsOfPorts:
    """A connection must not outlive an endpoint."""

    def test_deletes_every_connection_of_the_ports_in_one_call(
            self, manager: PortConnectionsManager) -> None:
        """One statement rather than a per-port loop"""
        manager.delete_many = MagicMock(return_value=MagicMock(deleted_count=3))

        assert manager.delete_connections_of_ports([PORT_A, PORT_B]) == 3
        manager.delete_many.assert_called_once_with({
            PortConnectionKey.ENDPOINTS.value: {'$in': [PORT_A, PORT_B]},
        })

    def test_no_ports_deletes_nothing(self, manager: PortConnectionsManager) -> None:
        """
        The guard that matters most here

        An empty $in matches nothing, but building the statement at all is a delete_many nobody asked
        for - and an object without ports is the common case on every object deletion.
        """
        manager.delete_many = MagicMock()

        assert manager.delete_connections_of_ports([]) == 0
        manager.delete_many.assert_not_called()

    def test_wraps_a_delete_failure(self, manager: PortConnectionsManager) -> None:
        """A BaseManager failure surfaces as the manager's own error type"""
        manager.delete_many = MagicMock(side_effect=BaseManagerDeleteError('boom'))

        with pytest.raises(PortConnectionsManagerDeleteError):
            manager.delete_connections_of_ports([PORT_A])


class TestGetConnectionOfPortByType:
    """'Is this port's cable slot taken' - the readable half of the cardinality refusal."""

    def test_looks_up_the_port_and_the_type_together(self, manager: PortConnectionsManager) -> None:
        """
        Both halves of the key, because a port may legitimately hold one of EACH kind

        Dropping the type from the filter would report a panel port's internal pairing as a reason it
        cannot be cabled.
        """
        manager.get_one_by = MagicMock(return_value=None)

        manager.get_connection_of_port_by_type(PORT_A, ConnectionType.CABLE.value)

        assert manager.get_one_by.call_args.args[0] == {
            PortConnectionKey.ENDPOINTS.value: PORT_A,
            PortConnectionKey.CONNECTION_TYPE.value: ConnectionType.CABLE.value,
        }

    def test_returns_none_when_the_slot_is_free(self, manager: PortConnectionsManager) -> None:
        """The ordinary case"""
        manager.get_one_by = MagicMock(return_value=None)

        assert manager.get_connection_of_port_by_type(PORT_A, ConnectionType.INTERNAL.value) is None

    def test_wraps_a_read_failure(self, manager: PortConnectionsManager) -> None:
        """A BaseManager failure surfaces as the manager's own error type"""
        manager.get_one_by = MagicMock(side_effect=BaseManagerGetError('boom'))

        with pytest.raises(PortConnectionsManagerGetError):
            manager.get_connection_of_port_by_type(PORT_A, ConnectionType.CABLE.value)


class TestGetConnectionByCableCi:
    """One inventoried cable belongs to at most one connection."""

    def test_looks_the_cable_ci_up(self, manager: PortConnectionsManager) -> None:
        """A single indexed lookup, served by the presence-filtered unique index"""
        manager.get_one_by = MagicMock(return_value=None)

        manager.get_connection_by_cable_ci(CABLE_CI_ID)

        assert manager.get_one_by.call_args.args[0] == {
            PortConnectionKey.CABLE_CI_ID.value: CABLE_CI_ID,
        }

    def test_returns_the_claiming_connection(self, manager: PortConnectionsManager) -> None:
        """The caller names it in the refusal, so the user can find the link already using the cable"""
        claiming = {PortConnectionKey.PUBLIC_ID.value: CONNECTION_ID}
        manager.get_one_by = MagicMock(return_value=claiming)

        assert manager.get_connection_by_cable_ci(CABLE_CI_ID) is claiming

    def test_wraps_a_read_failure(self, manager: PortConnectionsManager) -> None:
        """A BaseManager failure surfaces as the manager's own error type"""
        manager.get_one_by = MagicMock(side_effect=BaseManagerGetError('boom'))

        with pytest.raises(PortConnectionsManagerGetError):
            manager.get_connection_by_cable_ci(CABLE_CI_ID)


class TestReplaceConnection:
    """Writing cable information - and REMOVING what the document omits."""

    def test_sets_what_the_document_carries(self, manager: PortConnectionsManager) -> None:
        """The ordinary write"""
        manager.update = MagicMock()
        document = {PortConnectionKey.CABLE_NAME.value: 'Patch 1'}

        manager.replace_connection(CONNECTION_ID, document)

        criteria, update = manager.update.call_args.args

        assert criteria == {PortConnectionKey.PUBLIC_ID.value: CONNECTION_ID}
        assert update['$set'] == document

    def test_unsets_a_cable_ci_the_document_omits(self, manager: PortConnectionsManager) -> None:
        """
        The reason this is not update_item

        BaseManager.update wraps its payload in $set, so a key left out keeps its stored value - and
        'cable_ci_id' can not be nulled instead, because its unique index is filtered on the key's
        PRESENCE. Without the $unset a user could never remove a cable CI from a connection.
        """
        manager.update = MagicMock()

        manager.replace_connection(CONNECTION_ID, {PortConnectionKey.CABLE_NAME.value: 'Patch 1'})

        assert manager.update.call_args.args[1]['$unset'] == {
            PortConnectionKey.CABLE_CI_ID.value: '',
        }

    def test_does_not_unset_a_cable_ci_the_document_carries(self, manager: PortConnectionsManager) -> None:
        """The other half: a named cable CI is written, not removed"""
        manager.update = MagicMock()

        manager.replace_connection(CONNECTION_ID, {
            PortConnectionKey.CABLE_CI_ID.value: CABLE_CI_ID,
        })

        update = manager.update.call_args.args[1]

        assert '$unset' not in update
        assert update['$set'][PortConnectionKey.CABLE_CI_ID.value] == CABLE_CI_ID

    def test_wraps_an_update_failure(self, manager: PortConnectionsManager) -> None:
        """A BaseManager failure surfaces as the manager's own error type"""
        manager.update = MagicMock(side_effect=BaseManagerUpdateError('boom'))

        with pytest.raises(PortConnectionsManagerUpdateError):
            manager.replace_connection(CONNECTION_ID, {})
