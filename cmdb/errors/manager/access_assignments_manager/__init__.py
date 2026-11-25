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
This module provides all errors for the AccessAssignmentsManager
"""
from typing import Any

from .access_assignments_manager_errors import (
    AccessAssignmentsManagerError,
    AccessAssignmentsManagerInsertError,
    AccessAssignmentsManagerGetError,
    AccessAssignmentsManagerUpdateError,
    AccessAssignmentsManagerDeleteError,
    AccessAssignmentsManagerIterationError,
)
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'AccessAssignmentsManagerError',
    'AccessAssignmentsManagerInsertError',
    'AccessAssignmentsManagerGetError',
    'AccessAssignmentsManagerUpdateError',
    'AccessAssignmentsManagerDeleteError',
    'AccessAssignmentsManagerIterationError',
    'ACCESS_ASSIGNMENTS_MANAGER_ERRORS',
]


ACCESS_ASSIGNMENTS_MANAGER_ERRORS: dict[str, Any] = {
    "insert": AccessAssignmentsManagerInsertError,
    "get": AccessAssignmentsManagerGetError,
    "update": AccessAssignmentsManagerUpdateError,
    "delete": AccessAssignmentsManagerDeleteError,
    "iterate": AccessAssignmentsManagerIterationError,
}
