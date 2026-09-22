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
Validation schema for CmdbUser

A CmdbUser is a DataGerry user account (collection ``management.users``).

This module is the single source of the document's Cerberus validation schema,
consumed as CmdbUser.SCHEMA.

**It validates the REQUEST BODY, not the stored document.** Its only consumers are the two write
routes, through ``build_write_schema(CmdbUser.SCHEMA)``. That is why ``registration_time`` is typed
``dict``: a datetime leaves the API as ``{'$date': millis}`` (``cmdb.database.json_codec.default``,
applied at the single serialization point in ``base_api_response``) and the frontend sends that same
wrapper back, because it PUTs the whole user it was given. What is STORED is a BSON date, and
``CmdbUser.registration_time`` is a ``datetime`` in between. Three shapes, one field; when this rule
changes, the one it describes is the wire.
"""
from typing import Any
# -------------------------------------------------------------------------------------------------------------------- #

DEFAULT_AUTHENTICATOR: str = 'LocalAuthenticationProvider'
DEFAULT_GROUP: int = 2
DEFAULT_API_LEVEL: int = 0
DEFAULT_CONFIG_ITEMS_LIMIT: int = 1000
# Database a CmdbUser belongs to when the document names none. Only meaningful in cloud mode, where
# each subscription owns its own database; on-premise every user lives in the single configured one
DEFAULT_DATABASE: str = 'test'

# -------------------------------------------------------------------------------------------------------------------- #
# pylint: disable=R0801
def get_cmdb_user_schema() -> dict[str, Any]:
    """
    Builds the Cerberus validation schema for a CmdbUser document

    The keys come from `CmdbUserKey` so the schema, `CmdbUser.from_data` and `CmdbUser.to_json`
    cannot drift apart. The import is deliberately INSIDE the builder: `cmdb.models` imports this
    module at class-definition time, so importing the model package at module level would close a
    cycle

    Returns:
        dict: Field name to Cerberus rule mapping, consumed as CmdbUser.SCHEMA
    """
    # pylint: disable=import-outside-toplevel
    from cmdb.models.user_model.cmdb_user_key_enum import CmdbUserKey

    return {
        CmdbUserKey.PUBLIC_ID.value: {
            'type': 'integer'
        },
        CmdbUserKey.USER_NAME.value: {
            'type': 'string',
            'required': True,
        },
        CmdbUserKey.ACTIVE.value: {
            'type': 'boolean',
            'default': True,
            'required': False
        },
        CmdbUserKey.GROUP_ID.value: {
            'type': 'integer',
            'default': DEFAULT_GROUP,
            'required': True
        },
        CmdbUserKey.REGISTRATION_TIME.value: {
            # The WIRE shape {'$date': millis}, not the stored one - see the module docstring.
            # CmdbUser.from_data casts it to a datetime through coerce_document_dates
            'type': 'dict',
            'nullable': True,
            'empty': True,
            'required': False
        },
        CmdbUserKey.AUTHENTICATOR.value: {
            'type': 'string',
            'nullable': True,
            'default': DEFAULT_AUTHENTICATOR,
            'required': False
        },
        CmdbUserKey.PASSWORD.value: {
            'type': 'string',
            'nullable': True,
            'empty': True,
            'required': False
        },
        CmdbUserKey.FIRST_NAME.value: {
            'type': 'string',
            'nullable': True,
            'empty': True,
            'required': False
        },
        CmdbUserKey.LAST_NAME.value: {
            'type': 'string',
            'nullable': True,
            'empty': True,
            'required': False
        },
        CmdbUserKey.EMAIL.value: {
            'type': 'string',
            'nullable': True,
            'empty': True,
            'required': False
        },
        CmdbUserKey.IMAGE.value: {
            'type': 'string',
            'nullable': True,
            'empty': True,
            'required': False
        },
        CmdbUserKey.DATABASE.value: {
            'type': 'string',
            'nullable': True,
            'empty': True,
            'required': False
        },
        CmdbUserKey.API_LEVEL.value: {
            'type': 'integer',
            'nullable': True,
            'empty': True,
            'default': DEFAULT_API_LEVEL,
            'required': False
        },
        CmdbUserKey.CONFIG_ITEMS_LIMIT.value: {
            'type': 'integer',
            'nullable': True,
            'empty': True,
            'default': DEFAULT_CONFIG_ITEMS_LIMIT,
            'required': False
        }
    }
