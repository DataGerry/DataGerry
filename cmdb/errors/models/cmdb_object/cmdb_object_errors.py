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
This module contains the classes of all CmdbObject errors
"""
# -------------------------------------------------------------------------------------------------------------------- #

class CmdbObjectError(Exception):
    """
    Raised to catch all CmdbObject related errors
    """
    def __init__(self, err: str) -> None:
        """
        Raised to catch all CmdbObject related errors
        """
        super().__init__(err)

# ------------------------------------------------ CmdbObject - ERRORS ----------------------------------------------- #

class CmdbObjectInitError(CmdbObjectError):
    """
    Raised when a CmdbObject could not be initialised
    """


class CmdbObjectInitFromDataError(CmdbObjectError):
    """
    Raised when a CmdbObject could not be initialised from a dict
    """


class CmdbObjectToJsonError(CmdbObjectError):
    """
    Raised when a CmdbObject could not be transformed into a json compatible dict
    """
