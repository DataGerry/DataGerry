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
Nobody gives a user group they are in more than they hold themselves - the escalation rule of assignments and scope
roles

A scope role assigned to one of the caller's own groups - by an assignment write, or by changing a role already
assigned to one - may grant only what the caller's own grants already allow: each operation on each of its Types,
and writing fields wherever it grants a writing operation with ``write_regular_fields``. A role on every Type needs
the operation on every restricted Type. Judged against the caller's grants before the write
"""
from collections.abc import Collection, Mapping
from typing import Any

from cmdb.models.access_model import ScopeOperation, ScopeRoleKey
from cmdb.framework.access_engine import (
    FIELD_WRITING_OPERATIONS,
    AccessGrants,
    TypeSet,
    role_operations,
)
from cmdb.framework.access_rules.access_rule_constants import AccessRuleMessage, ReachPart
# -------------------------------------------------------------------------------------------------------------------- #


def types_beyond(allowed: TypeSet, restricted: TypeSet, role_types: TypeSet) -> TypeSet:
    """
    The role's Types the caller is not allowed - an unrestricted Type is allowed to everyone

    Args:
        allowed (TypeSet): The restricted Types the caller holds the permission on
        restricted (TypeSet): The restricted Types
        role_types (TypeSet): The Types the role names

    Returns:
        TypeSet: Every Type when the role names every Type and the caller lacks a restricted one; else the role's
            restricted ids the caller lacks; empty when nothing is beyond
    """
    if role_types.every_type:
        return TypeSet() if allowed.covers(restricted) else TypeSet.everything()

    return TypeSet.of(type_id for type_id in role_types.ids
                      if restricted.contains(type_id) and not allowed.contains(type_id))


def beyond_reach(grants: AccessGrants, role: Mapping[str, Any]) -> list[str]:
    """
    What a scope role grants beyond the caller's own grants

    Args:
        grants (AccessGrants): The caller's grants
        role (Mapping[str, Any]): The scope role as it would be stored

    Returns:
        list[str]: Each operation (and the field writing) the role grants on Types the caller lacks it on, in
            ScopeOperation order; empty when the role stays within the caller's reach
    """
    role_types: TypeSet = TypeSet.from_role_types(role.get(ScopeRoleKey.TYPES.value))
    operations: frozenset[ScopeOperation] = role_operations(role)
    beyond: list[str] = []

    for operation in [member for member in ScopeOperation if member in operations]:
        lacking: TypeSet = types_beyond(grants.granted[operation], grants.restricted, role_types)

        if not lacking.is_empty():
            beyond.append(ReachPart.OPERATION.value.format(operation=operation.value, types=_types_text(lacking)))

    writing: set[ScopeOperation] = set(operations & FIELD_WRITING_OPERATIONS)

    if role.get(ScopeRoleKey.WRITE_REGULAR_FIELDS.value) is True and writing:
        lacking_fields: TypeSet = TypeSet.union_of(
            types_beyond(grants.regular_write[operation], grants.restricted, role_types) for operation in writing
        )

        if not lacking_fields.is_empty():
            beyond.append(ReachPart.REGULAR_FIELDS.value.format(types=_types_text(lacking_fields)))

    return beyond


def own_reach_problem(grants: AccessGrants, role_id: int, role: Mapping[str, Any], group_ids: Collection[int],
                      caller_group_ids: Collection[int]) -> str | None:
    """
    Refuses a scope role reaching one of the caller's own groups with more than the caller holds

    Args:
        grants (AccessGrants): The caller's grants, as they are before the write
        role_id (int): The role's public_id
        role (Mapping[str, Any]): The role as it would be stored
        group_ids (Collection[int]): The groups the role is (to be) assigned to
        caller_group_ids (Collection[int]): The caller's groups

    Returns:
        str | None: The problem, or None when no own group is reached or the role stays within reach
    """
    if not set(group_ids) & set(caller_group_ids):
        return None

    beyond: list[str] = beyond_reach(grants, role)

    if not beyond:
        return None

    beyond_text: str = ReachPart.SEPARATOR.value.join(beyond)

    return AccessRuleMessage.BEYOND_OWN_REACH.value.format(role_id=role_id, beyond=beyond_text)


def _types_text(type_set: TypeSet) -> str:
    """
    A Type set as a refusal names it

    Args:
        type_set (TypeSet): The Types

    Returns:
        str: ``every Type`` or ``Types [ids]`` ascending
    """
    if type_set.every_type:
        return ReachPart.EVERY_TYPE.value

    return ReachPart.TYPE_IDS.value.format(ids=sorted(type_set.ids))
