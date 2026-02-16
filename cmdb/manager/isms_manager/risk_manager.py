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

from cmdb.database import MongoDatabaseManager

from cmdb.manager.generic_manager import GenericManager

from cmdb.models.isms_model import IsmsRisk, IsmsRiskAssessment, IsmsControlMeasureAssignment

from cmdb.errors.manager.risk_manager import RISK_MANAGER_ERRORS
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
        # Get all RiskAssessments which are referencing this IsmsRisk
        linked_risk_assessments = self.get_many_from_other_collection(
            IsmsRiskAssessment.COLLECTION,
            risk_id=public_id
        )

        # Extract the public_ids of the linked RiskAssessments
        linked_risk_assessment_ids = [ra['public_id'] for ra in linked_risk_assessments]

        if linked_risk_assessment_ids:
            # Delete all ControlMeassureAssignments which are referencing the linked RiskAssessments
            self.dbm.get_collection(IsmsControlMeasureAssignment.COLLECTION, self.db_name).delete_many(
                {'risk_assessment_id': {'$in': linked_risk_assessment_ids}}
            )

        # Delete all RiskAssessments referencing this Risk
        self.dbm.get_collection(IsmsRiskAssessment.COLLECTION, self.db_name).delete_many({'risk_id': public_id})

        # Delete the Risk itself
        return self.delete_item(public_id)
