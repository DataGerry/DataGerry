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
This module contains the classes of all PortsManager errors
"""
# -------------------------------------------------------------------------------------------------------------------- #

class PortsManagerError(Exception):
    """
    Raised to catch all PortsManager related errors
    """
    def __init__(self, err: str) -> None:
        """
        Raised to catch all PortsManager related errors
        """
        super().__init__(err)

# ----------------------------------------------- PortsManager - ERRORS ---------------------------------------------- #

class PortsManagerInitError(PortsManagerError):
    """
    Raised when PortsManager could not be initialised
    """


class PortsManagerInsertError(PortsManagerError):
    """
    Raised when PortsManager could not insert a CmdbPort
    """


class PortsManagerGetError(PortsManagerError):
    """
    Raised when PortsManager could not retrieve a CmdbPort
    """


class PortsManagerUpdateError(PortsManagerError):
    """
    Raised when PortsManager could not update a CmdbPort
    """


class PortsManagerDeleteError(PortsManagerError):
    """
    Raised when PortsManager could not delete a CmdbPort
    """


class PortsManagerIterationError(PortsManagerError):
    """
    Raised when PortsManager could not iterate over CmdbPorts
    """
