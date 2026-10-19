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
Unit tests for cmdb.manager.isms_manager.risk_manager.RiskManager

Pure tests: no Mongo. The manager is driven against a ``MagicMock(spec=RiskManager)`` with its
database collaborators (find_existing_public_ids / get_many_from_other_collection /
delete_many_from_other_collection / delete_many) stubbed, so only the batched-cascade bookkeeping is
exercised - the existing-id resolution, the RA -> CMA cascade order (RiskAssessments first, deleted by
the ids read), the returned (ids, ra_count, cma_count) tuple, the empty short circuits, and the
error-wrapping: the database layer's typed errors become RiskManagerDeleteError, a bug propagates as
itself. The real cascade is exercised against MongoDB by the
integration tier.
"""
# pylint: disable=protected-access
from unittest.mock import MagicMock

import pytest

from cmdb.manager.isms_manager.risk_manager import RiskManager
from cmdb.models.isms_model import IsmsRiskAssessment, IsmsControlMeasureAssignment

from cmdb.errors.manager import BaseManagerDeleteError, BaseManagerGetError
from cmdb.errors.manager.risk_manager import RiskManagerDeleteError, RiskManagerGetError
# -------------------------------------------------------------------------------------------------------------------- #

RISK_ID_A: int = 401
RISK_ID_B: int = 402
RA_ID_A: int = 501
RA_ID_B: int = 502


def _mock_manager() -> MagicMock:
    """A MagicMock standing in for a RiskManager instance."""
    return MagicMock(spec=RiskManager)


def _delete_result(count: int) -> MagicMock:
    """A stand-in for a pymongo DeleteResult carrying a deleted_count."""
    return MagicMock(deleted_count=count)


class TestDeleteManyWithFollowUp:
    """``delete_many_with_follow_up`` resolves existing ids, runs the shared cascade, deletes the Risks."""

    def test_resolves_existing_runs_cascade_and_returns_ids_and_counts(self) -> None:
        """Existing risks are resolved, the cascade (mocked) runs, and (ids, ra, cma) counts returned."""
        mgr = _mock_manager()
        mgr.find_existing_public_ids.return_value = {RISK_ID_B, RISK_ID_A}
        mgr._cascade_delete_risk_assessments.return_value = (2, 3)

        deleted_ids, deleted_ras, deleted_cmas = RiskManager.delete_many_with_follow_up(
            mgr, [RISK_ID_A, RISK_ID_B]
        )

        assert deleted_ids == [RISK_ID_A, RISK_ID_B]
        assert (deleted_ras, deleted_cmas) == (2, 3)
        # the cascade runs over exactly the existing ids, then the risks themselves are removed
        mgr._cascade_delete_risk_assessments.assert_called_once_with([RISK_ID_A, RISK_ID_B])
        mgr.delete_many.assert_called_once_with({'public_id': {'$in': [RISK_ID_A, RISK_ID_B]}})

    def test_empty_input_returns_zeros_without_querying(self) -> None:
        """An empty id list short-circuits to ([], 0, 0) and touches nothing."""
        mgr = _mock_manager()

        assert RiskManager.delete_many_with_follow_up(mgr, []) == ([], 0, 0)
        mgr.find_existing_public_ids.assert_not_called()
        mgr.delete_many.assert_not_called()

    def test_no_existing_risks_returns_zeros_without_deleting(self) -> None:
        """When none of the requested ids exist, nothing is cascaded/deleted and zeros are returned."""
        mgr = _mock_manager()
        mgr.find_existing_public_ids.return_value = set()

        assert RiskManager.delete_many_with_follow_up(mgr, [RISK_ID_A]) == ([], 0, 0)
        mgr._cascade_delete_risk_assessments.assert_not_called()
        mgr.delete_many.assert_not_called()

    def test_a_failed_existence_read_is_the_get_error(self) -> None:
        """The existence read raises its own RiskManagerGetError; nothing is deleted."""
        mgr = _mock_manager()
        mgr.find_existing_public_ids.side_effect = RiskManagerGetError('db down')

        with pytest.raises(RiskManagerGetError):
            RiskManager.delete_many_with_follow_up(mgr, [RISK_ID_A])

        mgr.delete_many.assert_not_called()

    @pytest.mark.parametrize('error', [BaseManagerGetError('down'), BaseManagerDeleteError('down')],
                             ids=['cascade read', 'cascade delete'])
    def test_a_failed_cascade_is_the_delete_error(self, error: Exception) -> None:
        """A typed failure of the cascade becomes RiskManagerDeleteError; the Risks are not deleted."""
        mgr = _mock_manager()
        mgr.find_existing_public_ids.return_value = {RISK_ID_A}
        mgr._cascade_delete_risk_assessments.side_effect = error

        with pytest.raises(RiskManagerDeleteError):
            RiskManager.delete_many_with_follow_up(mgr, [RISK_ID_A])

        mgr.delete_many.assert_not_called()

    def test_a_failed_risk_delete_is_the_delete_error(self) -> None:
        """The delete_many of the Risks themselves, after the cascade."""
        mgr = _mock_manager()
        mgr.find_existing_public_ids.return_value = {RISK_ID_A}
        mgr._cascade_delete_risk_assessments.return_value = (0, 0)
        mgr.delete_many.side_effect = BaseManagerDeleteError('down')

        with pytest.raises(RiskManagerDeleteError):
            RiskManager.delete_many_with_follow_up(mgr, [RISK_ID_A])

    def test_a_bug_propagates_as_itself(self) -> None:
        """A programming error in the cascade is not a database failure: it is not wrapped."""
        mgr = _mock_manager()
        mgr.find_existing_public_ids.return_value = {RISK_ID_A}
        mgr._cascade_delete_risk_assessments.side_effect = RuntimeError('bug')

        with pytest.raises(RuntimeError):
            RiskManager.delete_many_with_follow_up(mgr, [RISK_ID_A])


class TestCascadeDeleteRiskAssessments:
    """``_cascade_delete_risk_assessments`` removes the RAs of the risks and their CMAs, in order."""

    def test_deletes_ras_then_cmas_by_the_ids_read_and_returns_counts(self) -> None:
        """
        RAs are deleted first, by the ids read; then their CMAs; (ra, cma) counts returned

        RiskAssessments first: a failure between the two deletes leaves assignments of a missing
        RiskAssessment (read as "none"), never a RiskAssessment that silently lost its assignments. By
        the ids read, not by risk_id: a RiskAssessment created meanwhile is not deleted without its CMAs
        """
        mgr = _mock_manager()
        mgr.get_many_from_other_collection.return_value = [{'public_id': RA_ID_A}, {'public_id': RA_ID_B}]
        # first cross-collection delete removes RAs, second removes CMAs
        mgr.delete_many_from_other_collection.side_effect = [_delete_result(2), _delete_result(3)]

        deleted_ras, deleted_cmas = RiskManager._cascade_delete_risk_assessments(
            mgr, [RISK_ID_A, RISK_ID_B]
        )

        assert (deleted_ras, deleted_cmas) == (2, 3)
        ra_call, cma_call = mgr.delete_many_from_other_collection.call_args_list
        assert ra_call.args[0] == IsmsRiskAssessment.COLLECTION
        assert ra_call.args[1] == {'public_id': {'$in': [RA_ID_A, RA_ID_B]}}
        assert cma_call.args[0] == IsmsControlMeasureAssignment.COLLECTION
        assert cma_call.args[1] == {'risk_assessment_id': {'$in': [RA_ID_A, RA_ID_B]}}

    def test_only_the_ids_are_read(self) -> None:
        """The RiskAssessments are read projected to their public_id, by risk_id."""
        mgr = _mock_manager()
        mgr.get_many_from_other_collection.return_value = []

        RiskManager._cascade_delete_risk_assessments(mgr, [RISK_ID_A])

        call = mgr.get_many_from_other_collection.call_args
        assert call.kwargs['projection'] == {'public_id': 1, '_id': 0}
        assert call.kwargs['criteria'] == {'risk_id': {'$in': [RISK_ID_A]}}

    def test_no_assessments_skips_cross_collection_deletes(self) -> None:
        """When no RiskAssessment references the risks, no delete runs and counts are 0."""
        mgr = _mock_manager()
        mgr.get_many_from_other_collection.return_value = []

        result = RiskManager._cascade_delete_risk_assessments(mgr, [RISK_ID_A])

        assert result == (0, 0)
        mgr.delete_many_from_other_collection.assert_not_called()


class TestDeleteWithFollowUpFailure:
    """A failure anywhere in the cascade is reported as this manager's delete error."""

    def test_a_failed_cascade_becomes_a_delete_error(self) -> None:
        """
        The Risk must not be reported as deleted when its RiskAssessments were not

        The cascade runs first on purpose, so a failure there has to stop the whole delete rather
        than leaving assessments pointing at a Risk that is about to disappear.
        """
        mgr = _mock_manager()
        mgr._cascade_delete_risk_assessments.side_effect = BaseManagerDeleteError('cascade failed')

        with pytest.raises(RiskManagerDeleteError):
            RiskManager.delete_with_follow_up(mgr, RISK_ID_A)

        mgr.delete_item.assert_not_called()

    def test_a_failed_risk_delete_passes_through_unwrapped(self) -> None:
        """delete_item already raises RiskManagerDeleteError: it is not wrapped in itself again."""
        mgr = _mock_manager()
        failure = RiskManagerDeleteError('delete failed')
        mgr.delete_item.side_effect = failure

        with pytest.raises(RiskManagerDeleteError) as excinfo:
            RiskManager.delete_with_follow_up(mgr, RISK_ID_A)

        assert excinfo.value is failure

    def test_a_bug_in_the_cascade_propagates_as_itself(self) -> None:
        """A programming error is not a failed delete: the route answers it 500."""
        mgr = _mock_manager()
        mgr._cascade_delete_risk_assessments.side_effect = RuntimeError('bug')

        with pytest.raises(RuntimeError):
            RiskManager.delete_with_follow_up(mgr, RISK_ID_A)

        mgr.delete_item.assert_not_called()
