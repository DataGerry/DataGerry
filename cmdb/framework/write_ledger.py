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
A record of the writes one request made across collections, and the compensating undo of them

MongoDB's multi-document transactions need a replica set, and DataGerry runs on a standalone server (the
shipped compose file and CI both do). A request that writes several documents therefore cannot be made
atomic by the database; it is made **all-or-nothing by compensation** instead: every write is recorded as it
happens, and on failure the ledger undoes them in reverse order - an insert deleted, an update replaced by the
snapshot taken before it, a delete re-inserted under its old id.

**The undo verifies instead of trusting.** After each step the ledger reads back what is actually stored, and
anything it could not put back is reported as residue - so a caller can answer "this was left behind, here is
what" rather than a success, or a clean failure, that is not true. Every failure inside the undo is logged and
swallowed on purpose: it already runs on an error path, and an undo that raised would replace the honest residue
report with a stack trace naming neither.

Consecutive inserts into the same collection are undone as one batch: one delete, one verification read. A batch of
deletes recorded with ``deleted_many`` is undone the same way: one read of which snapshots are still stored, one
insert of the rest, one count.
"""
from dataclasses import dataclass
from logging import Logger, getLogger
from typing import Any, Callable

from cmdb.database.database_constants import PUBLIC_ID_FIELD
from cmdb.framework.write_ledger_constants import LedgerResidueKey, WriteKind
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# The stored identity of a MongoDB document: never part of a snapshot comparison, since a replace keeps it
MONGO_ID_FIELD: str = '_id'


@dataclass(frozen=True)
class LedgerEntry:
    """
    One recorded write

    Attributes:
        kind (WriteKind): What the write did
        manager (Any): The manager of the written collection - anything with BaseManager's API
        public_id (int | None): The written document's public_id; None for an INSERT_BATCH
        prior (dict[str, Any] | None): The document as it was before an UPDATE or a DELETE
        criteria (dict[str, Any] | None): What an INSERT_BATCH's documents match
        collection (str | None): The written collection of a COMPENSATED write, which names no manager
        description (str | None): What a COMPENSATED write did, as the residue names it
        undo (Callable[[], None] | None): A COMPENSATED write's inverse
        verify (Callable[[], bool] | None): Whether a COMPENSATED write's inverse took effect
    """
    kind: WriteKind
    manager: Any
    public_id: int | None = None
    prior: dict[str, Any] | None = None
    criteria: dict[str, Any] | None = None
    collection: str | None = None
    description: str | None = None
    undo: Callable[[], None] | None = None
    verify: Callable[[], bool] | None = None


@dataclass(frozen=True)
class LedgerResidue:
    """
    One write the undo could not take back

    Attributes:
        collection (str): The collection it is in
        kind (WriteKind): The write that is still in effect
        public_id (int | None): The document concerned; None for an INSERT_BATCH
        criteria (dict[str, Any] | None): What the INSERT_BATCH's surviving documents match
        description (str | None): What the COMPENSATED write did
    """
    collection: str
    kind: WriteKind
    public_id: int | None = None
    criteria: dict[str, Any] | None = None
    description: str | None = None


    def to_json(self) -> dict[str, Any]:
        """
        The residue as a refusal names it

        Returns:
            dict[str, Any]: collection, kind and the public_id, the description or the criteria
        """
        if self.public_id is not None:
            located: dict[str, Any] = {LedgerResidueKey.PUBLIC_ID.value: self.public_id}
        elif self.description is not None:
            located = {LedgerResidueKey.DESCRIPTION.value: self.description}
        else:
            located = {LedgerResidueKey.CRITERIA.value: self.criteria}

        return {LedgerResidueKey.COLLECTION.value: self.collection, LedgerResidueKey.KIND.value: self.kind.value,
                **located}


class WriteLedger:
    """
    Records the writes of one request and undoes them, in reverse order, when the request fails

    Record each write right after it succeeded - or, for a batch whose failure may leave some of it stored,
    right before it runs (``inserted_where``) - so the ledger never claims a write that did not happen and never
    misses one that did
    """

    def __init__(self) -> None:
        """Starts an empty ledger"""
        self._entries: list[LedgerEntry] = []


    @property
    def entries(self) -> tuple[LedgerEntry, ...]:
        """
        The recorded writes, in the order they happened

        Returns:
            tuple[LedgerEntry, ...]: The entries
        """
        return tuple(self._entries)


    def inserted(self, manager: Any, public_id: int) -> None:
        """
        Records one inserted document

        Args:
            manager (Any): The manager of its collection
            public_id (int): Its public_id
        """
        self._entries.append(LedgerEntry(WriteKind.INSERT, manager, public_id=public_id))


    def inserted_where(self, manager: Any, criteria: dict[str, Any]) -> None:
        """
        Records a batch of inserts by what its documents match - before the batch runs

        For a batch whose failure does not say which documents were stored (an unordered bulk insert stores the
        ones that succeed): the undo deletes everything the criteria match, so they must match only documents
        this request created - e.g. the children of a parent inserted by the same request

        Args:
            manager (Any): The manager of the batch's collection
            criteria (dict[str, Any]): What exactly the batch's documents match
        """
        self._entries.append(LedgerEntry(WriteKind.INSERT_BATCH, manager, criteria=dict(criteria)))


    def updated(self, manager: Any, public_id: int, prior: dict[str, Any]) -> None:
        """
        Records one updated document with the snapshot taken before the update

        Args:
            manager (Any): The manager of its collection
            public_id (int): Its public_id
            prior (dict[str, Any]): The document as stored before the update
        """
        self._entries.append(LedgerEntry(WriteKind.UPDATE, manager, public_id=public_id, prior=dict(prior)))


    def deleted(self, manager: Any, public_id: int, prior: dict[str, Any]) -> None:
        """
        Records one deleted document with its snapshot, so the undo can put it back under its old id

        Args:
            manager (Any): The manager of its collection
            public_id (int): Its public_id
            prior (dict[str, Any]): The document as stored before the delete
        """
        self._entries.append(LedgerEntry(WriteKind.DELETE, manager, public_id=public_id, prior=dict(prior)))


    def compensated(
            self,
            collection: str,
            description: str,
            undo: Callable[[], None],
            verify: Callable[[], bool]) -> None:
        """
        Records a write that brings its own inverse - before the write runs

        For a write a snapshot cannot undo well: re-pointing one field of many documents is undone by
        re-pointing it back, where restoring each document in full would also overwrite whatever else changed
        on it meanwhile. Record it before it runs, and make the inverse harmless when the write did not happen

        Args:
            collection (str): The collection the write changes, as the residue names it
            description (str): What the write does, as the residue names it
            undo (Callable[[], None]): The inverse; it may raise, which the undo reports as residue
            verify (Callable[[], bool]): Whether the stored state is back to what it was before the write
        """
        self._entries.append(LedgerEntry(
            WriteKind.COMPENSATED, None, collection=collection, description=description, undo=undo, verify=verify,
        ))


    def deleted_many(self, manager: Any, priors: list[dict[str, Any]], description: str) -> None:
        """
        Records a batch delete with the snapshots of its documents - before the batch runs

        Undone as one step whatever the batch's size: the snapshots still stored are found in one read, the rest
        re-inserted in one write, and the result checked with one count. Documents are identified by their
        MongoDB ``_id``, so a snapshot without a public_id is restored as well. Nothing is recorded for an empty
        batch

        Args:
            manager (Any): The manager of the batch's collection
            priors (list[dict[str, Any]]): The documents as stored before the delete, ``_id`` included
            description (str): What the delete removes, as the residue names it
        """
        snapshots: list[dict[str, Any]] = [dict(prior) for prior in priors]

        if not snapshots:
            return

        self.compensated(
            manager.collection,
            description,
            undo=lambda: _restore_missing(manager, snapshots),
            verify=lambda: _count_stored(manager, snapshots) == len(snapshots),
        )


    def undo(self) -> list[LedgerResidue]:
        """
        Takes every recorded write back, newest first, and reports what could not be taken back

        Returns:
            list[LedgerResidue]: The writes still in effect afterwards - empty when the undo was complete
        """
        residue: list[LedgerResidue] = []

        for group in self._undo_groups():
            first: LedgerEntry = group[0]

            if first.kind is WriteKind.INSERT:
                residue.extend(_undo_inserts(first.manager, [entry.public_id for entry in group]))
            elif first.kind is WriteKind.INSERT_BATCH:
                residue.extend(_undo_insert_batch(first.manager, first.criteria))
            elif first.kind is WriteKind.UPDATE:
                residue.extend(_undo_update(first.manager, first.public_id, first.prior))
            elif first.kind is WriteKind.COMPENSATED:
                residue.extend(_undo_compensated(first))
            else:
                residue.extend(_undo_delete(first.manager, first.public_id, first.prior))

        return residue


    def _undo_groups(self) -> list[list[LedgerEntry]]:
        """
        The entries newest first, consecutive inserts into the same collection joined into one group

        Returns:
            list[list[LedgerEntry]]: The groups in undo order; every group but an insert run holds one entry
        """
        groups: list[list[LedgerEntry]] = []

        for entry in reversed(self._entries):
            previous: LedgerEntry | None = groups[-1][-1] if groups else None

            if (previous is not None and entry.kind is WriteKind.INSERT and previous.kind is WriteKind.INSERT
                    and entry.manager is previous.manager):
                groups[-1].append(entry)
            else:
                groups.append([entry])

        return groups

# -------------------------------------------------------------------------------------------------------------------- #
#                                                   the undo steps                                                     #
# -------------------------------------------------------------------------------------------------------------------- #

def _undo_inserts(manager: Any, public_ids: list[int]) -> list[LedgerResidue]:
    """
    Deletes inserted documents in one statement, then reads back which are still stored

    Args:
        manager (Any): The manager of their collection
        public_ids (list[int]): The inserted documents

    Returns:
        list[LedgerResidue]: One per document still stored - all of them when the read-back itself failed
    """
    criteria: dict[str, Any] = {PUBLIC_ID_FIELD: {'$in': sorted(public_ids)}}

    try:
        manager.delete_many(criteria)
    except Exception as err:
        LOGGER.error("[_undo_inserts] Removing %s from %s failed: %s", public_ids, manager.collection, err,
                     exc_info=True)

    try:
        surviving: list[int] = sorted(
            document[PUBLIC_ID_FIELD] for document in manager.find(criteria=criteria) if PUBLIC_ID_FIELD in document
        )
    except Exception as err:
        # Nothing can be promised about a cleanup that could not be checked: report every id, so somebody looks
        LOGGER.error("[_undo_inserts] Verifying the removal from %s failed: %s", manager.collection, err,
                     exc_info=True)
        surviving = sorted(public_ids)

    return [LedgerResidue(manager.collection, WriteKind.INSERT, public_id=public_id) for public_id in surviving]


def _undo_insert_batch(manager: Any, criteria: dict[str, Any]) -> list[LedgerResidue]:
    """
    Deletes everything a recorded batch matches, then counts what still does

    Args:
        manager (Any): The manager of the batch's collection
        criteria (dict[str, Any]): What the batch's documents match

    Returns:
        list[LedgerResidue]: One entry naming the criteria when anything still matches, or the count failed
    """
    try:
        manager.delete_many(criteria)
    except Exception as err:
        LOGGER.error("[_undo_insert_batch] Removing %s from %s failed: %s", criteria, manager.collection, err,
                     exc_info=True)

    try:
        remaining: int = manager.count_documents(criteria)
    except Exception as err:
        LOGGER.error("[_undo_insert_batch] Verifying the removal from %s failed: %s", manager.collection, err,
                     exc_info=True)
        remaining = 1

    return [LedgerResidue(manager.collection, WriteKind.INSERT_BATCH, criteria=criteria)] if remaining else []


def _undo_update(manager: Any, public_id: int, prior: dict[str, Any]) -> list[LedgerResidue]:
    """
    Replaces an updated document with its prior snapshot, then checks the stored document is that snapshot

    Args:
        manager (Any): The manager of its collection
        public_id (int): The updated document
        prior (dict[str, Any]): The document as it was before the update

    Returns:
        list[LedgerResidue]: One entry when the document is not back to its snapshot
    """
    try:
        manager.replace(public_id, prior)
    except Exception as err:
        LOGGER.error("[_undo_update] Restoring %s ID %s failed: %s", manager.collection, public_id, err,
                     exc_info=True)

    if _stored_equals(manager, public_id, prior):
        return []

    return [LedgerResidue(manager.collection, WriteKind.UPDATE, public_id=public_id)]


def _undo_delete(manager: Any, public_id: int, prior: dict[str, Any]) -> list[LedgerResidue]:
    """
    Re-inserts a deleted document under its old id, then checks it is stored again

    A delete is recorded before it runs, so the document may still be stored - the delete never happened, or a
    first undo already put it back. It is then left alone rather than inserted a second time: the undo must not
    rely on a unique index to refuse the copy, and running it twice must change nothing more

    Args:
        manager (Any): The manager of its collection
        public_id (int): The deleted document
        prior (dict[str, Any]): The document as it was before the delete

    Returns:
        list[LedgerResidue]: One entry when the document is not stored again
    """
    try:
        if manager.get_one_by({PUBLIC_ID_FIELD: public_id}) is None:
            manager.insert(dict(prior), skip_public=True)
    except Exception as err:
        LOGGER.error("[_undo_delete] Re-inserting %s ID %s failed: %s", manager.collection, public_id, err,
                     exc_info=True)

    if _stored_equals(manager, public_id, prior):
        return []

    return [LedgerResidue(manager.collection, WriteKind.DELETE, public_id=public_id)]


def _undo_compensated(entry: LedgerEntry) -> list[LedgerResidue]:
    """
    Runs a recorded inverse, then its verification

    Args:
        entry (LedgerEntry): The COMPENSATED entry

    Returns:
        list[LedgerResidue]: One entry naming the write when its inverse did not take effect or could not be
            checked
    """
    try:
        entry.undo()
    except Exception as err:
        LOGGER.error("[_undo_compensated] Undoing '%s' in %s failed: %s", entry.description, entry.collection, err,
                     exc_info=True)

    try:
        restored: bool = bool(entry.verify())
    except Exception as err:
        LOGGER.error("[_undo_compensated] Verifying the undo of '%s' failed: %s", entry.description, err,
                     exc_info=True)
        restored = False

    if restored:
        return []

    return [LedgerResidue(entry.collection, WriteKind.COMPENSATED, description=entry.description)]


def _stored_ids_criteria(snapshots: list[dict[str, Any]]) -> dict[str, Any]:
    """
    The filter matching a batch of snapshots by their MongoDB ``_id``

    Args:
        snapshots (list[dict[str, Any]]): The documents

    Returns:
        dict[str, Any]: ``{'_id': {'$in': [...]}}``
    """
    return {MONGO_ID_FIELD: {'$in': [snapshot[MONGO_ID_FIELD] for snapshot in snapshots]}}


def _restore_missing(manager: Any, snapshots: list[dict[str, Any]]) -> None:
    """
    Re-inserts the snapshots that are no longer stored - one read, one write

    A snapshot still stored is left alone, so running the undo twice, or undoing a delete that never ran,
    inserts nothing

    Args:
        manager (Any): The manager of their collection
        snapshots (list[dict[str, Any]]): The documents as stored before the delete
    """
    stored: set[Any] = {
        document[MONGO_ID_FIELD]
        for document in manager.find(criteria=_stored_ids_criteria(snapshots), projection={MONGO_ID_FIELD: 1})
    }
    missing: list[dict[str, Any]] = [dict(snapshot) for snapshot in snapshots if snapshot[MONGO_ID_FIELD] not in stored]

    if missing:
        manager.insert_many(missing, skip_public=True)


def _count_stored(manager: Any, snapshots: list[dict[str, Any]]) -> int:
    """
    How many of a batch's snapshots are stored

    Args:
        manager (Any): The manager of their collection
        snapshots (list[dict[str, Any]]): The documents

    Returns:
        int: The number stored
    """
    return manager.count_documents(_stored_ids_criteria(snapshots))


def _stored_equals(manager: Any, public_id: int, expected: dict[str, Any]) -> bool:
    """
    Reads a document back and compares it with the snapshot, `_id` aside

    Args:
        manager (Any): The manager of its collection
        public_id (int): The document
        expected (dict[str, Any]): The snapshot it should equal

    Returns:
        bool: True when the stored document equals the snapshot; False when it differs, is missing, or the read
            failed
    """
    try:
        stored: dict[str, Any] | None = manager.get_one_by({PUBLIC_ID_FIELD: public_id})
    except Exception as err:
        LOGGER.error("[_stored_equals] Verifying %s ID %s failed: %s", manager.collection, public_id, err,
                     exc_info=True)
        return False

    if stored is None:
        return False

    return _without_id(stored) == _without_id(expected)


def _without_id(document: dict[str, Any]) -> dict[str, Any]:
    """
    A document without its MongoDB `_id`

    Args:
        document (dict[str, Any]): The document

    Returns:
        dict[str, Any]: A copy without `_id`
    """
    return {key: value for key, value in document.items() if key != MONGO_ID_FIELD}
