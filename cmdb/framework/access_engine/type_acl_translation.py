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
The type ACLs translated into scope roles and assignments that decide exactly as the ACLs do - pure, no reads

A Type whose ACL is activated becomes restricted: each existing group it grants operations gets them through a scope
role. Groups holding exactly the same operations on exactly the same Types share one role, assigned to each of them.
A Type whose activated ACL grants no existing group anything stays restricted through one role without operations,
assigned to the administrator group. An ACL that is absent or not activated restricts nothing and is not translated.
A group that no longer exists is dropped. Every role writes regular fields - an ACL never restricted fields
"""
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from cmdb.models.access_model import (
    AccessAssignmentKey,
    ScopeOperation,
    ScopeRoleKey,
    UNCONDITIONAL_SCOPE,
)
from cmdb.models.type_model.type_schema_key_enum import TypeSchemaKey
from cmdb.security.acl.acl_constants import AclKey
from cmdb.security.acl.acl_groups import group_permissions
from cmdb.framework.access_engine.access_engine_constants import (
    PERMISSION_OPERATIONS,
    TRANSLATED_DESCRIPTION,
    TRANSLATED_ROLE_NAME,
    TRANSLATED_ROLE_NAME_SUFFIX,
    TRANSLATED_ROLE_NO_OPERATION,
    TRANSLATED_ROLE_OPERATION_SEPARATOR,
    TRANSLATED_ROLE_TYPE_PLURAL,
    TRANSLATED_ROLE_TYPE_SINGULAR,
)
# -------------------------------------------------------------------------------------------------------------------- #

# The scope operation each stored ACL permission value reads as
VALUE_OPERATIONS: dict[str, ScopeOperation] = {
    permission.value: operation for permission, operation in PERMISSION_OPERATIONS.items()
}


@dataclass(frozen=True)
class TranslatedRole:
    """
    One scope role translated from the type ACLs and the groups it is assigned to

    Attributes:
        name (str): Its unique name
        types (tuple[int, ...]): The Types it names, ascending
        operations (tuple[ScopeOperation, ...]): The operations it grants, in ScopeOperation order - none for a
            Type whose ACL grants nobody
        group_ids (tuple[int, ...]): The groups it is assigned to, ascending
    """
    name: str
    types: tuple[int, ...]
    operations: tuple[ScopeOperation, ...]
    group_ids: tuple[int, ...]


def acl_is_activated(type_document: Mapping[str, Any]) -> bool:
    """
    Whether a stored Type's ACL is switched on - ``activated: true`` and nothing else, the reading every ACL check has

    Args:
        type_document (Mapping[str, Any]): The stored Type

    Returns:
        bool: True when it is
    """
    acl: Any = type_document.get(TypeSchemaKey.ACL.value)

    return isinstance(acl, dict) and acl.get(AclKey.ACTIVATED.value) is True


def granted_operations(values: Iterable[str]) -> frozenset[ScopeOperation]:
    """
    The scope operations a group's stored ACL permission values grant; a value that is no permission grants nothing

    Args:
        values (Iterable[str]): The stored values

    Returns:
        frozenset[ScopeOperation]: The operations
    """
    return frozenset(VALUE_OPERATIONS[value] for value in values if value in VALUE_OPERATIONS)


def group_rows(type_documents: Iterable[Mapping[str, Any]], existing_group_ids: Collection[int]
               ) -> tuple[dict[int, dict[frozenset[ScopeOperation], set[int]]], set[int]]:
    """
    Reads the activated ACLs as rows per group: the Types it holds each set of operations on - and the Types granting
    no existing group anything

    Args:
        type_documents (Iterable[Mapping[str, Any]]): The stored Types (public_id and acl are read)
        existing_group_ids (Collection[int]): Every group that exists

    Returns:
        tuple[dict[int, dict[frozenset[ScopeOperation], set[int]]], set[int]]: ``{group: {operations: {Types}}}``
            and the Types granting nobody
    """
    existing: set[int] = set(existing_group_ids)
    rows: dict[int, dict[frozenset[ScopeOperation], set[int]]] = {}
    granting_nobody: set[int] = set()

    for type_document in type_documents:
        type_id: Any = type_document.get(TypeSchemaKey.PUBLIC_ID.value)

        if not isinstance(type_id, int) or isinstance(type_id, bool) or not acl_is_activated(type_document):
            continue

        granted: bool = False

        for group_id, values in group_permissions(type_document.get(TypeSchemaKey.ACL.value)).items():
            operations: frozenset[ScopeOperation] = granted_operations(values)

            if group_id in existing and operations:
                rows.setdefault(group_id, {}).setdefault(operations, set()).add(type_id)
                granted = True

        if not granted:
            granting_nobody.add(type_id)

    return rows, granting_nobody


def translate_type_acls(type_documents: Iterable[Mapping[str, Any]], existing_group_ids: Collection[int],
                        admin_group_id: int, taken_names: Collection[str] = ()) -> tuple[TranslatedRole, ...]:
    """
    Translates the stored type ACLs into scope roles, each with the groups it is assigned to

    Args:
        type_documents (Iterable[Mapping[str, Any]]): The stored Types (public_id and acl are read)
        existing_group_ids (Collection[int]): Every group that exists - a grant to another group is dropped
        admin_group_id (int): The administrator group - it holds the role keeping a Type granting nobody restricted
        taken_names (Collection[str]): Role names already stored - a translated name never takes one, its numbering
            continues past them. Defaults to none

    Returns:
        tuple[TranslatedRole, ...]: The roles, ordered by operations then Types; names unique, also against the taken
    """
    rows, granting_nobody = group_rows(type_documents, existing_group_ids)
    holders: dict[tuple[frozenset[ScopeOperation], frozenset[int]], set[int]] = {}

    for group_id, group_rows_by_operations in rows.items():
        for operations, type_ids in group_rows_by_operations.items():
            holders.setdefault((operations, frozenset(type_ids)), set()).add(group_id)

    if granting_nobody:
        holders.setdefault((frozenset(), frozenset(granting_nobody)), set()).add(admin_group_id)

    ordered: list[tuple[tuple[ScopeOperation, ...], tuple[int, ...], tuple[int, ...]]] = []

    for operations, type_ids in sorted(holders, key=_role_order):
        ordered.append((_ordered_operations(operations), tuple(sorted(type_ids)),
                        tuple(sorted(holders[(operations, type_ids)]))))

    return _named(ordered, frozenset(taken_names))


def role_documents(roles: Iterable[TranslatedRole], first_role_id: int) -> list[dict[str, Any]]:
    """
    The scope role documents to store, numbered from a first public_id in order

    Args:
        roles (Iterable[TranslatedRole]): The translated roles
        first_role_id (int): The public_id of the first role

    Returns:
        list[dict[str, Any]]: The documents
    """
    return [{
        ScopeRoleKey.PUBLIC_ID.value: first_role_id + index,
        ScopeRoleKey.NAME.value: role.name,
        ScopeRoleKey.DESCRIPTION.value: TRANSLATED_DESCRIPTION,
        ScopeRoleKey.TYPES.value: list(role.types),
        ScopeRoleKey.OPERATIONS.value: [operation.value for operation in role.operations],
        ScopeRoleKey.WRITE_REGULAR_FIELDS.value: True,
        ScopeRoleKey.FIELD_CLASSES.value: [],
    } for index, role in enumerate(roles)]


def assignment_documents(roles: Iterable[TranslatedRole], first_role_id: int, first_assignment_id: int
                         ) -> list[dict[str, Any]]:
    """
    The assignment documents to store: each role to each of its groups, numbered in order

    Args:
        roles (Iterable[TranslatedRole]): The translated roles, in the order their documents were numbered
        first_role_id (int): The public_id of the first role
        first_assignment_id (int): The public_id of the first assignment

    Returns:
        list[dict[str, Any]]: The documents
    """
    pairs: list[tuple[int, int]] = [(first_role_id + index, group_id)
                                    for index, role in enumerate(roles) for group_id in role.group_ids]

    return [{
        AccessAssignmentKey.PUBLIC_ID.value: first_assignment_id + index,
        AccessAssignmentKey.GROUP_ID.value: group_id,
        AccessAssignmentKey.ROLE_ID.value: role_id,
        AccessAssignmentKey.SCOPE.value: UNCONDITIONAL_SCOPE,
        AccessAssignmentKey.DESCRIPTION.value: TRANSLATED_DESCRIPTION,
    } for index, (role_id, group_id) in enumerate(pairs)]


def _ordered_operations(operations: frozenset[ScopeOperation]) -> tuple[ScopeOperation, ...]:
    """
    Operations in ScopeOperation order

    Args:
        operations (frozenset[ScopeOperation]): The operations

    Returns:
        tuple[ScopeOperation, ...]: In order
    """
    return tuple(operation for operation in ScopeOperation if operation in operations)


def _role_order(key: tuple[frozenset[ScopeOperation], frozenset[int]]) -> tuple[list[int], list[int]]:
    """
    The order roles are listed in: by their operations (ScopeOperation order), then their Types

    Args:
        key (tuple[frozenset[ScopeOperation], frozenset[int]]): A role's operations and Types

    Returns:
        tuple[list[int], list[int]]: The sort key
    """
    members: list[ScopeOperation] = list(ScopeOperation)
    operations, type_ids = key

    return sorted(members.index(operation) for operation in operations), sorted(type_ids)


def _named(roles: list[tuple[tuple[ScopeOperation, ...], tuple[int, ...], tuple[int, ...]]],
           taken_names: frozenset[str] = frozenset()) -> tuple[TranslatedRole, ...]:
    """
    Names the roles: their operations and Type count, a number appended from the second role of a name on - and
    past every number a taken name already holds

    Args:
        roles (list[tuple[tuple[ScopeOperation, ...], tuple[int, ...], tuple[int, ...]]]): Operations, Types and
            groups of each role, in order
        taken_names (frozenset[str]): Names a role may not take. Defaults to none

    Returns:
        tuple[TranslatedRole, ...]: The named roles
    """
    seen: dict[str, int] = {}
    named: list[TranslatedRole] = []

    for operations, type_ids, group_ids in roles:
        base: str = TRANSLATED_ROLE_NAME.format(
            operations=(TRANSLATED_ROLE_OPERATION_SEPARATOR.join(operation.value for operation in operations)
                        or TRANSLATED_ROLE_NO_OPERATION),
            count=len(type_ids),
            types=TRANSLATED_ROLE_TYPE_SINGULAR if len(type_ids) == 1 else TRANSLATED_ROLE_TYPE_PLURAL,
        )
        name: str = _next_free_name(base, seen, taken_names)
        named.append(TranslatedRole(name=name, types=type_ids, operations=operations, group_ids=group_ids))

    return tuple(named)


def _next_free_name(base: str, seen: dict[str, int], taken_names: frozenset[str]) -> str:
    """
    The next name of a base no role took yet: the base itself first, then ``base #2``, ``base #3`` ... - a taken name
    is skipped

    Args:
        base (str): The name the role's operations and Types give
        seen (dict[str, int]): How far each base is numbered, changed in place
        taken_names (frozenset[str]): Names a role may not take

    Returns:
        str: The name
    """
    while True:
        seen[base] = seen.get(base, 0) + 1
        name: str = base if seen[base] == 1 else base + TRANSLATED_ROLE_NAME_SUFFIX.format(number=seen[base])

        if name not in taken_names:
            return name
