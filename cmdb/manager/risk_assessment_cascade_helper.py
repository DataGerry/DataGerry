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
The delete cascade into the ISMS risk assessments, shared by the two entities an assessment can assess

An IsmsRiskAssessment assesses either a CmdbObject or a CmdbObjectGroup - ``object_id`` names it and
``object_id_ref_type`` says which. Deleting either entity deletes its assessments and the
IsmsControlMeasureAssignments that belonged to them, and the two cascades differ in nothing but that
reference type. ``ObjectsManager`` and ``ObjectGroupsManager`` both call this one function.

The module is deliberately manager-free: it takes the database manager and the database name, so either
manager may call it without depending on the other (a manager must not, and this is how the pair shares
the code - the same arrangement as ``person_reference_helper``)
"""
from typing import Any

from cmdb.database import MongoDatabaseManager

from cmdb.models.isms_model import IsmsControlMeasureAssignment, IsmsRiskAssessment
from cmdb.models.isms_model.isms_control_measure_assignment_constants import ControlMeasureAssignmentKey
from cmdb.models.isms_model.isms_risk_assessment_constants import RiskAssessmentKey
from cmdb.models.object_group_model import ObjectReferenceType

from cmdb.errors.database import DocumentDeleteError
from cmdb.errors.manager import BaseManagerDeleteError
# -------------------------------------------------------------------------------------------------------------------- #


def delete_risk_assessments_of(
        dbm: MongoDatabaseManager,
        db_name: str,
        reference_type: ObjectReferenceType,
        object_id_criteria: Any) -> None:
    """
    Deletes the IsmsRiskAssessments of the given entities, and the assignments that belonged to them

    Three steps: find the assessments, delete them, then delete their control-measure assignments. The
    assessments are read before anything is deleted because the assignments are found by the ids of the
    assessments that are about to go: deleting the assessments first would leave nothing to look their
    assignments up by.

    Only assessments of ``reference_type`` are touched - an assessment of a CmdbObjectGroup that happens
    to share a CmdbObject's public_id is the group's, and the other way round

    Args:
        dbm (MongoDatabaseManager): The database manager
        db_name (str): The database the collections live in
        reference_type (ObjectReferenceType): Which kind of entity was deleted
        object_id_criteria (Any): The ``object_id`` filter value - one public_id, or an ``$in`` clause

    Raises:
        BaseManagerDeleteError: If deleting the assessments or the assignments fails
    """
    matching_risk_assessments: list[dict[str, Any]] = list(dbm.find(
        IsmsRiskAssessment.COLLECTION,
        db_name,
        {
            RiskAssessmentKey.OBJECT_ID_REF_TYPE.value: reference_type.value,
            RiskAssessmentKey.OBJECT_ID.value: object_id_criteria,
        },
        projection={RiskAssessmentKey.PUBLIC_ID.value: 1},
    ))

    if not matching_risk_assessments:
        return

    risk_assessment_ids: list[int] = [
        assessment[RiskAssessmentKey.PUBLIC_ID.value] for assessment in matching_risk_assessments
    ]

    try:
        dbm.delete_many_raw(
            collection=IsmsRiskAssessment.COLLECTION,
            db_name=db_name,
            filter_query={RiskAssessmentKey.PUBLIC_ID.value: {'$in': risk_assessment_ids}},
        )
        dbm.delete_many_raw(
            collection=IsmsControlMeasureAssignment.COLLECTION,
            db_name=db_name,
            filter_query={ControlMeasureAssignmentKey.RISK_ASSESSMENT_ID.value: {'$in': risk_assessment_ids}},
        )
    except DocumentDeleteError as err:
        raise BaseManagerDeleteError(err) from err
