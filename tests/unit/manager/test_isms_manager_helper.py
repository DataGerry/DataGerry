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
Unit tests for the ISMS manager helpers

Pure tests against MagicMock managers: the max-impact recompute, the projected calculation-basis read, the
grouped reference lookup, the delete-if-unused rule (check, delete, check again - and put back what gained a
reference meanwhile) in its single and batched form,
and the field-level snapshot a follow-up write is undone from.

Every error test pins both halves of the narrowing: the database layer's typed error becomes the manager's
own, and a programming error propagates as itself.
"""
from typing import Any
from unittest.mock import MagicMock

import pytest

from cmdb.framework.write_ledger import WriteLedger
from cmdb.manager.isms_manager.isms_manager_helper import (
    delete_isms_item_if_unused_by_risk,
    delete_unless_referenced,
    delete_unreferenced_batch,
    dotted_value,
    get_referenced_ids,
    load_calculation_basis,
    record_follow_up_write,
    recompute_max_impact,
    restore_operations,
    snapshot_projection,
    snapshots_restored,
)
from cmdb.models.isms_model import IsmsImpact, IsmsRisk
from cmdb.models.isms_model.isms_impact_constants import ImpactKey
from cmdb.models.isms_model.isms_risk_constants import RiskKey

from cmdb.errors.manager import (
    BaseManagerDeleteError,
    BaseManagerGetError,
    BaseManagerInsertError,
    BaseManagerIterationError,
)
from cmdb.errors.manager.threat_manager import (
    THREAT_MANAGER_ERRORS,
    ThreatManagerDeleteError,
    ThreatManagerGetError,
    ThreatManagerRiskUsageError,
)
# -------------------------------------------------------------------------------------------------------------------- #

BASIS_BY_ID: dict[int, float] = {1: 1.0, 2: 2.5, 3: 2.0}

ITEM_ID: int = 7
OTHER_ID: int = 8
THIRD_ID: int = 9
IN_USE_MESSAGE: str = 'in use'
COLLECTION: str = 'isms.other'
DB_NAME: str = 'isms-db'
PATH_A: str = 'matrix.value'
PATH_B: str = 'matrix.other'
DESCRIPTION: str = 'what the write did'


def _manager() -> MagicMock:
    """A manager carrying the Threat error map, its collection and its database"""
    manager = MagicMock(name='manager')
    manager.exceptions = THREAT_MANAGER_ERRORS
    manager.collection = 'isms.threat'
    manager.db_name = DB_NAME

    return manager


class TestRecomputeMaxImpact:
    """recompute_max_impact selects the highest-basis impact from a matrix."""

    def test_empty_matrix_returns_none_none(self) -> None:
        """An empty impacts list yields (None, None)."""
        assert recompute_max_impact([], BASIS_BY_ID) == (None, None)

    def test_single_entry_returns_its_id_and_basis(self) -> None:
        """A single known impact returns its id and calculation_basis."""
        assert recompute_max_impact([{'impact_id': 1}], BASIS_BY_ID) == (1, 1.0)

    def test_returns_entry_with_highest_basis(self) -> None:
        """Across several impacts the one with the highest basis wins (id 2 at 2.5)."""
        impacts = [{'impact_id': 1}, {'impact_id': 2}, {'impact_id': 3}]

        assert recompute_max_impact(impacts, BASIS_BY_ID) == (2, 2.5)

    def test_entries_without_impact_id_are_skipped(self) -> None:
        """Entries whose impact_id is None are ignored."""
        impacts = [{'impact_id': None}, {'impact_id': 3}]

        assert recompute_max_impact(impacts, BASIS_BY_ID) == (3, 2.0)

    def test_unknown_impact_ids_are_skipped(self) -> None:
        """An impact_id absent from the basis lookup is ignored."""
        impacts = [{'impact_id': 99}, {'impact_id': 1}]

        assert recompute_max_impact(impacts, BASIS_BY_ID) == (1, 1.0)

    def test_only_unknown_ids_returns_none_none(self) -> None:
        """When no entry has a known basis the result is (None, None)."""
        assert recompute_max_impact([{'impact_id': 99}], BASIS_BY_ID) == (None, None)

    def test_entries_with_none_basis_are_skipped(self) -> None:
        """An impact whose recorded basis is None does not become the maximum."""
        assert recompute_max_impact([{'impact_id': 1}, {'impact_id': 2}], {1: None, 2: 1.5}) == (2, 1.5)


class TestLoadCalculationBasis:
    """One projected read of the scale through the manager."""

    def test_reads_only_the_id_and_the_basis(self) -> None:
        """The projection names the two keys and drops _id; the answer maps id -> basis."""
        manager = _manager()
        manager.get_many_from_other_collection.return_value = [
            {'public_id': 1, 'calculation_basis': 1.5}, {'public_id': 2},
        ]

        assert load_calculation_basis(manager, IsmsImpact.COLLECTION, ImpactKey) == {1: 1.5, 2: None}
        manager.get_many_from_other_collection.assert_called_once_with(
            IsmsImpact.COLLECTION, projection={'public_id': 1, 'calculation_basis': 1, '_id': 0},
        )

    def test_a_failed_read_is_the_base_manager_get_error(self) -> None:
        """The read's typed error passes through for the caller to wrap."""
        manager = _manager()
        manager.get_many_from_other_collection.side_effect = BaseManagerGetError('down')

        with pytest.raises(BaseManagerGetError):
            load_calculation_basis(manager, IsmsImpact.COLLECTION, ImpactKey)


