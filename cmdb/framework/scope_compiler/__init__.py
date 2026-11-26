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
The access scope compiler (ACL feature, phase 9): an assignment's scope as a list of conditions on the object, checked
and cast against the scope role's Types, compiled into a MongoDB filter
"""
from .scope_compiler_constants import (
    KIND_OPERATORS,
    MAX_LIST_VALUES,
    MAX_SCOPE_BLOCKS,
    MAX_TEXT_LENGTH,
    MULTIPLE_PERSON_KIND,
    RELATION_FILTER_KEY,
    RelativeDateKey,
    ScopeBlockKey,
    ScopeMessage,
    ScopeBlockKind,
    ScopeOperator,
    UserToken,
    UserTokenKey,
)
from .scope_grammar import (
    block_kind,
    canonical_blocks,
    is_relative_date,
    is_user_token,
    network_value,
    scope_shape_problems,
)
from .scope_fields import ScopeField, field_views, field_views_of_document, resolve_scope_fields
from .scope_casting import cast_scope, cast_value
from .scope_matcher import document_matches
from .scope_resolution import ScopeContext, ScopeReferences, ScopeResolver, scope_references
from .field_comparisons import EMPTY_VALUES, compile_block, compile_condition, compile_scope, resolve_date
from .scope_staleness import (
    is_conditional,
    role_change_problems,
    scope_field_names,
    token_markers,
    type_change_problems,
)
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'KIND_OPERATORS',
    'MAX_LIST_VALUES',
    'MAX_SCOPE_BLOCKS',
    'MAX_TEXT_LENGTH',
    'MULTIPLE_PERSON_KIND',
    'RELATION_FILTER_KEY',
    'ScopeBlockKind',
    'UserToken',
    'UserTokenKey',
    'block_kind',
    'is_user_token',
    'network_value',
    'ScopeContext',
    'ScopeReferences',
    'ScopeResolver',
    'scope_references',
    'compile_block',
    'document_matches',
    'token_markers',
    'RelativeDateKey',
    'ScopeBlockKey',
    'ScopeMessage',
    'ScopeOperator',
    'canonical_blocks',
    'is_relative_date',
    'scope_shape_problems',
    'ScopeField',
    'field_views',
    'field_views_of_document',
    'resolve_scope_fields',
    'cast_scope',
    'cast_value',
    'EMPTY_VALUES',
    'compile_condition',
    'compile_scope',
    'resolve_date',
    'is_conditional',
    'role_change_problems',
    'scope_field_names',
    'type_change_problems',
]
