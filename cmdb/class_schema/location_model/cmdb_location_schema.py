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
Validation schema for CmdbLocation

A CmdbLocation is a node in the location tree that wraps a CmdbObject
(collection ``framework.locations``).

This module is the single source of the document's Cerberus validation schema,
consumed as CmdbLocation.SCHEMA.
"""
from typing import Any
# -------------------------------------------------------------------------------------------------------------------- #
# pylint: disable=R0801
def get_cmdb_location_schema() -> dict[str, Any]:
    """
    Builds the Cerberus validation schema for a CmdbLocation document

    Returns:
        dict: Field name to Cerberus rule mapping, consumed as CmdbLocation.SCHEMA
    """
    return {
        'public_id': {  # public_id of the CmdbLocation
            'type': 'integer',
        },
        'name': {  # Display name of the location
            'type': 'string',
        },
        'parent': {  # public_id of the parent CmdbLocation (None / root for the top level)
            'type': 'integer',
            'nullable': True,
        },
        'object_id': {  # public_id of the CmdbObject this location represents
            'type': 'integer',
            'nullable': True,
        },
        'type_id': {  # public_id of the CmdbType of the underlying object
            'type': 'integer',
        },
        'type_label': {  # Label of the underlying object's CmdbType
            'type': 'string',
        },
        'type_icon': {  # Icon of the underlying object's CmdbType
            'type': 'string',
            'default': 'fas fa-cube',
        },
        'type_selectable': {  # Whether this location may be chosen as a parent for others
            'type': 'boolean',
            'default': True,
        },
        'managed_by': {  # A LocationManagedBy value when a feature owns this node; absent when the
                         # node is the ordinary mirror of the object's own location field
            'type': 'string',
            'nullable': True,
            'required': False,
        },
    }
