# DataGerry - OpenSource Enterprise CMDB
# Copyright (C) 2025 becon GmbH
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
The schema of a CmdbUser
"""
from typing import Any
# -------------------------------------------------------------------------------------------------------------------- #

DEFAULT_AUTHENTICATOR: str = 'LocalAuthenticationProvider'
DEFAULT_GROUP: int = 2
DEFAULT_API_LEVEL = 0
DEFAULT_CONFIG_ITEMS_LIMIT = 1000

# -------------------------------------------------------------------------------------------------------------------- #
# pylint: disable=R0801
def get_cmdb_user_schema() -> dict[str, Any]:
    """
    Returns the CmdbUserSchema

    Returns:
        dict: Schema of the CmdbUser
    """
    return {
        'public_id': {
            'type': 'integer'
        },
        'user_name': {
            'type': 'string',
            'required': True,
        },
        'active': {
            'type': 'boolean',
            'default': True,
            'required': False
        },
        'group_id': {
            'type': 'integer',
            'default': DEFAULT_GROUP,
            'required': True
        },
        'registration_time': {
            'type': 'dict',
            'nullable': True,
            'empty': True,
            'required': False
        },
        'authenticator': {
            'type': 'string',
            'nullable': True,
            'default': DEFAULT_AUTHENTICATOR,
            'required': False
        },
        'password': {
            'type': 'string',
            'nullable': True,
            'empty': True,
            'required': False
        },
        'first_name': {
            'type': 'string',
            'nullable': True,
            'empty': True,
            'required': False
        },
        'last_name': {
            'type': 'string',
            'nullable': True,
            'empty': True,
            'required': False
        },
        'email': {
            'type': 'string',
            'nullable': True,
            'empty': True,
            'required': False
        },
        'image': {
            'type': 'string',
            'nullable': True,
            'empty': True,
            'required': False
        },
        'database': {
            'type': 'string',
            'nullable': True,
            'empty': True,
            'required': False
        },
        'api_level': {
            'type': 'integer',
            'nullable': True,
            'empty': True,
            'default': DEFAULT_API_LEVEL,
            'required': False
        },
        'config_items_limit': {
            'type': 'integer',
            'nullable': True,
            'empty': True,
            'default': DEFAULT_CONFIG_ITEMS_LIMIT,
            'required': False
        }
    }
