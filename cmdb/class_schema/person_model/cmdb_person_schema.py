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
The schema of a CmdbPerson
"""
from typing import Any
# -------------------------------------------------------------------------------------------------------------------- #
# pylint: disable=R0801
def get_cmdb_person_schema() -> dict[str, Any]:
    """
    Returns the CmdbPersonSchema

    Returns:
        dict: Schema of the CmdbPerson
    """
    return {
        'public_id': {  # public_id of the CmdbPerson
            'type': 'integer',
            'min': 1,
        },
        'display_name': {  # Displayed name of the Person
            'type': 'string',
            'required': True,
            'empty': False,
        },
        'first_name': {  # First name of the Person
            'type': 'string',
            'required': True,
            'empty': False,
        },
        'last_name': {  # Last name of the Person
            'type': 'string',
            'required': True,
            'empty': False,
        },
        'phone_number': {  # Optional phone number of the Person
            'type': 'string',
        },
        'email': {  # Optional email of the Person; validated against an email pattern
            'type': 'string',
            'required': False,
            'empty': True,
            'regex': r'^(?!.*\.\.)[\w\.-]+@[a-zA-Z\d-]+(\.[a-zA-Z]{2,})+$',  # Email regex pattern
        },
        'groups': {  # public_ids of the CmdbPersonGroups this Person is assigned to
            'type': 'list',
            'schema': {
                'type': 'integer',
                'min': 1,
            },
        },
    }
