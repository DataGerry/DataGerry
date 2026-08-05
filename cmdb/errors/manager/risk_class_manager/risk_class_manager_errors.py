# DataGerry - OpenSource Enterprise CMDB
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
This module contains the classes of all RiskClassManager errors
"""
# -------------------------------------------------------------------------------------------------------------------- #

class RiskClassManagerError(Exception):
    """
    Raised to catch all RiskClassManager related errors
    """
    def __init__(self, err: str) -> None:
        """
        Raised to catch all RiskClassManager related errors
        """
        super().__init__(err)

# --------------------------------------------- RiskClassManager - ERRORS -------------------------------------------- #

class RiskClassManagerInitError(RiskClassManagerError):
    """
    Raised when RiskClassManager could not be initialised
    """


class RiskClassManagerInsertError(RiskClassManagerError):
    """
    Raised when RiskClassManager could not insert an IsmsRiskClass
    """


class RiskClassManagerGetError(RiskClassManagerError):
    """
    Raised when RiskClassManager could not retrieve an IsmsRiskClass
    """


class RiskClassManagerUpdateError(RiskClassManagerError):
    """
    Raised when RiskClassManager could not update an IsmsRiskClass
    """


class RiskClassManagerDeleteError(RiskClassManagerError):
    """
    Raised when RiskClassManager could not delete an IsmsRiskClass
    """


class RiskClassManagerIterationError(RiskClassManagerError):
    """
    Raised when RiskClassManager could not iterate over IsmsRiskClasses
    """
