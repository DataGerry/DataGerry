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
Constants of the access engine: how a type ACL permission reads as a scope operation, which state of an object each
operation is judged on, and the steps a decision names
"""
from types import MappingProxyType
from collections.abc import Mapping

from cmdb.utils import BaseStrEnum
from cmdb.models.access_model import ScopeOperation
from cmdb.security.acl.permission import AccessControlPermission
# -------------------------------------------------------------------------------------------------------------------- #


class ObjectState(BaseStrEnum):
    """
    The states of an object an operation can be judged on

    Values:
        BEFORE: The object as it is stored
        AFTER: The object as it would be stored
    """
    BEFORE = 'before'
    AFTER = 'after'


class AccessDecisionStep(BaseStrEnum):
    """
    The step that decided an access decision - what a trace names as the reason

    Values:
        UNRESTRICTED: Allowed - no assignment restricts the object's Type
        SCOPE: Decided by the assignments - one of the user's grants the operation on the Type, or none does
        FIELD_CLASS: Refused - a changed field is one the roles granting the operation may not write
    """
    UNRESTRICTED = 'unrestricted'
    SCOPE = 'scope'
    FIELD_CLASS = 'field_class'


# The scope operation each type ACL permission reads as - the type ACL's READ is the engine's view, its UPDATE edit
PERMISSION_OPERATIONS: Mapping[AccessControlPermission, ScopeOperation] = MappingProxyType({
    AccessControlPermission.READ: ScopeOperation.VIEW,
    AccessControlPermission.CREATE: ScopeOperation.CREATE,
    AccessControlPermission.UPDATE: ScopeOperation.EDIT,
    AccessControlPermission.DELETE: ScopeOperation.DELETE,
})

# The type ACL permission each scope operation was - the reverse of PERMISSION_OPERATIONS
OPERATION_PERMISSIONS: Mapping[ScopeOperation, AccessControlPermission] = MappingProxyType(
    {operation: permission for permission, operation in PERMISSION_OPERATIONS.items()}
)

# The states of an object each operation is judged on: view and delete the stored object, create the object as it
# would be stored, edit both - so nobody pushes an object out of their reach or into someone else's
OPERATION_STATES: Mapping[ScopeOperation, tuple[ObjectState, ...]] = MappingProxyType({
    ScopeOperation.VIEW: (ObjectState.BEFORE,),
    ScopeOperation.CREATE: (ObjectState.AFTER,),
    ScopeOperation.EDIT: (ObjectState.BEFORE, ObjectState.AFTER),
    ScopeOperation.DELETE: (ObjectState.BEFORE,),
})

# The operations that write field values - their changed fields must each be writable
FIELD_WRITING_OPERATIONS: frozenset[ScopeOperation] = frozenset({ScopeOperation.CREATE, ScopeOperation.EDIT})

# The message of a decision missing a state its operation is judged on
MISSING_STATE_MESSAGE: str = "The operation '{operation}' is judged on the object {state} - it was not given!"

# The name of a scope role translated from the type ACLs: its operations, then how many Types it covers
TRANSLATED_ROLE_NAME: str = '{operations} on {count} {types} (translated from the type ACL)'
TRANSLATED_ROLE_TYPE_SINGULAR: str = 'Type'
TRANSLATED_ROLE_TYPE_PLURAL: str = 'Types'
TRANSLATED_ROLE_OPERATION_SEPARATOR: str = ', '

# How a translated role granting no operation is named in place of its operations
TRANSLATED_ROLE_NO_OPERATION: str = 'No access'

# What sets two translated roles of the same name apart
TRANSLATED_ROLE_NAME_SUFFIX: str = ' #{number}'

# The description of every scope role and assignment translated from the type ACLs
TRANSLATED_DESCRIPTION: str = 'Translated from the type ACL'

# What a refused object write says: the Type the operation is not allowed on, or the fields that may not be written
OPERATION_REFUSED_MESSAGE: str = "You may not {operation} objects of Type {type_id}!"
FIELDS_REFUSED_MESSAGE: str = "You may not write the fields {names} of objects of Type {type_id}!"

# The key a Type answer carries the caller's allowed operations under - what a screen shows or hides its actions by
ALLOWED_OPERATIONS_KEY: str = 'allowed_operations'
