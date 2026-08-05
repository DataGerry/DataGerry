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
This module contains the classes of all ProtectionGoalManager errors
"""
# -------------------------------------------------------------------------------------------------------------------- #

class ProtectionGoalManagerError(Exception):
    """
    Raised to catch all ProtectionGoalManager related errors
    """
    def __init__(self, err: str) -> None:
        """
        Raised to catch all ProtectionGoalManager related errors
        """
        super().__init__(err)

# ------------------------------------------ ProtectionGoalManager - ERRORS ------------------------------------------ #

class ProtectionGoalManagerInitError(ProtectionGoalManagerError):
    """
    Raised when ProtectionGoalManager could not be initialised
    """


class ProtectionGoalManagerInsertError(ProtectionGoalManagerError):
    """
    Raised when ProtectionGoalManager could not insert an IsmsProtectionGoal
    """


class ProtectionGoalManagerGetError(ProtectionGoalManagerError):
    """
    Raised when ProtectionGoalManager could not retrieve an IsmsProtectionGoal
    """


class ProtectionGoalManagerUpdateError(ProtectionGoalManagerError):
    """
    Raised when ProtectionGoalManager could not update an IsmsProtectionGoal
    """


class ProtectionGoalManagerDeleteError(ProtectionGoalManagerError):
    """
    Raised when ProtectionGoalManager could not delete an IsmsProtectionGoal
    """


class ProtectionGoalManagerIterationError(ProtectionGoalManagerError):
    """
    Raised when ProtectionGoalManager could not iterate over IsmsProtectionGoals
    """


class ProtectionGoalManagerRiskUsageError(ProtectionGoalManagerError):
    """
    Raised when ProtectionGoalManager could not delete an IsmsProtectionGoal because an IsmsRisk is using it
    """
