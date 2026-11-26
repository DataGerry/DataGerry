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
Keeps stored scopes valid (phase 9 step 3, ruled R11): a write that would leave a stored condition comparing a field its
Types no longer carry - or carry with another kind - is refused, naming the assignments

* **A Type update** may not remove, retype, or move into a multi-data section a field the scope of an assignment
  covering the Type compares, nor stop a person selector compared with a user token selecting that token's kind
  (``type_change_problems``). A Type that did not carry the field is not judged.
* **A scope role update** may not give a conditional assignment of the role a Type set on which its conditions no
  longer resolve or cast (``role_change_problems``) - a Type without the field is fine (its objects never match).

Pure: the callers read the stored assignments covering the Type / of the role, and the Types
"""
from typing import Any, Iterable

from cmdb.models.access_model import UNCONDITIONAL_SCOPE, AccessAssignmentKey
from cmdb.framework.scope_compiler.scope_casting import TOKEN_MARKERS, cast_scope
from cmdb.framework.scope_compiler.scope_compiler_constants import ScopeBlockKey, ScopeMessage, UserTokenKey
from cmdb.framework.scope_compiler.scope_fields import ScopeField, resolve_scope_fields
from cmdb.framework.scope_compiler.scope_grammar import is_user_token, scope_shape_problems
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'is_conditional',
    'scope_field_names',
    'token_markers',
    'type_change_problems',
    'role_change_problems',
]


def is_conditional(assignment: dict[str, Any]) -> bool:
    """
    Whether an assignment's scope is a condition list rather than ``"*"``

    Args:
        assignment (dict[str, Any]): A stored assignment

    Returns:
        bool: True for a list scope
    """
    scope: Any = assignment.get(AccessAssignmentKey.SCOPE.value, UNCONDITIONAL_SCOPE)

    return isinstance(scope, list) and not scope_shape_problems(scope)


def scope_field_names(assignment: dict[str, Any]) -> list[str]:
    """
    The field names an assignment's scope compares, each once, in order

    Args:
        assignment (dict[str, Any]): A stored assignment

    Returns:
        list[str]: The names; empty for ``"*"``
    """
    if not is_conditional(assignment):
        return []

    return list(dict.fromkeys(block[ScopeBlockKey.FIELD.value]
                              for block in assignment[AccessAssignmentKey.SCOPE.value]
                              if ScopeBlockKey.FIELD.value in block))


def token_markers(assignment: dict[str, Any]) -> dict[str, set[str]]:
    """
    The special types each field compared with a user token must stay selecting

    Args:
        assignment (dict[str, Any]): A stored assignment

    Returns:
        dict[str, set[str]]: Per field name, PERSON and / or PERSON_GROUP; empty for '*' or no token
    """
    if not is_conditional(assignment):
        return {}

    markers: dict[str, set[str]] = {}

    for block in assignment[AccessAssignmentKey.SCOPE.value]:
        value: Any = block.get(ScopeBlockKey.VALUE.value)

        if is_user_token(value):
            markers.setdefault(block[ScopeBlockKey.FIELD.value], set()).add(
                TOKEN_MARKERS[value[UserTokenKey.USER.value]])

    return markers


def type_change_problems(type_id: int, before: dict[str, ScopeField], after: dict[str, ScopeField],
                         assignments: Iterable[dict[str, Any]]) -> list[str]:
    """
    Why a Type update would leave stored scopes comparing a field it no longer carries as they compare it

    Args:
        type_id (int): The Type's public_id
        before (dict[str, ScopeField]): The stored Type's fields (``field_views``)
        after (dict[str, ScopeField]): The fields the update would store
        assignments (Iterable[dict[str, Any]]): The stored assignments whose role covers the Type

    Returns:
        list[str]: One problem per field removed, retyped or moved into a multi-data section, naming the assignments
            comparing it; empty when none
    """
    users: dict[str, list[int]] = {}
    token_users: dict[tuple[str, str], list[int]] = {}
    listed: list[dict[str, Any]] = list(assignments)

    for assignment in listed:
        for name in scope_field_names(assignment):
            users.setdefault(name, []).append(assignment[AccessAssignmentKey.PUBLIC_ID.value])

        for name, markers in token_markers(assignment).items():
            for marker in markers:
                token_users.setdefault((name, marker), []).append(assignment[AccessAssignmentKey.PUBLIC_ID.value])

    problems: list[str] = []

    for name, assignment_ids in users.items():
        stored: ScopeField | None = before.get(name)
        updated: ScopeField | None = after.get(name)

        if stored is None:
            continue

        if updated is None or updated.kind != stored.kind or (updated.in_mds and not stored.in_mds):
            problems.append(ScopeMessage.STALE_ON_TYPE.value.format(field=name, type_id=type_id,
                                                                    assignment_ids=sorted(assignment_ids)))

    for (name, marker), assignment_ids in sorted(token_users.items()):
        stored = before.get(name)
        updated = after.get(name)

        if stored is not None and updated is not None and updated.kind == stored.kind \
                and marker in stored.selectable and marker not in updated.selectable:
            problems.append(ScopeMessage.STALE_SELECTABLE.value.format(field=name, type_id=type_id, kind=marker,
                                                                       assignment_ids=sorted(assignment_ids)))

    return problems


def role_change_problems(role_id: int, assignments: Iterable[dict[str, Any]],
                         types: list[dict[str, ScopeField]]) -> list[str]:
    """
    Why a scope role update would leave the conditions of its assignments unresolvable on its new Types

    Args:
        role_id (int): The role's public_id
        assignments (Iterable[dict[str, Any]]): The role's stored assignments
        types (list[dict[str, ScopeField]]): The Types the updated role names, as ``field_views``

    Returns:
        list[str]: One problem per conditional assignment whose conditions no longer resolve or cast
    """
    problems: list[str] = []

    for assignment in assignments:
        if not is_conditional(assignment):
            continue

        scope: list[dict[str, Any]] = assignment[AccessAssignmentKey.SCOPE.value]
        fields, resolution = resolve_scope_fields(scope_field_names(assignment), types)
        _cast, casting = cast_scope(scope, fields)

        if resolution or casting:
            problems.append(ScopeMessage.STALE_ON_ROLE.value.format(
                role_id=role_id, assignment_id=assignment[AccessAssignmentKey.PUBLIC_ID.value],
                problems=' '.join(resolution + casting)))

    return problems
