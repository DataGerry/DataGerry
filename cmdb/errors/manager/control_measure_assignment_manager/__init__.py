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
This module provides all errors for the ControlMeasureAssignmentManager
"""
from typing import Any

from .control_measure_assignment_manager_errors import (
    ControlMeasureAssignmentManagerError,
    ControlMeasureAssignmentManagerInitError,
    ControlMeasureAssignmentManagerInsertError,
    ControlMeasureAssignmentManagerGetError,
    ControlMeasureAssignmentManagerUpdateError,
    ControlMeasureAssignmentManagerDeleteError,
    ControlMeasureAssignmentManagerIterationError,
)
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'ControlMeasureAssignmentManagerError',
    'ControlMeasureAssignmentManagerInitError',
    'ControlMeasureAssignmentManagerInsertError',
    'ControlMeasureAssignmentManagerGetError',
    'ControlMeasureAssignmentManagerUpdateError',
    'ControlMeasureAssignmentManagerDeleteError',
    'ControlMeasureAssignmentManagerIterationError',
]


CONTROL_MEASURE_ASSIGNMENT_MANAGER_ERRORS: dict[str, Any] = {
    "init": ControlMeasureAssignmentManagerInitError,
    "insert": ControlMeasureAssignmentManagerInsertError,
    "get": ControlMeasureAssignmentManagerGetError,
    "update": ControlMeasureAssignmentManagerUpdateError,
    "delete": ControlMeasureAssignmentManagerDeleteError,
    "iterate": ControlMeasureAssignmentManagerIterationError,
}
