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
This module contains the classes of all ScopeRolesManager errors
"""
# -------------------------------------------------------------------------------------------------------------------- #

class ScopeRolesManagerError(Exception):
    """
    Raised to catch all ScopeRolesManager related errors
    """
    def __init__(self, err: str | Exception) -> None:
        """
        Raised to catch all ScopeRolesManager related errors

        Takes the wrapped exception itself as readily as a message: str() reads the same either way,
        but args[0] then carries the error being wrapped, which a caller can branch on

        Args:
            err (str | Exception): The message, or the error being wrapped
        """
        super().__init__(err)

# -------------------------------------------- ScopeRolesManager - ERRORS -------------------------------------------- #

class ScopeRolesManagerInsertError(ScopeRolesManagerError):
    """
    Raised when ScopeRolesManager could not insert a CmdbScopeRole
    """


class ScopeRolesManagerGetError(ScopeRolesManagerError):
    """
    Raised when ScopeRolesManager could not retrieve a CmdbScopeRole
    """


class ScopeRolesManagerUpdateError(ScopeRolesManagerError):
    """
    Raised when ScopeRolesManager could not update a CmdbScopeRole
    """


class ScopeRolesManagerDeleteError(ScopeRolesManagerError):
    """
    Raised when ScopeRolesManager could not delete a CmdbScopeRole
    """


class ScopeRolesManagerIterationError(ScopeRolesManagerError):
    """
    Raised when ScopeRolesManager could not iterate over CmdbScopeRoles
    """
