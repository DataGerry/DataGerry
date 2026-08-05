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
This module contains the implementation of the ImpactManager
"""
from logging import Logger, getLogger
from typing import Any

from pymongo import UpdateOne

from cmdb.database import MongoDatabaseManager
from cmdb.manager.generic_manager import GenericManager
from cmdb.manager.isms_manager.isms_manager_helper import load_impact_calculation_basis, recompute_max_impact

from cmdb.models.isms_model import IsmsImpact, IsmsRiskAssessment
from cmdb.models.isms_model.risk_calculation_constants import RiskCalculationKey, RISK_CALCULATION_MATRIX_KEYS

from cmdb.errors.manager.impact_manager import IMPACT_MANAGER_ERRORS, ImpactManagerGetError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                 ImpactManager - CLASS                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class ImpactManager(GenericManager):
    """
    The ImpactManager manages the interaction between IsmsImpacts and the database

    Extends: GenericManager
    """
    def __init__(self, dbm: MongoDatabaseManager, database: str | None = None) -> None:
        super().__init__(dbm, IsmsImpact, IMPACT_MANAGER_ERRORS, database)

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

    def update_with_follow_up(self, public_id: int, new_data: dict[str, Any]) -> None:
        """
        Updates an IsmsImpact and propagates the new calculation_basis to every affected
        IsmsRiskAssessment.

        The Impact is updated first, then all RiskAssessments referencing it (in the
        risk_calculation_before or risk_calculation_after impact matrices) have their
        maximum_impact_id / maximum_impact_value recomputed and bulk-written.

        Args:
            public_id (int): The public_id of the Impact to update
            new_data (dict[str, Any]): The new data for the Impact
        """
        self.update_item(public_id, IsmsImpact.from_data(new_data))

        # Find IsmsRiskAssessments where this Impact is used
        affected_risk_assessments: list[dict[str, Any]] = self.dbm.find(
                                                    collection=IsmsRiskAssessment.COLLECTION,
                                                    db_name=self.db_name,
                                                    filter=self._impact_reference_query(public_id)
                                                )

        # Preload every Impact's calculation_basis once (a small, fixed set) so the recompute loop
        # below does not issue a lookup per Impact per RiskAssessment
        basis_by_id: dict[int, float | None] = load_impact_calculation_basis(self.dbm, self.db_name)
        basis_by_id[public_id] = new_data['calculation_basis']

        updates: list[UpdateOne] = []

        for risk_assessment in affected_risk_assessments:
            update_fields: dict[str, Any] = {}

            for matrix_key in RISK_CALCULATION_MATRIX_KEYS:
                impacts = risk_assessment.get(matrix_key, {}).get(RiskCalculationKey.IMPACTS, [])
                max_id, max_value = recompute_max_impact(impacts, basis_by_id)
                update_fields[f'{matrix_key.value}.{RiskCalculationKey.MAXIMUM_IMPACT_ID.value}'] = max_id
                update_fields[f'{matrix_key.value}.{RiskCalculationKey.MAXIMUM_IMPACT_VALUE.value}'] = max_value

            updates.append(UpdateOne({'public_id': risk_assessment['public_id']}, {'$set': update_fields}))

        if updates:
            self.dbm.bulk_write(IsmsRiskAssessment.COLLECTION, self.db_name, updates)

# -------------------------------------------------- HELPER METHODS -------------------------------------------------- #

    @staticmethod
    def _impact_reference_query(public_id: int) -> dict[str, Any]:
        """
        Builds the query matching every RiskAssessment whose before/after matrix references an Impact.

        Args:
            public_id (int): The public_id of the Impact

        Returns:
            dict[str, Any]: A Mongo `$or` filter over both risk-calculation impact matrices
        """
        return {
            '$or': [
                {f'{matrix.value}.{RiskCalculationKey.IMPACTS.value}.{RiskCalculationKey.IMPACT_ID.value}': public_id}
                for matrix in RISK_CALCULATION_MATRIX_KEYS
            ]
        }


    def is_impact_used(self, public_id: int) -> bool:
        """
        Checks if an Impact is used in any RiskAssessment

        Args:
            public_id (int): The public_id of the Impact

        Returns:
            bool: True if the Impact is used, False otherwise
        """
        return self.get_one_by(self._impact_reference_query(public_id), IsmsRiskAssessment.COLLECTION) is not None


    def impact_calculation_basis_exists(self, calculation_basis: float) -> bool:
        """
        Checks if a calculation_basis already exists for an IsmsImpact

        Args:
            calculation_basis (float): The calculation_basis which should be checked

        Raises:
            ImpactManagerGetError: If checking calculation_basis failed

        Returns:
            bool: True if calculation_basis exists, else false
        """
        try:
            result = self.get_one_by({'calculation_basis': calculation_basis})

            return bool(result)
        except Exception as err:
            LOGGER.error("[impact_calculation_basis_exists] Exception: %s. Type: %s", err, type(err))
            raise ImpactManagerGetError(str(err)) from err
