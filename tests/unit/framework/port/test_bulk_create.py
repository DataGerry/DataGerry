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
Unit tests for cmdb.framework.port.bulk_create

Two things carry this module, and both are orderings that every statement would still report success
for if they were wrong:

* **forward: ports before connections.** A connection stores two port ids, so building it first would
  reference rows that do not exist - and a failure between the two would leave a connection pointing at
  nothing
* **backward: connections before ports.** Removing a port while its connection still names it would
  recreate exactly that dangling row

The third is §37's honesty requirement: a rollback that could not finish must report what survived
rather than a success or a clean failure. The residue is computed from a **verification read**, not
from what the delete claimed, because `delete_many` reports what it matched.

Pure tests: the managers are mocks, so a failure can be forced anywhere in the batch
"""
from typing import Any
from unittest.mock import MagicMock

import pytest

from cmdb.framework.port.bulk_create import (
    BulkCreateResult,
    create_batch,
    create_face_ports,
    create_internal_connections,
    roll_back,
)
from cmdb.framework.port.name_syntax_constants import PortPreviewKey
from cmdb.models.port_connection_model import ConnectionType, PortConnectionKey
from cmdb.models.port_model import PortKey, PortSide
# -------------------------------------------------------------------------------------------------------------------- #

OBJECT_ID: int = 7700
AUTHOR_ID: int = 1


def _face(side: str, names: list[str]) -> dict[str, Any]:
    """One face of a preview."""
    return {PortPreviewKey.SIDE.value: side, PortPreviewKey.NAMES.value: names}


def _standard_preview(names: list[str]) -> dict[str, Any]:
    """A standard device's preview - one face."""
    return {PortPreviewKey.FACES.value: [_face(PortSide.SINGLE.value, names)]}


def _panel_preview(front: list[str], rear: list[str]) -> dict[str, Any]:
    """A patch panel's preview - two faces."""
    return {PortPreviewKey.FACES.value: [
        _face(PortSide.FRONT.value, front),
        _face(PortSide.REAR.value, rear),
    ]}


def _ports_manager(ids: list[int] | None = None, found: list[dict] | None = None) -> MagicMock:
    """A PortsManager stand-in handing out the given ids in order."""
    manager = MagicMock(name='ports_manager')
    manager.insert_item.side_effect = list(ids or range(100, 200))
    manager.find.return_value = found if found is not None else []

    return manager


def _connections_manager(ids: list[int] | None = None, found: list[dict] | None = None) -> MagicMock:
    """A PortConnectionsManager stand-in handing out the given ids in order."""
    manager = MagicMock(name='port_connections_manager')
    manager.insert_item.side_effect = list(ids or range(500, 600))
    manager.find.return_value = found if found is not None else []

    return manager


