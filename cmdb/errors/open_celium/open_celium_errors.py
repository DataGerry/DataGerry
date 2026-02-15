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
This module contains the classes of all OpenCelium general errors
"""
# -------------------------------------------------------------------------------------------------------------------- #

class OpenCeliumError(Exception):
    """
    Raised to catch all general OpenCelium related errors
    """
    def __init__(self, err: str) -> None:
        """
        Raised to catch all general OpenCelium related errors
        """
        super().__init__(err)

# ------------------------------------------------ OpenCelium - ERRORS ----------------------------------------------- #

class AuthError(OpenCeliumError):
    """
    Raised when the authentification with OpenCelium fails
    """


class OcNoSubError(OpenCeliumError):
    """
    Raised when a subscription was not found
    """


class OcMasterPwNotSetError(OpenCeliumError):
    """
    Raised when the master password for a subscription is not set
    """
