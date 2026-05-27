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
The schema of an IsmsRiskMatrix
"""
from typing import Any
# -------------------------------------------------------------------------------------------------------------------- #
# pylint: disable=R0801
def get_isms_risk_matrix_schema() -> dict[str, Any]:
    """
    Returns the IsmsRiskMatrixSchema

    Returns:
        dict: Schema of the IsmsRiskMatrix
    """
    return {
        'public_id': {  # public_id of the IsmsRiskMatrix
            'type': 'integer',
        },
        'risk_matrix': {  # Matrix cells (built from bottom-left, line by line)
            'type': 'list',
            'schema': {
                'type': 'dict',
                'schema': {
                    'row': {  # Zero-based row index of the cell
                        'type': 'integer',
                        'min': 0,
                    },
                    'column': {  # Zero-based column index of the cell
                        'type': 'integer',
                        'min': 0,
                    },
                    'risk_class_id': {  # public_id of the IsmsRiskClass assigned to this cell
                        'type': 'integer',
                    },
                    'impact_id': {  # public_id of the IsmsImpact represented by this cell
                        'type': 'integer',
                    },
                    'impact_value': {  # calculation_basis of the cell's IsmsImpact
                        'type': 'float',
                        'min': 0.0,
                    },
                    'likelihood_id': {  # public_id of the IsmsLikelihood represented by this cell
                        'type': 'integer',
                    },
                    'likelihood_value': {  # calculation_basis of the cell's IsmsLikelihood
                        'type': 'float',
                        'min': 0.0,
                    },
                    'calculated_value': {  # Computed risk value for the cell (impact x likelihood)
                        'type': 'float',
                        'min': 0.0,
                    },
                },
            },
        },
        'matrix_unit': {  # Unit / label describing the matrix values
            'type': 'string',
        },
    }