# -------------------------------------------------------------------------------------------------------------------- #
#                                                creating one face                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
class TestCreateFacePorts:
    """The ports of one face, from the names the preview produced."""

    def test_one_port_per_previewed_name(self) -> None:
        """The names come from the preview, which is what makes the batch what the customer saw"""
        manager = _ports_manager([101, 102, 103])

        assert create_face_ports(
            manager, OBJECT_ID, _face(PortSide.SINGLE.value, ['a', 'b', 'c']), AUTHOR_ID, {}, [],
        ) == [101, 102, 103]

    def test_each_port_carries_the_face_side_and_the_owner(self) -> None:
        """A panel's ports are only front or rear because the FACE says so"""
        manager = _ports_manager([101])

        create_face_ports(manager, OBJECT_ID, _face(PortSide.REAR.value, ['R1']), AUTHOR_ID, {}, [])

        candidate = manager.insert_item.call_args.args[0]

        assert candidate[PortKey.OBJECT_ID.value] == OBJECT_ID
        assert candidate[PortKey.SIDE.value] == PortSide.REAR.value
        assert candidate[PortKey.NAME.value] == 'R1'

    def test_the_server_owned_fields_are_stamped(self) -> None:
        """The author and the timestamps come from the request, exactly as on a single create"""
        manager = _ports_manager([101])

        create_face_ports(manager, OBJECT_ID, _face(PortSide.SINGLE.value, ['1']), AUTHOR_ID, {}, [])

        candidate = manager.insert_item.call_args.args[0]

        assert candidate[PortKey.AUTHOR_ID.value] == AUTHOR_ID
        assert candidate[PortKey.CREATION_TIME.value] is not None
        assert candidate[PortKey.LAST_EDIT_TIME.value] is None

    def test_the_shared_values_reach_every_port(self) -> None:
        """
        A customer creating 48 uplinks wants them all Up / SFP+ / 10G

        Setting that afterwards would be 48 more requests.
        """
        manager = _ports_manager([101, 102])

        create_face_ports(
            manager, OBJECT_ID, _face(PortSide.SINGLE.value, ['1', '2']), AUTHOR_ID,
            {PortKey.SPEED.value: 9}, [],
        )

        for call in manager.insert_item.call_args_list:
            assert call.args[0][PortKey.SPEED.value] == 9

    def test_the_shared_values_never_override_the_identity(self) -> None:
        """The name and the side are the batch's own business, whatever a body tried to say"""
        manager = _ports_manager([101])

        create_face_ports(
            manager, OBJECT_ID, _face(PortSide.FRONT.value, ['F1']), AUTHOR_ID,
            {PortKey.NAME.value: 'hijacked', PortKey.SIDE.value: PortSide.SINGLE.value}, [],
        )

        candidate = manager.insert_item.call_args.args[0]

        assert candidate[PortKey.NAME.value] == 'F1'
        assert candidate[PortKey.SIDE.value] == PortSide.FRONT.value

    def test_an_empty_face_creates_nothing(self) -> None:
        """Not reachable through the routes, which refuse a count below 1"""
        manager = _ports_manager()

        assert create_face_ports(manager, OBJECT_ID, _face(PortSide.SINGLE.value, []), AUTHOR_ID, {}, []) == []
        manager.insert_item.assert_not_called()


