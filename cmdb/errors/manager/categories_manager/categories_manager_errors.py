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
This module contains the classes of all CategoriesManager errors
"""
# -------------------------------------------------------------------------------------------------------------------- #

class CategoriesManagerError(Exception):
    """
    Raised to catch all CategoriesManager related errors
    """
    def __init__(self, err: str) -> None:
        """
        Raised to catch all CategoriesManager related errors
        """
        super().__init__(err)

# --------------------------------------------- CategoriesManager ERRORS --------------------------------------------- #

class CategoriesManagerInitError(CategoriesManagerError):
    """
    Raised when CategoriesManager could not be initialised
    """


class CategoriesManagerInsertError(CategoriesManagerError):
    """
    Raised when CategoriesManager could not insert a CmdbCategory
    """


class CategoriesManagerGetError(CategoriesManagerError):
    """
    Raised when CategoriesManager could not retrieve a CmdbCategory
    """


class CategoriesManagerUpdateError(CategoriesManagerError):
    """
    Raised when CategoriesManager could not update a CmdbCategory
    """


class CategoriesManagerDeleteError(CategoriesManagerError):
    """
    Raised when CategoriesManager could not delete a CmdbCategory
    """


class CategoriesManagerIterationError(CategoriesManagerError):
    """
    Raised when CategoriesManager could not iterate over CmdbCategories
    """


class CategoriesManagerTreeInitError(CategoriesManagerError):
    """
    Raised when CategoriesManager could not initialise the CategoryTree
    """
