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
Unit tests for ControlMeasureAssignmentManager.get_missing_control_measure_ids

Pure tests: no Mongo. The manager is a ``MagicMock(spec=...)`` with its cross-collection read stubbed, so what is
pinned is the method's own behaviour: one projected ``$in`` read for every referenced measure, none for an
assignment list naming no measure, and the unknown ids as the difference
"""
from typing import Any
from unittest.mock import MagicMock

from cmdb.manager.isms_manager.control_measure_assignment_manager import (
    CONTROL_MEASURE_ID_PROJECTION,
    ControlMeasureAssignmentManager,
)
from cmdb.models.isms_model import IsmsControlMeasure
from cmdb.models.isms_model.isms_control_measure_assignment_constants import ControlMeasureAssignmentKey
from cmdb.models.isms_model.isms_control_measure_constants import ControlMeasureKey
# -------------------------------------------------------------------------------------------------------------------- #

MEASURE_KEY: str = ControlMeasureAssignmentKey.CONTROL_MEASURE_ID.value
EXISTING_ID: int = 201
MISSING_ID: int = 202


def _manager(existing: list[int]) -> MagicMock:
    """A manager stand-in whose cross-collection read returns the given measures"""
    manager = MagicMock(spec=ControlMeasureAssignmentManager)
    manager.get_many_from_other_collection.return_value = [
        {ControlMeasureKey.PUBLIC_ID.value: public_id} for public_id in existing
    ]

    return manager


def _missing(manager: MagicMock, assignments: list[dict[str, Any]]) -> set[int]:
    """Runs the real method against the stand-in"""
    return ControlMeasureAssignmentManager.get_missing_control_measure_ids(manager, assignments)


def test_reports_the_ids_no_measure_holds() -> None:
    """The difference between what is referenced and what was found"""
    manager = _manager([EXISTING_ID])

    assert _missing(manager, [{MEASURE_KEY: EXISTING_ID}, {MEASURE_KEY: MISSING_ID}]) == {MISSING_ID}


def test_reads_only_the_public_ids_of_the_measures() -> None:
    """Projected: existence needs the id, not the measure document"""
    manager = _manager([EXISTING_ID])

    _missing(manager, [{MEASURE_KEY: EXISTING_ID}, {MEASURE_KEY: EXISTING_ID}])

    manager.get_many_from_other_collection.assert_called_once_with(
        IsmsControlMeasure.COLLECTION,
        projection=CONTROL_MEASURE_ID_PROJECTION,
        criteria={'public_id': {'$in': [EXISTING_ID]}},
    )
    assert CONTROL_MEASURE_ID_PROJECTION == {ControlMeasureKey.PUBLIC_ID.value: 1, '_id': 0}


def test_reads_nothing_when_no_measure_is_referenced() -> None:
    """An assignment without a measure id, or none at all, costs no query"""
    manager = _manager([])

    assert _missing(manager, [{MEASURE_KEY: None}, {}]) == set()
    assert _missing(manager, []) == set()
    manager.get_many_from_other_collection.assert_not_called()