# -------------------------------------------------------------------------------------------------------------------- #
#                                              the panel's pairing                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
class TestCreateInternalConnections:
    """The pairing IS the connection."""

    def test_one_connection_per_pair(self) -> None:
        """A 24-pair panel gets 24 internal connections, not 48"""
        manager = _connections_manager([501, 502])

        assert create_internal_connections(manager, [101, 102], [201, 202], AUTHOR_ID, []) == [501, 502]

    def test_front_i_is_joined_to_rear_i(self) -> None:
        """
        Positional, by public_id

        The names are never consulted - the concept forbids deriving the pairing from them, and this is
        what makes two faces named nothing alike pair correctly.
        """
        manager = _connections_manager([501, 502])

        create_internal_connections(manager, [101, 102], [201, 202], AUTHOR_ID, [])

        endpoints = [
            call.args[0][PortConnectionKey.ENDPOINTS.value]
            for call in manager.insert_item.call_args_list
        ]

        assert endpoints == [[101, 201], [102, 202]]

    def test_the_endpoints_are_stored_sorted(self) -> None:
        """
        A panel's internal link is shaped exactly like a cable, so the same index covers it

        Here the rear id is LOWER than the front one, which is what a re-numbered device produces.
        """
        manager = _connections_manager([501])

        create_internal_connections(manager, [900], [100], AUTHOR_ID, [])

        assert manager.insert_item.call_args.args[0][PortConnectionKey.ENDPOINTS.value] == [100, 900]

    def test_every_connection_is_internal(self) -> None:
        """A panel's pairing is not a cable, and the two live under different unique indexes"""
        manager = _connections_manager([501])

        create_internal_connections(manager, [101], [201], AUTHOR_ID, [])

        assert manager.insert_item.call_args.args[0][
            PortConnectionKey.CONNECTION_TYPE.value] == ConnectionType.INTERNAL.value

    def test_no_cable_information_is_written(self) -> None:
        """Cable fields are refused on an INTERNAL connection, so the batch must not set any"""
        manager = _connections_manager([501])

        create_internal_connections(manager, [101], [201], AUTHOR_ID, [])

        candidate = manager.insert_item.call_args.args[0]

        assert PortConnectionKey.CABLE_NAME.value not in candidate
        assert PortConnectionKey.CABLE_CI_ID.value not in candidate

    def test_unequal_faces_raise_rather_than_pairing_silently(self) -> None:
        """
        Cannot happen through the routes - one count drives both faces - so it must be loud here

        A zip that stopped at the shorter face would leave the extra ports unpaired and report success,
        which is precisely §37's forbidden state.
        """
        with pytest.raises(ValueError):
            create_internal_connections(_connections_manager(), [101, 102], [201], AUTHOR_ID, [])


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  the rollback                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
class TestRollBack:
    """Undoing a half-created device, and being honest about whether it worked."""

    def test_the_connections_go_before_the_ports(self) -> None:
        """
        The reverse of the creation order, and for the mirror reason

        Removing a port while its connection still names it would recreate the dangling row the
        forward order exists to avoid.
        """
        calls: list[str] = []

        ports_manager = _ports_manager()
        ports_manager.delete_many.side_effect = lambda _c: calls.append('ports')

        connections_manager = _connections_manager()
        connections_manager.delete_many.side_effect = lambda _c: calls.append('connections')

        roll_back(ports_manager, connections_manager, [101], [501])

        assert calls == ['connections', 'ports']

    def test_a_clean_rollback_reports_no_residue(self) -> None:
        """The verification read finds nothing, so the database is as it was"""
        assert roll_back(_ports_manager(), _connections_manager(), [101], [501]) == ([], [])

    def test_the_residue_comes_from_a_verification_read(self) -> None:
        """
        Not from what the delete claimed

        `delete_many` reports what it MATCHED, so a rollback trusting its own result would report a
        clean failure while rows survived - the one outcome §37 forbids reporting as anything else.
        """
        ports_manager = _ports_manager(found=[{PortKey.PUBLIC_ID.value: 102}])
        connections_manager = _connections_manager()

        residual_ports, residual_connections = roll_back(
            ports_manager, connections_manager, [101, 102], [501],
        )

        assert residual_ports == [102]
        assert residual_connections == []

    def test_a_delete_that_raises_does_not_stop_the_rollback(self) -> None:
        """
        This already runs on an error path

        A rollback that raised would replace an honest 'this was left behind' with a stack trace
        naming neither - and would skip the ports because the connections failed.
        """
        ports_manager = _ports_manager()
        connections_manager = _connections_manager()
        connections_manager.delete_many.side_effect = RuntimeError('boom')

        roll_back(ports_manager, connections_manager, [101], [501])

        ports_manager.delete_many.assert_called_once()

    def test_a_failed_verification_reports_everything_as_residue(self) -> None:
        """
        Nothing can be promised, so the honest answer is the pessimistic one

        It sends somebody to look, which is what the report is for.
        """
        ports_manager = _ports_manager()
        ports_manager.find.side_effect = RuntimeError('boom')

        residual_ports, _ = roll_back(ports_manager, _connections_manager(), [102, 101], [])

        assert residual_ports == [101, 102]

    def test_nothing_created_needs_no_statements(self) -> None:
        """A batch that failed on its very first insert has nothing to undo"""
        ports_manager = _ports_manager()
        connections_manager = _connections_manager()

        assert roll_back(ports_manager, connections_manager, [], []) == ([], [])
        ports_manager.delete_many.assert_not_called()
        connections_manager.delete_many.assert_not_called()


