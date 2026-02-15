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
Implementation of OperationType enumeration
"""
from enum import Enum
# -------------------------------------------------------------------------------------------------------------------- #

class OperationType(Enum):
    """
    Enumeration representing different types of API operations.
    
    This enum acts as an identifier for the type of operation performed in an API response.
    """
    GET = "GET"
    UPDATE = "UPDATE"
    PATCH = "PATCH"
    INSERT = "INSERT"
    DELETE = "DELETE"
