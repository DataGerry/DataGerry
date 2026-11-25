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
Validation schema for CmdbScopeRole

A CmdbScopeRole bundles what the permission system grants on a set of Types (collection ``access.scopeRoles``):
the operations - one set for all its Types - and which fields it may write, the regular ones and those of the named
field classes. Its Types are every Type (``*``, later ones included) or a list of Type ids; an empty list and an empty
operation set are legal, a role then grants nothing.

This module is the single source of the document's Cerberus validation schema,
consumed as CmdbScopeRole.SCHEMA.
"""
from typing import Any

from cmdb.class_schema.access_model.access_schema_helper import (
    check_not_blank,
    check_role_types,
    check_unique_values,
    get_description_rule,
    get_field_class_name_rule,
)
# -------------------------------------------------------------------------------------------------------------------- #

def get_cmdb_scope_role_schema() -> dict[str, Any]:
    """
    Builds the Cerberus validation schema for a CmdbScopeRole document

    Returns:
        dict[str, Any]: Field name to Cerberus rule mapping, consumed as CmdbScopeRole.SCHEMA
    """
    # pylint: disable=import-outside-toplevel
    # Resolved at call time, not at module import time: the model imports this builder while its own
    # package __init__ is still running (see class_schema/__init__.py)
    from cmdb.models.access_model.access_constants import MAX_ROLE_FIELD_CLASSES, NAME_MAX_LENGTH, ScopeRoleKey
    from cmdb.models.access_model.scope_operation_enum import ScopeOperation

    return {
        ScopeRoleKey.PUBLIC_ID.value: {  # public_id of the CmdbScopeRole
            'type': 'integer',
            'min': 1,
        },
        ScopeRoleKey.NAME.value: {  # The unique name the role is listed under
            'type': 'string',
            'required': True,
            'empty': False,
            'maxlength': NAME_MAX_LENGTH,
            'check_with': check_not_blank,
        },
        ScopeRoleKey.DESCRIPTION.value: get_description_rule(),  # What the role is for
        ScopeRoleKey.TYPES.value: {  # '*' (every Type, later ones included) or the ids of the Types it covers
            'type': ['string', 'list'],
            'required': True,
            'check_with': check_role_types,
        },
        ScopeRoleKey.OPERATIONS.value: {  # The operations it grants on its Types - one set for all of them
            'type': 'list',
            'required': True,
            'schema': {'type': 'string', 'allowed': [operation.value for operation in ScopeOperation]},
            'check_with': check_unique_values,
        },
        ScopeRoleKey.WRITE_REGULAR_FIELDS.value: {  # Whether it may write the fields carrying no field class
            'type': 'boolean',
            'required': False,
            'default': False,
        },
        ScopeRoleKey.FIELD_CLASSES.value: {  # The names of the field classes whose fields it may write
            'type': 'list',
            'required': False,
            'default': [],
            'maxlength': MAX_ROLE_FIELD_CLASSES,
            'schema': get_field_class_name_rule(),
            'check_with': check_unique_values,
        },
    }
