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
This module contains the classes of all ObjectLinksManager errors
"""
# -------------------------------------------------------------------------------------------------------------------- #

class ObjectLinksManagerError(Exception):
    """
    Raised to catch all ObjectLinksManager related errors
    """
    def __init__(self, err: str):
        """
        Raised to catch all ObjectLinksManager related errors
        """
        super().__init__(err)

# -------------------------------------------- ObjectLinksManager - ERRORS ------------------------------------------- #

class ObjectLinksManagerInsertError(ObjectLinksManagerError):
    """
    Raised when ObjectLinksManager could not insert a CmdbObjectLink
    """


class ObjectLinksManagerGetError(ObjectLinksManagerError):
    """
    Raised when ObjectLinksManager could not retrieve a CmdbObjectLink
    """


class ObjectLinksManagerGetObjectError(ObjectLinksManagerError):
    """
    Raised when ObjectLinksManager could not retrieve an CmdbObject
    """


class ObjectLinksManagerIterationError(ObjectLinksManagerError):
    """
    Raised when ObjectLinksManager could not iterate over CmdbObjectLinks
    """


class ObjectLinksManagerDeleteError(ObjectLinksManagerError):
    """
    Raised when ObjectLinksManager could not delete a CmdbObjectLink
    """
