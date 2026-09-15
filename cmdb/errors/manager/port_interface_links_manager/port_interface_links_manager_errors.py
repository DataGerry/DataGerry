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
This module contains the classes of all PortInterfaceLinksManager errors
"""
# -------------------------------------------------------------------------------------------------------------------- #

class PortInterfaceLinksManagerError(Exception):
    """
    Raised to catch all PortInterfaceLinksManager related errors
    """
    def __init__(self, err: str) -> None:
        """
        Raised to catch all PortInterfaceLinksManager related errors
        """
        super().__init__(err)

# ---------------------------------------- PortInterfaceLinksManager - ERRORS ---------------------------------------- #

class PortInterfaceLinksManagerInitError(PortInterfaceLinksManagerError):
    """
    Raised when PortInterfaceLinksManager could not be initialised
    """


class PortInterfaceLinksManagerInsertError(PortInterfaceLinksManagerError):
    """
    Raised when PortInterfaceLinksManager could not insert a CmdbPortInterfaceLink
    """


class PortInterfaceLinksManagerGetError(PortInterfaceLinksManagerError):
    """
    Raised when PortInterfaceLinksManager could not retrieve a CmdbPortInterfaceLink
    """


class PortInterfaceLinksManagerUpdateError(PortInterfaceLinksManagerError):
    """
    Raised when PortInterfaceLinksManager could not update a CmdbPortInterfaceLink
    """


class PortInterfaceLinksManagerDeleteError(PortInterfaceLinksManagerError):
    """
    Raised when PortInterfaceLinksManager could not delete a CmdbPortInterfaceLink
    """


class PortInterfaceLinksManagerIterationError(PortInterfaceLinksManagerError):
    """
    Raised when PortInterfaceLinksManager could not iterate over CmdbPortInterfaceLinks
    """
