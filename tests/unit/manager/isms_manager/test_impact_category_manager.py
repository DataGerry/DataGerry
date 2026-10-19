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
Unit tests for the ledgered writes of cmdb.manager.isms_manager.impact_category_manager.ImpactCategoryManager

Pure tests: the manager's own methods run against a ``MagicMock(spec=ImpactCategoryManager)``. Pinned, for the four
writes that reach past the category's own document:

  - each records its inverse in the request's ledger BEFORE the write it undoes runs (a category already gone is
    not recorded, so the undo never brings back one another request removed)
  - the inverse is the exact one: the pushed entries pulled, the rewritten assessment paths restored, the pushed
    description pulled, the removed descriptions put back
  - a typed failure becomes the manager's own error with the original as ``args[0]``; a programming error
    propagates as itself
"""
# pylint: disable=protected-access
from typing import Any
from unittest.mock import MagicMock

import pytest

from cmdb.framework.write_ledger import WriteLedger
from cmdb.framework.write_ledger_constants import WriteKind
from cmdb.manager.isms_manager.impact_category_manager import (
    CATEGORY_REWRITE_PATHS,
    IMPACT_DESCRIPTION_ID_PATH,
    IMPACTS_PATHS,
    ImpactCategoryManager,
)
from cmdb.models.isms_model import IsmsRiskAssessment

from cmdb.errors.manager import BaseManagerGetError, BaseManagerUpdateError
from cmdb.errors.manager.impact_category_manager import (
    ImpactCategoryManagerDeleteError,
    ImpactCategoryManagerInsertError,
    ImpactCategoryManagerUpdateError,
)
# -------------------------------------------------------------------------------------------------------------------- #

CATEGORY_ID: int = 7
IMPACT_ID: int = 3
RA_ID: int = 51
NEW_CATEGORY_DATA: dict[str, str] = {'name': 'Finance'}
CATEGORY_COLLECTION: str = 'isms.impactCategory'
STORED_CATEGORY: dict[str, Any] = {'public_id': CATEGORY_ID, 'name': 'Finance', 'impact_descriptions': []}
HOLDING_ASSESSMENT: dict[str, Any] = {
    'public_id': RA_ID,
    'risk_calculation_before': {'impacts': [{'impact_category_id': CATEGORY_ID, 'impact_id': IMPACT_ID}],
                                'maximum_impact_id': IMPACT_ID, 'maximum_impact_value': 2.0},
    'risk_calculation_after': {'impacts': [], 'maximum_impact_id': None, 'maximum_impact_value': None},
}
HOLDING_CATEGORY: dict[str, Any] = {
    'public_id': CATEGORY_ID, 'impact_descriptions': [{'impact_id': IMPACT_ID, 'value': 'kept text'}],
}


def _manager() -> MagicMock:
    """An ImpactCategoryManager whose insert answers CATEGORY_ID, whose reads find the stored category"""
    mgr = MagicMock(spec=ImpactCategoryManager)
    mgr.collection = CATEGORY_COLLECTION
    mgr.insert_item.return_value = CATEGORY_ID
    mgr.delete_item.return_value = True
    mgr.get_one.return_value = dict(STORED_CATEGORY)
    mgr.risk_assessments_holding_category.return_value = [HOLDING_ASSESSMENT]
    mgr.find.return_value = [HOLDING_CATEGORY]
    mgr.get_many_from_other_collection.return_value = []

    return mgr


def _kinds(ledger: WriteLedger) -> list[WriteKind]:
    """The kinds of the recorded entries, in recording order"""
    return [entry.kind for entry in ledger.entries]


class TestCreateWithFollowUp:
    """The category is inserted, then pushed into every RiskAssessment - both recorded."""

    def test_the_insert_and_the_push_are_recorded_and_the_id_answered(self) -> None:
        """The insert once it ran, the push before it runs"""
        mgr = _manager()
        ledger = WriteLedger()
        recorded_before_push: list[list[WriteKind]] = []
        mgr.add_impact_category_to_risk_assessments.side_effect = lambda _id: recorded_before_push.append(
            _kinds(ledger))

        assert ImpactCategoryManager.create_with_follow_up(mgr, NEW_CATEGORY_DATA, ledger) == CATEGORY_ID
        assert recorded_before_push == [[WriteKind.INSERT, WriteKind.COMPENSATED]]
        assert ledger.entries[1].collection == IsmsRiskAssessment.COLLECTION

    def test_the_undo_pulls_the_category_and_checks_no_assessment_holds_it(self) -> None:
        """The recorded inverse and its verification address this category"""
        mgr = _manager()
        mgr.risk_assessments_holding_category.return_value = []
        ledger = WriteLedger()
        ImpactCategoryManager.create_with_follow_up(mgr, NEW_CATEGORY_DATA, ledger)

        push_entry = ledger.entries[1]
        push_entry.undo()

        mgr.pull_category_from_risk_assessments.assert_called_once_with(CATEGORY_ID)
        assert push_entry.verify() is True
        mgr.risk_assessments_holding_category.assert_called_with(CATEGORY_ID)

    def test_a_failed_push_is_the_insert_error_with_both_writes_recorded(self) -> None:
        """The RiskAssessment update's typed failure, kept as the wrapper's argument; the undo has what it needs"""
        mgr = _manager()
        error = BaseManagerUpdateError('down')
        mgr.add_impact_category_to_risk_assessments.side_effect = error
        ledger = WriteLedger()

        with pytest.raises(ImpactCategoryManagerInsertError) as excinfo:
            ImpactCategoryManager.create_with_follow_up(mgr, NEW_CATEGORY_DATA, ledger)

        assert excinfo.value.args[0] is error
        assert _kinds(ledger) == [WriteKind.INSERT, WriteKind.COMPENSATED]

    def test_a_failed_insert_records_nothing(self) -> None:
        """Nothing was written, so nothing is to undo"""
        mgr = _manager()
        mgr.insert_item.side_effect = ImpactCategoryManagerInsertError('down')
        ledger = WriteLedger()

        with pytest.raises(ImpactCategoryManagerInsertError):
            ImpactCategoryManager.create_with_follow_up(mgr, NEW_CATEGORY_DATA, ledger)

        assert not ledger.entries
        mgr.add_impact_category_to_risk_assessments.assert_not_called()

    def test_a_bug_in_the_push_propagates_as_itself(self) -> None:
        """A programming error is not a failed insert"""
        mgr = _manager()
        mgr.add_impact_category_to_risk_assessments.side_effect = KeyError('bug')

        with pytest.raises(KeyError):
            ImpactCategoryManager.create_with_follow_up(mgr, NEW_CATEGORY_DATA, WriteLedger())


class TestDeleteWithFollowUp:
    """The assessments holding the category are rewritten, then the category is deleted - both recorded."""

    def test_the_rewrite_and_the_delete_are_each_recorded_before_they_run(self) -> None:
        """A field-level follow-up over the read assessments, then the category with its stored document"""
        mgr = _manager()
        ledger = WriteLedger()
        recorded_before_rewrite: list[list[WriteKind]] = []
        recorded_before_delete: list[list[WriteKind]] = []
        mgr._remove_category_from_risk_assessments.side_effect = lambda *_args: recorded_before_rewrite.append(
            _kinds(ledger))
        mgr.delete_item.side_effect = lambda _id: recorded_before_delete.append(_kinds(ledger)) or True

        assert ImpactCategoryManager.delete_with_follow_up(mgr, CATEGORY_ID, ledger) is True
        assert recorded_before_rewrite == [[WriteKind.COMPENSATED]]
        assert recorded_before_delete == [[WriteKind.COMPENSATED, WriteKind.DELETE]]
        assert ledger.entries[1].prior == STORED_CATEGORY
        mgr._remove_category_from_risk_assessments.assert_called_once_with(CATEGORY_ID, [HOLDING_ASSESSMENT])

    def test_the_rewrite_undo_restores_every_path_it_changes(self) -> None:
        """The impacts and both maximum fields of both matrices go back from the snapshot"""
        mgr = _manager()
        ledger = WriteLedger()
        ImpactCategoryManager.delete_with_follow_up(mgr, CATEGORY_ID, ledger)

        ledger.entries[0].undo()

        (operations,), kwargs = mgr.bulk_write.call_args
        assert kwargs == {'collection': IsmsRiskAssessment.COLLECTION}
        assert set(operations[0]._doc['$set']) == set(CATEGORY_REWRITE_PATHS)

    def test_a_category_already_gone_records_no_delete(self) -> None:
        """Another request removed the category first: the undo must not bring it back"""
        mgr = _manager()
        mgr.get_one.return_value = None
        mgr.delete_item.return_value = False
        ledger = WriteLedger()

        assert ImpactCategoryManager.delete_with_follow_up(mgr, CATEGORY_ID, ledger) is False
        assert _kinds(ledger) == [WriteKind.COMPENSATED]

    def test_no_assessment_holding_it_records_no_follow_up(self) -> None:
        """An empty rewrite has nothing to undo"""
        mgr = _manager()
        mgr.risk_assessments_holding_category.return_value = []
        ledger = WriteLedger()

        ImpactCategoryManager.delete_with_follow_up(mgr, CATEGORY_ID, ledger)

        assert _kinds(ledger) == [WriteKind.DELETE]

    @pytest.mark.parametrize('error', [BaseManagerGetError('down'), BaseManagerUpdateError('down')],
                             ids=['read', 'write'])
    def test_a_failed_follow_up_is_the_delete_error_and_deletes_nothing(self, error: Exception) -> None:
        """A failed read or write of the RiskAssessments stops before the category is deleted"""
        mgr = _manager()
        mgr._remove_category_from_risk_assessments.side_effect = error

        with pytest.raises(ImpactCategoryManagerDeleteError) as excinfo:
            ImpactCategoryManager.delete_with_follow_up(mgr, CATEGORY_ID, WriteLedger())

        assert excinfo.value.args[0] is error
        mgr.delete_item.assert_not_called()

    def test_a_failed_read_of_the_holders_is_the_delete_error(self) -> None:
        """The snapshot read fails before anything is recorded or written"""
        mgr = _manager()
        mgr.risk_assessments_holding_category.side_effect = BaseManagerGetError('down')
        ledger = WriteLedger()

        with pytest.raises(ImpactCategoryManagerDeleteError):
            ImpactCategoryManager.delete_with_follow_up(mgr, CATEGORY_ID, ledger)

        assert not ledger.entries
        mgr._remove_category_from_risk_assessments.assert_not_called()

    def test_a_bug_in_the_follow_up_propagates_as_itself(self) -> None:
        """A programming error is not a failed delete"""
        mgr = _manager()
        mgr._remove_category_from_risk_assessments.side_effect = TypeError('bug')

        with pytest.raises(TypeError):
            ImpactCategoryManager.delete_with_follow_up(mgr, CATEGORY_ID, WriteLedger())

        mgr.delete_item.assert_not_called()


class TestTheCategoryReadsAndThePull:
    """The read the delete snapshots with, and the inverse of the create's push."""

    def test_the_holders_are_read_projected_to_the_rewritten_paths(self) -> None:
        """Both matrices' impact lists name the category; only the id and the rewritten paths are read"""
        mgr = _manager()

        ImpactCategoryManager.risk_assessments_holding_category(mgr, CATEGORY_ID)

        args, kwargs = mgr.get_many_from_other_collection.call_args
        assert args == (IsmsRiskAssessment.COLLECTION,)
        assert set(kwargs['projection']) == {'public_id', '_id', *CATEGORY_REWRITE_PATHS}
        assert kwargs['criteria'] == {'$or': [{f'{path}.impact_category_id': CATEGORY_ID} for path in IMPACTS_PATHS]}

    def test_the_pull_removes_the_category_entries_from_both_matrices(self) -> None:
        """One raw update on the RiskAssessments, scoped to the assessments that hold it"""
        mgr = _manager()

        ImpactCategoryManager.pull_category_from_risk_assessments(mgr, CATEGORY_ID)

        (criteria, update), kwargs = mgr.update_many_raw.call_args
        assert kwargs == {'collection': IsmsRiskAssessment.COLLECTION}
        assert criteria == {'$or': [{f'{path}.impact_category_id': CATEGORY_ID} for path in IMPACTS_PATHS]}
        assert update == {'$pull': {path: {'impact_category_id': CATEGORY_ID} for path in IMPACTS_PATHS}}


