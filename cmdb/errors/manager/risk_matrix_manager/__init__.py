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
This module provides all errors for the RiskMatrixManager
"""
from typing import Any

from .risk_matrix_manager_errors import (
    RiskMatrixManagerError,
    RiskMatrixManagerInitError,
    RiskMatrixManagerInsertError,
    RiskMatrixManagerUpdateError,
    RiskMatrixManagerGetError,
    RiskMatrixManagerDeleteError,
    RiskMatrixManagerIterationError,
)
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'RiskMatrixManagerError',
    'RiskMatrixManagerInitError',
    'RiskMatrixManagerInsertError',
    'RiskMatrixManagerUpdateError',
    'RiskMatrixManagerGetError',
    'RiskMatrixManagerDeleteError',
    'RiskMatrixManagerIterationError',
]


RISK_MATRIX_MANAGER_ERRORS: dict[str, Any] = {
    "init": RiskMatrixManagerInitError,
    "insert": RiskMatrixManagerInsertError,
    "get": RiskMatrixManagerGetError,
    "update": RiskMatrixManagerUpdateError,
    "delete": RiskMatrixManagerDeleteError,
    "iterate": RiskMatrixManagerIterationError,
}
