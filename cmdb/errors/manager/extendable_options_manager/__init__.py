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
This module provides all errors for the ExtendableOptionsManager
"""
from typing import Any

from .extendable_options_manager_errors import (
    ExtendableOptionsManagerError,
    ExtendableOptionsManagerInitError,
    ExtendableOptionsManagerInsertError,
    ExtendableOptionsManagerGetError,
    ExtendableOptionsManagerUpdateError,
    ExtendableOptionsManagerDeleteError,
    ExtendableOptionsManagerIterationError,
)
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'ExtendableOptionsManagerError',
    'ExtendableOptionsManagerInitError',
    'ExtendableOptionsManagerInsertError',
    'ExtendableOptionsManagerGetError',
    'ExtendableOptionsManagerUpdateError',
    'ExtendableOptionsManagerDeleteError',
    'ExtendableOptionsManagerIterationError',
]


EXTENDABLE_OPTIONS_MANAGER_ERRORS: dict[str, Any] = {
    "init": ExtendableOptionsManagerInitError,
    "insert": ExtendableOptionsManagerInsertError,
    "get": ExtendableOptionsManagerGetError,
    "update": ExtendableOptionsManagerUpdateError,
    "delete": ExtendableOptionsManagerDeleteError,
    "iterate": ExtendableOptionsManagerIterationError,
}
