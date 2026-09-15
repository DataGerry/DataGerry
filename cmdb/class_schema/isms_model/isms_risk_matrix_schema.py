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
Validation schema for IsmsRiskMatrix

An IsmsRiskMatrix maps impact x likelihood cells to IsmsRiskClasses
(collection ``isms.riskMatrix``).

This module is the single source of the document's Cerberus validation schema,
consumed as IsmsRiskMatrix.SCHEMA.
"""
from typing import Any
# -------------------------------------------------------------------------------------------------------------------- #
# pylint: disable=R0801
def get_isms_risk_matrix_schema() -> dict[str, Any]:
    """
    Builds the Cerberus validation schema for a IsmsRiskMatrix document

    Returns:
        dict: Field name to Cerberus rule mapping, consumed as IsmsRiskMatrix.SCHEMA
    """
    # pylint: disable=import-outside-toplevel
    # Resolved at call time, not at module import time: the model imports this builder while its own
    # package __init__ is still running, so a module-level import back into cmdb.models would close that
    # cycle and leave every class_schema module unimportable on its own (see class_schema/__init__.py)
    from cmdb.models.isms_model.isms_risk_matrix_constants import RiskMatrixCellKey, RiskMatrixKey

    return {
        RiskMatrixKey.PUBLIC_ID.value: {  # public_id of the IsmsRiskMatrix
            'type': 'integer',
        },
        RiskMatrixKey.RISK_MATRIX.value: {  # Matrix cells (built from bottom-left, line by line)
            'type': 'list',
            'schema': {
                'type': 'dict',
                'schema': {
                    RiskMatrixCellKey.ROW.value: {  # Zero-based row index of the cell
                        'type': 'integer',
                        'min': 0,
                    },
                    RiskMatrixCellKey.COLUMN.value: {  # Zero-based column index of the cell
                        'type': 'integer',
                        'min': 0,
                    },
                    RiskMatrixCellKey.RISK_CLASS_ID.value: {  # public_id of the IsmsRiskClass assigned to this cell
                        'type': 'integer',
                    },
                    RiskMatrixCellKey.IMPACT_ID.value: {  # public_id of the IsmsImpact represented by this cell
                        'type': 'integer',
                    },
                    RiskMatrixCellKey.IMPACT_VALUE.value: {  # calculation_basis of the cell's IsmsImpact
                        'type': 'float',
                        'min': 0.0,
                    },
                    RiskMatrixCellKey.LIKELIHOOD_ID.value: {  # public_id of the IsmsLikelihood represented by this cell
                        'type': 'integer',
                    },
                    RiskMatrixCellKey.LIKELIHOOD_VALUE.value: {  # calculation_basis of the cell's IsmsLikelihood
                        'type': 'float',
                        'min': 0.0,
                    },
                    # Computed risk value for the cell (impact x likelihood)
                    RiskMatrixCellKey.CALCULATED_VALUE.value: {
                        'type': 'float',
                        'min': 0.0,
                    },
                },
            },
        },
        RiskMatrixKey.MATRIX_UNIT.value: {  # Unit / label describing the matrix values
            'type': 'string',
            # Nullable because the matrix HAS no unit until an admin sets one: the seeded default
            # writes null, and to_json writes null for an unset unit - without this the document the
            # first boot creates would not pass its own schema
            'nullable': True,
        },
    }
