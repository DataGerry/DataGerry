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
This module contains the implementation of the ImpactCategoryManager
"""
from logging import Logger, getLogger
<<<<<<< HEAD
=======
from typing import Any
>>>>>>> origin/version-3.2

from pymongo import UpdateOne

from cmdb.database import MongoDatabaseManager
from cmdb.manager.generic_manager import GenericManager
from cmdb.manager.isms_manager.isms_manager_helper import load_impact_calculation_basis, recompute_max_impact

from cmdb.models.isms_model import IsmsImpactCategory, IsmsRiskAssessment
from cmdb.models.isms_model.risk_calculation_constants import RiskCalculationKey, RISK_CALCULATION_MATRIX_KEYS

from cmdb.errors.manager.impact_category_manager import IMPACT_CATEGORY_MANAGER_ERRORS
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                             ImpactCategoryManager - CLASS                                            #
# -------------------------------------------------------------------------------------------------------------------- #
class ImpactCategoryManager(GenericManager):
    """
    The ImpactCategoryManager manages the interaction between IsmsImpactCategories and the database

    Extends: GenericManager
    """
    def __init__(self, dbm: MongoDatabaseManager, database: str | None = None) -> None:
        super().__init__(dbm, IsmsImpactCategory, IMPACT_CATEGORY_MANAGER_ERRORS, database)

# --------------------------------------------------- CRUD - CREATE -------------------------------------------------- #

    def create_with_follow_up(self, new_data: dict[str, Any]) -> int:
        """
        Creates a new ImpactCategory and updates all existing RiskAssessments to
        include this ImpactCategory with an empty (None) impact assignment

        Args:
            new_data (dict): The data for the new ImpactCategory to create

        Returns:
            int: The public_id of the newly created ImpactCategory
        """
        # First create the new IsmsImpactCategorys
        created_impact_category_id = self.insert_item(new_data)
        self.add_impact_category_to_risk_assessments(created_impact_category_id)

        return created_impact_category_id

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

    def delete_with_follow_up(self, impact_category_id: int) -> bool:
        """
        Deletes an ImpactCategory and updates all existing RiskAssessments by:
        1. Removing the ImpactCategory from their impacts
        2. Recalculating the maximum impact values for before and after matrices
        3. Deleting the ImpactCategory using the manager's delete_item method

        Args:
            impact_category_id (int): The public_id of the ImpactCategory to delete

        Returns:
            bool: True if the ImpactCategory was successfully deleted, False otherwise
        """
        all_risk_assessments: list[dict[str, Any]] = self.dbm.find(
                                                collection=IsmsRiskAssessment.COLLECTION,
                                                db_name=self.db_name,
                                                filter={}
                                        )

        # Preload every Impact's calculation_basis once so the per-RiskAssessment recompute below
        # does not issue a lookup per remaining impact (and reads from the IsmsImpact collection,
        # not this manager's own IsmsImpactCategory collection)
        basis_by_id: dict[int, float | None] = load_impact_calculation_basis(self.dbm, self.db_name)

        updates: list[UpdateOne] = []

        for risk_assessment in all_risk_assessments:
            update_fields: dict[str, Any] = {}

            for matrix_key in RISK_CALCULATION_MATRIX_KEYS:
                impacts = risk_assessment.get(matrix_key, {}).get(RiskCalculationKey.IMPACTS, [])
                remaining_impacts = [impact for impact in impacts
                                     if impact.get(RiskCalculationKey.IMPACT_CATEGORY_ID) != impact_category_id]

                max_id, max_value = recompute_max_impact(remaining_impacts, basis_by_id)

                update_fields[f'{matrix_key.value}.{RiskCalculationKey.IMPACTS.value}'] = remaining_impacts
                update_fields[f'{matrix_key.value}.{RiskCalculationKey.MAXIMUM_IMPACT_ID.value}'] = max_id
                update_fields[f'{matrix_key.value}.{RiskCalculationKey.MAXIMUM_IMPACT_VALUE.value}'] = max_value

            updates.append(UpdateOne({'public_id': risk_assessment['public_id']}, {'$set': update_fields}))

        # Apply the updates to RiskAssessments
        if updates:
            self.dbm.bulk_write(IsmsRiskAssessment.COLLECTION, self.db_name, updates)

        # Delete the ImpactCategory itself through the Manager
        return self.delete_item(impact_category_id)

# -------------------------------------------------- HELPER METHODS -------------------------------------------------- #

    def add_impact_category_to_risk_assessments(self, impact_category_public_id: int) -> None:
        """
        Adds a new ImpactCategory reference with a None impact_id to all existing RiskAssessments
        (both in risk_calculation_before.impacts and risk_calculation_after.impacts).

        Args:
            impact_category_public_id (int): The public_id of the newly created ImpactCategory
        """
        new_impact_entry = {
            RiskCalculationKey.IMPACT_CATEGORY_ID.value: impact_category_public_id,
            RiskCalculationKey.IMPACT_ID.value: None
        }

        impacts_paths = [f'{matrix.value}.{RiskCalculationKey.IMPACTS.value}'
                         for matrix in RISK_CALCULATION_MATRIX_KEYS]

        update_operation = {
            "$push": {path: new_impact_entry for path in impacts_paths}
        }

        # Target the IsmsRiskAssessment collection directly: this manager is bound to the
        # IsmsImpactCategory collection, so self.update_many would push into the wrong collection
        self.dbm.update_many(IsmsRiskAssessment.COLLECTION, self.db_name, {}, update_operation, plain=True)


    def add_new_impact_to_categories(self, new_impact_id: int) -> None:
        """
        Adds the new IsmsImpact entry to all IsmsImpactCategories

        Args:
            new_impact_id (int): public_id of the newly created IsmsImpact
        """
        update = {
            "impact_descriptions": {
                "impact_id": new_impact_id,
                "value": "-"
            }
        }

        self.update_many({}, update, add_to_set=True)


    def remove_deleted_impact_from_categories(self, deleted_impact_id: int) -> None:
        """
        Removes the IsmsImpact entry from all IsmsImpactCategories

        Args:
            deleted_impact_id (int): public_id of the deleted IsmsImpact
        """
        update = {
            "impact_descriptions": {
                "impact_id": {"$eq": deleted_impact_id}
            }
        }

        # Call update_many_pull to remove the references in all ImpactCategory documents
        self.update_many_pull({}, update)
