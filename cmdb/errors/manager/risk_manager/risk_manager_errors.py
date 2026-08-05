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
This module contains the classes of all RiskManager errors
"""
# -------------------------------------------------------------------------------------------------------------------- #

class RiskManagerError(Exception):
    """
    Raised to catch all RiskManager related errors
    """
    def __init__(self, err: str) -> None:
        """
        Raised to catch all RiskManager related errors
        """
        super().__init__(err)

# ---------------------------------------------- RiskManager - ERRORS ---------------------------------------------- #

class RiskManagerInitError(RiskManagerError):
    """
    Raised when RiskManager could not be initialised
    """


class RiskManagerInsertError(RiskManagerError):
    """
    Raised when RiskManager could not insert an IsmsRisk
    """


class RiskManagerGetError(RiskManagerError):
    """
    Raised when RiskManager could not retrieve an IsmsRisk
    """


class RiskManagerUpdateError(RiskManagerError):
    """
    Raised when RiskManager could not update an IsmsRisk
    """


class RiskManagerDeleteError(RiskManagerError):
    """
    Raised when RiskManager could not delete an IsmsRisk
    """


class RiskManagerIterationError(RiskManagerError):
    """
    Raised when RiskManager could not iterate over IsmsRisks
    """
