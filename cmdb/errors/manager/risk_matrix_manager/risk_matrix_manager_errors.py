# DataGerry - OpenSource Enterprise CMDB
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
This module contains the classes of all RiskMatrixManager errors
"""
# -------------------------------------------------------------------------------------------------------------------- #

class RiskMatrixManagerError(Exception):
    """
    Raised to catch all RiskMatrixManager related errors
    """
    def __init__(self, err: str) -> None:
        """
        Raised to catch all RiskMatrixManager related errors
        """
        super().__init__(err)

# ------------------------------------------ RiskMatrixManager - ERRORS ------------------------------------------ #

class RiskMatrixManagerInitError(RiskMatrixManagerError):
    """
    Raised when RiskMatrixManager could not be initialised
    """


class RiskMatrixManagerInsertError(RiskMatrixManagerError):
    """
    Raised when RiskMatrixManager could not insert an IsmsRiskMatrix
    """


class RiskMatrixManagerGetError(RiskMatrixManagerError):
    """
    Raised when RiskMatrixManager could not retrieve an IsmsRiskMatrix
    """


class RiskMatrixManagerUpdateError(RiskMatrixManagerError):
    """
    Raised when RiskMatrixManager could not update an IsmsRiskMatrix
    """


class RiskMatrixManagerDeleteError(RiskMatrixManagerError):
    """
    Raised when RiskMatrixManager could not delete an IsmsRiskMatrix
    """


class RiskMatrixManagerIterationError(RiskMatrixManagerError):
    """
    Raised when RiskMatrixManager could not iterate over IsmsRiskMatrices
    """
