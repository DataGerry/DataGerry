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

from cmdb.manager.generic_manager import GenericManager

from cmdb.models.isms_model import IsmsLikelihood, IsmsRiskAssessment

from cmdb.errors.manager.likelihood_manager import LIKELIHOOD_MANAGER_ERRORS, LikelihoodManagerGetError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                               LikelihoodManager - CLASS                                              #
# -------------------------------------------------------------------------------------------------------------------- #
class LikelihoodManager(GenericManager):
    """
    The LikelihoodManager manages the interaction between IsmsLikelihood and the database

    Extends: GenericManager
    """
    def __init__(self, dbm: MongoDatabaseManager, database: str = None):
        super().__init__(dbm, IsmsLikelihood, LIKELIHOOD_MANAGER_ERRORS, database)

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

    def update_with_follow_up(self, public_id: int, new_data: dict[str, Any]) -> None:
        """
        Updates an IsmsLikelihood and propagates the new calculation_basis to the likelihood_value
        of every IsmsRiskAssessment referencing it.

        The Likelihood is updated first, then a single aggregation-pipeline update rewrites the
        likelihood_value in the before / after matrices where the likelihood_id matches.

        Args:
            public_id (int): public_id of the IsmsLikelihood which is changed
            new_data (dict[str, Any]): new data for the Likelihood
        """
        self.update_item(public_id, IsmsLikelihood.from_data(new_data))

        criteria = {
            '$or': [
                {'risk_calculation_before.likelihood_id': public_id},
                {'risk_calculation_after.likelihood_id': public_id}
            ]
        }

        update_data = [
            {'$set': {
                'risk_calculation_before.likelihood_value': {
                    '$cond': [
                        {'$eq': ['$risk_calculation_before.likelihood_id', public_id]},
                        new_data['calculation_basis'],
                        '$risk_calculation_before.likelihood_value'
                    ]
                },
                'risk_calculation_after.likelihood_value': {
                    '$cond': [
                        {'$eq': ['$risk_calculation_after.likelihood_id', public_id]},
                        new_data['calculation_basis'],
                        '$risk_calculation_after.likelihood_value'
                    ]
                }
            }}
        ]

        self.dbm.update_many(IsmsRiskAssessment.COLLECTION, self.db_name, criteria, update_data, plain=True)

# -------------------------------------------------- HELPER METHODS -------------------------------------------------- #

    def is_likelihood_used(self, public_id: int) -> bool:
        """
        Checks if the IsmsLikelihood is used by any IsmsRiskAssessment

        Args:
            public_id (int): public_id of the IsmsLikelihood

        Returns:
            bool: True if it is used, else False
        """
        query = {
            '$or': [
                {'risk_calculation_before.likelihood_id': public_id},
                {'risk_calculation_after.likelihood_id': public_id}
            ]
        }

        return self.get_one_by(query, IsmsRiskAssessment.COLLECTION) is not None


    def likelihood_calculation_basis_exists(self, calculation_basis: float) -> bool:
        """
        Checks if a calculation_basis already exists for an IsmsLikelihood

        Args:
            calculation_basis (float): The calculation_basis which should be checked

        Raises:
            LikelihoodManagerGetError: If checking calculation_basis failed

        Returns:
            bool: True if calculation_basis exists, else false
        """
        try:
            result = self.get_one_by({'calculation_basis': calculation_basis})

            return bool(result)
        except Exception as err:
            LOGGER.error("[likelihood_calculation_basis_exists] Exception: %s. Type: %s", err, type(err))
            raise LikelihoodManagerGetError(str(err)) from err
