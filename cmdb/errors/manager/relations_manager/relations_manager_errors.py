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
This module contains the classes of all RelationsManager errors
"""
# -------------------------------------------------------------------------------------------------------------------- #

class RelationsManagerError(Exception):
    """
    Raised to catch all RelationsManager related errors
    """
    def __init__(self, err: str) -> None:
        """
        Raised to catch all RelationsManager related errors
        """
        super().__init__(err)

# --------------------------------------------- RelationsManager - ERRORS -------------------------------------------- #

class RelationsManagerInitError(RelationsManagerError):
    """
    Raised when RelationsManager could not be initialised
    """


class RelationsManagerInsertError(RelationsManagerError):
    """
    Raised when RelationsManager could not insert a CmdbRelation
    """


class RelationsManagerGetError(RelationsManagerError):
    """
    Raised when RelationsManager could not retrieve a CmdbRelation
    """


class RelationsManagerUpdateError(RelationsManagerError):
    """
    Raised when RelationsManager could not update a CmdbRelation
    """


class RelationsManagerDeleteError(RelationsManagerError):
    """
    Raised when RelationsManager could not delete a CmdbRelation
    """


class RelationsManagerIterationError(RelationsManagerError):
    """
    Raised when RelationsManager could not iterate over CmdbRelations
    """
