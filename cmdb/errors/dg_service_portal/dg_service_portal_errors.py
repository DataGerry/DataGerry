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
Contains DataGerry ServicePortal error classes
"""
# -------------------------------------------------------------------------------------------------------------------- #

class DgServicePortalError(Exception):
    """
    Raised to catch all DgServicePortal related errors
    """
    def __init__(self, err: str) -> None:
        """
        Raised to catch all DgServicePortal related errors
        """
        super().__init__(err)

# --------------------------------------------- DgServicePortal - ERRORS --------------------------------------------- #

class DgServicePortalGetError(DgServicePortalError):
    """
    Raised when DataGerry fails to retrieve information from the DataGerry Service Portal
    """
