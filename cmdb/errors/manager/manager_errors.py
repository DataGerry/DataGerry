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
Contains all BaseManager error classes
"""
# -------------------------------------------------------------------------------------------------------------------- #

class BaseManagerError(Exception):
    """
    Raised to catch all BaseManager related errors
    """
    def __init__(self, err: str) -> None:
        """
        Raised to catch all BaseManager related errors
        """
        super().__init__(err)

# ------------------------------------------------ BaseManager ERRORS ------------------------------------------------ #

class BaseManagerInitError(BaseManagerError):
    """
    Raised when the BaseManager could not be initialised
    """


class BaseManagerGetError(BaseManagerError):
    """
    Raised when the BaseManager could not retrieve a document
    """


class BaseManagerIterationError(BaseManagerError):
    """
    Raised when the BaseManager iteration fails
    """


class BaseManagerInsertError(BaseManagerError):
    """
    Raised when the BaseManager could not insert a document into the database
    """


class BaseManagerUpdateError(BaseManagerError):
    """
    Raised when the BaseManager could not update a document in the database
    """


class BaseManagerDeleteError(BaseManagerError):
    """
    Raised when the BaseManager could not delete a document from the database
    """
