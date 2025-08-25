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
This module contains the classes of all RiskAssessmentManager errors
"""
# -------------------------------------------------------------------------------------------------------------------- #

class RiskAssessmentManagerError(Exception):
    """
    Raised to catch all RiskAssessmentManager related errors
    """
    def __init__(self, err: str) -> None:
        """
        Raised to catch all RiskAssessmentManager related errors
        """
        super().__init__(err)

# ------------------------------------------ RiskAssessmentManager - ERRORS ------------------------------------------ #

class RiskAssessmentManagerInitError(RiskAssessmentManagerError):
    """
    Raised when RiskAssessmentManager could not be initialised
    """


class RiskAssessmentManagerInsertError(RiskAssessmentManagerError):
    """
    Raised when RiskAssessmentManager could not insert an IsmsRiskAssessment
    """


class RiskAssessmentManagerGetError(RiskAssessmentManagerError):
    """
    Raised when RiskAssessmentManager could not retrieve an IsmsRiskAssessment
    """


class RiskAssessmentManagerUpdateError(RiskAssessmentManagerError):
    """
    Raised when RiskAssessmentManager could not update an IsmsRiskAssessment
    """


class RiskAssessmentManagerDeleteError(RiskAssessmentManagerError):
    """
    Raised when RiskAssessmentManager could not delete an IsmsRiskAssessment
    """


class RiskAssessmentManagerIterationError(RiskAssessmentManagerError):
    """
    Raised when RiskAssessmentManager could not iterate over IsmsRiskAssessments
    """
