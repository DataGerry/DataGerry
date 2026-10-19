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

Every write here that reaches past the category's own document - into every IsmsRiskAssessment's impact matrices,
or into every category's impact descriptions - takes the request's ``WriteLedger`` and records its inverse in it
BEFORE it runs, so a failure anywhere in the route takes the whole change back (``undone_on_failure``):

- creating a category records the insert, then the push into every assessment (undone by pulling the entries of
  that category - the id is new, so no other entry carries it)
- deleting a category records the assessments it rewrites, field by field (the impact lists and the maximum impact
  of both matrices), then the category itself, read right before its delete
- creating an Impact records the description pushed into every category (undone by pulling it again)
- deleting an Impact records the description entry each category held (undone by restoring that list)

A failed write is the manager's own typed error; a programming error propagates as itself
"""
from logging import Logger, getLogger
from typing import Any

from pymongo import UpdateOne

from cmdb.database import MongoDatabaseManager
from cmdb.framework.write_ledger import WriteLedger
from cmdb.manager.generic_manager import GenericManager
from cmdb.manager.isms_manager.isms_manager_constants import (
    CATEGORY_ADDED_DESCRIPTION,
    CATEGORY_REMOVED_DESCRIPTION,
    IMPACT_DESCRIPTION_ADDED_DESCRIPTION,
    IMPACT_DESCRIPTION_REMOVED_DESCRIPTION,
    PUBLIC_ID_KEY,
)
from cmdb.manager.isms_manager.isms_manager_helper import (
    load_impact_calculation_basis,
    recompute_max_impact,
    record_follow_up_write,
    snapshot_projection,
)

from cmdb.models.isms_model import IsmsImpactCategory, IsmsRiskAssessment
from cmdb.models.isms_model.risk_calculation_constants import RiskCalculationKey, RISK_CALCULATION_MATRIX_KEYS
from cmdb.models.isms_model.isms_impact_category_constants import (
    NEW_IMPACT_DESCRIPTION_PLACEHOLDER,
    ImpactCategoryKey,
    ImpactDescriptionKey,
)

from cmdb.errors.manager import BaseManagerGetError, BaseManagerUpdateError
from cmdb.errors.manager.impact_category_manager import (
    IMPACT_CATEGORY_MANAGER_ERRORS,
    ImpactCategoryManagerDeleteError,
    ImpactCategoryManagerInsertError,
    ImpactCategoryManagerUpdateError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# The impact lists of both matrices, and every path the delete's rewrite of an assessment changes
IMPACTS_PATHS: list[str] = [
    f'{matrix.value}.{RiskCalculationKey.IMPACTS.value}' for matrix in RISK_CALCULATION_MATRIX_KEYS
]
CATEGORY_REWRITE_PATHS: list[str] = [
    f'{matrix.value}.{key.value}'
    for matrix in RISK_CALCULATION_MATRIX_KEYS
    for key in (
        RiskCalculationKey.IMPACTS, RiskCalculationKey.MAXIMUM_IMPACT_ID, RiskCalculationKey.MAXIMUM_IMPACT_VALUE,
    )
]
# Where an impact's description sits inside a category, as a filter path
IMPACT_DESCRIPTION_ID_PATH: str = (
    f'{ImpactCategoryKey.IMPACT_DESCRIPTIONS.value}.{ImpactDescriptionKey.IMPACT_ID.value}'
)

# -------------------------------------------------------------------------------------------------------------------- #
#                                             ImpactCategoryManager - CLASS                                            #
# -------------------------------------------------------------------------------------------------------------------- #
class ImpactCategoryManager(GenericManager):
    """
    The ImpactCategoryManager manages the interaction between IsmsImpactCategories and the database

    Extends: GenericManager
    """
    def __init__(self, dbm: MongoDatabaseManager, database: str | None = None) -> None:
        """
        Initialises the ImpactCategoryManager

        Args:
            dbm (MongoDatabaseManager): Database interaction manager
            database (str | None): Target database name, used in cloud mode. Defaults to None
        """
        super().__init__(dbm, IsmsImpactCategory, IMPACT_CATEGORY_MANAGER_ERRORS, database)

# --------------------------------------------------- CRUD - CREATE -------------------------------------------------- #

    def create_with_follow_up(self, new_data: dict[str, Any], ledger: WriteLedger) -> int:
        """
        Creates an ImpactCategory and adds it to every RiskAssessment with an empty (None) impact assignment

        Both writes are recorded in the ledger: the insert once it ran, the push into the assessments before it
        runs, with its inverse (the category's entries pulled out again) and its check (no assessment carries it)

        Args:
            new_data (dict[str, Any]): The data for the new ImpactCategory
            ledger (WriteLedger): The request's ledger

        Raises:
            ImpactCategoryManagerInsertError: If the insert or the RiskAssessment update failed

        Returns:
            int: The public_id of the newly created ImpactCategory
        """
        created_impact_category_id: int = self.insert_item(new_data)
        ledger.inserted(self, created_impact_category_id)

        ledger.compensated(
            IsmsRiskAssessment.COLLECTION,
            CATEGORY_ADDED_DESCRIPTION.format(public_id=created_impact_category_id),
            undo=lambda: self.pull_category_from_risk_assessments(created_impact_category_id),
            verify=lambda: not self.risk_assessments_holding_category(created_impact_category_id),
        )

        try:
            self.add_impact_category_to_risk_assessments(created_impact_category_id)
        except BaseManagerUpdateError as err:
            LOGGER.error("[create_with_follow_up] %s: %s", type(err).__name__, err)
            raise ImpactCategoryManagerInsertError(err) from err

        return created_impact_category_id

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

    def delete_with_follow_up(self, impact_category_id: int, ledger: WriteLedger) -> bool:
        """
        Deletes an ImpactCategory after removing it from every RiskAssessment holding it

        The assessments holding the category are read once, projected to the paths the rewrite changes, and
        recorded as a field-level follow-up before they are rewritten (the category's entries removed, both
        maximum impacts recomputed); the category is recorded with its stored document, read right before its delete

        Args:
            impact_category_id (int): The public_id of the ImpactCategory to delete
            ledger (WriteLedger): The request's ledger

        Raises:
            ImpactCategoryManagerDeleteError: If reading or updating the RiskAssessments, or the delete, failed

        Returns:
            bool: True if the ImpactCategory was deleted, False when it no longer existed
        """
        try:
            risk_assessments: list[dict[str, Any]] = self.risk_assessments_holding_category(impact_category_id)

            record_follow_up_write(
                ledger, self, IsmsRiskAssessment.COLLECTION,
                CATEGORY_REMOVED_DESCRIPTION.format(public_id=impact_category_id),
                risk_assessments, CATEGORY_REWRITE_PATHS,
            )

            self._remove_category_from_risk_assessments(impact_category_id, risk_assessments)

            stored: dict[str, Any] | None = self.get_one(impact_category_id)
        except (BaseManagerGetError, BaseManagerUpdateError) as err:
            LOGGER.error("[delete_with_follow_up] %s: %s", type(err).__name__, err)
            raise ImpactCategoryManagerDeleteError(err) from err

        # Recorded before the delete runs, from the read just made: a delete that lands and then reports a failure is
        # undone too, and one that never happened leaves the stored category alone on undo. Nothing is recorded for
        # a category already gone, so the undo cannot bring back one another request removed
        if stored is not None:
            ledger.deleted(self, impact_category_id, stored)

        return self.delete_item(impact_category_id)

# -------------------------------------------------- HELPER METHODS -------------------------------------------------- #

    def risk_assessments_holding_category(self, impact_category_id: int) -> list[dict[str, Any]]:
        """
        The RiskAssessments whose impact matrices name an ImpactCategory, projected to the paths its removal changes

        Args:
            impact_category_id (int): The public_id of the ImpactCategory

        Raises:
            BaseManagerGetError: If the RiskAssessments could not be read

        Returns:
            list[dict[str, Any]]: Each assessment's public_id with both matrices' impacts and maximum impact
        """
        return self.get_many_from_other_collection(
            IsmsRiskAssessment.COLLECTION,
            projection=snapshot_projection(CATEGORY_REWRITE_PATHS),
            criteria={'$or': [
                {f'{path}.{RiskCalculationKey.IMPACT_CATEGORY_ID.value}': impact_category_id}
                for path in IMPACTS_PATHS
            ]},
        )


    def _remove_category_from_risk_assessments(
            self,
            impact_category_id: int,
            risk_assessments: list[dict[str, Any]]) -> None:
        """
        Removes an ImpactCategory from the impact matrices of the given RiskAssessments, recomputing their
        maximum impact, in one bulk write

        Args:
            impact_category_id (int): The public_id of the ImpactCategory being deleted
            risk_assessments (list[dict[str, Any]]): The assessments holding it (``risk_assessments_holding_category``)

        Raises:
            BaseManagerGetError: If the Impacts could not be read
            BaseManagerUpdateError: If the bulk write failed
        """
        if not risk_assessments:
            return

        # Preload every Impact's calculation_basis once so the per-RiskAssessment recompute below
        # does not issue a lookup per remaining impact
        basis_by_id: dict[int, float | None] = load_impact_calculation_basis(self)

        updates: list[UpdateOne] = []

        for risk_assessment in risk_assessments:
            update_fields: dict[str, Any] = {}

            for matrix_key in RISK_CALCULATION_MATRIX_KEYS:
                matrix: dict[str, Any] = risk_assessment.get(matrix_key.value) or {}
                impacts: list[dict[str, Any]] = matrix.get(RiskCalculationKey.IMPACTS.value) or []
                remaining_impacts = [impact for impact in impacts
                                     if impact.get(RiskCalculationKey.IMPACT_CATEGORY_ID) != impact_category_id]

                max_id, max_value = recompute_max_impact(remaining_impacts, basis_by_id)

                update_fields[f'{matrix_key.value}.{RiskCalculationKey.IMPACTS.value}'] = remaining_impacts
                update_fields[f'{matrix_key.value}.{RiskCalculationKey.MAXIMUM_IMPACT_ID.value}'] = max_id
                update_fields[f'{matrix_key.value}.{RiskCalculationKey.MAXIMUM_IMPACT_VALUE.value}'] = max_value

            updates.append(UpdateOne({PUBLIC_ID_KEY: risk_assessment[PUBLIC_ID_KEY]}, {'$set': update_fields}))

        self.bulk_write(updates, collection=IsmsRiskAssessment.COLLECTION)


    def pull_category_from_risk_assessments(self, impact_category_id: int) -> None:
        """
        Pulls every entry of an ImpactCategory out of both impact matrices of every RiskAssessment

        The inverse of ``add_impact_category_to_risk_assessments`` - exact for a category just created, whose id
        no other entry carries. The maximum impact is left alone: the pushed entry carried no impact

        Args:
            impact_category_id (int): The public_id of the ImpactCategory

        Raises:
            BaseManagerUpdateError: If the RiskAssessments could not be updated
        """
        entry_filter: dict[str, Any] = {RiskCalculationKey.IMPACT_CATEGORY_ID.value: impact_category_id}

        self.update_many_raw(
            {'$or': [{f'{path}.{RiskCalculationKey.IMPACT_CATEGORY_ID.value}': impact_category_id}
                     for path in IMPACTS_PATHS]},
            {'$pull': {path: entry_filter for path in IMPACTS_PATHS}},
            collection=IsmsRiskAssessment.COLLECTION,
        )


    def add_impact_category_to_risk_assessments(self, impact_category_public_id: int) -> None:
        """
        Adds a new ImpactCategory reference with a None impact_id to all existing RiskAssessments
        (both in risk_calculation_before.impacts and risk_calculation_after.impacts).

        Args:
            impact_category_public_id (int): The public_id of the newly created ImpactCategory

        Raises:
            BaseManagerUpdateError: If the RiskAssessments could not be updated
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

        # Named explicitly: this manager is bound to the IsmsImpactCategory collection
        self.update_many_raw({}, update_operation, collection=IsmsRiskAssessment.COLLECTION)


    def add_new_impact_to_categories(self, new_impact_id: int, ledger: WriteLedger) -> None:
        """
        Adds the new IsmsImpact's description entry (a placeholder text) to every IsmsImpactCategory

        Recorded in the ledger before it runs: undone by pulling the impact's entries out again, checked by no
        category holding one

        Args:
            new_impact_id (int): public_id of the newly created IsmsImpact
            ledger (WriteLedger): The request's ledger

        Raises:
            ImpactCategoryManagerUpdateError: If the ImpactCategories could not be updated
        """
        update = {
            ImpactCategoryKey.IMPACT_DESCRIPTIONS.value: {
                ImpactDescriptionKey.IMPACT_ID.value: new_impact_id,
                ImpactDescriptionKey.VALUE.value: NEW_IMPACT_DESCRIPTION_PLACEHOLDER,
            }
        }

        ledger.compensated(
            self.collection,
            IMPACT_DESCRIPTION_ADDED_DESCRIPTION.format(public_id=new_impact_id),
            undo=lambda: self._pull_impact_descriptions(new_impact_id),
            verify=lambda: not self.find(criteria={IMPACT_DESCRIPTION_ID_PATH: new_impact_id}),
        )

        try:
            self.update_many({}, update, add_to_set=True)
        except BaseManagerUpdateError as err:
            LOGGER.error("[add_new_impact_to_categories] %s: %s", type(err).__name__, err)
            raise ImpactCategoryManagerUpdateError(err) from err


    def remove_deleted_impact_from_categories(self, deleted_impact_id: int, ledger: WriteLedger) -> None:
        """
        Removes the IsmsImpact's description entry from every IsmsImpactCategory

        The categories holding one are read first, projected to their description lists, and recorded as a
        field-level follow-up: the undo puts each list back as it was

        Args:
            deleted_impact_id (int): public_id of the deleted IsmsImpact
            ledger (WriteLedger): The request's ledger

        Raises:
            ImpactCategoryManagerUpdateError: If the ImpactCategories could not be read or updated
        """
        descriptions_path: str = ImpactCategoryKey.IMPACT_DESCRIPTIONS.value

        try:
            holding: list[dict[str, Any]] = self.find(
                criteria={IMPACT_DESCRIPTION_ID_PATH: deleted_impact_id},
                projection=snapshot_projection([descriptions_path]),
            )

            record_follow_up_write(
                ledger, self, self.collection,
                IMPACT_DESCRIPTION_REMOVED_DESCRIPTION.format(public_id=deleted_impact_id),
                holding, [descriptions_path],
            )

            self._pull_impact_descriptions(deleted_impact_id)
        except (BaseManagerGetError, BaseManagerUpdateError) as err:
            LOGGER.error("[remove_deleted_impact_from_categories] %s: %s", type(err).__name__, err)
            raise ImpactCategoryManagerUpdateError(err) from err


    def _pull_impact_descriptions(self, impact_id: int) -> None:
        """
        Pulls every description entry of one IsmsImpact out of every IsmsImpactCategory

        Args:
            impact_id (int): public_id of the IsmsImpact

        Raises:
            BaseManagerUpdateError: If the ImpactCategories could not be updated
        """
        self.update_many_pull(
            {IMPACT_DESCRIPTION_ID_PATH: impact_id},
            {ImpactCategoryKey.IMPACT_DESCRIPTIONS.value: {ImpactDescriptionKey.IMPACT_ID.value: impact_id}},
        )
