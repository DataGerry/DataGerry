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
This module provides all errors for the PersonGroupsManager
"""
from typing import Any

from .person_groups_manager_errors import (
    PersonGroupsManagerError,
    PersonGroupsManagerInitError,
    PersonGroupsManagerInsertError,
    PersonGroupsManagerGetError,
    PersonGroupsManagerUpdateError,
    PersonGroupsManagerDeleteError,
    PersonGroupsManagerIterationError,
)
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'PersonGroupsManagerError',
    'PersonGroupsManagerInitError',
    'PersonGroupsManagerInsertError',
    'PersonGroupsManagerGetError',
    'PersonGroupsManagerUpdateError',
    'PersonGroupsManagerDeleteError',
    'PersonGroupsManagerIterationError',
]


PERSON_GROUPS_MANAGER_ERRORS: dict[str, Any] = {
    "init": PersonGroupsManagerInitError,
    "insert": PersonGroupsManagerInsertError,
    "get": PersonGroupsManagerGetError,
    "update": PersonGroupsManagerUpdateError,
    "delete": PersonGroupsManagerDeleteError,
    "iterate": PersonGroupsManagerIterationError,
}
