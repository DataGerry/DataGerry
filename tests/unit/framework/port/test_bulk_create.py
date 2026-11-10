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

The fourth is the shape of the write: ONE ``insert_many_items`` for every port and one for the connections, whatever
the size, with the rollback record taken from the ids the reservation wrote into the documents - an unordered insert
that fails does not say which documents it stored.

Pure tests: the managers are mocks whose ``insert_many_items`` reserves ids into the documents the way the real one
does, so a failure can be forced after the reservation
"""
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock

import pytest

from cmdb.framework.port.bulk_create import (
    BulkCreateResult,
    build_face_port_documents,
    build_internal_connection_documents,
    create_batch,
    create_internal_connections,
    create_ports,
    insert_batch,
    roll_back,
    split_by_lengths,
)
from cmdb.framework.port.name_syntax_constants import PortPreviewKey
from cmdb.framework.port.bulk_create_constants import BulkCreateFailureReason
from cmdb.errors.database import DocumentInsertDuplicateKeyError, DocumentLockTimeoutError, DocumentNetworkError
from cmdb.errors.manager.ports_manager import PortsManagerInsertError
from cmdb.models.port_connection_model import ConnectionType, PortConnectionKey
from cmdb.models.port_model import PortKey, PortSide
# -------------------------------------------------------------------------------------------------------------------- #

OBJECT_ID: int = 7700
AUTHOR_ID: int = 1
CREATED_AT: datetime = datetime(2026, 1, 1, tzinfo=timezone.utc)
PUBLIC_ID: str = PortKey.PUBLIC_ID.value


def _face(side: str, names: list[str], numbers: list[int] | None = None) -> dict[str, Any]:
    """One face of a preview; `numbers` is absent for a syntax with no counter token."""
    face: dict[str, Any] = {PortPreviewKey.SIDE.value: side, PortPreviewKey.NAMES.value: names}

    if numbers is not None:
        face[PortPreviewKey.NUMBERS.value] = numbers

    return face


def _standard_preview(names: list[str]) -> dict[str, Any]:
    """A standard device's preview - one face."""
    return {PortPreviewKey.FACES.value: [_face(PortSide.SINGLE.value, names)]}


def _panel_preview(front: list[str], rear: list[str]) -> dict[str, Any]:
    """A patch panel's preview - two faces."""
    return {PortPreviewKey.FACES.value: [
        _face(PortSide.FRONT.value, front),
        _face(PortSide.REAR.value, rear),
    ]}


def _batch_manager(name: str, ids: list[int], found: list[dict] | None,
                   fail_with: Exception | None) -> MagicMock:
    """
    A manager whose insert_many_items behaves like the real one

    It writes the next ids into the documents in place (the reservation), records each batch, then raises
    `fail_with` if given - the unordered insert failing after the ids were reserved - or answers the ids
    """
    manager = MagicMock(name=name)
    issued = iter(ids)
    manager.batches = []

    def _insert_many_items(documents: list[dict[str, Any]]) -> list[int]:
        for document in documents:
            document[PUBLIC_ID] = next(issued)

        manager.batches.append(documents)

        if fail_with is not None:
            raise fail_with

        return [document[PUBLIC_ID] for document in documents]

    manager.insert_many_items.side_effect = _insert_many_items
    manager.find.return_value = found if found is not None else []

    return manager


def _ports_manager(ids: list[int] | None = None, found: list[dict] | None = None,
                   fail_with: Exception | None = None) -> MagicMock:
    """A PortsManager stand-in reserving the given ids in order."""
    return _batch_manager('ports_manager', list(ids or range(100, 200)), found, fail_with)


def _connections_manager(ids: list[int] | None = None, found: list[dict] | None = None,
                         fail_with: Exception | None = None) -> MagicMock:
    """A PortConnectionsManager stand-in reserving the given ids in order."""
    return _batch_manager('port_connections_manager', list(ids or range(500, 600)), found, fail_with)


def _written(manager: MagicMock) -> list[dict[str, Any]]:
    """Every document handed to insert_many_items, in order."""
    return [document for batch in manager.batches for document in batch]


