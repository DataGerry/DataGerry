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
Validation schema for IsmsLikelihood

An IsmsLikelihood is a likelihood level with a numeric calculation basis
(collection ``isms.likelihood``).

This module is the single source of the document's Cerberus validation schema,
consumed as IsmsLikelihood.SCHEMA.
"""
from typing import Any
# -------------------------------------------------------------------------------------------------------------------- #
# pylint: disable=R0801
def get_isms_likelihood_schema() -> dict[str, Any]:
    """
    Builds the Cerberus validation schema for a IsmsLikelihood document

    Returns:
        dict: Field name to Cerberus rule mapping, consumed as IsmsLikelihood.SCHEMA
    """
    return {
        'public_id': {  # public_id of the IsmsLikelihood
            'type': 'integer',
            'min': 1,
        },
        'name': {  # Name of the likelihood level
            'type': 'string',
            'required': True,
            'empty': False,
        },
        'calculation_basis': {  # Numeric weight of this likelihood level used in risk calculation (>= 1e-9)
            'type': 'float',
            'min': 1e-9,
            'required': True,
            'empty': False,
        },
        'description': {  # Optional description of the likelihood level
            'type': 'string',
        },
    }
