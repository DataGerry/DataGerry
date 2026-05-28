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
Validation schema for CmdbCachedUser

A CmdbCachedUser caches a cloud user and their subscriptions with a TTL
(collection ``cache.users``).

This module is the single source of the document's Cerberus validation schema,
consumed as CmdbCachedUser.SCHEMA.
"""
from typing import Any
# -------------------------------------------------------------------------------------------------------------------- #
# pylint: disable=R0801
def get_cmdb_cached_user_schema() -> dict[str, Any]:
    """
    Builds the Cerberus validation schema for a CmdbCachedUser document

    Returns:
        dict: Field name to Cerberus rule mapping, consumed as CmdbCachedUser.SCHEMA
    """
    return {
        'public_id': {  # public_id of the cached CmdbUser
            'type': 'integer',
        },
        'user_name': {  # Login name of the cached user
            'type': 'string',
            'required': True,
        },
        'password': {  # Hashed password (nullable for token / SSO-only cached users)
            'type': 'string',
            'nullable': True,
            'empty': True,
            'required': False,
        },
        'email': {  # Email of the cached user (optional)
            'type': 'string',
            'nullable': True,
            'empty': True,
            'required': False,
        },
        'active': {  # Whether the cached user is active
            'type': 'boolean',
            'required': False,
            'default': True,
        },
        'subscriptions': {  # Cloud subscriptions the user has access to (at least one required)
            'type': 'list',
            'nullable': False,
            'empty': False,
            'required': True,
            'schema': {
                'type': 'dict',
                'schema': {
                    'id': {  # Subscription identifier
                        'type': 'string',
                        'required': True,
                        'default': None,
                    },
                    'name': {  # Subscription / tenant name
                        'type': 'string',
                        'nullable': False,
                        'empty': False,
                        'required': True,
                    },
                    'api_key': {  # API key scoped to this subscription
                        'type': 'string',
                        'default': None,
                    },
                    'is_valid': {  # Whether this subscription is currently valid
                        'type': 'boolean',
                        'required': True,
                    },
                    'database': {  # Tenant database name for this subscription
                        'type': 'string',
                        'nullable': False,
                        'empty': False,
                        'required': True,
                    },
                    'api_level': {  # API access level granted within this subscription
                        'type': 'integer',
                        'nullable': False,
                        'empty': False,
                        'required': True,
                    },
                    'config_item_limit': {  # Maximum number of config items allowed (minimum 1)
                        'type': 'integer',
                        'nullable': False,
                        'empty': False,
                        'required': True,
                        'min': 1,
                    },
                },
            },
        },
    }
