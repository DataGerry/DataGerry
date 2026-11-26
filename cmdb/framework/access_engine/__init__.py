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
The access engine: decides from the stored scope roles and assignments which objects a user may view, create, edit
and delete. Every access decision goes through it - the type ACL functions in ``cmdb.security.acl`` delegate here
"""
from cmdb.models.access_model import ScopeOperation
from .access_engine_constants import (
    ObjectState,
    AccessDecisionStep,
    PERMISSION_OPERATIONS,
    OPERATION_PERMISSIONS,
    OPERATION_STATES,
    FIELD_WRITING_OPERATIONS,
    MISSING_STATE_MESSAGE,
    TRANSLATED_ROLE_NAME,
    TRANSLATED_ROLE_TYPE_SINGULAR,
    TRANSLATED_ROLE_TYPE_PLURAL,
    TRANSLATED_ROLE_OPERATION_SEPARATOR,
    TRANSLATED_ROLE_NO_OPERATION,
    TRANSLATED_ROLE_NAME_SUFFIX,
    TRANSLATED_DESCRIPTION,
    OPERATION_REFUSED_MESSAGE,
    FIELDS_REFUSED_MESSAGE,
    ALLOWED_OPERATIONS_KEY,
)
from .access_type_set import TypeSet
from .access_grants import (
    GrantEntry,
    AccessGrants,
    role_operations,
    restricted_types,
    grant_entries,
    build_grants,
)
from .access_grants_reads import (
    GRANTS_CACHE_KEY,
    EVERY_ASSIGNMENT_KEY,
    read_grants,
    grants_cache_key,
    load_grants,
    load_access_rules,
    forget_grants,
)
from .acl_synthesis import group_entries, held_permission_values, synthesised_acls
from .access_denial import (
    NO_OPERATION_MESSAGE,
    DeniedTypes,
    operation_list,
    permission_operations,
    denied_for,
    denied_types_of,
    object_criteria,
    id_criteria,
    type_criteria,
    no_object_criteria,
    operations_allowed,
)
from .access_filters import (
    denied_types,
    denied_type_ids,
    scope_filter,
    record_scope_filter,
    type_reachable,
    permitted_types_criteria,
    type_allows,
    operations_on_types,
    allowed_operation_values,
    object_operation_values,
    synthesised_acl_values,
)
from .object_field_changes import TOP_LEVEL, field_values, changed_field_names, same_value
from .scope_evaluation import ConditionalGrant, ScopeEvaluation, load_scope_evaluation
from .access_decision import AccessDecision, judged_states, refused_fields, decide, can, refusal_message
from .type_acl_translation import (
    VALUE_OPERATIONS,
    TranslatedRole,
    acl_is_activated,
    granted_operations,
    group_rows,
    translate_type_acls,
    role_documents,
    assignment_documents,
)
from .type_acl_migration import (
    type_id_of,
    acl_allows,
    acl_differences,
    type_entries,
    inactive_type_ids,
    pending_report,
)
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'ObjectState',
    'AccessDecisionStep',
    'PERMISSION_OPERATIONS',
    'OPERATION_PERMISSIONS',
    'OPERATION_STATES',
    'TypeSet',
    'GrantEntry',
    'AccessGrants',
    'role_operations',
    'restricted_types',
    'grant_entries',
    'build_grants',
    'GRANTS_CACHE_KEY',
    'read_grants',
    'grants_cache_key',
    'load_grants',
    'forget_grants',
    'NO_OPERATION_MESSAGE',
    'DeniedTypes',
    'operation_list',
    'permission_operations',
    'denied_for',
    'denied_types_of',
    'object_criteria',
    'id_criteria',
    'type_criteria',
    'no_object_criteria',
    'operations_allowed',
    'denied_types',
    'denied_type_ids',
    'scope_filter',
    'record_scope_filter',
    'type_reachable',
    'ScopeOperation',
    'ScopeEvaluation',
    'ConditionalGrant',
    'load_scope_evaluation',
    'permitted_types_criteria',
    'type_allows',
    'operations_on_types',
    'allowed_operation_values',
    'object_operation_values',
    'synthesised_acl_values',
    'EVERY_ASSIGNMENT_KEY',
    'load_access_rules',
    'group_entries',
    'held_permission_values',
    'synthesised_acls',
    'ALLOWED_OPERATIONS_KEY',
    'FIELD_WRITING_OPERATIONS',
    'MISSING_STATE_MESSAGE',
    'TOP_LEVEL',
    'field_values',
    'changed_field_names',
    'same_value',
    'AccessDecision',
    'judged_states',
    'refused_fields',
    'decide',
    'can',
    'refusal_message',
    'OPERATION_REFUSED_MESSAGE',
    'FIELDS_REFUSED_MESSAGE',
    'TRANSLATED_ROLE_NAME',
    'TRANSLATED_ROLE_TYPE_SINGULAR',
    'TRANSLATED_ROLE_TYPE_PLURAL',
    'TRANSLATED_ROLE_OPERATION_SEPARATOR',
    'TRANSLATED_ROLE_NO_OPERATION',
    'TRANSLATED_ROLE_NAME_SUFFIX',
    'TRANSLATED_DESCRIPTION',
    'VALUE_OPERATIONS',
    'TranslatedRole',
    'acl_is_activated',
    'granted_operations',
    'group_rows',
    'translate_type_acls',
    'role_documents',
    'type_id_of',
    'acl_allows',
    'acl_differences',
    'type_entries',
    'inactive_type_ids',
    'pending_report',
    'assignment_documents',
]