class TestGetReferencedIds:
    """The grouped reference lookup shared by the three ``get_used_*_ids``."""

    def test_the_pipeline_matches_unwinds_matches_and_groups(self) -> None:
        """$unwind serves a list field and a scalar one alike, so one pipeline fits all three."""
        manager = _manager()
        manager.aggregate_all.return_value = [{'_id': ITEM_ID}]

        assert get_referenced_ids(manager, IsmsRisk.COLLECTION, 'threats', [ITEM_ID, OTHER_ID]) == {ITEM_ID}

        pipeline, collection = manager.aggregate_all.call_args.args
        assert collection == IsmsRisk.COLLECTION
        assert pipeline == [
            {'$match': {'threats': {'$in': [ITEM_ID, OTHER_ID]}}},
            {'$unwind': '$threats'},
            {'$match': {'threats': {'$in': [ITEM_ID, OTHER_ID]}}},
            {'$group': {'_id': '$threats'}},
        ]

    def test_an_empty_selection_queries_nothing(self) -> None:
        """No candidates, no aggregation."""
        manager = _manager()

        assert get_referenced_ids(manager, IsmsRisk.COLLECTION, 'threats', []) == set()
        manager.aggregate_all.assert_not_called()

    def test_a_failed_aggregation_passes_through(self) -> None:
        """BaseManagerIterationError is the caller's to wrap."""
        manager = _manager()
        manager.aggregate_all.side_effect = BaseManagerIterationError('down')

        with pytest.raises(BaseManagerIterationError):
            get_referenced_ids(manager, IsmsRisk.COLLECTION, 'threats', [ITEM_ID])