# -------------------------------------------------------------------------------------------------------------------- #
#                                                 the orchestration                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
class TestCreateBatch:
    """The whole batch, and what happens when it fails part-way."""

    def test_a_standard_device_gets_ports_and_no_connections(self) -> None:
        """Its ports connect to nothing internally"""
        connections_manager = _connections_manager()

        result = create_batch(
            _ports_manager([101, 102]), connections_manager, OBJECT_ID,
            _standard_preview(['1', '2']), AUTHOR_ID,
        )

        assert result.succeeded()
        assert result.port_ids == [101, 102]
        assert result.connection_ids == []
        connections_manager.insert_item.assert_not_called()

    def test_a_panel_gets_both_faces_and_one_connection_per_pair(self) -> None:
        """24 pairs means 48 ports and 24 internal connections"""
        result = create_batch(
            _ports_manager([101, 102, 201, 202]), _connections_manager([501, 502]), OBJECT_ID,
            _panel_preview(['F1', 'F2'], ['R1', 'R2']), AUTHOR_ID,
        )

        assert result.port_ids == [101, 102, 201, 202]
        assert result.connection_ids == [501, 502]

    def test_the_ports_are_created_before_the_connections(self) -> None:
        """
        A connection stores two port ids, so the reverse order would reference rows that do not exist

        Asserted as an ordering rather than as two calls, because both would report success either way.
        """
        calls: list[str] = []

        ports_manager = _ports_manager([101, 201])
        ports_manager.insert_item.side_effect = lambda _c: (
            calls.append('port') or (101 if calls.count('port') == 1 else 201)
        )
        connections_manager = _connections_manager()
        connections_manager.insert_item.side_effect = lambda _c: calls.append('connection') or 501

        create_batch(
            ports_manager, connections_manager, OBJECT_ID,
            _panel_preview(['F1'], ['R1']), AUTHOR_ID,
        )

        assert calls == ['port', 'port', 'connection']

    def test_the_pairing_uses_the_created_ids_across_the_two_faces(self) -> None:
        """
        The front face's ids pair with the rear face's, not with each other

        Flattening the two faces before pairing would join front 1 to front 2.
        """
        connections_manager = _connections_manager([501, 502])

        create_batch(
            _ports_manager([101, 102, 201, 202]), connections_manager, OBJECT_ID,
            _panel_preview(['F1', 'F2'], ['R1', 'R2']), AUTHOR_ID,
        )

        endpoints = [
            call.args[0][PortConnectionKey.ENDPOINTS.value]
            for call in connections_manager.insert_item.call_args_list
        ]

        assert endpoints == [[101, 201], [102, 202]]

    def test_a_failure_mid_batch_rolls_everything_back(self) -> None:
        """
        §37: never 24 front / 18 rear / 18 internal

        The third port fails, and the two already written are removed again.
        """
        ports_manager = _ports_manager()
        ports_manager.insert_item.side_effect = [101, 102, RuntimeError('duplicate')]

        result = create_batch(
            ports_manager, _connections_manager(), OBJECT_ID,
            _standard_preview(['1', '2', '3']), AUTHOR_ID,
        )

        assert not result.succeeded()
        assert not result.has_residue()
        ports_manager.delete_many.assert_called_once()

    def test_a_failure_creating_a_connection_also_removes_the_ports(self) -> None:
        """A panel whose pairing failed is not a panel, so its ports go too"""
        connections_manager = _connections_manager()
        connections_manager.insert_item.side_effect = RuntimeError('boom')
        ports_manager = _ports_manager([101, 201])

        result = create_batch(
            ports_manager, connections_manager, OBJECT_ID,
            _panel_preview(['F1'], ['R1']), AUTHOR_ID,
        )

        assert not result.succeeded()
        ports_manager.delete_many.assert_called_once_with(
            {PortKey.PUBLIC_ID.value: {'$in': [101, 201]}},
        )

    def test_a_failed_rollback_is_reported_as_residue(self) -> None:
        """
        Neither a success nor a clean failure

        This is the state the honest message exists for: rows survive that nobody asked for, and the
        caller cannot fix it by editing their request.
        """
        ports_manager = _ports_manager(found=[{PortKey.PUBLIC_ID.value: 101}])
        ports_manager.insert_item.side_effect = [101, RuntimeError('boom')]

        result = create_batch(
            ports_manager, _connections_manager(), OBJECT_ID,
            _standard_preview(['1', '2']), AUTHOR_ID,
        )

        assert not result.succeeded()
        assert result.has_residue()
        assert result.residual_port_ids == [101]

    def test_the_error_is_carried_back(self) -> None:
        """The caller reports WHY, not just that something went wrong"""
        ports_manager = _ports_manager()
        ports_manager.insert_item.side_effect = RuntimeError('a duplicate name')

        result = create_batch(
            ports_manager, _connections_manager(), OBJECT_ID, _standard_preview(['1']), AUTHOR_ID,
        )

        assert 'a duplicate name' in result.error


