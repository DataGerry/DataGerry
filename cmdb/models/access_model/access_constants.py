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
Constants of the permission data model: the keys of field classes, scope roles and assignments, the reserved values
and the caps their documents are held to
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #


class FieldClassKey(BaseStrEnum):
    """
    Keys of a stored field class - a named protection class a type field can carry

    Attributes:
        PUBLIC_ID: The field class's public_id
        NAME: Its identifier, the value a field and a scope role reference - unique and immutable
        LABEL: The name it is shown under, freely editable
        DESCRIPTION: What the class protects
    """
    PUBLIC_ID = 'public_id'
    NAME = 'name'
    LABEL = 'label'
    DESCRIPTION = 'description'


class ScopeRoleKey(BaseStrEnum):
    """
    Keys of a stored scope role - the operations and writable fields it grants on its Types, reusable across groups

    Attributes:
        PUBLIC_ID: The scope role's public_id
        NAME: The unique name it is listed under
        DESCRIPTION: What the role is for
        TYPES: ``ALL_TYPES`` (every Type, also later ones) or the public_ids of the CmdbTypes it covers
        OPERATIONS: The ``ScopeOperation`` values it grants, one set for all its Types
        WRITE_REGULAR_FIELDS: Whether it may write the fields that carry no field class
        FIELD_CLASSES: The names of the field classes whose fields it may write
    """
    PUBLIC_ID = 'public_id'
    NAME = 'name'
    DESCRIPTION = 'description'
    TYPES = 'types'
    OPERATIONS = 'operations'
    WRITE_REGULAR_FIELDS = 'write_regular_fields'
    FIELD_CLASSES = 'field_classes'


class AccessAssignmentKey(BaseStrEnum):
    """
    Keys of a stored assignment - a user group granted a scope role within a scope

    Attributes:
        PUBLIC_ID: The assignment's public_id
        GROUP_ID: The public_id of the CmdbUserGroup it grants to
        ROLE_ID: The public_id of the scope role it grants
        SCOPE: The objects it applies to - ``UNCONDITIONAL_SCOPE`` for all of the role's Types
        DESCRIPTION: What the assignment is for
    """
    PUBLIC_ID = 'public_id'
    GROUP_ID = 'group_id'
    ROLE_ID = 'role_id'
    SCOPE = 'scope'
    DESCRIPTION = 'description'


# The built-in field class: its fields are written only by the server. A code constant, never stored - the name is
# reserved, so no stored field class can take it
SYSTEM_FIELD_CLASS: str = 'system'

# A field class name: a lowercase slug of at most 64 characters, starting with a letter
FIELD_CLASS_NAME_PATTERN: str = r'^[a-z][a-z0-9_-]{0,63}$'

# A scope role's TYPES value covering every Type, including the ones created later
ALL_TYPES: str = '*'

# An assignment's SCOPE value matching every object of the role's Types
UNCONDITIONAL_SCOPE: str = '*'

# The names of the indexes serving a group's and a role's assignments in public_id order
ASSIGNMENT_GROUP_INDEX_NAME: str = 'group_id_public_id'
ASSIGNMENT_ROLE_INDEX_NAME: str = 'role_id_public_id'

# The name of the index storing one group, role and scope once
ASSIGNMENT_UNIQUE_INDEX_NAME: str = 'group_role_scope'

# The longest scope role name
NAME_MAX_LENGTH: int = 255

# The longest field class label
LABEL_MAX_LENGTH: int = 255

# The longest description of a field class, a scope role or an assignment
DESCRIPTION_MAX_LENGTH: int = 4000

# The most Types a scope role may list
MAX_ROLE_TYPES: int = 5000

# The most field classes a scope role may grant
MAX_ROLE_FIELD_CLASSES: int = 1000

# The schema messages of the permission data model, read by Cerberus' error reporter after the field name
RESERVED_FIELD_CLASS_MSG: str = "is reserved for the built-in field class '{name}'"
NOT_BLANK_MSG: str = 'must not be blank'
VALUES_NOT_UNIQUE_MSG: str = 'names a value more than once: {values}'
ROLE_TYPES_SHAPE_MSG: str = "must be '{all_types}' (every Type) or a list of Type ids"
ROLE_TYPES_TOO_MANY_MSG: str = 'lists more than {limit} Types'
SCOPE_SHAPE_MSG: str = "A scope is '{unconditional}' (every object of the role's Types) or a list of conditions"
