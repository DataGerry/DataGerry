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
Unit tests for RiskAssessmentManager.delete_with_follow_up - which of its two deletes runs first

Pure: the manager is a MagicMock whose two delete calls are recorded in one list, so the ORDER is asserted.
"""
from unittest.mock import MagicMock

import pytest

from cmdb.manager.isms_manager.risk_assessment_manager import RiskAssessmentManager
from cmdb.models.isms_model import IsmsControlMeasureAssignment
from cmdb.models.isms_model.isms_control_measure_assignment_constants import ControlMeasureAssignmentKey
from cmdb.errors.manager.risk_assessment_manager import RiskAssessmentManagerDeleteError
# -------------------------------------------------------------------------------------------------------------------- #

RA_ID: int = 41


def _manager(calls: list[str]) -> MagicMock:
    """A manager recording the order of its two deletes."""
    manager = MagicMock()
    manager.delete_item.side_effect = lambda _public_id: calls.append('assessment') or True
    manager.delete_many_from_other_collection.side_effect = lambda *_a: calls.append('assignments')

    return manager


def test_the_assessment_is_deleted_before_its_assignments() -> None:
    """
    A failure between the two then leaves orphaned assignments - which readers treat as unassigned - instead of a
    surviving assessment that silently lost them
    """
    calls: list[str] = []
    manager = _manager(calls)

    assert RiskAssessmentManager.delete_with_follow_up(manager, RA_ID) is True
    assert calls == ['assessment', 'assignments']
    manager.delete_many_from_other_collection.assert_called_once_with(
        IsmsControlMeasureAssignment.COLLECTION, {ControlMeasureAssignmentKey.RISK_ASSESSMENT_ID.value: RA_ID},
    )


def test_a_failed_assessment_delete_leaves_the_assignments_alone() -> None:
    """Nothing after the failing step runs."""
    calls: list[str] = []
    manager = _manager(calls)
    manager.delete_item.side_effect = RuntimeError('delete failed')

    with pytest.raises(RiskAssessmentManagerDeleteError):
        RiskAssessmentManager.delete_with_follow_up(manager, RA_ID)

    manager.delete_many_from_other_collection.assert_not_called()


def test_the_answer_is_whether_the_assessment_was_deleted() -> None:
    """Not the cascade's result: a missing assessment is False even when its orphans are cleaned up."""
    manager = _manager([])
    manager.delete_item.side_effect = lambda _public_id: False

    assert RiskAssessmentManager.delete_with_follow_up(manager, RA_ID) is False
