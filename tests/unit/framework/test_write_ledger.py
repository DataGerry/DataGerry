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
Unit tests for cmdb.framework.write_ledger - the compensating undo of a request's writes

Managers are MagicMocks recording their calls in one shared list, so the undo ORDER is asserted, not only that
each step ran. Each undo step is also broken on purpose: a failing undo must report residue, never raise.
"""
from typing import Any
from unittest.mock import MagicMock

import pytest

from cmdb.framework.write_ledger import LedgerResidue, WriteLedger
from cmdb.framework.write_ledger_constants import LedgerResidueKey, WriteKind
# -------------------------------------------------------------------------------------------------------------------- #

PORTS: str = 'framework.ports'
CONNECTIONS: str = 'framework.portConnections'
PRIOR: dict[str, Any] = {'public_id': 7, 'name': 'before', '_id': 'stored-id'}
BATCH_CRITERIA: dict[str, Any] = {'risk_assessment_id': 40}


def _manager(collection: str, calls: list[tuple], stored: dict[int, dict[str, Any]] | None = None,
             remaining: int = 0) -> MagicMock:
    """A manager whose writes are recorded in `calls` and whose reads answer `stored` / `remaining`."""
    manager = MagicMock()
    manager.collection = collection
    store: dict[int, dict[str, Any]] = dict(stored or {})

    manager.delete_many.side_effect = lambda criteria: calls.append((collection, 'delete_many', criteria))
    manager.find.side_effect = lambda criteria: [
        {'public_id': public_id} for public_id in criteria['public_id']['$in'] if public_id in store
    ]
    manager.count_documents.side_effect = lambda _criteria: remaining

    def _replace(public_id: int, document: dict[str, Any]) -> None:
        calls.append((collection, 'replace', public_id))
        store[public_id] = dict(document)

    def _insert(document: dict[str, Any], skip_public: bool = False) -> int:
        calls.append((collection, 'insert', document['public_id'], skip_public))
        store[document['public_id']] = dict(document)
        return document['public_id']

    manager.replace.side_effect = _replace
    manager.insert.side_effect = _insert
    manager.get_one_by.side_effect = lambda criteria: store.get(criteria['public_id'])

    return manager


class TestRecording:
    """What the ledger holds."""

    def test_the_entries_keep_the_order_the_writes_happened_in(self) -> None:
        """Newest last - the undo reverses it."""
        manager = MagicMock()
        ledger = WriteLedger()
        ledger.inserted(manager, 1)
        ledger.updated(manager, 2, PRIOR)
        ledger.deleted(manager, 3, PRIOR)
        ledger.inserted_where(manager, BATCH_CRITERIA)

        assert [entry.kind for entry in ledger.entries] == [
            WriteKind.INSERT, WriteKind.UPDATE, WriteKind.DELETE, WriteKind.INSERT_BATCH,
        ]

    def test_a_snapshot_is_copied_so_later_changes_do_not_alter_it(self) -> None:
        """The caller keeps mutating its documents; the ledger must remember them as they were."""
        prior = dict(PRIOR)
        ledger = WriteLedger()
        ledger.updated(MagicMock(), 7, prior)
        prior['name'] = 'after'

        assert ledger.entries[0].prior['name'] == 'before'

    def test_an_empty_ledger_undoes_nothing(self) -> None:
        """No writes, no calls, no residue."""
        assert not WriteLedger().undo()


class TestUndoOrder:
    """Newest first, and consecutive inserts into one collection as one statement."""

    def test_inserts_are_removed_newest_collection_first_in_one_delete_each(self) -> None:
        """Ports then connections were written, so connections go first - one delete per collection."""
        calls: list[tuple] = []
        ports, connections = _manager(PORTS, calls), _manager(CONNECTIONS, calls)
        ledger = WriteLedger()
        for port_id in (11, 12):
            ledger.inserted(ports, port_id)
        ledger.inserted(connections, 21)

        assert not ledger.undo()
        assert calls == [
            (CONNECTIONS, 'delete_many', {'public_id': {'$in': [21]}}),
            (PORTS, 'delete_many', {'public_id': {'$in': [11, 12]}}),
        ]

    def test_every_kind_is_undone_in_reverse_order(self) -> None:
        """insert, update, delete - undone as re-insert, restore, delete."""
        calls: list[tuple] = []
        manager = _manager(PORTS, calls, stored={7: {'public_id': 7, 'name': 'after'}})
        ledger = WriteLedger()
        ledger.inserted(manager, 5)
        ledger.updated(manager, 7, PRIOR)
        ledger.deleted(manager, 9, {'public_id': 9})

        assert not ledger.undo()
        assert calls == [
            (PORTS, 'insert', 9, True),
            (PORTS, 'replace', 7),
            (PORTS, 'delete_many', {'public_id': {'$in': [5]}}),
        ]


class TestEachUndoStep:
    """What each kind of undo does, and what it reports when it cannot."""

    def test_an_insert_still_stored_after_the_delete_is_residue(self) -> None:
        """The verification read decides, not the delete's own result."""
        manager = _manager(PORTS, [], stored={11: {'public_id': 11}})
        ledger = WriteLedger()
        ledger.inserted(manager, 11)
        ledger.inserted(manager, 12)

        assert ledger.undo() == [LedgerResidue(PORTS, WriteKind.INSERT, public_id=11)]

    def test_a_failed_insert_delete_is_logged_and_the_survivors_reported(self) -> None:
        """The delete raising does not end the undo: the verification read still names what is stored."""
        manager = _manager(PORTS, [], stored={11: {'public_id': 11}})
        manager.delete_many.side_effect = RuntimeError('delete failed')
        ledger = WriteLedger()
        ledger.inserted(manager, 11)

        assert ledger.undo() == [LedgerResidue(PORTS, WriteKind.INSERT, public_id=11)]

    def test_an_unverifiable_insert_removal_reports_every_id(self) -> None:
        """Nothing can be promised about a cleanup that could not be checked."""
        manager = _manager(PORTS, [])
        manager.find.side_effect = RuntimeError('read failed')
        ledger = WriteLedger()
        ledger.inserted(manager, 12)
        ledger.inserted(manager, 11)

        assert [item.public_id for item in ledger.undo()] == [11, 12]

    @pytest.mark.parametrize('remaining, expected', [(0, 0), (2, 1)], ids=['all-gone', 'some-left'])
    def test_a_batch_is_residue_while_anything_still_matches(self, remaining: int, expected: int) -> None:
        """The criteria are deleted, then counted."""
        manager = _manager(PORTS, [], remaining=remaining)
        ledger = WriteLedger()
        ledger.inserted_where(manager, BATCH_CRITERIA)

        residue = ledger.undo()

        manager.delete_many.assert_called_once_with(BATCH_CRITERIA)
        assert len(residue) == expected

    def test_a_batch_whose_delete_fails_is_residue_when_it_still_matches(self) -> None:
        """A failed delete is logged, not raised - the count then reports what is left."""
        manager = _manager(PORTS, [], remaining=2)
        manager.delete_many.side_effect = RuntimeError('delete failed')
        ledger = WriteLedger()
        ledger.inserted_where(manager, BATCH_CRITERIA)

        assert ledger.undo() == [LedgerResidue(PORTS, WriteKind.INSERT_BATCH, criteria=BATCH_CRITERIA)]

    def test_a_batch_whose_count_fails_is_residue(self) -> None:
        """An unverifiable cleanup is reported, so somebody looks."""
        manager = _manager(PORTS, [])
        manager.count_documents.side_effect = RuntimeError('count failed')
        ledger = WriteLedger()
        ledger.inserted_where(manager, BATCH_CRITERIA)

        assert ledger.undo() == [LedgerResidue(PORTS, WriteKind.INSERT_BATCH, criteria=BATCH_CRITERIA)]

    def test_an_update_whose_document_is_gone_is_residue(self) -> None:
        """Nothing to compare the snapshot against: the restore did not take."""
        manager = _manager(PORTS, [])
        manager.replace.side_effect = RuntimeError('no such document')
        ledger = WriteLedger()
        ledger.updated(manager, 7, PRIOR)

        assert ledger.undo() == [LedgerResidue(PORTS, WriteKind.UPDATE, public_id=7)]

    def test_an_update_is_restored_from_its_snapshot_id_aside(self) -> None:
        """The stored document equals the snapshot again; its _id is not compared."""
        manager = _manager(PORTS, [], stored={7: {'public_id': 7, 'name': 'after', 'added': True}})
        ledger = WriteLedger()
        ledger.updated(manager, 7, PRIOR)

        assert not ledger.undo()
        manager.replace.assert_called_once_with(7, PRIOR)

    def test_an_update_that_is_not_back_to_its_snapshot_is_residue(self) -> None:
        """A replace that failed leaves the changed document - reported, not raised."""
        manager = _manager(PORTS, [], stored={7: {'public_id': 7, 'name': 'after'}})
        manager.replace.side_effect = RuntimeError('replace failed')
        ledger = WriteLedger()
        ledger.updated(manager, 7, PRIOR)

        assert ledger.undo() == [LedgerResidue(PORTS, WriteKind.UPDATE, public_id=7)]

    def test_a_delete_is_undone_by_re_inserting_under_the_old_id(self) -> None:
        """skip_public: the document comes back exactly, id included."""
        calls: list[tuple] = []
        manager = _manager(PORTS, calls)
        ledger = WriteLedger()
        ledger.deleted(manager, 9, {'public_id': 9, 'name': 'gone'})

        assert not ledger.undo()
        assert calls == [(PORTS, 'insert', 9, True)]

    def test_a_delete_that_did_not_happen_is_not_re_inserted(self) -> None:
        """
        Recorded before it ran: the document is still stored, so it is left alone - never inserted a second time,
        whether or not a unique index would have refused the copy
        """
        manager = _manager(PORTS, [], stored={9: {'public_id': 9}})
        ledger = WriteLedger()
        ledger.deleted(manager, 9, {'public_id': 9})

        assert not ledger.undo()
        manager.insert.assert_not_called()

    def test_a_failed_read_back_is_residue(self) -> None:
        """An undo that cannot be verified is reported."""
        manager = _manager(PORTS, [])
        manager.get_one_by.side_effect = RuntimeError('read failed')
        ledger = WriteLedger()
        ledger.deleted(manager, 9, {'public_id': 9})

        assert ledger.undo() == [LedgerResidue(PORTS, WriteKind.DELETE, public_id=9)]


