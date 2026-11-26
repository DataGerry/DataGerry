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
Judges an assignment's scope against its role's Types (phase 9, ruled R29): the shape (``scope_shape_problems``), each
compared field resolved across the role's Types (``resolve_scope_fields``) and each value cast (``cast_scope``) - every
problem into the one 400 of the write. The scope stored is the cast one, in canonical form. ``"*"`` needs nothing
"""
from typing import Any

from cmdb.manager.types_manager import TypesManager
from cmdb.models.access_model import ALL_TYPES, UNCONDITIONAL_SCOPE, ScopeRoleKey
from cmdb.models.type_model import TypeSchemaKey
from cmdb.framework.scope_compiler import (
    canonical_blocks,
    cast_scope,
    field_views_of_document,
    resolve_scope_fields,
    scope_field_names,
    scope_shape_problems,
)
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'role_type_documents',
    'judge_scope',
]

_TYPE_FIELDS_PROJECTION: dict[str, int] = {'_id': 0, TypeSchemaKey.PUBLIC_ID.value: 1, TypeSchemaKey.FIELDS.value: 1,
                                           TypeSchemaKey.RENDER_META.value: 1}


def role_type_documents(role: dict[str, Any], types_manager: TypesManager) -> list[dict[str, Any]]:
    """
    The Types a scope role names, as much of them as a scope condition reads - every Type for a role on every Type

    Args:
        role (dict[str, Any]): The stored scope role
        types_manager (TypesManager): The Types of the request's database

    Raises:
        TypesManagerGetError: When the read fails

    Returns:
        list[dict[str, Any]]: The Type documents (``public_id``, ``fields``, ``render_meta``)
    """
    role_types: Any = role.get(ScopeRoleKey.TYPES.value)
    criteria: dict[str, Any] = {} if role_types == ALL_TYPES else \
        {TypeSchemaKey.PUBLIC_ID.value: {'$in': list(role_types or [])}}

    return types_manager.find(criteria=criteria, projection=_TYPE_FIELDS_PROJECTION)


def judge_scope(scope: Any, type_documents: list[dict[str, Any]]) -> tuple[Any, list[str]]:
    """
    Judges a scope against its role's Types

    Args:
        scope (Any): The scope as sent (the schema let through ``"*"`` or a list)
        type_documents (list[dict[str, Any]]): The role's Types (``role_type_documents``)

    Returns:
        tuple[Any, list[str]]: The scope to store - cast and canonical when it passed - and every problem
    """
    if scope == UNCONDITIONAL_SCOPE:
        return scope, []

    shape: list[str] = scope_shape_problems(scope)

    if shape:
        return scope, shape

    fields, resolution = resolve_scope_fields(scope_field_names({'scope': scope}),
                                              [field_views_of_document(document) for document in type_documents])
    cast, casting = cast_scope(scope, fields)
    problems: list[str] = resolution + casting

    return (scope if problems else canonical_blocks(cast)), problems
