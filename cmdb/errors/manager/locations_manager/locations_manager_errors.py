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
This module contains the classes of all LocationsManager errors
"""
# -------------------------------------------------------------------------------------------------------------------- #

class LocationsManagerError(Exception):
    """
    Raised to catch all LocationsManager related errors
    """
    def __init__(self, err: str) -> None:
        """
        Raised to catch all LocationsManager related errors
        """
        super().__init__(err)

# --------------------------------------------- LocationsManager - ERRORS -------------------------------------------- #

class LocationsManagerInitError(LocationsManagerError):
    """
    Raised when LocationsManager could not be initialised
    """


class LocationsManagerInsertError(LocationsManagerError):
    """
    Raised when LocationsManager could not insert an CmdbLocation
    """


class LocationsManagerGetError(LocationsManagerError):
    """
    Raised when LocationsManager could not retrieve an CmdbLocation
    """


class LocationsManagerUpdateError(LocationsManagerError):
    """
    Raised when LocationsManager could not update an CmdbLocation
    """


class LocationsManagerDeleteError(LocationsManagerError):
    """
    Raised when LocationsManager could not delete an CmdbLocation
    """


class LocationsManagerIterationError(LocationsManagerError):
    """
    Raised when LocationsManager could not iterate over CmdbLocations
    """


class LocationsManagerChildrenError(LocationsManagerError):
    """
    Raised when LocationsManager failed to get all child CmdbLocations
    """
