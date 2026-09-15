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
from logging import Logger, getLogger
from typing import Any

from cmdb.database import MongoDatabaseManager

from cmdb.manager.generic_manager import GenericManager

from cmdb.models.isms_model import IsmsRisk, IsmsRiskAssessment, IsmsControlMeasureAssignment

from cmdb.errors.manager.risk_manager import RISK_MANAGER_ERRORS, RiskManagerDeleteError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                  RiskManager - CLASS                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
class RiskManager(GenericManager):
    """
    The RiskManager manages the interaction between IsmsRisks and the database

    Extends: GenericManager
    """
    def __init__(self, dbm: MongoDatabaseManager, database: str = None):
        super().__init__(dbm, IsmsRisk, RISK_MANAGER_ERRORS, database)

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

    def delete_with_follow_up(self, public_id: int) -> bool:
        """
        Deletes the Risk with the given public_id and all associated RiskAssessments
        that reference it via the 'risk_id' field.

        Args:
            public_id (int): The public_id of the Risk to delete

        Returns:
            bool: True if the Risk was successfully deleted, False otherwise
        """
        try:
            self._cascade_delete_risk_assessments([public_id])

            # Delete the Risk itself
            return self.delete_item(public_id)
        except Exception as err:
            raise RiskManagerDeleteError(str(err)) from err


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
            RiskManagerDeleteError: If any part of the cascade fails

        Returns:
            tuple[list[int], int, int]: (deleted Risk public_ids, deleted RiskAssessment count,
                deleted ControlMeasureAssignment count)
        """
        if not public_ids:
            return [], 0, 0

        try:
            # Only existing Risks are reported / cascaded; the delete_many below removes exactly these
            existing_risk_ids: list[int] = [
                risk['public_id'] for risk in self.get_many(public_id={'$in': public_ids})
            ]

            if not existing_risk_ids:
                return [], 0, 0

            deleted_ras, deleted_cmas = self._cascade_delete_risk_assessments(existing_risk_ids)

            self.delete_many({'public_id': {'$in': existing_risk_ids}})

            return existing_risk_ids, deleted_ras, deleted_cmas
        except Exception as err:
            raise RiskManagerDeleteError(str(err)) from err


    def _cascade_delete_risk_assessments(self, risk_ids: list[int]) -> tuple[int, int]:
        """
        Deletes every RiskAssessment of the given Risks and the ControlMeasureAssignments beneath them

        The shared downstream cascade used by both the single (delete_with_follow_up) and bulk
        (delete_many_with_follow_up) Risk deletes: the RiskAssessments referencing any of ``risk_ids``
        and, beneath them, the ControlMeasureAssignments referencing those RiskAssessments are removed
        in one $in query each. Does NOT delete the Risks themselves. Assumes it runs inside a caller's
        try/except that wraps failures as RiskManagerDeleteError

        Args:
            risk_ids (list[int]): public_ids of the IsmsRisks whose RiskAssessments should be removed

        Returns:
            tuple[int, int]: (deleted RiskAssessment count, deleted ControlMeasureAssignment count)
        """
        linked_risk_assessments: list[dict[str, Any]] = self.get_many_from_other_collection(
            IsmsRiskAssessment.COLLECTION,
            risk_id={'$in': risk_ids},
        )

        linked_risk_assessment_ids: list[int] = [ra['public_id'] for ra in linked_risk_assessments]

        if not linked_risk_assessment_ids:
            return 0, 0

        # Delete all ControlMeasureAssignments referencing the linked RiskAssessments
        deleted_cmas: int = self.delete_many_from_other_collection(
            IsmsControlMeasureAssignment.COLLECTION,
            {'risk_assessment_id': {'$in': linked_risk_assessment_ids}},
        ).deleted_count

        # Delete all RiskAssessments referencing the Risks
        deleted_ras: int = self.delete_many_from_other_collection(
            IsmsRiskAssessment.COLLECTION,
            {'risk_id': {'$in': risk_ids}},
        ).deleted_count

        return deleted_ras, deleted_cmas
