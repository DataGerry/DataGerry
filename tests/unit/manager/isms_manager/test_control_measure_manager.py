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
Unit tests for cmdb.manager.isms_manager.control_measure_manager.ControlMeasureManager

Pure tests: no Mongo. The manager is driven against a ``MagicMock(spec=ControlMeasureManager)`` with
its cross-collection database collaborator (aggregate_from_other_collection) stubbed, so only the
manager's own behavior is exercised - the grouped ``$in`` pipeline shape, the empty-input short
circuit, and the error-wrapping into the ControlMeasureManager error hierarchy. The aggregation
itself is pinned against real MongoDB in
tests/integration/isms/test_integration_control_measure_manager.py.
"""
from unittest.mock import MagicMock

import pytest

from cmdb.manager.isms_manager.control_measure_manager import ControlMeasureManager
from cmdb.models.isms_model import IsmsControlMeasureAssignment

from cmdb.errors.manager import BaseManagerIterationError
from cmdb.errors.manager.control_measure_manager import ControlMeasureManagerGetError
# -------------------------------------------------------------------------------------------------------------------- #

CONTROL_ID_A: int = 101
CONTROL_ID_B: int = 102
CONTROL_ID_C: int = 103


def _mock_manager() -> MagicMock:
    """A MagicMock standing in for a ControlMeasureManager instance."""
    return MagicMock(spec=ControlMeasureManager)


class TestGetUsedControlMeasureIds:
    """``get_used_control_measure_ids`` reports which candidates an assignment references."""

    def test_returns_the_referenced_subset(self) -> None:
        """Only the control ids the grouped aggregation returns are reported as used."""
        mgr = _mock_manager()
        mgr.aggregate_from_other_collection.return_value = [{'_id': CONTROL_ID_A}, {'_id': CONTROL_ID_C}]

        result = ControlMeasureManager.get_used_control_measure_ids(mgr, [CONTROL_ID_A, CONTROL_ID_B, CONTROL_ID_C])

        assert result == {CONTROL_ID_A, CONTROL_ID_C}

    def test_pipeline_matches_candidates_and_groups_by_control_measure_id(self) -> None:
        """The aggregation runs on the assignment collection, matching the candidates and grouping them."""
        mgr = _mock_manager()
        mgr.aggregate_from_other_collection.return_value = []

        ControlMeasureManager.get_used_control_measure_ids(mgr, [CONTROL_ID_A, CONTROL_ID_B])

        collection, pipeline = mgr.aggregate_from_other_collection.call_args.args
        assert collection == IsmsControlMeasureAssignment.COLLECTION
        assert pipeline[0]['$match'] == {'control_measure_id': {'$in': [CONTROL_ID_A, CONTROL_ID_B]}}
        assert pipeline[1]['$group'] == {'_id': '$control_measure_id'}

    def test_empty_input_returns_empty_without_querying(self) -> None:
        """An empty candidate list short-circuits to an empty set and never queries."""
        mgr = _mock_manager()

        assert ControlMeasureManager.get_used_control_measure_ids(mgr, []) == set()
        mgr.aggregate_from_other_collection.assert_not_called()

    def test_iteration_error_wraps_as_control_measure_get_error(self) -> None:
        """A ``BaseManagerIterationError`` from the aggregation becomes ``ControlMeasureManagerGetError``."""
        mgr = _mock_manager()
        mgr.aggregate_from_other_collection.side_effect = BaseManagerIterationError('bad pipeline')

        with pytest.raises(ControlMeasureManagerGetError):
            ControlMeasureManager.get_used_control_measure_ids(mgr, [CONTROL_ID_A])

    def test_unexpected_error_wraps_as_control_measure_get_error(self) -> None:
        """A generic exception is also wrapped as ``ControlMeasureManagerGetError``."""
        mgr = _mock_manager()
        mgr.aggregate_from_other_collection.side_effect = RuntimeError('boom')

        with pytest.raises(ControlMeasureManagerGetError):
            ControlMeasureManager.get_used_control_measure_ids(mgr, [CONTROL_ID_A])
