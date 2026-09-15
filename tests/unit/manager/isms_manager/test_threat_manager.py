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
cross-collection database collaborator (aggregate_from_other_collection) stubbed, so only the
manager's own behavior is exercised - the array-membership ``$in``/``$unwind``/``$group`` pipeline
shape, the empty-input short circuit, and the error-wrapping into the ThreatManager error hierarchy.
The aggregation itself is pinned against real MongoDB in
tests/integration/isms/test_integration_threat_vulnerability_delete.py.
"""
from unittest.mock import MagicMock

import pytest

from cmdb.manager.isms_manager.threat_manager import ThreatManager
from cmdb.models.isms_model import IsmsRisk

from cmdb.errors.manager import BaseManagerIterationError
from cmdb.errors.manager.threat_manager import ThreatManagerGetError
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
        mgr.aggregate_from_other_collection.return_value = [{'_id': THREAT_ID_A}, {'_id': THREAT_ID_C}]

        result = ThreatManager.get_used_threat_ids(mgr, [THREAT_ID_A, THREAT_ID_B, THREAT_ID_C])

        assert result == {THREAT_ID_A, THREAT_ID_C}

    def test_pipeline_matches_unwinds_and_groups_the_array_field(self) -> None:
        """The aggregation runs on the Risk collection, filtering + unwinding the threats array."""
        mgr = _mock_manager()
        mgr.aggregate_from_other_collection.return_value = []
        candidates = [THREAT_ID_A, THREAT_ID_B]

        ThreatManager.get_used_threat_ids(mgr, candidates)

        collection, pipeline = mgr.aggregate_from_other_collection.call_args.args
        assert collection == IsmsRisk.COLLECTION
        assert pipeline[0]['$match'] == {'threats': {'$in': candidates}}
        assert pipeline[1]['$unwind'] == '$threats'
        assert pipeline[2]['$match'] == {'threats': {'$in': candidates}}
        assert pipeline[3]['$group'] == {'_id': '$threats'}

    def test_empty_input_returns_empty_without_querying(self) -> None:
        """An empty candidate list short-circuits to an empty set and never queries."""
        mgr = _mock_manager()

        assert ThreatManager.get_used_threat_ids(mgr, []) == set()
        mgr.aggregate_from_other_collection.assert_not_called()

    def test_iteration_error_wraps_as_threat_get_error(self) -> None:
        """A ``BaseManagerIterationError`` from the aggregation becomes ``ThreatManagerGetError``."""
        mgr = _mock_manager()
        mgr.aggregate_from_other_collection.side_effect = BaseManagerIterationError('bad pipeline')

        with pytest.raises(ThreatManagerGetError):
            ThreatManager.get_used_threat_ids(mgr, [THREAT_ID_A])

    def test_unexpected_error_wraps_as_threat_get_error(self) -> None:
        """A generic exception is also wrapped as ``ThreatManagerGetError``."""
        mgr = _mock_manager()
        mgr.aggregate_from_other_collection.side_effect = RuntimeError('boom')

        with pytest.raises(ThreatManagerGetError):
            ThreatManager.get_used_threat_ids(mgr, [THREAT_ID_A])
