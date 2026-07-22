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
<<<<<<< HEAD
=======
from typing import Any
>>>>>>> origin/version-3.2

from cmdb.database import MongoDatabaseManager

from cmdb.manager.generic_manager import GenericManager
from cmdb.manager.isms_manager.isms_manager_helper import load_calculation_basis, recompute_max_impact

from cmdb.models.isms_model import (
    IsmsRiskAssessment,
    IsmsControlMeasureAssignment,
    IsmsImpact,
    IsmsLikelihood,
)
from cmdb.models.isms_model.risk_calculation_constants import RiskCalculationKey, RISK_CALCULATION_MATRIX_KEYS

from cmdb.errors.manager.risk_assessment_manager import RISK_ASSESMENT_MANAGER_ERRORS
from cmdb.errors.manager.risk_assessment_manager import RiskAssessmentManagerDeleteError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                             RiskAssessmentManager - CLASS                                            #
# -------------------------------------------------------------------------------------------------------------------- #
class RiskAssessmentManager(GenericManager):
    """
    The RiskAssessmentManager manages the interaction between IsmsRiskAssessments and the database

    Extends: GenericManager
    """
    def __init__(self, dbm: MongoDatabaseManager, database: str = None):
        super().__init__(dbm, IsmsRiskAssessment, RISK_ASSESMENT_MANAGER_ERRORS, database)

# -------------------------------------------------- HELPER METHODS -------------------------------------------------- #

    def recalculate_risk_values(self, data: dict[str, Any]) -> None:
        """
        Derives the risk-calculation values on both matrices server-side, in place.

        The maximum_impact_id / maximum_impact_value and likelihood_value of risk_calculation_before
        and risk_calculation_after are recomputed from the current IsmsImpact / IsmsLikelihood
        calculation bases, overwriting any client-supplied values so the backend is the single source
        of truth for them.

        Args:
            data (dict[str, Any]): The RiskAssessment payload to normalise in place
        """
        impact_basis = load_calculation_basis(self.dbm, self.db_name, IsmsImpact.COLLECTION)
        likelihood_basis = load_calculation_basis(self.dbm, self.db_name, IsmsLikelihood.COLLECTION)

        for matrix_key in RISK_CALCULATION_MATRIX_KEYS:
            matrix = data.get(matrix_key.value)

            if not isinstance(matrix, dict):
                continue

            impacts = matrix.get(RiskCalculationKey.IMPACTS.value, [])
            max_id, max_value = recompute_max_impact(impacts, impact_basis)
            matrix[RiskCalculationKey.MAXIMUM_IMPACT_ID.value] = max_id
            matrix[RiskCalculationKey.MAXIMUM_IMPACT_VALUE.value] = max_value

            likelihood_id = matrix.get(RiskCalculationKey.LIKELIHOOD_ID.value)
            matrix[RiskCalculationKey.LIKELIHOOD_VALUE.value] = (
                likelihood_basis.get(likelihood_id) if likelihood_id else None
            )

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

    def delete_with_follow_up(self, public_id: int) -> bool:
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
            # When an IsmsRiskAssessment is deleted, delete all IsmsControlMeasureAssignments linked to
            # it in a single cross-collection delete rather than one delete per assignment
            self.delete_many_from_other_collection(
                IsmsControlMeasureAssignment.COLLECTION,
                {'risk_assessment_id': public_id}
            )

            return self.delete_item(public_id)
        except Exception as err:
            raise RiskAssessmentManagerDeleteError(str(err)) from err
