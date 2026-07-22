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
Validation schema for IsmsImpactCategory

An IsmsImpactCategory groups per-impact-level descriptions used in risk calculation
(collection ``isms.impactCategory``).

This module is the single source of the document's Cerberus validation schema,
consumed as IsmsImpactCategory.SCHEMA.
"""
from typing import Any
# -------------------------------------------------------------------------------------------------------------------- #
# pylint: disable=R0801
def get_isms_impact_category_schema() -> dict[str, Any]:
    """
    Builds the Cerberus validation schema for a IsmsImpactCategory document

    Returns:
        dict: Field name to Cerberus rule mapping, consumed as IsmsImpactCategory.SCHEMA
    """
    return {
        'public_id': {  # public_id of the IsmsImpactCategory
            'type': 'integer',
            'min': 1,
        },
        'name': {  # Name of the impact category
            'type': 'string',
            'required': True,
            'empty': False,
        },
        'impact_descriptions': {  # Per-impact-level description entries for this category
            'type': 'list',
            'schema': {
                'type': 'dict',
                'schema': {
                    'impact_id': {  # public_id of the IsmsImpact the description belongs to
                        'type': 'integer',
                        'min': 1,
                    },
                    'value': {  # Description text shown for that impact level
                        'type': 'string',
                    },
                },
            },
        },
        'sort': {  # Sort order of the category
            'type': 'integer',
        },
    }