class TestResidueJson:
    """How a refusal names what is left."""

    def test_a_document_is_named_by_its_id(self) -> None:
        """collection, kind, public_id."""
        assert LedgerResidue(PORTS, WriteKind.INSERT, public_id=3).to_json() == {
            LedgerResidueKey.COLLECTION.value: PORTS,
            LedgerResidueKey.KIND.value: WriteKind.INSERT.value,
            LedgerResidueKey.PUBLIC_ID.value: 3,
        }

    def test_a_batch_is_named_by_its_criteria(self) -> None:
        """Its ids were never known."""
        assert LedgerResidue(PORTS, WriteKind.INSERT_BATCH, criteria=BATCH_CRITERIA).to_json()[
            LedgerResidueKey.CRITERIA.value] == BATCH_CRITERIA


class TestCompensated:
    """A write that brings its own inverse and its own check."""

    def test_the_inverse_runs_in_its_place_in_the_undo_order(self) -> None:
        """Newest first, between the other kinds."""
        calls: list[tuple] = []
        manager = _manager(PORTS, calls)
        ledger = WriteLedger()
        ledger.inserted(manager, 5)
        ledger.compensated(CONNECTIONS, 'the field of 1', undo=lambda: calls.append((CONNECTIONS, 'inverse')),
                           verify=lambda: True)

        assert not ledger.undo()
        assert calls == [(CONNECTIONS, 'inverse'), (PORTS, 'delete_many', {'public_id': {'$in': [5]}})]

    @pytest.mark.parametrize('undo, verify', [
        (lambda: None, lambda: False),
        (lambda: (_ for _ in ()).throw(RuntimeError('inverse failed')), lambda: False),
        (lambda: None, lambda: (_ for _ in ()).throw(RuntimeError('check failed'))),
    ], ids=['not-restored', 'inverse-raises', 'check-raises'])
    def test_an_inverse_that_did_not_take_is_residue_named_by_its_description(self, undo, verify) -> None:
        """Logged and reported, never raised."""
        ledger = WriteLedger()
        ledger.compensated(CONNECTIONS, 'the field of 1', undo=undo, verify=verify)

        residue = ledger.undo()

        assert residue == [LedgerResidue(CONNECTIONS, WriteKind.COMPENSATED, description='the field of 1')]
        assert residue[0].to_json()[LedgerResidueKey.DESCRIPTION.value] == 'the field of 1'



