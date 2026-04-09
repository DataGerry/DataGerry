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
Implementation of IsmsLikelihood in DataGerry - ISMS
"""
from logging import Logger, getLogger

from cmdb.models.cmdb_dao import CmdbDAO

from cmdb.errors.models.isms_likelihood import (
    IsmsLikelihoodInitError,
    IsmsLikelihoodInitFromDataError,
    IsmsLikelihoodToJsonError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                IsmsLikelihood - CLASS                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class IsmsLikelihood(CmdbDAO):
    """
    Implementation of IsmsLikelihood which represents the likelihood of events of the ISMS general configuration

    Extends: CmdbDAO
    """
    COLLECTION = "isms.likelihood"
    MODEL = 'Likelihood'
    # pylint: disable=R0801
    SCHEMA: dict = {
        'public_id': {
            'type': 'integer',
            'min': 1,
        },
        'name': {
            'type': 'string',
            'required': True,
            'empty': False
        },
        'calculation_basis': {
            'type': 'float',
            'min': 1e-9,
            'required': True,
            'empty': False
        },
        'description': {
            'type': 'string',
        }
    }


    def __init__(self, public_id: int, name: str, calculation_basis: str, description: str):
        """
        Initialises an IsmsLikelihood

        Args:
            public_id (int): public_id of the IsmsLikelihood
            name (str): The name of the IsmsLikelihood
            calculation_basis (float): The calculation_basis of the IsmsLikelihood
            description (str): The description of the IsmsLikelihood

        Raises:
            IsmsLikelihoodInitError: When the IsmsLikelihood could not be initialised
        """
        try:
            self.name = name
            self.calculation_basis = calculation_basis
            self.description = description

            super().__init__(public_id=public_id)
        except Exception as err:
            raise IsmsLikelihoodInitError(err) from err

# -------------------------------------------------- CLASS FUNCTIONS ------------------------------------------------- #

    @classmethod
    def from_data(cls, data: dict) -> "IsmsLikelihood":
        """
        Initialises a IsmsLikelihood from a dict

        Args:
            data (dict): Data with which the IsmsLikelihood should be initialised

        Raises:
            IsmsLikelihoodInitFromDataError: If the initialisation with the given data fails

        Returns:
            IsmsLikelihood: IsmsLikelihood with the given data
        """
        try:
            return cls(
                public_id = data.get('public_id'),
                name = data.get('name'),
                calculation_basis = data.get('calculation_basis'),
                description = data.get('description'),
            )
        except Exception as err:
            raise IsmsLikelihoodInitFromDataError(err) from err

    @classmethod
    def to_json(cls, instance: "IsmsLikelihood") -> dict:
        """
        Converts a IsmsLikelihood into a json compatible dict

        Args:
            instance (IsmsLikelihood): The IsmsLikelihood which should be converted

        Raises:
            IsmsLikelihoodToJsonError: If the IsmsLikelihood could not be converted to a json compatible dict

        Returns:
            dict: Json compatible dict of the IsmsLikelihood values
        """
        try:
            return {
                'public_id': instance.get_public_id(),
                'name': instance.name,
                'calculation_basis': instance.calculation_basis,
                'description': instance.description,
            }
        except Exception as err:
            raise IsmsLikelihoodToJsonError(err) from err
