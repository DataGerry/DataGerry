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
from cmdb.models.right_model.right_constants import ObjectRightName
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


class FieldAccess(BaseStrEnum):
    """What a user may do with one field of an object in an edit (phase 12, D8)"""
    WRITE = 'write'
    READ = 'read'
    SYSTEM = 'system'


class ExplainStep(BaseStrEnum):
    """
    What decided one operation of an explanation - the checks before the engine, then the engine's own steps

    Values:
        USER_INACTIVE: Refused - the user may not log in
        FUNCTIONAL_RIGHT: Refused - the user's groups lack the object right of the operation
        TYPE_INACTIVE: Refused - a write on an object of a deactivated Type
        UNRESTRICTED / SCOPE / FIELD_CLASS: The engine's step (``AccessDecisionStep``)
    """
    USER_INACTIVE = 'user_inactive'
    FUNCTIONAL_RIGHT = 'functional_right'
    TYPE_INACTIVE = 'type_inactive'
    UNRESTRICTED = 'unrestricted'
    SCOPE = 'scope'
    FIELD_CLASS = 'field_class'


class ExplainVerdict(BaseStrEnum):
    """
    A user group's answer for one operation: allowed, denied, or decided by a condition naming the member (a user
    token) - then only the explanation of a member answers
    """
    ALLOWED = 'allowed'
    DENIED = 'denied'
    DEPENDS_ON_MEMBER = 'depends_on_member'


class ExplainKey(BaseStrEnum):
    """The keys of an explanation"""
    OPERATION = 'operation'
    ALLOWED = 'allowed'
    VERDICT = 'verdict'
    STEP = 'step'
    RIGHT = 'right'
    ASSIGNMENT_IDS = 'assignment_ids'
    REFUSED_FIELDS = 'refused_fields'
    ASSIGNMENT_ID = 'assignment_id'
    GROUP_ID = 'group_id'
    ROLE_ID = 'role_id'
    OPERATIONS = 'operations'
    UNCONDITIONAL = 'unconditional'
    CONDITIONS = 'conditions'
    CONDITION = 'condition'
    MET = 'met'
    MATCHED = 'matched'
    GRANTS_HERE = 'grants_here'
    NAME = 'name'
    ACCESS = 'access'
    SET_BY = 'set_by'
    RULE_ID = 'rule_id'
    RULE_NAME = 'rule_name'


# The operations an explanation answers, in this order, and the object right each one needs
EXPLAINED_OPERATIONS: tuple[ScopeOperation, ...] = (ScopeOperation.VIEW, ScopeOperation.CREATE, ScopeOperation.EDIT,
                                                    ScopeOperation.DELETE)
OPERATION_RIGHTS: Mapping[ScopeOperation, str] = MappingProxyType({
    ScopeOperation.VIEW: ObjectRightName.VIEW.value,
    ScopeOperation.CREATE: ObjectRightName.ADD.value,
    ScopeOperation.EDIT: ObjectRightName.EDIT.value,
    ScopeOperation.DELETE: ObjectRightName.DELETE.value,
})
