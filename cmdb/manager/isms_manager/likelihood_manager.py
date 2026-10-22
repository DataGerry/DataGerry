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
This module contains the implementation of the LikelihoodManager
"""
from logging import Logger, getLogger
from typing import Any

from cmdb.database import MongoDatabaseManager
from cmdb.framework.write_ledger import WriteLedger

from cmdb.manager.generic_manager import GenericManager
from cmdb.manager.isms_manager.isms_manager_constants import (
    LIKELIHOOD_IN_USE_MESSAGE,
    LIKELIHOOD_PROPAGATION_DESCRIPTION,
)
from cmdb.manager.isms_manager.isms_manager_helper import (
    delete_unless_referenced,
    record_follow_up_write,
    snapshot_projection,
)
from cmdb.utils import Builder

from cmdb.models.isms_model import IsmsLikelihood, IsmsRiskAssessment
from cmdb.models.isms_model.risk_calculation_constants import RiskCalculationKey, RISK_CALCULATION_MATRIX_KEYS
from cmdb.models.isms_model.isms_likelihood_constants import LikelihoodKey

from cmdb.errors.models.isms_likelihood import IsmsLikelihoodInitFromDataError
from cmdb.errors.manager import BaseManagerGetError, BaseManagerUpdateError
from cmdb.errors.manager.likelihood_manager import (
    LIKELIHOOD_MANAGER_ERRORS,
    LikelihoodManagerAssessmentUsageError,
    LikelihoodManagerCalculationBasisError,
    LikelihoodManagerUpdateError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# The dotted paths of a RiskAssessment that the propagation of a Likelihood's calculation_basis rewrites
LIKELIHOOD_VALUE_PATHS: list[str] = [
    f'{matrix.value}.{RiskCalculationKey.LIKELIHOOD_VALUE.value}' for matrix in RISK_CALCULATION_MATRIX_KEYS
]

# -------------------------------------------------------------------------------------------------------------------- #
#                                               LikelihoodManager - CLASS                                              #
# -------------------------------------------------------------------------------------------------------------------- #
class LikelihoodManager(GenericManager):
    """
    The LikelihoodManager manages the interaction between IsmsLikelihood and the database

    Extends: GenericManager
    """
    def __init__(self, dbm: MongoDatabaseManager, database: str | None = None) -> None:
        """
        Initialises the LikelihoodManager

        Args:
            dbm (MongoDatabaseManager): Database interaction manager
            database (str | None): Target database name, used in cloud mode. Defaults to None
        """
        super().__init__(dbm, IsmsLikelihood, LIKELIHOOD_MANAGER_ERRORS, database)

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

    def update_with_follow_up(self, public_id: int, new_data: dict[str, Any], ledger: WriteLedger) -> dict[str, Any]:
        """
        Updates an IsmsLikelihood and propagates the new calculation_basis to the likelihood_value of every
        IsmsRiskAssessment referencing it

        The Likelihood is updated first, then a single aggregation-pipeline update rewrites the likelihood_value
        in the before / after matrices where the likelihood_id matches. Both writes are recorded in ``ledger``:
        the Likelihood with its stored snapshot, the propagation with the likelihood values it is about to
        overwrite

        Args:
            public_id (int): public_id of the IsmsLikelihood which is changed
            new_data (dict[str, Any]): new data for the Likelihood
            ledger (WriteLedger): The request's ledger, which the two writes are recorded in

        Raises:
            LikelihoodManagerGetError: If the stored Likelihood could not be read
            LikelihoodManagerUpdateError: If the Likelihood does not exist or cannot be built from the data, or if
                the update, the read of the affected RiskAssessments or the propagation failed

        Returns:
            dict[str, Any]: The Likelihood document as stored
        """
        prior: dict[str, Any] | None = self.get_item(public_id, as_dict=True)

        if prior is None:
            raise LikelihoodManagerUpdateError(f"The Likelihood with ID: {public_id} does not exist!")

        try:
            likelihood: IsmsLikelihood = IsmsLikelihood.from_data(new_data)
        except IsmsLikelihoodInitFromDataError as err:
            raise LikelihoodManagerUpdateError(err) from err

        self.update_item(public_id, likelihood)
        ledger.updated(self, public_id, prior)

        try:
            self._propagate_calculation_basis(public_id, new_data[LikelihoodKey.CALCULATION_BASIS.value], ledger)
        except (BaseManagerGetError, BaseManagerUpdateError) as err:
            LOGGER.error("[update_with_follow_up] %s: %s", type(err).__name__, err)
            raise LikelihoodManagerUpdateError(err) from err

        return IsmsLikelihood.to_json(likelihood)


    def _propagate_calculation_basis(self, public_id: int, calculation_basis: float, ledger: WriteLedger) -> None:
        """
        Rewrites the likelihood_value of every RiskAssessment matrix that names the Likelihood, in one update

        The affected RiskAssessments are read first, projected to the values about to be overwritten, and
        recorded in the ledger before the update runs

        Args:
            public_id (int): The public_id of the updated Likelihood
            calculation_basis (float): Its new calculation_basis
            ledger (WriteLedger): The request's ledger; the write is recorded before it runs

        Raises:
            BaseManagerGetError: If the RiskAssessments could not be read
            BaseManagerUpdateError: If the update failed
        """
        criteria: dict[str, Any] = self.likelihood_reference_query(public_id)

        affected: list[dict[str, Any]] = self.get_many_from_other_collection(
            IsmsRiskAssessment.COLLECTION,
            projection=snapshot_projection(LIKELIHOOD_VALUE_PATHS),
            criteria=criteria,
        )

        if not affected:
            return

        record_follow_up_write(ledger, self, IsmsRiskAssessment.COLLECTION,
                               LIKELIHOOD_PROPAGATION_DESCRIPTION.format(public_id=public_id), affected,
                               LIKELIHOOD_VALUE_PATHS)

        self.update_many_raw(
            criteria,
            self.likelihood_value_pipeline(public_id, calculation_basis),
            collection=IsmsRiskAssessment.COLLECTION,
        )

# -------------------------------------------------- HELPER METHODS -------------------------------------------------- #

    @staticmethod
    def likelihood_reference_query(public_id: int) -> dict[str, Any]:
        """
        Builds the query matching every RiskAssessment whose before/after matrix names a Likelihood

        Args:
            public_id (int): The public_id of the Likelihood

        Returns:
            dict[str, Any]: A Mongo `$or` filter over both risk-calculation matrices
        """
        return {
            '$or': [
                {f'{matrix.value}.{RiskCalculationKey.LIKELIHOOD_ID.value}': public_id}
                for matrix in RISK_CALCULATION_MATRIX_KEYS
            ]
        }


    @staticmethod
    def likelihood_value_pipeline(public_id: int, calculation_basis: float) -> list[dict[str, Any]]:
        """
        The update pipeline setting likelihood_value to the new basis in each matrix that names the Likelihood

        A matrix naming another Likelihood keeps its value

        Args:
            public_id (int): The public_id of the Likelihood
            calculation_basis (float): Its new calculation_basis

        Returns:
            list[dict[str, Any]]: The one-stage update pipeline
        """
        return [
            Builder.set_({
                f'{matrix.value}.{RiskCalculationKey.LIKELIHOOD_VALUE.value}': {
                    '$cond': [
                        {'$eq': [f'${matrix.value}.{RiskCalculationKey.LIKELIHOOD_ID.value}', public_id]},
                        calculation_basis,
                        f'${matrix.value}.{RiskCalculationKey.LIKELIHOOD_VALUE.value}',
                    ]
                }
                for matrix in RISK_CALCULATION_MATRIX_KEYS
            })
        ]


    def is_likelihood_used(self, public_id: int) -> bool:
        """
        Checks if the IsmsLikelihood is used by any IsmsRiskAssessment

        Args:
            public_id (int): public_id of the IsmsLikelihood

        Raises:
            BaseManagerGetError: If the RiskAssessments could not be read

        Returns:
            bool: True if it is used, else False
        """
        return self.get_one_by(self.likelihood_reference_query(public_id), IsmsRiskAssessment.COLLECTION) is not None


    def delete_if_unused(self, public_id: int) -> bool:
        """
        Deletes an IsmsLikelihood that no IsmsRiskAssessment references

        Args:
            public_id (int): public_id of the IsmsLikelihood to delete

        Raises:
            LikelihoodManagerAssessmentUsageError: If an IsmsRiskAssessment references it
            LikelihoodManagerDeleteError: If the usage check, the delete or the restore of a Likelihood that gained
                a reference meanwhile fails

        Returns:
            bool: True if the IsmsLikelihood was deleted, False when it did not exist
        """
        return delete_unless_referenced(
            self,
            public_id,
            lambda: self.is_likelihood_used(public_id),
            LikelihoodManagerAssessmentUsageError,
            LIKELIHOOD_IN_USE_MESSAGE,
        )


    def likelihood_calculation_basis_exists(self, calculation_basis: float) -> bool:
        """
        Checks if a calculation_basis already exists for an IsmsLikelihood

        The readable half of the uniqueness rule; the unique index on calculation_basis is what holds under
        concurrency

        Args:
            calculation_basis (float): The calculation_basis which should be checked

        Raises:
            LikelihoodManagerCalculationBasisError: If checking calculation_basis failed (a LikelihoodManagerGetError)

        Returns:
            bool: True if calculation_basis exists, else false
        """
        try:
            return self.get_one_by({LikelihoodKey.CALCULATION_BASIS.value: calculation_basis}) is not None
        except BaseManagerGetError as err:
            LOGGER.error("[likelihood_calculation_basis_exists] %s: %s", type(err).__name__, err)
            raise LikelihoodManagerCalculationBasisError(err) from err