class TestImpactDescriptionFanOut:
    """Creating an Impact adds its description to every category, deleting it removes it - both recorded."""

    def test_the_add_is_recorded_before_it_runs(self) -> None:
        """A compensated step on the categories' collection, then the $addToSet"""
        mgr = _manager()
        ledger = WriteLedger()
        recorded_before_add: list[list[WriteKind]] = []
        mgr.update_many.side_effect = lambda *_args, **_kwargs: recorded_before_add.append(_kinds(ledger))

        ImpactCategoryManager.add_new_impact_to_categories(mgr, IMPACT_ID, ledger)

        assert recorded_before_add == [[WriteKind.COMPENSATED]]
        assert ledger.entries[0].collection == CATEGORY_COLLECTION
        (criteria, update), kwargs = mgr.update_many.call_args
        assert (criteria, kwargs) == ({}, {'add_to_set': True})
        assert update['impact_descriptions']['impact_id'] == IMPACT_ID

    def test_the_add_undo_pulls_the_description_and_checks_none_is_left(self) -> None:
        """The inverse pulls every entry of the impact; the check reads by the description's impact_id"""
        mgr = _manager()
        mgr.find.return_value = []
        ledger = WriteLedger()
        ImpactCategoryManager.add_new_impact_to_categories(mgr, IMPACT_ID, ledger)

        ledger.entries[0].undo()

        mgr._pull_impact_descriptions.assert_called_once_with(IMPACT_ID)
        assert ledger.entries[0].verify() is True
        mgr.find.assert_called_with(criteria={IMPACT_DESCRIPTION_ID_PATH: IMPACT_ID})

    def test_a_failed_add_is_the_managers_update_error(self) -> None:
        """Mapped by the Impact routes to their 400; the original kept as the argument"""
        mgr = _manager()
        error = BaseManagerUpdateError('down')
        mgr.update_many.side_effect = error

        with pytest.raises(ImpactCategoryManagerUpdateError) as excinfo:
            ImpactCategoryManager.add_new_impact_to_categories(mgr, IMPACT_ID, WriteLedger())

        assert excinfo.value.args[0] is error

    def test_the_remove_snapshots_the_holding_categories_then_pulls(self) -> None:
        """The description lists are read and recorded field by field before the pull"""
        mgr = _manager()
        ledger = WriteLedger()
        recorded_before_pull: list[list[WriteKind]] = []
        mgr._pull_impact_descriptions.side_effect = lambda _id: recorded_before_pull.append(_kinds(ledger))

        ImpactCategoryManager.remove_deleted_impact_from_categories(mgr, IMPACT_ID, ledger)

        assert recorded_before_pull == [[WriteKind.COMPENSATED]]
        criteria = mgr.find.call_args.kwargs['criteria']
        assert criteria == {IMPACT_DESCRIPTION_ID_PATH: IMPACT_ID}
        mgr._pull_impact_descriptions.assert_called_once_with(IMPACT_ID)

    def test_the_remove_undo_puts_each_description_list_back(self) -> None:
        """The snapshot of the list is written back with $set on the categories' own collection"""
        mgr = _manager()
        ledger = WriteLedger()
        ImpactCategoryManager.remove_deleted_impact_from_categories(mgr, IMPACT_ID, ledger)

        ledger.entries[0].undo()

        (operations,), kwargs = mgr.bulk_write.call_args
        assert kwargs == {'collection': CATEGORY_COLLECTION}
        assert operations[0]._doc == {'$set': {'impact_descriptions': HOLDING_CATEGORY['impact_descriptions']}}

    def test_no_category_holding_it_records_nothing_but_still_pulls(self) -> None:
        """An empty snapshot has nothing to undo; the pull is harmless"""
        mgr = _manager()
        mgr.find.return_value = []
        ledger = WriteLedger()

        ImpactCategoryManager.remove_deleted_impact_from_categories(mgr, IMPACT_ID, ledger)

        assert not ledger.entries
        mgr._pull_impact_descriptions.assert_called_once_with(IMPACT_ID)

    @pytest.mark.parametrize('failing, error', [
        ('find', BaseManagerGetError('down')),
        ('_pull_impact_descriptions', BaseManagerUpdateError('down')),
    ], ids=['read', 'pull'])
    def test_a_failed_remove_is_the_managers_update_error(self, failing: str, error: Exception) -> None:
        """Either half's typed failure, kept as the argument"""
        mgr = _manager()
        getattr(mgr, failing).side_effect = error

        with pytest.raises(ImpactCategoryManagerUpdateError) as excinfo:
            ImpactCategoryManager.remove_deleted_impact_from_categories(mgr, IMPACT_ID, WriteLedger())

        assert excinfo.value.args[0] is error

    @pytest.mark.parametrize('method, failing', [
        ('add_new_impact_to_categories', 'update_many'),
        ('remove_deleted_impact_from_categories', '_pull_impact_descriptions'),
    ], ids=['add', 'remove'])
    def test_a_bug_in_the_fan_out_propagates_as_itself(self, method: str, failing: str) -> None:
        """A programming error is not a failed update"""
        mgr = _manager()
        getattr(mgr, failing).side_effect = TypeError('bug')

        with pytest.raises(TypeError):
            getattr(ImpactCategoryManager, method)(mgr, IMPACT_ID, WriteLedger())

    def test_the_pull_names_the_impact_in_both_filter_and_update(self) -> None:
        """Only the categories describing the impact, only that impact's entries"""
        mgr = _manager()

        ImpactCategoryManager._pull_impact_descriptions(mgr, IMPACT_ID)

        mgr.update_many_pull.assert_called_once_with(
            {IMPACT_DESCRIPTION_ID_PATH: IMPACT_ID}, {'impact_descriptions': {'impact_id': IMPACT_ID}},
        )
