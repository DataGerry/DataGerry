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
Validation schema for CmdbCiExplorerProfile

A CmdbCiExplorerProfile is a saved CI Explorer filter (collection ``framework.ciExplorerProfile``).

This module is the single source of the document's Cerberus validation schema,
consumed as CmdbCiExplorerProfile.SCHEMA.
"""
from typing import Any
# -------------------------------------------------------------------------------------------------------------------- #
# pylint: disable=R0801
def get_cmdb_ci_explorer_profile_schema() -> dict[str, Any]:
    """
    Builds the Cerberus validation schema for a CmdbCiExplorerProfile document

    Returns:
        dict: Field name to Cerberus rule mapping, consumed as CmdbCiExplorerProfile.SCHEMA
    """
    return {
        'public_id': {  # public_id of the CmdbCiExplorerProfile
            'type': 'integer',
            'min': 1,
        },
        'name': {  # Name of the saved CI Explorer filter (visible to users)
            'type': 'string',
            'required': True,
            'empty': False,
        },
        'types_filter': {  # public_ids of CmdbTypes the saved filter restricts neighbours to
            'type': 'list',
            'required': False,
            'nullable': True,
            'empty': True,
        },
        'relations_filter': {  # public_ids of CmdbRelations the saved filter restricts edges to
            'type': 'list',
            'required': False,
            'nullable': True,
            'empty': True,
        },
        'with_locations': {  # If True the saved filter includes the dg_location hierarchy
            'type': 'boolean',
            'required': False,
            'nullable': True,
            'empty': True,
            'default': True,
        },
        'with_ipam_relations': {  # If True the saved filter includes IPAM-hierarchy neighbours
            'type': 'boolean',
            'required': False,
            'nullable': True,
            'empty': True,
            'default': False,
        },
    }
