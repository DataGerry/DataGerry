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
This module contains the classes of all PersonGroupsManager errors
"""
# -------------------------------------------------------------------------------------------------------------------- #

class PersonGroupsManagerError(Exception):
    """
    Raised to catch all PersonGroupsManager related errors
    """
    def __init__(self, err: str) -> None:
        """
        Raised to catch all PersonGroupsManager related errors
        """
        super().__init__(err)

# ------------------------------------------- PersonGroupsManager - ERRORS ------------------------------------------- #

class PersonGroupsManagerInitError(PersonGroupsManagerError):
    """
    Raised when PersonGroupsManager could not be initialised
    """


class PersonGroupsManagerInsertError(PersonGroupsManagerError):
    """
    Raised when PersonGroupsManager could not insert an CmdbPersonGroup
    """


class PersonGroupsManagerGetError(PersonGroupsManagerError):
    """
    Raised when PersonGroupsManager could not retrieve an CmdbPersonGroup
    """


class PersonGroupsManagerUpdateError(PersonGroupsManagerError):
    """
    Raised when PersonGroupsManager could not update an CmdbPersonGroup
    """


class PersonGroupsManagerDeleteError(PersonGroupsManagerError):
    """
    Raised when PersonGroupsManager could not delete an CmdbPersonGroup
    """


class PersonGroupsManagerIterationError(PersonGroupsManagerError):
    """
    Raised when PersonGroupsManager could not iterate over CmdbPersonGroups
    """
