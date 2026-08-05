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
This module contains the classes of all ObjectRelationsManager errors
"""
# -------------------------------------------------------------------------------------------------------------------- #

class ObjectRelationsManagerError(Exception):
    """
    Raised to catch all ObjectRelationsManager related errors
    """
    def __init__(self, err: str) -> None:
        """
        Raised to catch all ObjectRelationsManager related errors
        """
        super().__init__(err)

# ------------------------------------------ ObjectRelationsManager - ERRORS ----------------------------------------- #

class ObjectRelationsManagerInitError(ObjectRelationsManagerError):
    """
    Raised when ObjectRelationsManager could not be initialised
    """


class ObjectRelationsManagerInsertError(ObjectRelationsManagerError):
    """
    Raised when ObjectRelationsManager could not insert a CmdbObjectRelation
    """


class ObjectRelationsManagerGetError(ObjectRelationsManagerError):
    """
    Raised when ObjectRelationsManager could not retrieve a CmdbObjectRelation
    """


class ObjectRelationsManagerUpdateError(ObjectRelationsManagerError):
    """
    Raised when ObjectRelationsManager could not update a CmdbObjectRelation
    """


class ObjectRelationsManagerDeleteError(ObjectRelationsManagerError):
    """
    Raised when ObjectRelationsManager could not delete a CmdbObjectRelation
    """


class ObjectRelationsManagerIterationError(ObjectRelationsManagerError):
    """
    Raised when ObjectRelationsManager could not iterate over CmdbObjectRelations
    """
