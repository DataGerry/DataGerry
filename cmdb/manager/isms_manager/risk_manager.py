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
This module contains the implementation of the RiskManager
"""
from typing import Any

from cmdb.database import MongoDatabaseManager

from cmdb.manager.generic_manager import GenericManager
from cmdb.manager.isms_manager.isms_manager_constants import MONGO_ID_KEY

from cmdb.models.isms_model import IsmsRisk, IsmsRiskAssessment, IsmsControlMeasureAssignment
from cmdb.models.isms_model.isms_control_measure_assignment_constants import ControlMeasureAssignmentKey
from cmdb.models.isms_model.isms_risk_assessment_constants import RiskAssessmentKey
from cmdb.models.isms_model.isms_risk_constants import RiskKey

from cmdb.errors.manager import BaseManagerDeleteError, BaseManagerGetError
from cmdb.errors.manager.risk_manager import RISK_MANAGER_ERRORS, RiskManagerDeleteError
# -------------------------------------------------------------------------------------------------------------------- #
#                                                  RiskManager - CLASS                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
class RiskManager(GenericManager):
    """
    The RiskManager manages the interaction between IsmsRisks and the database

    Extends: GenericManager
    """
    def __init__(self, dbm: MongoDatabaseManager, database: str | None = None) -> None:
        """
        Initialises the RiskManager

        Args:
            dbm (MongoDatabaseManager): Database interaction manager
            database (str | None): Target database name, used in cloud mode. Defaults to None
        """
        super().__init__(dbm, IsmsRisk, RISK_MANAGER_ERRORS, database)

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

    def delete_with_follow_up(self, public_id: int) -> bool:
        """
        Deletes the Risk with the given public_id, its RiskAssessments (referencing it via 'risk_id') and the
        ControlMeasureAssignments of those RiskAssessments

        The cascade runs first, the Risk goes last: a failure part-way leaves a Risk that can be deleted again

        Args:
            public_id (int): The public_id of the Risk to delete

        Raises:
            RiskManagerDeleteError: If the cascade or the delete of the Risk failed

        Returns:
            bool: True if the Risk was successfully deleted, False otherwise
        """
        try:
            self._cascade_delete_risk_assessments([public_id])
        except (BaseManagerGetError, BaseManagerDeleteError) as err:
            raise RiskManagerDeleteError(err) from err

        return self.delete_item(public_id)


    def delete_many_with_follow_up(self, public_ids: list[int]) -> tuple[list[int], int, int]:
        """
        Bulk-deletes several IsmsRisks and their cascade (RiskAssessments + ControlMeasureAssignments)

        The batched form of delete_with_follow_up: instead of running the Risk -> RiskAssessment ->
        ControlMeasureAssignment cascade once per Risk, it resolves the whole batch and runs the
        cascade in a fixed number of queries regardless of how many Risks are deleted. Only Risks that
        actually exist are reported as deleted (the cascade removes exactly those); a non-existent id
        is a silent no-op

        Args:
            public_ids (list[int]): public_ids of the IsmsRisks to delete

        Raises:
            RiskManagerGetError: If the existing Risks could not be read
            RiskManagerDeleteError: If any part of the cascade or the delete of the Risks fails

        Returns:
            tuple[list[int], int, int]: (deleted Risk public_ids, deleted RiskAssessment count,
                deleted ControlMeasureAssignment count)
        """
        if not public_ids:
            return [], 0, 0

        # Only existing Risks are reported / cascaded; the delete_many below removes exactly these
        existing_risk_ids: list[int] = sorted(self.find_existing_public_ids(public_ids))

        if not existing_risk_ids:
            return [], 0, 0

        try:
            deleted_ras, deleted_cmas = self._cascade_delete_risk_assessments(existing_risk_ids)

            self.delete_many({RiskKey.PUBLIC_ID.value: {'$in': existing_risk_ids}})
        except (BaseManagerGetError, BaseManagerDeleteError) as err:
            raise RiskManagerDeleteError(err) from err

        return existing_risk_ids, deleted_ras, deleted_cmas


    def _cascade_delete_risk_assessments(self, risk_ids: list[int]) -> tuple[int, int]:
        """
        Deletes every RiskAssessment of the given Risks and the ControlMeasureAssignments beneath them

        The shared downstream cascade used by both the single (delete_with_follow_up) and bulk
        (delete_many_with_follow_up) Risk deletes. Does NOT delete the Risks themselves.

        The RiskAssessments are read first (their ids only), then deleted BY THOSE IDS, then their
        assignments: the same order as the single RiskAssessment delete. A failure between the two deletes
        leaves assignments pointing at a RiskAssessment that no longer exists, which every reader already
        treats as "no RiskAssessment" - never a surviving RiskAssessment that has silently lost its
        assignments. Deleting by the ids read, not by ``risk_id``, keeps a RiskAssessment created in the
        meantime from being deleted without its assignments

        Args:
            risk_ids (list[int]): public_ids of the IsmsRisks whose RiskAssessments should be removed

        Raises:
            BaseManagerGetError: If the RiskAssessments could not be read
            BaseManagerDeleteError: If a delete failed

        Returns:
            tuple[int, int]: (deleted RiskAssessment count, deleted ControlMeasureAssignment count)
        """
        linked_risk_assessments: list[dict[str, Any]] = self.get_many_from_other_collection(
            IsmsRiskAssessment.COLLECTION,
            projection={RiskAssessmentKey.PUBLIC_ID.value: 1, MONGO_ID_KEY: 0},
            criteria={RiskAssessmentKey.RISK_ID.value: {'$in': risk_ids}},
        )

        linked_risk_assessment_ids: list[int] = [
            ra[RiskAssessmentKey.PUBLIC_ID.value] for ra in linked_risk_assessments
        ]

        if not linked_risk_assessment_ids:
            return 0, 0

        deleted_ras: int = self.delete_many_from_other_collection(
            IsmsRiskAssessment.COLLECTION,
            {RiskAssessmentKey.PUBLIC_ID.value: {'$in': linked_risk_assessment_ids}},
        ).deleted_count

        deleted_cmas: int = self.delete_many_from_other_collection(
            IsmsControlMeasureAssignment.COLLECTION,
            {ControlMeasureAssignmentKey.RISK_ASSESSMENT_ID.value: {'$in': linked_risk_assessment_ids}},
        ).deleted_count

        return deleted_ras, deleted_cmas
