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
This module provides all errors for the ImpactCategoryManager
"""
from typing import Any

from .impact_category_manager_errors import (
    ImpactCategoryManagerError,
    ImpactCategoryManagerInitError,
    ImpactCategoryManagerInsertError,
    ImpactCategoryManagerGetError,
    ImpactCategoryManagerUpdateError,
    ImpactCategoryManagerDeleteError,
    ImpactCategoryManagerIterationError,
)
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'ImpactCategoryManagerError',
    'ImpactCategoryManagerInitError',
    'ImpactCategoryManagerInsertError',
    'ImpactCategoryManagerGetError',
    'ImpactCategoryManagerUpdateError',
    'ImpactCategoryManagerDeleteError',
    'ImpactCategoryManagerIterationError',
]


IMPACT_CATEGORY_MANAGER_ERRORS: dict[str, Any] = {
    "init": ImpactCategoryManagerInitError,
    "insert": ImpactCategoryManagerInsertError,
    "get": ImpactCategoryManagerGetError,
    "update": ImpactCategoryManagerUpdateError,
    "delete": ImpactCategoryManagerDeleteError,
    "iterate": ImpactCategoryManagerIterationError,
}
