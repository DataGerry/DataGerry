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
This module provides the predefined IsmsRiskMatrix
"""
from typing import Any

from cmdb.database.predefined_data.predefined_data_constants import RiskMatrixKey
# -------------------------------------------------------------------------------------------------------------------- #

def get_default_risk_matrix() -> dict[str, Any]:
    """
    Returns the default (empty) IsmsRiskMatrix, inserted at setup

    Returns:
        dict[str, Any]: The default IsmsRiskMatrix document
    """
    return {
        RiskMatrixKey.PUBLIC_ID: 1,
        RiskMatrixKey.RISK_MATRIX: [],
        RiskMatrixKey.MATRIX_UNIT: None
    }
