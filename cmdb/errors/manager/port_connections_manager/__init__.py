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
This package provides all errors of the PortConnectionsManager
"""
from typing import Any

from .port_connections_manager_errors import (
    PortConnectionsManagerError,
    PortConnectionsManagerInitError,
    PortConnectionsManagerInsertError,
    PortConnectionsManagerGetError,
    PortConnectionsManagerUpdateError,
    PortConnectionsManagerDeleteError,
    PortConnectionsManagerIterationError,
)
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'PortConnectionsManagerError',
    'PortConnectionsManagerInitError',
    'PortConnectionsManagerInsertError',
    'PortConnectionsManagerGetError',
    'PortConnectionsManagerUpdateError',
    'PortConnectionsManagerDeleteError',
    'PortConnectionsManagerIterationError',
    'PORT_CONNECTIONS_MANAGER_ERRORS',
]


# Per-operation exception map consumed by GenericManager: each operation key maps to the
# PortConnectionsManager error raised when that operation fails
PORT_CONNECTIONS_MANAGER_ERRORS: dict[str, Any] = {
    "init": PortConnectionsManagerInitError,
    "insert": PortConnectionsManagerInsertError,
    "get": PortConnectionsManagerGetError,
    "update": PortConnectionsManagerUpdateError,
    "delete": PortConnectionsManagerDeleteError,
    "iterate": PortConnectionsManagerIterationError,
}