class TestDeleteUnlessReferenced:
    """Check, delete, check again."""

    @staticmethod
    def _call(manager: MagicMock, references: list[bool]) -> bool:
        """Runs the rule with a usage check answering ``references`` in turn"""
        answers = iter(references)

        return delete_unless_referenced(
            manager, ITEM_ID, lambda: next(answers), ThreatManagerRiskUsageError, IN_USE_MESSAGE,
        )

    def test_an_unreferenced_item_is_deleted_atomically(self) -> None:
        """One find_one_and_delete by public_id; True."""
        manager = _manager()
        manager.find_one_and_delete.return_value = {'public_id': ITEM_ID}

        assert self._call(manager, [False, False]) is True
        manager.find_one_and_delete.assert_called_once_with({'public_id': ITEM_ID})
        manager.insert.assert_not_called()

    def test_a_referenced_item_is_refused_before_the_delete(self) -> None:
        """The usage error, unwrapped and carrying the message; nothing deleted."""
        manager = _manager()

        with pytest.raises(ThreatManagerRiskUsageError) as excinfo:
            self._call(manager, [True])

        assert str(excinfo.value) == IN_USE_MESSAGE
        manager.find_one_and_delete.assert_not_called()

    def test_a_missing_item_is_false_and_not_checked_again(self) -> None:
        """Nothing was deleted, so there is nothing to put back."""
        manager = _manager()
        manager.find_one_and_delete.return_value = None

        assert self._call(manager, [False]) is False

    def test_an_item_referenced_meanwhile_is_put_back_and_refused(self) -> None:
        """The second check finds a reference: the removed document is re-inserted under its id."""
        manager = _manager()
        removed: dict[str, Any] = {'public_id': ITEM_ID, 'name': 'kept'}
        manager.find_one_and_delete.return_value = removed

        with pytest.raises(ThreatManagerRiskUsageError):
            self._call(manager, [False, True])

        manager.insert.assert_called_once_with(removed, skip_public=True)

    @pytest.mark.parametrize('step, error', [
        ('check', BaseManagerGetError('down')),
        ('delete', BaseManagerDeleteError('down')),
        ('restore', BaseManagerInsertError('down')),
    ], ids=lambda value: value if isinstance(value, str) else type(value).__name__)
    def test_a_typed_failure_of_any_step_is_the_delete_error(self, step: str, error: Exception) -> None:
        """The check, the delete and the restore all answer the manager's configured delete error."""
        manager = _manager()
        manager.find_one_and_delete.return_value = {'public_id': ITEM_ID}
        checks: list[bool] = [False, True]

        def check() -> bool:
            if step == 'check':
                raise error

            return checks.pop(0)

        if step == 'delete':
            manager.find_one_and_delete.side_effect = error
        if step == 'restore':
            manager.insert.side_effect = error

        with pytest.raises(ThreatManagerDeleteError) as excinfo:
            delete_unless_referenced(manager, ITEM_ID, check, ThreatManagerRiskUsageError, IN_USE_MESSAGE)

        assert excinfo.value.args[0] is error

    def test_a_bug_propagates_as_itself(self) -> None:
        """A programming error in the check is no failed delete."""
        manager = _manager()

        def check() -> bool:
            raise RuntimeError('bug')

        with pytest.raises(RuntimeError):
            delete_unless_referenced(manager, ITEM_ID, check, ThreatManagerRiskUsageError, IN_USE_MESSAGE)


class TestDeleteIsmsItemIfUnusedByRisk:
    """The leaf ISMS entities ask the IsmsRisk collection through their reference list."""

    def test_the_check_reads_the_risk_list(self) -> None:
        """get_one_by on IsmsRisk with the list field and the id."""
        manager = _manager()
        manager.get_one_by.return_value = None
        manager.find_one_and_delete.return_value = {'public_id': ITEM_ID}

        assert delete_isms_item_if_unused_by_risk(
            manager, ITEM_ID, RiskKey.THREATS, ThreatManagerRiskUsageError, IN_USE_MESSAGE,
        ) is True
        manager.get_one_by.assert_called_with({RiskKey.THREATS.value: ITEM_ID}, IsmsRisk.COLLECTION)


