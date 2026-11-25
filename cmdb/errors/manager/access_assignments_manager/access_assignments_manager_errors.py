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
This module contains the classes of all AccessAssignmentsManager errors
"""
# -------------------------------------------------------------------------------------------------------------------- #

class AccessAssignmentsManagerError(Exception):
    """
    Raised to catch all AccessAssignmentsManager related errors
    """
    def __init__(self, err: str | Exception) -> None:
        """
        Raised to catch all AccessAssignmentsManager related errors

        Takes the wrapped exception itself as readily as a message: str() reads the same either way,
        but args[0] then carries the error being wrapped, which a caller can branch on

        Args:
            err (str | Exception): The message, or the error being wrapped
        """
        super().__init__(err)

# ---------------------------------------- AccessAssignmentsManager - ERRORS ----------------------------------------- #

class AccessAssignmentsManagerInsertError(AccessAssignmentsManagerError):
    """
    Raised when AccessAssignmentsManager could not insert a CmdbAccessAssignment
    """


class AccessAssignmentsManagerGetError(AccessAssignmentsManagerError):
    """
    Raised when AccessAssignmentsManager could not retrieve a CmdbAccessAssignment
    """


class AccessAssignmentsManagerUpdateError(AccessAssignmentsManagerError):
    """
    Raised when AccessAssignmentsManager could not update a CmdbAccessAssignment
    """


class AccessAssignmentsManagerDeleteError(AccessAssignmentsManagerError):
    """
    Raised when AccessAssignmentsManager could not delete a CmdbAccessAssignment
    """


class AccessAssignmentsManagerIterationError(AccessAssignmentsManagerError):
    """
    Raised when AccessAssignmentsManager could not iterate over CmdbAccessAssignments
    """
