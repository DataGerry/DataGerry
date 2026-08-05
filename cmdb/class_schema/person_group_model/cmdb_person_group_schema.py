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
Validation schema for CmdbPersonGroup

A CmdbPersonGroup groups CmdbPersons (collection ``management.personGroup``).

This module is the single source of the document's Cerberus validation schema,
consumed as CmdbPersonGroup.SCHEMA.
"""
from typing import Any
# -------------------------------------------------------------------------------------------------------------------- #
# pylint: disable=R0801
def get_cmdb_person_group_schema() -> dict[str, Any]:
    """
    Builds the Cerberus validation schema for a CmdbPersonGroup document

    Returns:
        dict: Field name to Cerberus rule mapping, consumed as CmdbPersonGroup.SCHEMA
    """
    return {
        'public_id': {  # public_id of the CmdbPersonGroup
            'type': 'integer',
            'min': 1,
        },
        'name': {  # Name of the person group
            'type': 'string',
            'required': True,
            'empty': False,
        },
        'email': {  # Contact email for the group; validated against an email pattern (required, may be empty)
            'type': 'string',
            'required': True,
            'empty': True,
            'regex': r'^(?!.*\.\.)[\w\.-]+@[a-zA-Z\d-]+(\.[a-zA-Z]{2,})+$',  # Email regex pattern
        },
        'group_members': {  # public_ids of the CmdbPersons that belong to this group
            'type': 'list',
            'schema': {
                'type': 'integer',
                'min': 1,
            },
        },
    }
