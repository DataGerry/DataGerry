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
This module contains the classes of all ReportsManager errors
"""
# -------------------------------------------------------------------------------------------------------------------- #

class ReportsManagerError(Exception):
    """
    Raised to catch all ReportsManager related errors
    """
    def __init__(self, err: str) -> None:
        """
        Raised to catch all ReportsManager related errors
        """
        super().__init__(err)

# ------------------------------------------ ReportsManager - ERRORS ------------------------------------------ #

class ReportsManagerInitError(ReportsManagerError):
    """
    Raised when ReportsManager could not be initialised
    """


class ReportsManagerInsertError(ReportsManagerError):
    """
    Raised when ReportsManager could not insert an CmdbReport
    """


class ReportsManagerGetError(ReportsManagerError):
    """
    Raised when ReportsManager could not retrieve an CmdbReport
    """


class ReportsManagerUpdateError(ReportsManagerError):
    """
    Raised when ReportsManager could not update an CmdbReport
    """


class ReportsManagerDeleteError(ReportsManagerError):
    """
    Raised when ReportsManager could not delete an CmdbReport
    """


class ReportsManagerIterationError(ReportsManagerError):
    """
    Raised when ReportsManager could not iterate over CmdbReports
    """
