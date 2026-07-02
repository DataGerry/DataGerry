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
Implementation of IsmsRiskMatrix in DataGerry - ISMS
"""
from logging import Logger, getLogger

from cmdb.models.cmdb_dao import CmdbDAO

from cmdb.class_schema.isms_model.isms_risk_matrix_schema import get_isms_risk_matrix_schema

from cmdb.errors.models.isms_risk_matrix import (
    IsmsRiskMatrixInitError,
    IsmsRiskMatrixInitFromDataError,
    IsmsRiskMatrixToJsonError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                IsmsRiskMatrix - CLASS                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class IsmsRiskMatrix(CmdbDAO):
    """
    Implementation of IsmsRiskMatrix.

    The matrix cells are build from bottom left line by line

    Extends: CmdbDAO
    """
    COLLECTION = "isms.riskMatrix"

    SCHEMA: dict = get_isms_risk_matrix_schema()


    def __init__(self, public_id: int, risk_matrix: list, matrix_unit: str = None):
        """
        Initialises an IsmsRiskMatrix

        Args:
            public_id (int): public_id of the IsmsRiskMatrix
            risk_matrix (list): The data of the IsmsRiskMatrix
            matrix_unit (str, optional): The optional unit value of the IsmsRiskMatrix

        Raises:
            IsmsRiskMatrixInitError: When the IsmsRiskMatrix could not be initialised
        """
        try:
            self.risk_matrix = risk_matrix
            self.matrix_unit = matrix_unit

            super().__init__(public_id=public_id)
        except Exception as err:
            raise IsmsRiskMatrixInitError(err) from err

# -------------------------------------------------- CLASS FUNCTIONS ------------------------------------------------- #

    @classmethod
    def from_data(cls, data: dict) -> "IsmsRiskMatrix":
        """
        Initialises a IsmsRiskMatrix from a dict

        Args:
            data (dict): Data with which the IsmsRiskMatrix should be initialised

        Raises:
            IsmsRiskMatrixInitFromDataError: If the initialisation with the given data fails

        Returns:
            IsmsRiskMatrix: IsmsRiskMatrix with the given data
        """
        try:
            return cls(
                public_id = data.get('public_id'),
                risk_matrix = data.get('risk_matrix'),
                matrix_unit = data.get('matrix_unit'),
            )
        except Exception as err:
            raise IsmsRiskMatrixInitFromDataError(err) from err


    @classmethod
    def to_json(cls, instance: "IsmsRiskMatrix") -> dict:
        """
        Converts a IsmsRiskMatrix into a json compatible dict

        Args:
            instance (IsmsRiskMatrix): The IsmsRiskMatrix which should be converted

        Raises:
            IsmsRiskMatrixToJsonError: If the IsmsRiskMatrix could not be converted to a json compatible dict

        Returns:
            dict: Json compatible dict of the IsmsRiskMatrix values
        """
        try:
            return {
                'public_id': instance.get_public_id(),
                'risk_matrix': instance.risk_matrix,
                'matrix_unit': instance.matrix_unit,
            }
        except Exception as err:
            raise IsmsRiskMatrixToJsonError(err) from err