class _BatchStore:
    """A collection kept in memory by `_id`, with the three calls a batch-delete undo makes"""

    def __init__(self, collection: str, documents: list[dict[str, Any]]) -> None:
        self.collection = collection
        self.stored: dict[Any, dict[str, Any]] = {doc['_id']: dict(doc) for doc in documents}
        self.inserts: list[list[dict[str, Any]]] = []
        self.fail_insert = False

    def find(self, criteria: dict[str, Any], projection: dict[str, Any]) -> list[dict[str, Any]]:
        """The stored documents among the criteria's `_id`s, projected to `_id`"""
        assert projection == {'_id': 1}
        return [{'_id': key} for key in criteria['_id']['$in'] if key in self.stored]

    def insert_many(self, documents: list[dict[str, Any]], skip_public: bool) -> None:
        """Stores the documents as they are"""
        assert skip_public
        if self.fail_insert:
            raise RuntimeError('insert failed')
        self.inserts.append(documents)
        self.stored.update({doc['_id']: dict(doc) for doc in documents})

    def count_documents(self, criteria: dict[str, Any]) -> int:
        """How many of the criteria's `_id`s are stored"""
        return sum(key in self.stored for key in criteria['_id']['$in'])


BATCH_DOCS: list[dict[str, Any]] = [{'_id': 'a', 'user_id': 1}, {'_id': 'b', 'user_id': 2}, {'_id': 'c'}]


