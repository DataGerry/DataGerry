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
This module contains the classes of all CiExplorerProfileManager errors
"""
# -------------------------------------------------------------------------------------------------------------------- #

class CiExplorerProfileManagerError(Exception):
    """
    Raised to catch all CiExplorerProfileManager related errors
    """
    def __init__(self, err: str) -> None:
        """
        Raised to catch all CiExplorerProfileManager related errors
        """
        super().__init__(err)

# ----------------------------------------- CiExplorerProfileManager - ERRORS ---------------------------------------- #

class CiExplorerProfileManagerInitError(CiExplorerProfileManagerError):
    """
    Raised when CiExplorerProfileManager could not be initialised
    """


class CiExplorerProfileManagerInsertError(CiExplorerProfileManagerError):
    """
    Raised when CiExplorerProfileManager could not insert a CiExplorerProfile
    """


class CiExplorerProfileManagerGetError(CiExplorerProfileManagerError):
    """
    Raised when CiExplorerProfileManager could not retrieve a CiExplorerProfile
    """


class CiExplorerProfileManagerUpdateError(CiExplorerProfileManagerError):
    """
    Raised when CiExplorerProfileManager could not update a CiExplorerProfile
    """


class CiExplorerProfileManagerDeleteError(CiExplorerProfileManagerError):
    """
    Raised when CiExplorerProfileManager could not delete a CiExplorerProfile
    """


class CiExplorerProfileManagerIterationError(CiExplorerProfileManagerError):
    """
    Raised when CiExplorerProfileManager could not iterate over CiExplorerProfiles
    """