class TestDeleteUnreferencedBatch:
    """The batched rule: one reference query, one read, one delete, one reference query again."""

    @staticmethod
    def _holding(stored_ids: set[int]) -> MagicMock:
        """A manager holding ``stored_ids``"""
        manager = _manager()
        manager.find.side_effect = lambda criteria: [
            {'public_id': public_id} for public_id in criteria['public_id']['$in'] if public_id in stored_ids
        ]

        return manager

    def test_a_batch_that_is_all_referenced_reads_and_deletes_nothing(self) -> None:
        """Every requested id is in use: no read, no delete, every id reported referenced (sorted, once)"""
        manager = self._holding({ITEM_ID, ITEM_ID + 1})

        deleted, referenced = delete_unreferenced_batch(
            manager, [ITEM_ID + 1, ITEM_ID, ITEM_ID + 1], set,
        )

        assert (deleted, referenced) == ([], [ITEM_ID, ITEM_ID + 1])
        manager.find.assert_not_called()
        manager.delete_many.assert_not_called()

    def test_deletes_the_stored_unreferenced_ids_in_one_delete(self) -> None:
        """Duplicates collapse, missing ids drop out, the referenced id is reported."""
        manager = self._holding({ITEM_ID, OTHER_ID})

        deleted, in_use = delete_unreferenced_batch(
            manager, [OTHER_ID, ITEM_ID, ITEM_ID, THIRD_ID], lambda ids: {OTHER_ID} & set(ids),
        )

        manager.delete_many.assert_called_once_with({'public_id': {'$in': [ITEM_ID]}})
        assert (deleted, in_use) == ([ITEM_ID], [OTHER_ID])

    def test_items_referenced_meanwhile_are_put_back(self) -> None:
        """The second reference query sees OTHER_ID referenced: it is re-inserted and reported in use."""
        manager = self._holding({ITEM_ID, OTHER_ID})
        answers = iter([set(), {OTHER_ID}])

        deleted, in_use = delete_unreferenced_batch(manager, [ITEM_ID, OTHER_ID], lambda ids: next(answers))

        manager.insert_many.assert_called_once_with([{'public_id': OTHER_ID}], skip_public=True)
        assert (deleted, in_use) == ([ITEM_ID], [OTHER_ID])

    def test_nothing_stored_deletes_nothing(self) -> None:
        """The read finds none of the candidates: no delete, no second reference query."""
        manager = self._holding(set())
        check = MagicMock(return_value=set())

        assert delete_unreferenced_batch(manager, [ITEM_ID], check) == ([], [])
        manager.delete_many.assert_not_called()
        check.assert_called_once()

    def test_a_failed_read_is_the_get_error(self) -> None:
        """The read's BaseManagerGetError becomes the manager's GetError; nothing deleted."""
        manager = _manager()
        manager.find.side_effect = BaseManagerGetError('down')

        with pytest.raises(ThreatManagerGetError):
            delete_unreferenced_batch(manager, [ITEM_ID], lambda ids: set())

        manager.delete_many.assert_not_called()

    def test_a_failed_delete_is_the_delete_error(self) -> None:
        """The delete's BaseManagerDeleteError becomes the manager's DeleteError."""
        manager = self._holding({ITEM_ID})
        manager.delete_many.side_effect = BaseManagerDeleteError('down')

        with pytest.raises(ThreatManagerDeleteError):
            delete_unreferenced_batch(manager, [ITEM_ID], lambda ids: set())

    def test_a_failed_restore_is_the_delete_error(self) -> None:
        """Putting back an item that gained a reference failed: the manager's DeleteError."""
        manager = self._holding({ITEM_ID})
        manager.insert_many.side_effect = BaseManagerInsertError('down')
        answers = iter([set(), {ITEM_ID}])

        with pytest.raises(ThreatManagerDeleteError):
            delete_unreferenced_batch(manager, [ITEM_ID], lambda ids: next(answers))

    def test_a_bug_propagates_as_itself(self) -> None:
        """A programming error in the read is no failed read."""
        manager = _manager()
        manager.find.side_effect = RuntimeError('bug')

        with pytest.raises(RuntimeError):
            delete_unreferenced_batch(manager, [ITEM_ID], lambda ids: set())


