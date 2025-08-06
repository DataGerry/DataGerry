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
This module provides all errors for the ProtectionGoalManager
"""
from typing import Any

from .protection_goal_manager_errors import (
    ProtectionGoalManagerError,
    ProtectionGoalManagerInitError,
    ProtectionGoalManagerInsertError,
    ProtectionGoalManagerGetError,
    ProtectionGoalManagerUpdateError,
    ProtectionGoalManagerDeleteError,
    ProtectionGoalManagerIterationError,
    ProtectionGoalManagerRiskUsageError,
)
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'ProtectionGoalManagerError',
    'ProtectionGoalManagerInitError',
    'ProtectionGoalManagerInsertError',
    'ProtectionGoalManagerGetError',
    'ProtectionGoalManagerUpdateError',
    'ProtectionGoalManagerDeleteError',
    'ProtectionGoalManagerIterationError',
    'ProtectionGoalManagerRiskUsageError',
]


PROTECTION_GOAL_MANAGER_ERRORS: dict[str, Any] = {
    "init": ProtectionGoalManagerInitError,
    "insert": ProtectionGoalManagerInsertError,
    "get": ProtectionGoalManagerGetError,
    "update": ProtectionGoalManagerUpdateError,
    "delete": ProtectionGoalManagerDeleteError,
    "iterate": ProtectionGoalManagerIterationError,
}
