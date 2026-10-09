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
Unit tests for cmdb.manager.risk_assessment_cascade_helper.delete_risk_assessments_of

Pure tests: a mock database manager. Pins the three steps of the cascade both deletes share - which
assessments are selected (by id AND reference type), that the assessments are read before anything is
deleted, which documents the two deletes remove - and how a failed delete surfaces
"""
from typing import Any
from unittest.mock import MagicMock

import pytest

from cmdb.manager.risk_assessment_cascade_helper import delete_risk_assessments_of
from cmdb.models.isms_model import IsmsControlMeasureAssignment, IsmsRiskAssessment
from cmdb.models.isms_model.isms_control_measure_assignment_constants import ControlMeasureAssignmentKey
from cmdb.models.isms_model.isms_risk_assessment_constants import RiskAssessmentKey
from cmdb.models.object_group_model import ObjectReferenceType
from cmdb.errors.database import DocumentDeleteError
from cmdb.errors.manager import BaseManagerDeleteError
# -------------------------------------------------------------------------------------------------------------------- #

DB_NAME: str = 'cascade-db'
ENTITY_ID: int = 4
ENTITY_IDS_CLAUSE: dict[str, list[int]] = {'$in': [4, 5]}
ASSESSMENT_IDS: list[int] = [11, 12]


def _dbm(assessment_ids: list[int] | None = None) -> MagicMock:
    """A database manager whose find answers the given assessments (ASSESSMENT_IDS by default)."""
    dbm = MagicMock(name='dbm')
    dbm.find.return_value = [
        {RiskAssessmentKey.PUBLIC_ID.value: assessment_id}
        for assessment_id in (ASSESSMENT_IDS if assessment_ids is None else assessment_ids)
    ]

    return dbm


class TestWhichAssessmentsAreSelected:
    """The read that decides what goes."""

    @pytest.mark.parametrize('reference_type', list(ObjectReferenceType), ids=lambda kind: kind.value)
    def test_by_id_and_reference_type(self, reference_type: ObjectReferenceType) -> None:
        """
        Both halves of the filter

        An assessment's object_id holds a CmdbObject or a CmdbObjectGroup; without the reference type,
        deleting group 4 would delete the assessments of object 4, and the other way round
        """
        dbm = _dbm()

        delete_risk_assessments_of(dbm, DB_NAME, reference_type, ENTITY_ID)

        assert dbm.find.call_args.args == (
            IsmsRiskAssessment.COLLECTION, DB_NAME,
            {RiskAssessmentKey.OBJECT_ID_REF_TYPE.value: reference_type.value,
             RiskAssessmentKey.OBJECT_ID.value: ENTITY_ID},
        )

    def test_an_in_clause_is_handed_on(self) -> None:
        """The batched form: one query for many entities"""
        dbm = _dbm()

        delete_risk_assessments_of(dbm, DB_NAME, ObjectReferenceType.OBJECT, ENTITY_IDS_CLAUSE)

        assert dbm.find.call_args.args[2][RiskAssessmentKey.OBJECT_ID.value] == ENTITY_IDS_CLAUSE

    def test_only_the_ids_are_read(self) -> None:
        """Projected to public_id: the cascade needs the ids, not the assessments themselves"""
        dbm = _dbm()

        delete_risk_assessments_of(dbm, DB_NAME, ObjectReferenceType.OBJECT, ENTITY_ID)

        assert dbm.find.call_args.kwargs['projection'] == {RiskAssessmentKey.PUBLIC_ID.value: 1}


class TestWhatIsDeleted:
    """The two deletes."""

    def test_the_assessments_then_their_assignments(self) -> None:
        """
        Two bulk deletes keyed on the same id list, assessments first

        The assignments are found by the assessments they belong to, which is why the ids are read before
        anything is deleted
        """
        dbm = _dbm()

        delete_risk_assessments_of(dbm, DB_NAME, ObjectReferenceType.OBJECT_GROUP, ENTITY_ID)

        deletes: list[dict[str, Any]] = [call.kwargs for call in dbm.delete_many_raw.call_args_list]
        assert deletes == [
            {'collection': IsmsRiskAssessment.COLLECTION, 'db_name': DB_NAME,
             'filter_query': {RiskAssessmentKey.PUBLIC_ID.value: {'$in': ASSESSMENT_IDS}}},
            {'collection': IsmsControlMeasureAssignment.COLLECTION, 'db_name': DB_NAME,
             'filter_query': {ControlMeasureAssignmentKey.RISK_ASSESSMENT_ID.value: {'$in': ASSESSMENT_IDS}}},
        ]

    def test_nothing_when_no_assessment_matches(self) -> None:
        """The common case: an entity nobody assessed costs one query and no deletes"""
        dbm = _dbm([])

        delete_risk_assessments_of(dbm, DB_NAME, ObjectReferenceType.OBJECT, ENTITY_ID)

        dbm.delete_many_raw.assert_not_called()


class TestAFailedDelete:
    """How a failure surfaces."""

    def test_it_is_a_base_manager_delete_error_carrying_the_cause(self) -> None:
        """The manager-level error the callers already map, wrapping the database error itself"""
        dbm = _dbm()
        failure = DocumentDeleteError('delete failed')
        dbm.delete_many_raw.side_effect = failure

        with pytest.raises(BaseManagerDeleteError) as caught:
            delete_risk_assessments_of(dbm, DB_NAME, ObjectReferenceType.OBJECT, ENTITY_ID)

        assert caught.value.args[0] is failure

    def test_the_assignments_are_not_deleted_after_a_failed_assessment_delete(self) -> None:
        """The first delete failing stops the cascade - the assignments still belong to stored assessments"""
        dbm = _dbm()
        dbm.delete_many_raw.side_effect = DocumentDeleteError('delete failed')

        with pytest.raises(BaseManagerDeleteError):
            delete_risk_assessments_of(dbm, DB_NAME, ObjectReferenceType.OBJECT, ENTITY_ID)

        assert dbm.delete_many_raw.call_count == 1
