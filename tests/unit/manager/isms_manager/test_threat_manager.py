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
Unit tests for cmdb.manager.isms_manager.threat_manager.ThreatManager

Pure tests: no Mongo. The manager is driven against a ``MagicMock(spec=ThreatManager)`` with its
cross-collection database collaborator (aggregate_all) stubbed, so only the
manager's own behavior is exercised - the array-membership ``$in``/``$unwind``/``$group`` pipeline
shape, the empty-input short circuit, the error-wrapping into the ThreatManager error hierarchy (a
bug propagates as itself), and the risk-usage refusal of the delete.
The aggregation itself is exercised against real MongoDB by the integration tier.
"""
from unittest.mock import MagicMock

import pytest

from cmdb.manager.isms_manager.threat_manager import ThreatManager
from cmdb.models.isms_model import IsmsRisk, IsmsThreat

from cmdb.errors.manager import BaseManagerDeleteError, BaseManagerIterationError
from cmdb.errors.manager.threat_manager import (
    THREAT_MANAGER_ERRORS,
    ThreatManagerDeleteError,
    ThreatManagerGetError,
    ThreatManagerRiskUsageError,
)
# -------------------------------------------------------------------------------------------------------------------- #

THREAT_ID_A: int = 301
THREAT_ID_B: int = 302
THREAT_ID_C: int = 303


def _mock_manager() -> MagicMock:
    """A MagicMock standing in for a ThreatManager instance."""
    return MagicMock(spec=ThreatManager)


class TestGetUsedThreatIds:
    """``get_used_threat_ids`` reports which candidates a Risk's threats array holds."""

    def test_returns_the_referenced_subset(self) -> None:
        """Only the threat ids the grouped aggregation returns are reported as used."""
        mgr = _mock_manager()
        mgr.aggregate_all.return_value = [{'_id': THREAT_ID_A}, {'_id': THREAT_ID_C}]

        result = ThreatManager.get_used_threat_ids(mgr, [THREAT_ID_A, THREAT_ID_B, THREAT_ID_C])

        assert result == {THREAT_ID_A, THREAT_ID_C}

    def test_pipeline_matches_unwinds_and_groups_the_array_field(self) -> None:
        """The aggregation runs on the Risk collection, filtering + unwinding the threats array."""
        mgr = _mock_manager()
        mgr.aggregate_all.return_value = []
        candidates = [THREAT_ID_A, THREAT_ID_B]

        ThreatManager.get_used_threat_ids(mgr, candidates)

        pipeline, collection = mgr.aggregate_all.call_args.args
        assert collection == IsmsRisk.COLLECTION
        assert pipeline[0]['$match'] == {'threats': {'$in': candidates}}
        assert pipeline[1]['$unwind'] == '$threats'
        assert pipeline[2]['$match'] == {'threats': {'$in': candidates}}
        assert pipeline[3]['$group'] == {'_id': '$threats'}

    def test_empty_input_returns_empty_without_querying(self) -> None:
        """An empty candidate list short-circuits to an empty set and never queries."""
        mgr = _mock_manager()

        assert ThreatManager.get_used_threat_ids(mgr, []) == set()
        mgr.aggregate_all.assert_not_called()

    def test_iteration_error_wraps_as_threat_get_error(self) -> None:
        """A ``BaseManagerIterationError`` from the aggregation becomes ``ThreatManagerGetError``."""
        mgr = _mock_manager()
        mgr.aggregate_all.side_effect = BaseManagerIterationError('bad pipeline')

        with pytest.raises(ThreatManagerGetError):
            ThreatManager.get_used_threat_ids(mgr, [THREAT_ID_A])

    def test_a_bug_propagates_as_itself(self) -> None:
        """A programming error is not a failed lookup: it is not wrapped, so the route answers 500."""
        mgr = _mock_manager()
        mgr.aggregate_all.side_effect = RuntimeError('boom')

        with pytest.raises(RuntimeError):
            ThreatManager.get_used_threat_ids(mgr, [THREAT_ID_A])


class TestDeleteWithFollowUp:
    """``delete_with_follow_up`` refuses a Threat a Risk references, through the Risk's ``threats`` list."""

    @staticmethod
    def _manager(referencing_risk: dict | None) -> MagicMock:
        """A manager whose Threat is stored, and referenced by ``referencing_risk`` (or by nothing)"""
        mgr = _mock_manager()
        mgr.exceptions = THREAT_MANAGER_ERRORS
        mgr.collection = IsmsThreat.COLLECTION
        mgr.get_one_by.return_value = referencing_risk
        mgr.find_one_and_delete.return_value = {'public_id': THREAT_ID_A}

        return mgr

    def test_the_usage_check_reads_the_risk_list(self) -> None:
        """The check asks the IsmsRisk collection for a Risk holding the id in its list."""
        mgr = self._manager(None)

        assert ThreatManager.delete_with_follow_up(mgr, THREAT_ID_A) is True
        mgr.get_one_by.assert_called_with({'threats': THREAT_ID_A}, IsmsRisk.COLLECTION)

    def test_a_referenced_threat_is_refused(self) -> None:
        """The usage error is raised unwrapped, and nothing is deleted."""
        mgr = self._manager({'public_id': 1})

        with pytest.raises(ThreatManagerRiskUsageError):
            ThreatManager.delete_with_follow_up(mgr, THREAT_ID_A)

        mgr.find_one_and_delete.assert_not_called()

    def test_a_failed_delete_is_the_delete_error(self) -> None:
        """The delete's BaseManagerDeleteError becomes the manager's DeleteError."""
        mgr = self._manager(None)
        mgr.find_one_and_delete.side_effect = BaseManagerDeleteError('down')

        with pytest.raises(ThreatManagerDeleteError):
            ThreatManager.delete_with_follow_up(mgr, THREAT_ID_A)
