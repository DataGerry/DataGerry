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
database collaborators (get_many / get_many_from_other_collection / delete_many_from_other_collection
/ delete_many) stubbed, so only the batched-cascade bookkeeping is exercised - the existing-id
resolution, the RA -> CMA cascade order, the returned (ids, ra_count, cma_count) tuple, the empty
short circuits, and the error-wrapping. The real cascade is pinned against MongoDB in
tests/integration/isms/test_integration_risk_manager.py.
"""
# pylint: disable=protected-access
from unittest.mock import MagicMock

import pytest

from cmdb.manager.isms_manager.risk_manager import RiskManager
from cmdb.models.isms_model import IsmsRiskAssessment, IsmsControlMeasureAssignment

from cmdb.errors.manager.risk_manager import RiskManagerDeleteError
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
        mgr.get_many.return_value = [{'public_id': RISK_ID_A}, {'public_id': RISK_ID_B}]
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
        mgr.get_many.assert_not_called()
        mgr.delete_many.assert_not_called()

    def test_no_existing_risks_returns_zeros_without_deleting(self) -> None:
        """When none of the requested ids exist, nothing is cascaded/deleted and zeros are returned."""
        mgr = _mock_manager()
        mgr.get_many.return_value = []

        assert RiskManager.delete_many_with_follow_up(mgr, [RISK_ID_A]) == ([], 0, 0)
        mgr._cascade_delete_risk_assessments.assert_not_called()
        mgr.delete_many.assert_not_called()

    def test_error_wraps_as_risk_delete_error(self) -> None:
        """A failure anywhere in the cascade is wrapped as RiskManagerDeleteError."""
        mgr = _mock_manager()
        mgr.get_many.side_effect = RuntimeError('db down')

        with pytest.raises(RiskManagerDeleteError):
            RiskManager.delete_many_with_follow_up(mgr, [RISK_ID_A])


class TestCascadeDeleteRiskAssessments:
    """``_cascade_delete_risk_assessments`` removes the RAs of the risks and their CMAs, in order."""

    def test_deletes_cmas_then_ras_and_returns_counts(self) -> None:
        """CMAs are deleted by risk_assessment_id, then RAs by risk_id; (ra, cma) counts returned."""
        mgr = _mock_manager()
        mgr.get_many_from_other_collection.return_value = [{'public_id': RA_ID_A}, {'public_id': RA_ID_B}]
        # first cross-collection delete removes CMAs, second removes RAs
        mgr.delete_many_from_other_collection.side_effect = [_delete_result(3), _delete_result(2)]

        deleted_ras, deleted_cmas = RiskManager._cascade_delete_risk_assessments(
            mgr, [RISK_ID_A, RISK_ID_B]
        )

        assert (deleted_ras, deleted_cmas) == (2, 3)
        cma_call, ra_call = mgr.delete_many_from_other_collection.call_args_list
        assert cma_call.args[0] == IsmsControlMeasureAssignment.COLLECTION
        assert cma_call.args[1] == {'risk_assessment_id': {'$in': [RA_ID_A, RA_ID_B]}}
        assert ra_call.args[0] == IsmsRiskAssessment.COLLECTION
        assert ra_call.args[1] == {'risk_id': {'$in': [RISK_ID_A, RISK_ID_B]}}

    def test_no_assessments_skips_cross_collection_deletes(self) -> None:
        """When no RiskAssessment references the risks, no delete runs and counts are 0."""
        mgr = _mock_manager()
        mgr.get_many_from_other_collection.return_value = []

        result = RiskManager._cascade_delete_risk_assessments(mgr, [RISK_ID_A])

        assert result == (0, 0)
        mgr.delete_many_from_other_collection.assert_not_called()
