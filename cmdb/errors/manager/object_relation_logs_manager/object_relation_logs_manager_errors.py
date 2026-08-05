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
This module contains the classes of all ObjectRelationLogsManager errors
"""
# -------------------------------------------------------------------------------------------------------------------- #

class ObjectRelationLogsManagerError(Exception):
    """
    Raised to catch all ObjectRelationLogsManager related errors
    """
    def __init__(self, err: str) -> None:
        """
        Raised to catch all ObjectRelationLogsManager related errors
        """
        super().__init__(err)

# --------------------------------------- ObjectRelationsManagerError - ERRORS --------------------------------------- #

class ObjectRelationLogsManagerInitError(ObjectRelationLogsManagerError):
    """
    Raised when ObjectRelationLogsManager could not be initialised
    """


class ObjectRelationLogsManagerBuildError(ObjectRelationLogsManagerError):
    """
    Raised when ObjectRelationLogsManager could not build a CmdbObjectRelationLog
    """


class ObjectRelationLogsManagerInsertError(ObjectRelationLogsManagerError):
    """
    Raised when ObjectRelationLogsManager could not insert a CmdbObjectRelationLog
    """


class ObjectRelationLogsManagerGetError(ObjectRelationLogsManagerError):
    """
    Raised when ObjectRelationLogsManager could not retrieve a CmdbObjectRelationLog
    """


class ObjectRelationLogsManagerDeleteError(ObjectRelationLogsManagerError):
    """
    Raised when ObjectRelationLogsManager could not delete a CmdbObjectRelationLog
    """


class ObjectRelationLogsManagerIterationError(ObjectRelationLogsManagerError):
    """
    Raised when ObjectRelationLogsManager could not iterate over CmdbObjectRelationLog
    """