class TestDeletedMany:
    """A batch delete undone in one read, one insert and one count."""

    def test_an_empty_batch_records_nothing(self) -> None:
        """Nothing was deleted, so there is nothing to undo."""
        ledger = WriteLedger()

        ledger.deleted_many(_BatchStore(PORTS, []), [], 'nothing')

        assert not ledger.entries

    def test_re_inserts_only_the_missing_snapshots_in_one_write(self) -> None:
        """'a' survived the partial delete; 'b' and 'c' (which has no public_id) come back together."""
        store = _BatchStore(PORTS, BATCH_DOCS)
        ledger = WriteLedger()
        ledger.deleted_many(store, BATCH_DOCS, 'the batch')
        del store.stored['b'], store.stored['c']

        assert not ledger.undo()
        assert store.inserts == [[BATCH_DOCS[1], BATCH_DOCS[2]]]
        assert set(store.stored) == {'a', 'b', 'c'}

    def test_undoing_a_delete_that_never_ran_inserts_nothing(self) -> None:
        """Every snapshot is still stored: the undo is a read and a count."""
        store = _BatchStore(PORTS, BATCH_DOCS)
        ledger = WriteLedger()
        ledger.deleted_many(store, BATCH_DOCS, 'the batch')

        assert not ledger.undo()
        assert not store.inserts

    def test_the_snapshots_are_copies(self) -> None:
        """A caller changing its list after recording does not change what is restored."""
        store = _BatchStore(PORTS, [])
        priors = [{'_id': 'a', 'user_id': 1}]
        ledger = WriteLedger()
        ledger.deleted_many(store, priors, 'the batch')
        priors[0]['user_id'] = 99

        ledger.undo()

        assert store.stored['a'] == {'_id': 'a', 'user_id': 1}

    def test_a_failed_re_insert_is_residue_named_by_its_description(self) -> None:
        """The count finds them missing."""
        store = _BatchStore(PORTS, [])
        store.fail_insert = True
        ledger = WriteLedger()
        ledger.deleted_many(store, BATCH_DOCS, 'the batch')

        assert ledger.undo() == [LedgerResidue(PORTS, WriteKind.COMPENSATED, description='the batch')]
