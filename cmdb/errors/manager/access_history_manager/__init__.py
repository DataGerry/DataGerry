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
This module provides all errors for the AccessHistoryManager
"""
from typing import Any

from .access_history_manager_errors import (
    AccessHistoryManagerError,
    AccessHistoryManagerInsertError,
    AccessHistoryManagerGetError,
    AccessHistoryManagerUpdateError,
    AccessHistoryManagerDeleteError,
    AccessHistoryManagerIterationError,
)
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'AccessHistoryManagerError',
    'AccessHistoryManagerInsertError',
    'AccessHistoryManagerGetError',
    'AccessHistoryManagerUpdateError',
    'AccessHistoryManagerDeleteError',
    'AccessHistoryManagerIterationError',
    'ACCESS_HISTORY_MANAGER_ERRORS',
]


ACCESS_HISTORY_MANAGER_ERRORS: dict[str, Any] = {
    "insert": AccessHistoryManagerInsertError,
    "get": AccessHistoryManagerGetError,
    "update": AccessHistoryManagerUpdateError,
    "delete": AccessHistoryManagerDeleteError,
    "iterate": AccessHistoryManagerIterationError,
}
