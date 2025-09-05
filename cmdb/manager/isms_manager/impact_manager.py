# DATAGERRY - OpenSource Enterprise CMDB
# Copyright (C) 2025 becon GmbH
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

from cmdb.models.isms_model import IsmsImpact, IsmsRiskAssessment

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
        Updates an IsmsImpact with new data and propagates the updated calculation_basis
        to all affected IsmsRiskAssessments.

        This method first updates the Impact itself, then searches all RiskAssessments where
        the Impact is used in either risk_calculation_before or risk_calculation_after matrices
        It recalculates the maximum impact value and maximum impact ID based on the new
        calculation_basis and updates the affected RiskAssessments accordingly.

        Args:
            public_id (int): The public_id of the Impact to update
            new_data (dict[str, Any]): The new data for the Impact
        """
        # First update the IsmsImpact
        self.update_item(public_id, IsmsImpact.from_data(new_data))

        new_basis = new_data['calculation_basis']

        # Find IsmsRiskAssessments where this Impact is used
        query: dict[str, list[dict[str, int]]] = {
            '$or': [
                {'risk_calculation_before.impacts.impact_id': public_id},
                {'risk_calculation_after.impacts.impact_id': public_id}
            ]
        }

        updates = []

        affected_risk_assessments: list[dict[str, Any]] = self.dbm.find(
                                                    collection=IsmsRiskAssessment.COLLECTION,
                                                    db_name=self.db_name,
                                                    filter=query
                                                )

        for risk_assessment in affected_risk_assessments:
            update_fields = {}

            # Check the before-Matrix
            before: dict[str, Any] = risk_assessment.get('risk_calculation_before', {})
            before_impacts = before.get('impacts', [])

            max_before_value = -1
            max_before_id = None

            for item in before_impacts:
                impact_id = item.get('impact_id')

                if impact_id:
                    if impact_id == public_id:
                        basis = new_basis
                    else:
                        impact = self.get_item(impact_id, as_dict=True)
                        basis = impact['calculation_basis'] if impact else None
                    if basis is not None and basis > max_before_value:
                        max_before_value = basis
                        max_before_id = impact_id

            if max_before_id is not None:
                update_fields['risk_calculation_before.maximum_impact_id'] = max_before_id
                update_fields['risk_calculation_before.maximum_impact_value'] = max_before_value
            else:
                update_fields['risk_calculation_before.maximum_impact_id'] = None
                update_fields['risk_calculation_before.maximum_impact_value'] = None


            # Check the after-Matrix
            after: dict = risk_assessment.get('risk_calculation_after', {})
            after_impacts = after.get('impacts', [])

            max_after_value = -1
            max_after_id = None

            for item in after_impacts:
                impact_id = item.get('impact_id')
                if impact_id:
                    if impact_id == public_id:
                        basis = new_basis
                    else:
                        impact = self.get_item(impact_id, as_dict=True)
                        basis = impact['calculation_basis'] if impact else None
                    if basis is not None and basis > max_after_value:
                        max_after_value = basis
                        max_after_id = impact_id

            if max_after_id is not None:
                update_fields['risk_calculation_after.maximum_impact_id'] = max_after_id
                update_fields['risk_calculation_after.maximum_impact_value'] = max_after_value
            else:
                update_fields['risk_calculation_after.maximum_impact_id'] = None
                update_fields['risk_calculation_after.maximum_impact_value'] = None

            # Collect the update operation
            if update_fields:
                updates.append(UpdateOne({'public_id': risk_assessment['public_id']}, {'$set': update_fields}))

        # Bulk execute all updates
        if updates:
            self.dbm.bulk_write(IsmsRiskAssessment.COLLECTION, self.db_name, updates)

# -------------------------------------------------- HELPER METHODS -------------------------------------------------- #

    def is_impact_used(self, public_id: int) -> bool:
        """
        Checks if an Impact is used in any RiskAssessment

        Args:
            public_id (int): The public_id of the Impact

        Returns:
            bool: True if the Impact is used, False otherwise
        """
        query = {
            '$or': [
                {'risk_calculation_before.impacts.impact_id': public_id},
                {'risk_calculation_after.impacts.impact_id': public_id}
            ]
        }

        return self.get_one_by(query, IsmsRiskAssessment.COLLECTION) is not None


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
