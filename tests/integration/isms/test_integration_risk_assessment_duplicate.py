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
Integration tests for the RiskAssessment duplicate helpers, against the real collections

  - the source check reads the real RiskAssessment collection: a stored id passes, a missing one is the 404
  - the source's assignments are read from the real assignment collection, only the source's, without ``_id``
  - their copies store through the real assignment manager under new ids, on the duplicate, and the source keeps
    its own
"""
from http import HTTPStatus
from typing import Any, Iterator

import pytest
from flask import Flask
from werkzeug.exceptions import HTTPException

from cmdb.database import MongoDatabaseManager
from cmdb.manager import RiskAssessmentManager
from cmdb.manager.isms_manager.control_measure_assignment_manager import ControlMeasureAssignmentManager
from cmdb.models.isms_model import IsmsControlMeasureAssignment, IsmsRiskAssessment
from cmdb.models.isms_model.isms_control_measure_assignment_constants import ControlMeasureAssignmentKey
from cmdb.models.isms_model.priority_enum import Priority
from cmdb.models.person_group_model.person_reference_type_enum import PersonReferenceType
from cmdb.interface.rest_api.routes.isms_routes.risk_assessment_duplicate_helper import (
    abort_if_duplicate_source_missing,
    copied_assignments,
    read_source_assignments,
)
# -------------------------------------------------------------------------------------------------------------------- #

SOURCE_ID: int = 97951
OTHER_RA_ID: int = 97952
DUPLICATE_ID: int = 97953
MISSING_RA_ID: int = 97959
SOURCE_ASSIGNMENT_ID: int = 97961
OTHER_ASSIGNMENT_ID: int = 97962
MEASURE_ID: int = 97971
OTHER_MEASURE_ID: int = 97972
PERSON_ID: int = 97981
IMPLEMENTATION_STATUS: int = 2

PUBLIC_ID_KEY: str = ControlMeasureAssignmentKey.PUBLIC_ID.value
RISK_ASSESSMENT_KEY: str = ControlMeasureAssignmentKey.RISK_ASSESSMENT_ID.value
CONTROL_MEASURE_KEY: str = ControlMeasureAssignmentKey.CONTROL_MEASURE_ID.value
ALL_RA_IDS: list[int] = [SOURCE_ID, OTHER_RA_ID, DUPLICATE_ID]


def _assignment(public_id: int, risk_assessment_id: int, measure_id: int) -> dict[str, Any]:
    """A complete stored assignment"""
    return {
        PUBLIC_ID_KEY: public_id,
        RISK_ASSESSMENT_KEY: risk_assessment_id,
        CONTROL_MEASURE_KEY: measure_id,
        'planned_implementation_date': None,
        'implementation_status': IMPLEMENTATION_STATUS,
        'finished_implementation_date': None,
        'priority': Priority.HIGH.value,
        'responsible_for_implementation_id_ref_type': PersonReferenceType.PERSON.value,
        'responsible_for_implementation_id': PERSON_ID,
    }


@pytest.fixture(name='flask_context', autouse=True)
def fixture_flask_context() -> Iterator[None]:
    """abort() needs an application context"""
    with Flask(__name__).app_context():
        yield


@pytest.fixture(name='stored', autouse=True)
def fixture_stored(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[Any]:
    """The source and another assessment, one assignment each; removed afterwards with every copy"""
    assessments = database_manager.get_collection(IsmsRiskAssessment.COLLECTION, database_name)
    assignments = database_manager.get_collection(IsmsControlMeasureAssignment.COLLECTION, database_name)

    def _purge() -> None:
        assessments.delete_many({PUBLIC_ID_KEY: {'$in': ALL_RA_IDS}})
        assignments.delete_many({RISK_ASSESSMENT_KEY: {'$in': ALL_RA_IDS}})

    _purge()
    assessments.insert_many([{PUBLIC_ID_KEY: SOURCE_ID}, {PUBLIC_ID_KEY: OTHER_RA_ID}])
    assignments.insert_many([_assignment(SOURCE_ASSIGNMENT_ID, SOURCE_ID, MEASURE_ID),
                             _assignment(OTHER_ASSIGNMENT_ID, OTHER_RA_ID, OTHER_MEASURE_ID)])

    yield assignments

    _purge()


@pytest.fixture(name='manager')
def fixture_manager(database_manager: MongoDatabaseManager) -> RiskAssessmentManager:
    """The real RiskAssessment manager"""
    return RiskAssessmentManager(database_manager)


class TestTheSourceIsStored:
    """abort_if_duplicate_source_missing against the real collection"""

    def test_a_stored_source_passes(self, manager: RiskAssessmentManager) -> None:
        """No abort"""
        abort_if_duplicate_source_missing(manager, SOURCE_ID)

    def test_a_missing_source_is_a_404(self, manager: RiskAssessmentManager) -> None:
        """No document carries the id"""
        with pytest.raises(HTTPException) as caught:
            abort_if_duplicate_source_missing(manager, MISSING_RA_ID)

        assert caught.value.code == HTTPStatus.NOT_FOUND


class TestTheSourceAssignmentsAreCopied:
    """read_source_assignments + copied_assignments + the real assignment manager"""

    def test_only_the_sources_assignments_are_read_without_id(self, manager: RiskAssessmentManager) -> None:
        """The other assessment's assignment is not among them"""
        read: list[dict[str, Any]] = read_source_assignments(manager, SOURCE_ID)

        assert [assignment[PUBLIC_ID_KEY] for assignment in read] == [SOURCE_ASSIGNMENT_ID]
        assert '_id' not in read[0]

    def test_the_copies_store_under_new_ids_on_the_duplicate(
            self, manager: RiskAssessmentManager, database_manager: MongoDatabaseManager, stored: Any) -> None:
        """The source keeps its own assignment; the copy carries every other key"""
        cma_manager = ControlMeasureAssignmentManager(database_manager)

        created_ids: list[int] = cma_manager.insert_many_items(
            copied_assignments(read_source_assignments(manager, SOURCE_ID), DUPLICATE_ID),
        )

        copy: dict[str, Any] = stored.find_one({RISK_ASSESSMENT_KEY: DUPLICATE_ID}, {'_id': 0})
        assert SOURCE_ASSIGNMENT_ID not in created_ids
        assert copy[PUBLIC_ID_KEY] in created_ids
        expected: dict[str, Any] = _assignment(copy[PUBLIC_ID_KEY], DUPLICATE_ID, MEASURE_ID)
        assert {key: copy.get(key) for key in expected} == expected
        assert stored.count_documents({RISK_ASSESSMENT_KEY: SOURCE_ID}) == 1