def _face_documents(face: dict[str, Any], values: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """The documents one face builds."""
    return build_face_port_documents(OBJECT_ID, face, AUTHOR_ID, values or {}, CREATED_AT)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                building one face                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
class TestBuildFacePortDocuments:
    """The ports of one face, from the names the preview produced - pure, nothing written"""

    def test_one_document_per_previewed_name_in_order(self) -> None:
        """The names come from the preview, which is what makes the batch what the customer saw"""
        documents = _face_documents(_face(PortSide.SINGLE.value, ['a', 'b', 'c']))

        assert [document[PortKey.NAME.value] for document in documents] == ['a', 'b', 'c']
        assert all(PUBLIC_ID not in document for document in documents)

    def test_each_port_carries_the_face_side_and_the_owner(self) -> None:
        """A panel's ports are only front or rear because the FACE says so"""
        (document,) = _face_documents(_face(PortSide.REAR.value, ['R1']))

        assert document[PortKey.OBJECT_ID.value] == OBJECT_ID
        assert document[PortKey.SIDE.value] == PortSide.REAR.value
        assert document[PortKey.NAME.value] == 'R1'

    def test_the_server_owned_fields_are_stamped(self) -> None:
        """The author and the timestamps come from the request, exactly as on a single create"""
        (document,) = _face_documents(_face(PortSide.SINGLE.value, ['1']))

        assert document[PortKey.AUTHOR_ID.value] == AUTHOR_ID
        assert document[PortKey.CREATION_TIME.value] == CREATED_AT
        assert document[PortKey.LAST_EDIT_TIME.value] is None

    def test_the_shared_values_reach_every_port(self) -> None:
        """A customer creating 48 uplinks wants them all Up / SFP+ / 10G - not 48 more requests"""
        documents = _face_documents(_face(PortSide.SINGLE.value, ['1', '2']), {PortKey.SPEED.value: 9})

        assert [document[PortKey.SPEED.value] for document in documents] == [9, 9]

    def test_the_shared_values_never_override_the_identity(self) -> None:
        """The name and the side are the batch's own business, whatever a body tried to say"""
        (document,) = _face_documents(
            _face(PortSide.FRONT.value, ['F1']),
            {PortKey.NAME.value: 'hijacked', PortKey.SIDE.value: PortSide.SINGLE.value},
        )

        assert document[PortKey.NAME.value] == 'F1'
        assert document[PortKey.SIDE.value] == PortSide.FRONT.value

    def test_an_empty_face_builds_nothing(self) -> None:
        """Not reachable through the routes, which refuse a count below 1"""
        assert not _face_documents(_face(PortSide.SINGLE.value, []))


class TestTheCreatedPortsCarryTheirNumber:
    """
    Backlog #201: a bulk-created port stored no `port_number`, so a whole device read back
    lexicographically

    `get_ports_of_object` sorts by `port_number` then `name`. With the number absent every port of a
    batch sorted equal and the tiebreak was the name as a string - `Gi0/1, Gi0/10, Gi0/11, ... Gi0/2`.
    A port made through `POST /ports/` never had the problem, because that route has always accepted
    `port_number`; the two create paths disagreed.
    """

    def test_each_port_stores_the_number_that_rendered_its_name(self) -> None:
        """Taken from the preview by position, not re-derived - the name and the number are one pair."""
        documents = _face_documents(_face(PortSide.SINGLE.value, ['Gi0/1', 'Gi0/2', 'Gi0/3'], [1, 2, 3]))

        assert [document[PortKey.PORT_NUMBER.value] for document in documents] == [1, 2, 3]

    def test_a_second_batch_keeps_its_own_start(self) -> None:
        """The numbering continues where the previous batch stopped, as the names do."""
        documents = _face_documents(_face(PortSide.SINGLE.value, ['Gi0/49', 'Gi0/50'], [49, 50]))

        assert [document[PortKey.PORT_NUMBER.value] for document in documents] == [49, 50]

    def test_a_face_without_numbers_writes_none(self) -> None:
        """A syntax with no counter renders a name carrying no number - so the field carries none either"""
        (document,) = _face_documents(_face(PortSide.SINGLE.value, ['Uplink']))

        assert PortKey.PORT_NUMBER.value not in document

    def test_the_shared_values_do_not_override_the_number(self) -> None:
        """The batch's shared field values are applied first, so the identity always wins."""
        (document,) = _face_documents(_face(PortSide.SINGLE.value, ['Gi0/7'], [7]), {PortKey.PORT_NUMBER.value: 999})

        assert document[PortKey.PORT_NUMBER.value] == 7


# -------------------------------------------------------------------------------------------------------------------- #
#                                           one write for every port                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
class TestCreatePorts:
    """Every face in ONE insert_many_items, answered face by face"""

    def test_both_faces_are_one_write(self) -> None:
        """A panel's front and rear go in one batch, front first - one reservation, one insert"""
        manager = _ports_manager([101, 102, 201, 202])

        create_ports(manager, OBJECT_ID, _panel_preview(['F1', 'F2'], ['R1', 'R2'])[PortPreviewKey.FACES.value],
                     AUTHOR_ID, {}, [])

        assert manager.insert_many_items.call_count == 1
        assert [document[PortKey.NAME.value] for document in _written(manager)] == ['F1', 'F2', 'R1', 'R2']
        manager.insert_item.assert_not_called()

    def test_the_ids_are_answered_per_face(self) -> None:
        """Split back by each face's length, so front port i stays front port i"""
        manager = _ports_manager([101, 102, 201, 202])

        assert create_ports(
            manager, OBJECT_ID, _panel_preview(['F1', 'F2'], ['R1', 'R2'])[PortPreviewKey.FACES.value],
            AUTHOR_ID, {}, [],
        ) == [[101, 102], [201, 202]]

    def test_every_port_of_the_batch_shares_one_creation_time(self) -> None:
        """One write, one moment"""
        manager = _ports_manager()

        create_ports(manager, OBJECT_ID, _panel_preview(['F1'], ['R1'])[PortPreviewKey.FACES.value], AUTHOR_ID, {}, [])

        assert len({document[PortKey.CREATION_TIME.value] for document in _written(manager)}) == 1

    def test_no_face_writes_nothing(self) -> None:
        """An empty preview costs no round trip"""
        manager = _ports_manager()

        assert create_ports(manager, OBJECT_ID, [], AUTHOR_ID, {}, []) == []
        manager.insert_many_items.assert_not_called()


class TestSplitByLengths:
    """Cutting the flat id list back into faces"""

    @pytest.mark.parametrize('values,lengths,expected', [
        pytest.param([1, 2, 3, 4], [2, 2], [[1, 2], [3, 4]], id='two faces'),
        pytest.param([1, 2, 3], [3], [[1, 2, 3]], id='one face'),
        pytest.param([1, 2, 3], [1, 0, 2], [[1], [], [2, 3]], id='an empty face'),
        pytest.param([], [], [], id='nothing'),
    ])
    def test_consecutive_parts(self, values: list[int], lengths: list[int], expected: list[list[int]]) -> None:
        """Parts in order, each as long as asked"""
        assert split_by_lengths(values, lengths) == expected


# -------------------------------------------------------------------------------------------------------------------- #
#                                              the panel's pairing                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
class TestBuildInternalConnectionDocuments:
    """The pairing IS the connection - pure"""

    def test_front_i_is_joined_to_rear_i(self) -> None:
        """
        Positional, by public_id

        The names are never consulted - the concept forbids deriving the pairing from them, and this is
        what makes two faces named nothing alike pair correctly.
        """
        documents = build_internal_connection_documents([101, 102], [201, 202], AUTHOR_ID, CREATED_AT)

        assert [document[PortConnectionKey.ENDPOINTS.value] for document in documents] == [[101, 201], [102, 202]]

    def test_the_endpoints_are_stored_sorted(self) -> None:
        """A re-numbered device has the rear id LOWER - stored sorted, shaped like a cable for the same index"""
        (document,) = build_internal_connection_documents([900], [100], AUTHOR_ID, CREATED_AT)

        assert document[PortConnectionKey.ENDPOINTS.value] == [100, 900]

    def test_every_connection_is_internal_and_stamped(self) -> None:
        """A panel's pairing is not a cable, and the two live under different unique indexes"""
        (document,) = build_internal_connection_documents([101], [201], AUTHOR_ID, CREATED_AT)

        assert document[PortConnectionKey.CONNECTION_TYPE.value] == ConnectionType.INTERNAL.value
        assert document[PortConnectionKey.AUTHOR_ID.value] == AUTHOR_ID
        assert document[PortConnectionKey.CREATION_TIME.value] == CREATED_AT
        assert document[PortConnectionKey.LAST_EDIT_TIME.value] is None

    def test_no_cable_information_is_written(self) -> None:
        """Cable fields are refused on an INTERNAL connection, so the batch must not set any"""
        (document,) = build_internal_connection_documents([101], [201], AUTHOR_ID, CREATED_AT)

        assert PortConnectionKey.CABLE_NAME.value not in document
        assert PortConnectionKey.CABLE_CI_ID.value not in document

    def test_unequal_faces_raise_rather_than_pairing_silently(self) -> None:
        """
        Cannot happen through the routes - one count drives both faces - so it must be loud here

        A zip that stopped at the shorter face would leave the extra ports unpaired and report success,
        which is precisely §37's forbidden state.
        """
        with pytest.raises(ValueError):
            build_internal_connection_documents([101, 102], [201], AUTHOR_ID, CREATED_AT)


class TestCreateInternalConnections:
    """One write for every pair"""

    def test_one_connection_per_pair_in_one_write(self) -> None:
        """A 24-pair panel gets 24 internal connections, not 48 - in one insert_many_items"""
        manager = _connections_manager([501, 502])

        assert create_internal_connections(manager, [101, 102], [201, 202], AUTHOR_ID, []) == [501, 502]
        assert manager.insert_many_items.call_count == 1
        assert [document[PortConnectionKey.ENDPOINTS.value] for document in _written(manager)] == [
            [101, 201], [102, 202],
        ]

    def test_unequal_faces_write_nothing(self) -> None:
        """The pairing is checked before the write"""
        manager = _connections_manager()

        with pytest.raises(ValueError):
            create_internal_connections(manager, [101, 102], [201], AUTHOR_ID, [])

        manager.insert_many_items.assert_not_called()


# -------------------------------------------------------------------------------------------------------------------- #
#                                    the ledger, which a failed write needs                                            #
# -------------------------------------------------------------------------------------------------------------------- #
class TestInsertBatch:
    """
    Everything the batch MAY have stored has to be rollback-able

    An unordered insert that fails answers nothing and does not say which documents it stored. Recording what the
    write returned would record nothing exactly when the rollback needs everything - the batch would report a clean
    failure while its ports sat there. So the ids are taken from the documents, which the reservation filled in
    """

    def test_a_completed_write_records_and_answers_its_ids(self) -> None:
        """The ordinary case: the ledger and the answer agree"""
        ledger: list[int] = []
        manager = _ports_manager([101, 102])

        assert insert_batch(manager, [{}, {}], ledger) == [101, 102]
        assert ledger == [101, 102]

    def test_a_failed_write_still_records_every_reserved_id(self) -> None:
        """The insert raised after the reservation: every id is in the ledger, and the error propagates"""
        ledger: list[int] = []
        manager = _ports_manager([101, 102, 103], fail_with=RuntimeError('boom'))

        with pytest.raises(RuntimeError):
            insert_batch(manager, [{}, {}, {}], ledger)

        assert ledger == [101, 102, 103]

    def test_a_failure_before_the_reservation_records_nothing(self) -> None:
        """No id was written into a document, so nothing can have been stored"""
        ledger: list[int] = []
        manager = MagicMock()
        manager.insert_many_items.side_effect = RuntimeError('no block')

        with pytest.raises(RuntimeError):
            insert_batch(manager, [{}, {}], ledger)

        assert not ledger

    def test_no_documents_costs_no_round_trip(self) -> None:
        """Nothing to write, nothing recorded"""
        manager = _ports_manager()

        assert insert_batch(manager, [], []) == []
        manager.insert_many_items.assert_not_called()


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
    """The whole batch, and what happens when it fails"""

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
        connections_manager.insert_many_items.assert_not_called()

    def test_a_panel_is_two_writes_with_one_connection_per_pair(self) -> None:
        """2 pairs: 4 ports in one write, 2 internal connections in a second"""
        ports_manager = _ports_manager([101, 102, 201, 202])
        connections_manager = _connections_manager([501, 502])

        result = create_batch(ports_manager, connections_manager, OBJECT_ID,
                              _panel_preview(['F1', 'F2'], ['R1', 'R2']), AUTHOR_ID)

        assert result.port_ids == [101, 102, 201, 202]
        assert result.connection_ids == [501, 502]
        assert (ports_manager.insert_many_items.call_count, connections_manager.insert_many_items.call_count) == (1, 1)

    def test_the_ports_are_created_before_the_connections(self) -> None:
        """
        A connection stores two port ids, so the reverse order would reference rows that do not exist

        Asserted as an ordering rather than as two calls, because both would report success either way.
        """
        calls: list[str] = []
        ports_manager = _ports_manager([101, 201])
        connections_manager = _connections_manager([501])
        port_write = ports_manager.insert_many_items.side_effect
        connection_write = connections_manager.insert_many_items.side_effect
        ports_manager.insert_many_items.side_effect = lambda documents: calls.append('ports') or port_write(documents)
        connections_manager.insert_many_items.side_effect = (
            lambda documents: calls.append('connections') or connection_write(documents)
        )

        create_batch(ports_manager, connections_manager, OBJECT_ID, _panel_preview(['F1'], ['R1']), AUTHOR_ID)

        assert calls == ['ports', 'connections']

    def test_the_pairing_uses_the_created_ids_across_the_two_faces(self) -> None:
        """The front face's ids pair with the rear face's - flattening first would join front 1 to front 2"""
        connections_manager = _connections_manager([501, 502])

        create_batch(
            _ports_manager([101, 102, 201, 202]), connections_manager, OBJECT_ID,
            _panel_preview(['F1', 'F2'], ['R1', 'R2']), AUTHOR_ID,
        )

        assert [document[PortConnectionKey.ENDPOINTS.value] for document in _written(connections_manager)] == [
            [101, 201], [102, 202],
        ]

    def test_a_failed_port_write_rolls_back_every_reserved_id(self) -> None:
        """
        §37: never 24 front / 18 rear / 18 internal

        The unordered insert may have stored any part of the batch, so every reserved id is rolled back - the
        verification read decides what really survived.
        """
        ports_manager = _ports_manager([101, 102, 103], fail_with=RuntimeError('boom'))

        result = create_batch(ports_manager, _connections_manager(), OBJECT_ID,
                              _standard_preview(['1', '2', '3']), AUTHOR_ID)

        assert not result.succeeded()
        assert not result.has_residue()
        assert result.port_ids == [101, 102, 103]
        ports_manager.delete_many.assert_called_once_with({PUBLIC_ID: {'$in': [101, 102, 103]}})

    def test_a_failed_pairing_also_removes_the_ports(self) -> None:
        """A panel whose pairing failed is not a panel: its connections' reserved ids and its ports go"""
        ports_manager = _ports_manager([101, 201])
        connections_manager = _connections_manager([501], fail_with=RuntimeError('boom'))

        result = create_batch(ports_manager, connections_manager, OBJECT_ID,
                              _panel_preview(['F1'], ['R1']), AUTHOR_ID)

        assert not result.succeeded()
        connections_manager.delete_many.assert_called_once_with({PUBLIC_ID: {'$in': [501]}})
        ports_manager.delete_many.assert_called_once_with({PUBLIC_ID: {'$in': [101, 201]}})

    def test_a_failed_rollback_is_reported_as_residue(self) -> None:
        """
        Neither a success nor a clean failure

        Rows survive that nobody asked for, and the caller cannot fix it by editing their request.
        """
        ports_manager = _ports_manager([101, 102], found=[{PUBLIC_ID: 101}], fail_with=RuntimeError('boom'))

        result = create_batch(ports_manager, _connections_manager(), OBJECT_ID,
                              _standard_preview(['1', '2']), AUTHOR_ID)

        assert not result.succeeded()
        assert result.residual_port_ids == [101]

    def test_a_failed_write_is_reported_as_the_servers_failure(self) -> None:
        """The reason is in words the user can read - never the database's own text; no duplicate"""
        ports_manager = _ports_manager(fail_with=RuntimeError("E11000 in collection 'framework.ports'"))

        result = create_batch(ports_manager, _connections_manager(), OBJECT_ID, _standard_preview(['1']), AUTHOR_ID)

        assert result.error == BulkCreateFailureReason.WRITE_FAILED.value
        assert result.duplicate is False

    def test_a_lost_race_is_reported_as_a_duplicate(self) -> None:
        """A concurrent write took a previewed name: the one failure the user can resolve"""
        refusal = DocumentInsertDuplicateKeyError('duplicate', key_pattern={PortKey.NAME.value: 1})
        failure = PortsManagerInsertError(refusal)
        failure.__cause__ = refusal

        result = create_batch(_ports_manager(fail_with=failure), _connections_manager(), OBJECT_ID,
                              _standard_preview(['1']), AUTHOR_ID)

        assert result.error == BulkCreateFailureReason.NAME_TAKEN.value
        assert result.duplicate is True


class TestAnOutageIsRolledBackThenPassedOn:
    """A lost connection or a lock timeout is the app handlers' to answer (503 / 423), after the rollback"""

    @pytest.mark.parametrize('outage', [
        pytest.param(DocumentNetworkError('connection lost'), id='lost connection'),
        pytest.param(DocumentLockTimeoutError('locked'), id='lock timeout'),
    ])
    def test_the_outage_propagates_after_the_rollback(self, outage: Exception) -> None:
        """The same error comes out, and the reserved ids were rolled back first"""
        ports_manager = _ports_manager([101, 102], fail_with=outage)

        with pytest.raises(type(outage)) as caught:
            create_batch(ports_manager, _connections_manager(), OBJECT_ID, _standard_preview(['1', '2']), AUTHOR_ID)

        assert caught.value is outage
        ports_manager.delete_many.assert_called_once_with({PUBLIC_ID: {'$in': [101, 102]}})

    def test_the_residue_of_an_outage_is_logged(self, caplog: pytest.LogCaptureFixture) -> None:
        """The handlers' answer cannot carry ids, so whoever cleans up finds them in the log"""
        ports_manager = _ports_manager([101, 102], found=[{PUBLIC_ID: 102}], fail_with=DocumentNetworkError('gone'))

        with pytest.raises(DocumentNetworkError):
            create_batch(ports_manager, _connections_manager(), OBJECT_ID, _standard_preview(['1', '2']), AUTHOR_ID)

        assert 'left behind: ports [102]' in caplog.text


class TestBulkCreateResult:
    """The two questions a caller asks of an outcome."""

    def test_a_result_is_no_duplicate_unless_it_says_so(self) -> None:
        """The flag defaults off, so every existing construction keeps meaning 'the write failed'"""
        assert BulkCreateResult([], [], 'boom', [], []).duplicate is False

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
#                                      per-face field values on a panel                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class TestValuesAreResolvedPerFace:
    """A panel's two faces are not the same equipment, so each carries its own field values."""

    def test_each_face_is_handed_its_own_values(self) -> None:
        """create_batch looks the face's values up by side rather than spreading one set"""
        manager = _ports_manager()

        create_batch(manager, _connections_manager(), OBJECT_ID, _panel_preview(['F1'], ['R1']), AUTHOR_ID, {
            PortSide.FRONT.value: {PortKey.DESCRIPTION.value: 'front side'},
            PortSide.REAR.value: {PortKey.DESCRIPTION.value: 'rear side'},
        })

        written = {
            document[PortKey.SIDE.value]: document[PortKey.DESCRIPTION.value] for document in _written(manager)
        }

        assert written == {PortSide.FRONT.value: 'front side', PortSide.REAR.value: 'rear side'}

    def test_a_face_the_mapping_does_not_name_gets_no_values(self) -> None:
        """Absent rather than guessed - the model's own defaults still apply"""
        manager = _ports_manager()

        create_batch(manager, _connections_manager(), OBJECT_ID, _standard_preview(['1']), AUTHOR_ID, {})

        assert PortKey.DESCRIPTION.value not in _written(manager)[0]
