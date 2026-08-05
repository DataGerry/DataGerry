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
This module contains the classes of all ObjectsManager errors
"""
# -------------------------------------------------------------------------------------------------------------------- #

class ObjectsManagerError(Exception):
    """
    Raised to catch all ObjectsManager related errors
    """
    def __init__(self, err: str) -> None:
        """
        Raised to catch all ObjectsManager related errors
        """
        super().__init__(err)

# ---------------------------------------------- ObjectsManager - ERRORS --------------------------------------------- #

class ObjectsManagerInsertError(ObjectsManagerError):
    """
    Raised when ObjectsManager could not insert a CmdbObject
    """


class ObjectsManagerDeleteError(ObjectsManagerError):
    """
    Raised when ObjectsManager could not delete a CmdbObject
    """


class ObjectsManagerUpdateError(ObjectsManagerError):
    """
    Raised when ObjectsManager could not update a CmdbObject
    """


class ObjectsManagerGetError(ObjectsManagerError):
    """
    Raised when ObjectsManager could not retrieve a CmdbObject
    """


class ObjectsManagerGetTypeError(ObjectsManagerError):
    """
    Raised when ObjectsManager could not retrieve the CmdbType of the CmdbObject
    """


class ObjectsManagerInitError(ObjectsManagerError):
    """
    Raised when ObjectsManager could not initialise a CmdbObject
    """


class ObjectsManagerIterationError(ObjectsManagerError):
    """
    Raised when ObjectsManager could not iterate over CmdbObjects
    """


class ObjectsManagerMdsReferencesError(ObjectsManagerError):
    """
    Raised when ObjectsManager could not merge MDS references
    """


class ObjectsManagerCheckError(ObjectsManagerError):
    """
    Raised when ObjectsManager fails a class internal check
    """


class ObjectsManagerSummaryLineError(ObjectsManagerError):
    """
    Raised when ObjectsManager fails to retrieve the summaryline of a CmdbObject
    """
