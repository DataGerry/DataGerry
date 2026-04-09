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
This module contains the implementation of the RiskAssessmentManager
"""
from logging import Logger, getLogger

from cmdb.database import MongoDatabaseManager

from cmdb.manager.generic_manager import GenericManager

from cmdb.models.isms_model import IsmsRiskAssessment, IsmsControlMeasureAssignment

from cmdb.errors.manager.risk_assessment_manager import RISK_ASSESMENT_MANAGER_ERRORS
from cmdb.errors.manager.risk_assessment_manager import RiskAssessmentManagerDeleteError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                             RiskAssessmentManager - CLASS                                            #
# -------------------------------------------------------------------------------------------------------------------- #
class RiskAssessmentManager(GenericManager):
    """
    The ThreatManager manages the interaction between IsmsRiskAssessments and the database

    Extends: GenericManager
    """
    def __init__(self, dbm: MongoDatabaseManager, database: str = None):
        super().__init__(dbm, IsmsRiskAssessment, RISK_ASSESMENT_MANAGER_ERRORS, database)

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

    def delete_with_followup(self, public_id: int) -> bool:
        """
        Deletes an IsmsRiskAssessment from the database with followup logics

        Args:
            public_id (int): The public_id of the IsmsRiskAssessment to delete

        Raises:
            RiskAssessmentManagerDeleteError: If something went wrong

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # When an IsmsRiskAssessment is deleted, delete also all IsmsControlMeasureAssignments where it is linked
            linked_control_measure_assignments = self.get_many_from_other_collection(
                IsmsControlMeasureAssignment.COLLECTION,
                risk_assessment_id=public_id
            )

            for control_measure_assignment in linked_control_measure_assignments:
                self.delete(
                    {'public_id':control_measure_assignment['public_id']},
                    IsmsControlMeasureAssignment.COLLECTION
                )

            return self.delete_item(public_id)
        except Exception as err:
            raise RiskAssessmentManagerDeleteError(err) from err
