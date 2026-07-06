# DATAGERRY - OpenSource Enterprise CMDB
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
Implementation of LogAction Enumeration
"""
from enum import Enum
# -------------------------------------------------------------------------------------------------------------------- #

class LogAction(Enum):
    """
    Enum representing different types of log actions for tracking object changes.

    This Enum is used to categorize and identify the type of action performed
    during object manipulation, helping to track and log events for auditing,
    versioning, or other purposes.

    Attributes:
        CREATE (int): Represents the action of creating a new object
        EDIT (int): Represents the action of modifying an existing object
        ACTIVE_CHANGE (int): Represents the action of changing the active state of an object
        DELETE (int): Represents the action of deleting an object
    """
    CREATE = 0
    EDIT = 1
    ACTIVE_CHANGE = 2
    DELETE = 3
