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
This module contains the classes of all TypesManager errors
"""
# -------------------------------------------------------------------------------------------------------------------- #

class TypesManagerError(Exception):
    """
    Raised to catch all TypesManager related errors
    """
    def __init__(self, err: str) -> None:
        """
        Raised to catch all TypesManager related errors
        """
        super().__init__(err)

# ----------------------------------------------- TypesManager - ERRORS ---------------------------------------------- #

class TypesManagerGetError(TypesManagerError):
    """
    Raised when TypesManager could not retrieve a CmdbType
    """


class TypesManagerInsertError(TypesManagerError):
    """
    Raised when TypesManager could not create a CmdbType
    """


class TypesManagerUpdateError(TypesManagerError):
    """
    Raised when TypesManager could not update a CmdbType
    """


class TypesManagerUpdateMDSError(TypesManagerError):
    """
    Raised when TypesManager could not update the MultiDataSections of a CmdbType
    """


class TypesManagerDeleteError(TypesManagerError):
    """
    Raised when TypesManager could not delete a CmdbType
    """


class TypesManagerInitError(TypesManagerError):
    """
    Raised when TypesManager could not initialise a CmdbType
    """


class TypesManagerIterationError(TypesManagerError):
    """
    Raised when TypesManager could not iterate over CmdbTypes
    """
