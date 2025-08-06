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
This module contains the classes of all ObjectGroupsManager errors
"""
# -------------------------------------------------------------------------------------------------------------------- #

class ObjectGroupsManagerError(Exception):
    """
    Raised to catch all ObjectGroupsManager related errors
    """
    def __init__(self, err: str) -> None:
        """
        Raised to catch all ObjectGroupsManager related errors
        """
        super().__init__(err)

# ------------------------------------------- ObjectGroupsManager - ERRORS ------------------------------------------- #

class ObjectGroupsManagerInitError(ObjectGroupsManagerError):
    """
    Raised when ObjectGroupsManager could not be initialised
    """


class ObjectGroupsManagerInsertError(ObjectGroupsManagerError):
    """
    Raised when ObjectGroupsManager could not insert an CmdbObjectGroup
    """


class ObjectGroupsManagerGetError(ObjectGroupsManagerError):
    """
    Raised when ObjectGroupsManager could not retrieve an CmdbObjectGroup
    """


class ObjectGroupsManagerUpdateError(ObjectGroupsManagerError):
    """
    Raised when ObjectGroupsManager could not update an CmdbObjectGroup
    """


class ObjectGroupsManagerDeleteError(ObjectGroupsManagerError):
    """
    Raised when ObjectGroupsManager could not delete an CmdbObjectGroup
    """


class ObjectGroupsManagerIterationError(ObjectGroupsManagerError):
    """
    Raised when ObjectGroupsManager could not iterate over CmdbObjectGroups
    """