class TestFollowUpSnapshot:
    """The field-level inverse of a follow-up write."""

    def test_dotted_value_tells_absent_from_none(self) -> None:
        """A stored None is found; a missing key is not."""
        assert dotted_value({'matrix': {'value': None}}, PATH_A) == (True, None)
        assert dotted_value({'matrix': {}}, PATH_A) == (False, None)
        assert dotted_value({'matrix': 3}, PATH_A) == (False, None)

    def test_the_restore_sets_what_was_there_and_unsets_what_was_not(self) -> None:
        """One update per snapshot: $set for a present path, $unset for an absent one."""
        operations = restore_operations([{'public_id': ITEM_ID, 'matrix': {'value': 4}}], [PATH_A, PATH_B])

        assert len(operations) == 1
        assert operations[0]._filter == {'public_id': ITEM_ID}  # pylint: disable=protected-access
        assert operations[0]._doc == {  # pylint: disable=protected-access
            '$set': {PATH_A: 4}, '$unset': {PATH_B: ''},
        }

    def test_a_restore_of_present_paths_only_sets(self) -> None:
        """Every path was there: the update is a $set alone, with no empty $unset"""
        operations = restore_operations([{'public_id': ITEM_ID, 'matrix': {'value': 4, 'other': 1}}],
                                        [PATH_A, PATH_B])

        assert operations[0]._doc == {'$set': {PATH_A: 4, PATH_B: 1}}  # pylint: disable=protected-access

    def test_a_restore_of_absent_paths_only_unsets(self) -> None:
        """No path was there: the update is an $unset alone, with no empty $set"""
        operations = restore_operations([{'public_id': ITEM_ID}], [PATH_A])

        assert operations[0]._doc == {'$unset': {PATH_A: ''}}  # pylint: disable=protected-access

    def test_the_projection_reads_the_id_and_the_paths(self) -> None:
        """Nothing else of the document, and no _id."""
        assert snapshot_projection([PATH_A]) == {'public_id': 1, '_id': 0, PATH_A: 1}

    @pytest.mark.parametrize('stored, expected', [
        ([{'public_id': ITEM_ID, 'matrix': {'value': 4}}], True),
        ([{'public_id': ITEM_ID, 'matrix': {'value': 5}}], False),
        ([], False),
    ], ids=['restored', 'still changed', 'gone'])
    def test_restored_compares_the_paths_read_back(self, stored: list[dict[str, Any]], expected: bool) -> None:
        """Every snapshot must read back as it was."""
        manager = _manager()
        manager.get_many_from_other_collection.return_value = stored

        snapshots = [{'public_id': ITEM_ID, 'matrix': {'value': 4}}]

        assert snapshots_restored(manager, COLLECTION, snapshots, [PATH_A]) is expected

    def test_the_ledger_undoes_the_paths_and_verifies_them(self) -> None:
        """Recorded before the write; the undo bulk-writes the snapshot back and the residue is empty."""
        manager = _manager()
        snapshots = [{'public_id': ITEM_ID, 'matrix': {'value': 4}}]
        manager.get_many_from_other_collection.return_value = snapshots
        ledger = WriteLedger()

        record_follow_up_write(ledger, manager, COLLECTION, DESCRIPTION, snapshots, [PATH_A])

        assert not ledger.undo()
        (operations,), kwargs = manager.bulk_write.call_args
        assert (kwargs, len(operations)) == ({'collection': COLLECTION}, 1)

    def test_an_undo_that_does_not_take_is_residue(self) -> None:
        """The read-back still differs: the residue names the collection and the description."""
        manager = _manager()
        snapshots = [{'public_id': ITEM_ID, 'matrix': {'value': 4}}]
        manager.get_many_from_other_collection.return_value = [{'public_id': ITEM_ID, 'matrix': {'value': 5}}]
        ledger = WriteLedger()

        record_follow_up_write(ledger, manager, COLLECTION, DESCRIPTION, snapshots, [PATH_A])

        residue = ledger.undo()
        assert [(entry.collection, entry.description) for entry in residue] == [(COLLECTION, DESCRIPTION)]

    def test_nothing_is_recorded_for_no_snapshot(self) -> None:
        """An empty follow-up has nothing to undo."""
        ledger = WriteLedger()

        record_follow_up_write(ledger, _manager(), COLLECTION, DESCRIPTION, [], [PATH_A])

        assert not ledger.entries
