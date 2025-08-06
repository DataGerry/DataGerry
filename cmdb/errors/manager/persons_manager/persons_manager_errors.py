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
This module contains the classes of all PersonsManager errors
"""
# -------------------------------------------------------------------------------------------------------------------- #

class PersonsManagerError(Exception):
    """
    Raised to catch all PersonsManager related errors
    """
    def __init__(self, err: str) -> None:
        """
        Raised to catch all PersonsManager related errors
        """
        super().__init__(err)

# ----------------------------------------- PersonsManager - ERRORS ---------------------------------------- #

class PersonsManagerInitError(PersonsManagerError):
    """
    Raised when PersonsManager could not be initialised
    """


class PersonsManagerInsertError(PersonsManagerError):
    """
    Raised when PersonsManager could not insert an CmdbPerson
    """


class PersonsManagerGetError(PersonsManagerError):
    """
    Raised when PersonsManager could not retrieve an CmdbPerson
    """


class PersonsManagerUpdateError(PersonsManagerError):
    """
    Raised when PersonsManager could not update an CmdbPerson
    """


class PersonsManagerDeleteError(PersonsManagerError):
    """
    Raised when PersonsManager could not delete an CmdbPerson
    """


class PersonsManagerIterationError(PersonsManagerError):
    """
    Raised when PersonsManager could not iterate over CmdbPersons
    """
