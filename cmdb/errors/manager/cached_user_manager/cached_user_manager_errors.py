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
This module contains the classes of all CachedUserManager errors
"""
# -------------------------------------------------------------------------------------------------------------------- #

class CachedUserManagerError(Exception):
    """
    Raised to catch all CachedUserManager related errors
    """
    def __init__(self, err: str) -> None:
        """
        Raised to catch all CachedUserManager related errors
        """
        super().__init__(err)

# -------------------------------------------- CachedUserManager - ERRORS -------------------------------------------- #

class CachedUserManagerInitError(CachedUserManagerError):
    """
    Raised when CachedUserManager could not be initialised
    """


class CachedUserManagerInsertError(CachedUserManagerError):
    """
    Raised when CachedUserManager could not insert an CmdbCachedUser
    """


class CachedUserManagerGetError(CachedUserManagerError):
    """
    Raised when CachedUserManager could not retrieve an CmdbCachedUser
    """


class CachedUserManagerUpdateError(CachedUserManagerError):
    """
    Raised when CachedUserManager could not update an CmdbCachedUser
    """


class CachedUserManagerDeleteError(CachedUserManagerError):
    """
    Raised when CachedUserManager could not delete an CmdbCachedUser
    """


class CachedUserManagerIterationError(CachedUserManagerError):
    """
    Raised when CachedUserManager could not iterate over CmdbCachedUsers
    """
