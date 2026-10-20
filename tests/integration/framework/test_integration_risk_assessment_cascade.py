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
Integration tests for the ISMS cascade the object delete and the object-group delete share

Both managers call ``risk_assessment_cascade_helper.delete_risk_assessments_of``, each for its own
reference type. The two counters are independent, so an object and an object group with the same
public_id is the normal case: against a real MongoDB, each delete takes its own assessments and their
control-measure assignments, and leaves the other entity's alone
"""
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.object_groups_manager import ObjectGroupsManager
from cmdb.manager.objects_manager import ObjectsManager
from cmdb.manager.risk_assessment_cascade_helper import delete_risk_assessments_of
from cmdb.models.isms_model import IsmsControlMeasureAssignment, IsmsRiskAssessment
from cmdb.models.isms_model.isms_control_measure_assignment_constants import ControlMeasureAssignmentKey
from cmdb.models.isms_model.isms_risk_assessment_constants import RiskAssessmentKey
from cmdb.models.object_group_model import ObjectReferenceType
# -------------------------------------------------------------------------------------------------------------------- #

SHARED_ID: int = 89601
OTHER_OBJECT_ID: int = 89602
UNASSESSED_ID: int = 89603

OBJECT_RA_ID: int = 89611
GROUP_RA_ID: int = 89612
OTHER_OBJECT_RA_ID: int = 89613
OBJECT_CMA_ID: int = 89621
GROUP_CMA_ID: int = 89622
OTHER_OBJECT_CMA_ID: int = 89623

ALL_RA_IDS: list[int] = [OBJECT_RA_ID, GROUP_RA_ID, OTHER_OBJECT_RA_ID]
ALL_CMA_IDS: list[int] = [OBJECT_CMA_ID, GROUP_CMA_ID, OTHER_OBJECT_CMA_ID]


@pytest.fixture(name='collections')
def fixture_collections(database_manager: MongoDatabaseManager, database_name: str):
    """
    Seeds an assessment + assignment for object SHARED_ID, for group SHARED_ID and for another object

    Answers the two collections; everything seeded is removed after
    """
    assessments = database_manager.get_collection(IsmsRiskAssessment.COLLECTION, database_name)
    assignments = database_manager.get_collection(IsmsControlMeasureAssignment.COLLECTION, database_name)

    def _purge() -> None:
        assessments.delete_many({RiskAssessmentKey.PUBLIC_ID.value: {'$in': ALL_RA_IDS}})
        assignments.delete_many({ControlMeasureAssignmentKey.PUBLIC_ID.value: {'$in': ALL_CMA_IDS}})

    _purge()
    assessments.insert_many([
        {RiskAssessmentKey.PUBLIC_ID.value: assessment_id,
         RiskAssessmentKey.OBJECT_ID_REF_TYPE.value: reference_type.value,
         RiskAssessmentKey.OBJECT_ID.value: entity_id}
        for assessment_id, reference_type, entity_id in [
            (OBJECT_RA_ID, ObjectReferenceType.OBJECT, SHARED_ID),
            (GROUP_RA_ID, ObjectReferenceType.OBJECT_GROUP, SHARED_ID),
            (OTHER_OBJECT_RA_ID, ObjectReferenceType.OBJECT, OTHER_OBJECT_ID),
        ]
    ])
    assignments.insert_many([
        {ControlMeasureAssignmentKey.PUBLIC_ID.value: assignment_id,
         ControlMeasureAssignmentKey.RISK_ASSESSMENT_ID.value: assessment_id}
        for assignment_id, assessment_id in [
            (OBJECT_CMA_ID, OBJECT_RA_ID), (GROUP_CMA_ID, GROUP_RA_ID), (OTHER_OBJECT_CMA_ID, OTHER_OBJECT_RA_ID),
        ]
    ])
    yield assessments, assignments
    _purge()


def _remaining(collections: tuple[Any, Any]) -> tuple[set[int], set[int]]:
    """The seeded assessment and assignment ids still stored."""
    assessments, assignments = collections

    return (
        {doc[RiskAssessmentKey.PUBLIC_ID.value] for doc in assessments.find(
            {RiskAssessmentKey.PUBLIC_ID.value: {'$in': ALL_RA_IDS}})},
        {doc[ControlMeasureAssignmentKey.PUBLIC_ID.value] for doc in assignments.find(
            {ControlMeasureAssignmentKey.PUBLIC_ID.value: {'$in': ALL_CMA_IDS}})},
    )


class TestTheObjectDelete:
    """ObjectsManager.delete_objects_from_risk_assessment_cascade."""

    def test_it_takes_the_objects_assessments_only(self, database_manager: MongoDatabaseManager,
                                                    collections: tuple[Any, Any]) -> None:
        """The object's assessment and assignment go; the group's with the same id stay, and so do the others"""
        ObjectsManager(database_manager).delete_objects_from_risk_assessment_cascade([SHARED_ID])

        assert _remaining(collections) == ({GROUP_RA_ID, OTHER_OBJECT_RA_ID}, {GROUP_CMA_ID, OTHER_OBJECT_CMA_ID})

    def test_a_batch_takes_every_listed_object(self, database_manager: MongoDatabaseManager,
                                               collections: tuple[Any, Any]) -> None:
        """One call for both objects; the group's assessment is still not touched"""
        ObjectsManager(database_manager).delete_objects_from_risk_assessment_cascade([SHARED_ID, OTHER_OBJECT_ID])

        assert _remaining(collections) == ({GROUP_RA_ID}, {GROUP_CMA_ID})


class TestTheGroupDelete:
    """ObjectGroupsManager.delete_object_group_from_risk_assessment_cascade."""

    def test_it_takes_the_groups_assessments_only(self, database_manager: MongoDatabaseManager,
                                                   collections: tuple[Any, Any]) -> None:
        """The group's assessment and assignment go; the object's with the same id stay"""
        ObjectGroupsManager(database_manager).delete_object_group_from_risk_assessment_cascade(SHARED_ID)

        assert _remaining(collections) == (
            {OBJECT_RA_ID, OTHER_OBJECT_RA_ID}, {OBJECT_CMA_ID, OTHER_OBJECT_CMA_ID},
        )


class TestTheHelper:
    """delete_risk_assessments_of itself."""

    def test_an_entity_nobody_assessed_changes_nothing(self, database_manager: MongoDatabaseManager,
                                                       database_name: str, collections: tuple[Any, Any]) -> None:
        """No match, no delete"""
        delete_risk_assessments_of(database_manager, database_name, ObjectReferenceType.OBJECT, UNASSESSED_ID)

        assert _remaining(collections) == (set(ALL_RA_IDS), set(ALL_CMA_IDS))
