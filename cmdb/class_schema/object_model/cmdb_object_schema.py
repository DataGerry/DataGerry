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
Validation schema for CmdbObject

A CmdbObject is the stored instance of a CmdbType and the core record of the CMDB
(collection ``framework.objects``).

This module is the single source of the document's Cerberus validation schema,
consumed as CmdbObject.SCHEMA.
"""
from typing import Any
# -------------------------------------------------------------------------------------------------------------------- #

def get_cmdb_object_schema() -> dict[str, Any]:
    """
    Builds the Cerberus validation schema for a CmdbObject document

    Returns:
        dict: Field name to Cerberus rule mapping, consumed as CmdbObject.SCHEMA
    """
    return {
        'public_id': {  # public_id of the CmdbObject
            'type': 'integer'
        },
        'type_id': {    # public_id of the CmdbType of this CmdbObject
            'type': 'integer'
        },
        'version': {  # Version of the data of the CmdbObject
            'type': 'string',
            'default': '1.0.0'
        },
        'author_id': {  # The public_id of the CmdbUser which created this CmdbObject
            'type': 'integer',
            'required': True
        },
        'creation_time': {  # The datetime when this CmdbObject was created
            'type': 'dict',
            'nullable': True,
            'required': False
        },
        'last_edit_time': {  # The datetime of when this CmdbObject was edited the last time
            'type': 'dict',
            'nullable': True,
            'required': False
        },
        'active': {  # Defines if the CmdbObject is active or not (True = active, False = inactive)
            'type': 'boolean',
            'required': False,
            'default': True
        },
        'special_type': {  # The assigned SpecialType of this CmdbObjects CmdbType if any
            'type': 'string',
            'required': False,
            'nullable': True,
        },
        'fields': {  # Stores the values for the fields of the CmdbObject
            'type': 'list',
            'required': True,
            'default': [],
        },
        'ci_explorer_tooltip': {  # This tooltip will be displayed in the CI Explorer when hovering over this CmdbObject
            'type': 'string',
            'required': False,
            'nullable': True,
            'empty': True,
        },
        'multi_data_sections': {  # Stores everything related to MDS of this CmdbObject
            'type': 'list',
            'required': False,
            'default': [],
        },
        'location_name': {  # Transient: custom CmdbLocation tree name; consumed by the location sync, never stored
            'type': 'string',
            'required': False,
            'nullable': True,
            'empty': True,
        }
    }
