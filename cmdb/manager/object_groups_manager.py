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
This module contains the implementation of the ObjectGroupsManager
"""
from logging import Logger, getLogger
from typing import Any

from pymongo.results import UpdateResult

from cmdb.database import MongoDatabaseManager
from cmdb.manager.generic_manager import GenericManager

from cmdb.models.object_group_model import (
    CmdbObjectGroup,
    ObjectGroupKey,
    ObjectReferenceType,
    ObjectGroupMode,
)
from cmdb.models.isms_model import IsmsRiskAssessment, IsmsControlMeasureAssignment
from cmdb.models.isms_model.isms_risk_assessment_constants import RiskAssessmentKey
from cmdb.models.isms_model.isms_control_measure_assignment_constants import ControlMeasureAssignmentKey

from cmdb.errors.manager.object_groups_manager import (
    OBJECT_GROUPS_MANAGER_ERRORS,
    ObjectGroupsManagerDeleteError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                              ObjectGroupsManager- CLASS                                              #
# -------------------------------------------------------------------------------------------------------------------- #
class ObjectGroupsManager(GenericManager):
    """
    The ObjectGroupsManager manages the interaction between CmdbObjectGroups and the database

    Extends: GenericManager
    """
    def __init__(self, dbm: MongoDatabaseManager, database: str | None = None):
        super().__init__(dbm, CmdbObjectGroup, OBJECT_GROUPS_MANAGER_ERRORS, database)

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

    def delete_with_follow_up(self, public_id: int) -> bool:
        """
        Deletes a CmdbObjectGroup and cleans all affected collections from it

        Args:
            public_id (int): public_id of CmdbObjectGroup which should be deleted

        Raises:
            ObjectGroupsManagerDeleteError: If the deletion or any cascade step fails

        Returns:
            bool: True if deletion was a success, else False
        """
        try:
            self.delete_object_group_from_risk_assessment_cascade(public_id)

            return self.delete_item(public_id)
        except Exception as err:
            raise ObjectGroupsManagerDeleteError(err) from err


    def delete_object_group_from_risk_assessment_cascade(self, deleted_group_id: int) -> None:
        """
        Deletes all RiskAssessments and their associated ControlMeasureAssignments that reference
        the given CmdbObjectGroup.

        This function performs the following steps:
        1. Finds all RiskAssessments where 'object_id_ref_type' is 'OBJECT_GROUP' and
        'object_id' matches the deleted group ID
        2. Deletes these RiskAssessments
        3. Deletes all ControlMeasureAssignments referencing the deleted RiskAssessments

        The cascade is intentionally self-contained (using the cross-collection delete primitive)
        rather than delegating to the RiskAssessment/ControlMeasureAssignment managers, since a
        manager must not depend on another manager.

        Args:
            deleted_group_id (int): The public_id of the deleted CmdbObjectGroup
        """
        # Find all RiskAssessments referencing this ObjectGroup
        risk_assessment_query = {
            RiskAssessmentKey.OBJECT_ID_REF_TYPE.value: ObjectReferenceType.OBJECT_GROUP.value,
            RiskAssessmentKey.OBJECT_ID.value: deleted_group_id,
        }

        matching_risk_assessments = list(self.dbm.find(
            IsmsRiskAssessment.COLLECTION,
            self.db_name,
            risk_assessment_query,
            projection={RiskAssessmentKey.PUBLIC_ID.value: 1}
        ))

        if not matching_risk_assessments:
            return  # Nothing to delete

        # Collect all RiskAssessment public_ids
        risk_assessment_ids = [ra[RiskAssessmentKey.PUBLIC_ID.value] for ra in matching_risk_assessments]

        # Delete the RiskAssessments
        self.delete_many_from_other_collection(
            IsmsRiskAssessment.COLLECTION,
            {RiskAssessmentKey.PUBLIC_ID.value: {'$in': risk_assessment_ids}},
        )

        # Delete all ControlMeasureAssignments referencing those RiskAssessments
        self.delete_many_from_other_collection(
            IsmsControlMeasureAssignment.COLLECTION,
            {ControlMeasureAssignmentKey.RISK_ASSESSMENT_ID.value: {'$in': risk_assessment_ids}},
        )


    def remove_ids_from_groups(self, public_ids: int | list[int], group_type: ObjectGroupMode) -> UpdateResult:
        """
        Removes a public_id or list of public_ids of CmdbObjects from the 'assigned_ids' of all CmdbObjectGroups
        of the provided group_type

        Args:
            public_ids (int | list[int]): public_id or public_ids of the target CmdbObjects
            group_type (ObjectGroupMode): It is either STATIC or DYNAMIC

        Returns:
            UpdateResult: Result of the deletion
        """
        criteria: dict[str, Any] = {ObjectGroupKey.GROUP_TYPE.value: group_type.value}

        if isinstance(public_ids, list):
            criteria[ObjectGroupKey.ASSIGNED_IDS.value] = {"$in": public_ids}
            update: dict[str, Any] = {ObjectGroupKey.ASSIGNED_IDS.value: {"$in": public_ids}}
        else:
            criteria[ObjectGroupKey.ASSIGNED_IDS.value] = public_ids
            update = {ObjectGroupKey.ASSIGNED_IDS.value: public_ids}

        return self.update_many_pull(
            criteria=criteria,
            update=update,
        )
