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
from cmdb.framework.write_ledger import WriteLedger
from cmdb.manager.generic_manager import GenericManager
from cmdb.manager.isms_manager.isms_manager_constants import (
    IMPACT_IN_USE_MESSAGE,
    IMPACT_PROPAGATION_DESCRIPTION,
    PUBLIC_ID_KEY,
)
from cmdb.manager.isms_manager.isms_manager_helper import (
    delete_unless_referenced,
    load_impact_calculation_basis,
    record_follow_up_write,
    recompute_max_impact,
    snapshot_projection,
)

from cmdb.models.isms_model import IsmsImpact, IsmsRiskAssessment
from cmdb.models.isms_model.risk_calculation_constants import RiskCalculationKey, RISK_CALCULATION_MATRIX_KEYS
from cmdb.models.isms_model.isms_impact_constants import ImpactKey

from cmdb.errors.models.isms_impact import IsmsImpactInitFromDataError
from cmdb.errors.manager import BaseManagerGetError, BaseManagerUpdateError
from cmdb.errors.manager.impact_manager import (
    IMPACT_MANAGER_ERRORS,
    ImpactManagerAssessmentUsageError,
    ImpactManagerCalculationBasisError,
    ImpactManagerUpdateError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# The dotted paths of a RiskAssessment that the propagation of an Impact's calculation_basis rewrites
MAXIMUM_IMPACT_PATHS: list[str] = [
    f'{matrix.value}.{key.value}'
    for matrix in RISK_CALCULATION_MATRIX_KEYS
    for key in (RiskCalculationKey.MAXIMUM_IMPACT_ID, RiskCalculationKey.MAXIMUM_IMPACT_VALUE)
]

# The dotted paths the propagation reads: the impact matrices it recomputes from, and what it rewrites
IMPACT_PROPAGATION_READ_PATHS: list[str] = [
    f'{matrix.value}.{RiskCalculationKey.IMPACTS.value}' for matrix in RISK_CALCULATION_MATRIX_KEYS
] + MAXIMUM_IMPACT_PATHS

# -------------------------------------------------------------------------------------------------------------------- #
#                                                 ImpactManager - CLASS                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class ImpactManager(GenericManager):
    """
    The ImpactManager manages the interaction between IsmsImpacts and the database

    Extends: GenericManager
    """
    def __init__(self, dbm: MongoDatabaseManager, database: str | None = None) -> None:
        """
        Initialises the ImpactManager

        Args:
            dbm (MongoDatabaseManager): Database interaction manager
            database (str | None): Target database name, used in cloud mode. Defaults to None
        """
        super().__init__(dbm, IsmsImpact, IMPACT_MANAGER_ERRORS, database)

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

    def update_with_follow_up(self, public_id: int, new_data: dict[str, Any], ledger: WriteLedger) -> dict[str, Any]:
        """
        Updates an IsmsImpact and propagates the new calculation_basis to every affected IsmsRiskAssessment

        The Impact is updated first, then all RiskAssessments referencing it (in the risk_calculation_before or
        risk_calculation_after impact matrices) have their maximum_impact_id / maximum_impact_value recomputed and
        bulk-written. Both writes are recorded in ``ledger``: the Impact with its stored snapshot, the propagation
        with the maximum-impact fields it is about to overwrite - so a caller undoing the ledger puts back exactly
        those fields and leaves the rest of each RiskAssessment alone

        Args:
            public_id (int): The public_id of the Impact to update
            new_data (dict[str, Any]): The new data for the Impact
            ledger (WriteLedger): The request's ledger, which the two writes are recorded in

        Raises:
            ImpactManagerGetError: If the stored Impact could not be read
            ImpactManagerUpdateError: If the Impact does not exist or cannot be built from the data, or if the
                update, the read of the affected RiskAssessments or the propagation failed

        Returns:
            dict[str, Any]: The Impact document as stored
        """
        prior: dict[str, Any] | None = self.get_item(public_id, as_dict=True)

        if prior is None:
            raise ImpactManagerUpdateError(f"The Impact with ID: {public_id} does not exist!")

        try:
            impact: IsmsImpact = IsmsImpact.from_data(new_data)
        except IsmsImpactInitFromDataError as err:
            raise ImpactManagerUpdateError(err) from err

        self.update_item(public_id, impact)
        ledger.updated(self, public_id, prior)

        try:
            self._propagate_calculation_basis(public_id, new_data[ImpactKey.CALCULATION_BASIS.value], ledger)
        except (BaseManagerGetError, BaseManagerUpdateError) as err:
            LOGGER.error("[update_with_follow_up] %s: %s", type(err).__name__, err)
            raise ImpactManagerUpdateError(err) from err

        return IsmsImpact.to_json(impact)


    def _propagate_calculation_basis(self, public_id: int, calculation_basis: float, ledger: WriteLedger) -> None:
        """
        Recomputes the maximum impact of every RiskAssessment using the Impact, in one bulk write

        The affected RiskAssessments are read once, projected to the impact matrices and the fields rewritten;
        every Impact's calculation_basis is preloaded once (a small, fixed set) so the recompute does not issue a
        lookup per Impact per RiskAssessment

        Args:
            public_id (int): The public_id of the updated Impact
            calculation_basis (float): Its new calculation_basis
            ledger (WriteLedger): The request's ledger; the write is recorded before it runs

        Raises:
            BaseManagerGetError: If the RiskAssessments or the Impacts could not be read
            BaseManagerUpdateError: If the bulk write failed
        """
        affected: list[dict[str, Any]] = self.get_many_from_other_collection(
            IsmsRiskAssessment.COLLECTION,
            projection=snapshot_projection(IMPACT_PROPAGATION_READ_PATHS),
            criteria=self.impact_reference_query(public_id),
        )

        if not affected:
            return

        basis_by_id: dict[int, float | None] = load_impact_calculation_basis(self)
        basis_by_id[public_id] = calculation_basis

        operations: list[UpdateOne] = self.max_impact_operations(affected, basis_by_id)

        record_follow_up_write(ledger, self, IsmsRiskAssessment.COLLECTION,
                               IMPACT_PROPAGATION_DESCRIPTION.format(public_id=public_id), affected,
                               MAXIMUM_IMPACT_PATHS)

        self.bulk_write(operations, collection=IsmsRiskAssessment.COLLECTION)

# -------------------------------------------------- HELPER METHODS -------------------------------------------------- #

    @staticmethod
    def max_impact_operations(
            risk_assessments: list[dict[str, Any]],
            basis_by_id: dict[int, float | None]) -> list[UpdateOne]:
        """
        One update per RiskAssessment setting the maximum impact of both matrices

        Args:
            risk_assessments (list[dict[str, Any]]): The RiskAssessments, each with its public_id and impact matrices
            basis_by_id (dict[int, float | None]): Every Impact's calculation_basis

        Returns:
            list[UpdateOne]: The operations, in the order of the RiskAssessments
        """
        operations: list[UpdateOne] = []

        for risk_assessment in risk_assessments:
            update_fields: dict[str, Any] = {}

            for matrix_key in RISK_CALCULATION_MATRIX_KEYS:
                matrix: dict[str, Any] = risk_assessment.get(matrix_key.value) or {}
                impacts: list[dict[str, Any]] = matrix.get(RiskCalculationKey.IMPACTS.value) or []
                max_id, max_value = recompute_max_impact(impacts, basis_by_id)
                update_fields[f'{matrix_key.value}.{RiskCalculationKey.MAXIMUM_IMPACT_ID.value}'] = max_id
                update_fields[f'{matrix_key.value}.{RiskCalculationKey.MAXIMUM_IMPACT_VALUE.value}'] = max_value

            operations.append(UpdateOne(
                {PUBLIC_ID_KEY: risk_assessment[PUBLIC_ID_KEY]},
                {'$set': update_fields},
            ))

        return operations


    @staticmethod
    def impact_reference_query(public_id: int) -> dict[str, Any]:
        """
        Builds the query matching every RiskAssessment whose before/after matrix references an Impact

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

        Raises:
            BaseManagerGetError: If the RiskAssessments could not be read

        Returns:
            bool: True if the Impact is used, False otherwise
        """
        return self.get_one_by(self.impact_reference_query(public_id), IsmsRiskAssessment.COLLECTION) is not None


    def delete_if_unused(self, public_id: int) -> bool:
        """
        Deletes an IsmsImpact that no IsmsRiskAssessment references

        Args:
            public_id (int): public_id of the IsmsImpact to delete

        Raises:
            ImpactManagerAssessmentUsageError: If an IsmsRiskAssessment references it
            ImpactManagerDeleteError: If the usage check, the delete or the restore of an Impact that gained a
                reference meanwhile fails

        Returns:
            bool: True if the IsmsImpact was deleted, False when it did not exist
        """
        return delete_unless_referenced(
            self,
            public_id,
            lambda: self.is_impact_used(public_id),
            ImpactManagerAssessmentUsageError,
            IMPACT_IN_USE_MESSAGE,
        )


    def impact_calculation_basis_exists(self, calculation_basis: float) -> bool:
        """
        Checks if a calculation_basis already exists for an IsmsImpact

        The readable half of the uniqueness rule; the unique index on calculation_basis is what holds under
        concurrency

        Args:
            calculation_basis (float): The calculation_basis which should be checked

        Raises:
            ImpactManagerCalculationBasisError: If checking calculation_basis failed (an ImpactManagerGetError)

        Returns:
            bool: True if calculation_basis exists, else false
        """
        try:
            return self.get_one_by({ImpactKey.CALCULATION_BASIS.value: calculation_basis}) is not None
        except BaseManagerGetError as err:
            LOGGER.error("[impact_calculation_basis_exists] %s: %s", type(err).__name__, err)
            raise ImpactManagerCalculationBasisError(err) from err
