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
This module contains the implementation of the ImpactCategoryManager
"""
import logging

from pymongo import UpdateOne
from pymongo.cursor import Cursor

from cmdb.database import MongoDatabaseManager

from cmdb.manager.generic_manager import GenericManager

from cmdb.models.isms_model import IsmsImpactCategory, IsmsRiskAssessment

from cmdb.errors.manager.impact_category_manager import IMPACT_CATEGORY_MANAGER_ERRORS
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER = logging.getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                             ImpactCategoryManager - CLASS                                            #
# -------------------------------------------------------------------------------------------------------------------- #
class ImpactCategoryManager(GenericManager):
    """
    The ImpactCategoryManager manages the interaction between IsmsImpactCategories and the database

    Extends: GenericManager
    """
    def __init__(self, dbm: MongoDatabaseManager, database: str = None):
        super().__init__(dbm, IsmsImpactCategory, IMPACT_CATEGORY_MANAGER_ERRORS, database)

# --------------------------------------------------- CRUD - CREATE -------------------------------------------------- #

    def create_with_follow_up(self, new_data: dict) -> int:
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
        # Fetch all RiskAssessments
        all_risk_assessments: Cursor = self.dbm.find(
                                                collection=IsmsRiskAssessment.COLLECTION,
                                                db_name=self.db_name,
                                                filter={}
                                        )

        updates = []

        for risk_assessment in all_risk_assessments:
            update_fields = {}

            # Process 'risk_calculation_before'
            before = risk_assessment.get('risk_calculation_before', {})
            before_impacts = before.get('impacts', [])
            new_before_impacts = [impact for impact in before_impacts if
                                  impact.get('impact_category_id') != impact_category_id]

            max_before_value, max_before_id = self.calculate_max_impact_value(new_before_impacts)

            update_fields['risk_calculation_before.impacts'] = new_before_impacts
            update_fields['risk_calculation_before.maximum_impact_id'] = max_before_id
            update_fields['risk_calculation_before.maximum_impact_value'] = max_before_value

            # Process 'risk_calculation_after'
            after = risk_assessment.get('risk_calculation_after', {})
            after_impacts = after.get('impacts', [])
            new_after_impacts = [impact for impact in after_impacts if
                                 impact.get('impact_category_id') != impact_category_id]

            max_after_value, max_after_id = self.calculate_max_impact_value(new_after_impacts)

            update_fields['risk_calculation_after.impacts'] = new_after_impacts
            update_fields['risk_calculation_after.maximum_impact_id'] = max_after_id
            update_fields['risk_calculation_after.maximum_impact_value'] = max_after_value

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
            impact_category_id (int): The public_id of the newly created ImpactCategory
        """
        new_impact_entry = {
            "impact_category_id": impact_category_public_id,
            "impact_id": None
        }

        update_operation = {
            "$push": {
                "risk_calculation_before.impacts": new_impact_entry,
                "risk_calculation_after.impacts": new_impact_entry
            }
        }

        self.update_many(criteria={}, update=update_operation, plain=True)


    def calculate_max_impact_value(self, impacts: list) -> tuple[float | None, int | None]:
        """
        Calculates the maximum impact value and corresponding impact_id from a list of impacts

        Args:
            impacts (list): List of impact dictionaries.

        Returns:
            tuple[float | None, int | None]: (max_value, max_impact_id) or (None, None) if no impacts
        """
        max_value = -1
        max_impact_id = None

        for impact in impacts:
            impact_id = impact.get('impact_id')
            if impact_id is not None:
                impact_data = self.get_item(impact_id, as_dict=True)
                value = impact_data.get('calculation_basis') if impact_data else None

                if value is not None and value > max_value:
                    max_value = value
                    max_impact_id = impact_id

        return (max_value if max_value >= 0 else None, max_impact_id)


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
            new_impact_id (int): public_id of the deleted IsmsImpact
        """
        update = {
            "impact_descriptions": {
                "impact_id": {"$eq": deleted_impact_id}
            }
        }

        # Call update_many_pull to remove the references in all ImpactCategory documents
        self.update_many_pull({}, update)
