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
    # Imported inside the builder: the model imports this schema, so a module-level import of the
    # model's constants would close a cycle (see the class_schema convention)
    # pylint: disable=import-outside-toplevel
    from cmdb.models.isms_model.isms_impact_category_constants import (
        ImpactCategoryKey,
        ImpactDescriptionKey,
    )

    return {
        ImpactCategoryKey.PUBLIC_ID.value: {  # public_id of the IsmsImpactCategory
            'type': 'integer',
            'min': 1,
        },
        ImpactCategoryKey.NAME.value: {  # Name of the impact category
            'type': 'string',
            'required': True,
            'empty': False,
        },
        ImpactCategoryKey.IMPACT_DESCRIPTIONS.value: {  # One description entry per IsmsImpact
            'type': 'list',
            'schema': {
                'type': 'dict',
                'schema': {
                    ImpactDescriptionKey.IMPACT_ID.value: {  # public_id of the described IsmsImpact
                        'type': 'integer',
                        'min': 1,
                    },
                    ImpactDescriptionKey.VALUE.value: {  # Description text shown for that impact level
                        'type': 'string',
                    },
                },
            },
        },
        ImpactCategoryKey.SORT.value: {  # Sort order of the category
            'type': 'integer',
        },
    }
