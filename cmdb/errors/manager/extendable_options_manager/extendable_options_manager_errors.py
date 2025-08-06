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
This module contains the classes of all ExtendableOptionsManager errors
"""
# -------------------------------------------------------------------------------------------------------------------- #

class ExtendableOptionsManagerError(Exception):
    """
    Raised to catch all ExtendableOptionsManager related errors
    """
    def __init__(self, err: str) -> None:
        """
        Raised to catch all ExtendableOptionsManager related errors
        """
        super().__init__(err)

# ----------------------------------------- ExtendableOptionsManager - ERRORS ---------------------------------------- #

class ExtendableOptionsManagerInitError(ExtendableOptionsManagerError):
    """
    Raised when ExtendableOptionsManager could not be initialised
    """


class ExtendableOptionsManagerInsertError(ExtendableOptionsManagerError):
    """
    Raised when ExtendableOptionsManager could not insert a CmdbExtendableOption
    """


class ExtendableOptionsManagerGetError(ExtendableOptionsManagerError):
    """
    Raised when ExtendableOptionsManager could not retrieve a CmdbExtendableOption
    """


class ExtendableOptionsManagerUpdateError(ExtendableOptionsManagerError):
    """
    Raised when ExtendableOptionsManager could not update a CmdbExtendableOption
    """


class ExtendableOptionsManagerDeleteError(ExtendableOptionsManagerError):
    """
    Raised when ExtendableOptionsManager could not delete a CmdbExtendableOption
    """


class ExtendableOptionsManagerIterationError(ExtendableOptionsManagerError):
    """
    Raised when ExtendableOptionsManager could not iterate over CmdbExtendableOptions
    """
