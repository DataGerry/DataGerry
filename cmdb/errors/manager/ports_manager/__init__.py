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
This package provides all errors of the PortsManager
"""
from typing import Any

from .ports_manager_errors import (
    PortsManagerError,
    PortsManagerInitError,
    PortsManagerInsertError,
    PortsManagerGetError,
    PortsManagerUpdateError,
    PortsManagerDeleteError,
    PortsManagerIterationError,
)
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'PortsManagerError',
    'PortsManagerInitError',
    'PortsManagerInsertError',
    'PortsManagerGetError',
    'PortsManagerUpdateError',
    'PortsManagerDeleteError',
    'PortsManagerIterationError',
    'PORTS_MANAGER_ERRORS',
]


# Per-operation exception map consumed by GenericManager: each operation key maps to the PortsManager
# error raised when that operation fails
PORTS_MANAGER_ERRORS: dict[str, Any] = {
    "init": PortsManagerInitError,
    "insert": PortsManagerInsertError,
    "get": PortsManagerGetError,
    "update": PortsManagerUpdateError,
    "delete": PortsManagerDeleteError,
    "iterate": PortsManagerIterationError,
}
