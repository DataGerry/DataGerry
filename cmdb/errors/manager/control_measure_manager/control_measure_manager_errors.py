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
This module contains the classes of all ControlMeasureManager errors
"""
# -------------------------------------------------------------------------------------------------------------------- #

class ControlMeasureManagerError(Exception):
    """
    Raised to catch all ControlMeasureManager related errors
    """
    def __init__(self, err: str) -> None:
        """
        Raised to catch all ControlMeasureManager related errors
        """
        super().__init__(err)

# ------------------------------------------ ControlMeasureManager - ERRORS ------------------------------------------ #

class ControlMeasureManagerInitError(ControlMeasureManagerError):
    """
    Raised when ControlMeasureManager could not be initialised
    """


class ControlMeasureManagerInsertError(ControlMeasureManagerError):
    """
    Raised when ControlMeasureManager could not insert an IsmsControlMeasure
    """


class ControlMeasureManagerGetError(ControlMeasureManagerError):
    """
    Raised when ControlMeasureManager could not retrieve an IsmsControlMeasure
    """


class ControlMeasureManagerUpdateError(ControlMeasureManagerError):
    """
    Raised when ControlMeasureManager could not update an IsmsControlMeasure
    """


class ControlMeasureManagerDeleteError(ControlMeasureManagerError):
    """
    Raised when ControlMeasureManager could not delete an IsmsControlMeasure
    """


class ControlMeasureManagerIterationError(ControlMeasureManagerError):
    """
    Raised when ControlMeasureManager could not iterate over IsmsControlMeasures
    """