class TestBulkCreateResult:
    """The two questions a caller asks of an outcome."""

    def test_a_complete_batch_succeeded_with_no_residue(self) -> None:
        """The ordinary case"""
        result = BulkCreateResult([1], [2], None, [], [])

        assert result.succeeded() is True
        assert result.has_residue() is False

    def test_a_failed_batch_did_not_succeed(self) -> None:
        """An error is what distinguishes them, not an empty id list"""
        assert BulkCreateResult([], [], 'boom', [], []).succeeded() is False

    @pytest.mark.parametrize('ports,connections', [([1], []), ([], [2]), ([1], [2])], ids=str)
    def test_residue_on_either_side_counts(self, ports: list, connections: list) -> None:
        """A leftover connection is as much of a problem as a leftover port"""
        assert BulkCreateResult([], [], 'boom', ports, connections).has_residue() is True


# -------------------------------------------------------------------------------------------------------------------- #
#                                    the ledger, which a partial failure needs                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class TestTheLedger:
    """
    Everything created has to be rollback-able, including the part of a face that succeeded

    This is the case the naive shape gets wrong: a function that returns its ids only on success loses
    every port a partial failure already wrote, the rollback never learns about them, and the caller is
    told the batch failed cleanly while a dozen ports sit there. §37's forbidden state, arrived at by
    an error path nobody tested.
    """

    def test_a_face_failing_part_way_still_records_what_it_created(self) -> None:
        """The twelve ports written before the thirteenth failed are in the ledger"""
        ledger: list[int] = []
        manager = _ports_manager()
        manager.insert_item.side_effect = [101, 102, RuntimeError('boom')]

        with pytest.raises(RuntimeError):
            create_face_ports(
                manager, OBJECT_ID, _face(PortSide.SINGLE.value, ['1', '2', '3']), AUTHOR_ID, {},
                ledger,
            )

        assert ledger == [101, 102]

    def test_a_pairing_failing_part_way_still_records_what_it_created(self) -> None:
        """The same for the panel's connections"""
        ledger: list[int] = []
        manager = _connections_manager()
        manager.insert_item.side_effect = [501, RuntimeError('boom')]

        with pytest.raises(RuntimeError):
            create_internal_connections(manager, [101, 102], [201, 202], AUTHOR_ID, ledger)

        assert ledger == [501]

    def test_a_batch_rolls_back_the_ports_of_a_partially_failed_face(self) -> None:
        """
        End to end: the rollback removes what the failed face had already written

        Without the ledger this deletes nothing and reports a clean failure.
        """
        ports_manager = _ports_manager()
        ports_manager.insert_item.side_effect = [101, 102, RuntimeError('boom')]

        result = create_batch(
            ports_manager, _connections_manager(), OBJECT_ID,
            _standard_preview(['1', '2', '3']), AUTHOR_ID,
        )

        assert result.port_ids == [101, 102]
        ports_manager.delete_many.assert_called_once_with(
            {PortKey.PUBLIC_ID.value: {'$in': [101, 102]}},
        )

    def test_a_batch_rolls_back_a_completed_face_when_the_second_one_fails(self) -> None:
        """
        A panel whose REAR face fails still has 24 front ports written

        An accumulation that only ran after every face finished would lose all of them.
        """
        ports_manager = _ports_manager()
        ports_manager.insert_item.side_effect = [101, 102, 201, RuntimeError('boom')]

        result = create_batch(
            ports_manager, _connections_manager(), OBJECT_ID,
            _panel_preview(['F1', 'F2'], ['R1', 'R2']), AUTHOR_ID,
        )

        assert result.port_ids == [101, 102, 201]
        ports_manager.delete_many.assert_called_once_with(
            {PortKey.PUBLIC_ID.value: {'$in': [101, 102, 201]}},
        )
