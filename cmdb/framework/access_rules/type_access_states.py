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
What a change to the assignments or scope roles does to each Type, over every user group - pure, no reads

A Type is **open** when no assigned role names it (everybody may do everything), **viewable** when some assignment
with the unconditional scope grants view on it, else **locked** (restricted, and nobody may view it). A change is
refused when it locks a Type that was not locked, and - unless confirmed - when it opens a Type that was restricted
"""
from collections.abc import Iterable, Mapping
from typing import Any

from cmdb.utils import BaseStrEnum
from cmdb.models.access_model import AccessAssignmentKey, ScopeOperation, ScopeRoleKey, UNCONDITIONAL_SCOPE
from cmdb.framework.access_engine import TypeSet, restricted_types, role_operations
from cmdb.framework.access_rules.access_rule_constants import AccessRuleMessage
# -------------------------------------------------------------------------------------------------------------------- #


class TypeAccessState(BaseStrEnum):
    """
    What every user group together may do with a Type

    Values:
        OPEN: No assigned role names it - everybody may do everything
        VIEWABLE: Some group may view it
        LOCKED: Assigned roles restrict it, and no group may view it
    """
    OPEN = 'open'
    VIEWABLE = 'viewable'
    LOCKED = 'locked'


def assigned_roles(assignments: Iterable[Mapping[str, Any]], roles_by_id: Mapping[int, Mapping[str, Any]]
                   ) -> list[Mapping[str, Any]]:
    """
    The roles some assignment grants - any group's - each once

    Args:
        assignments (Iterable[Mapping[str, Any]]): Every stored assignment
        roles_by_id (Mapping[int, Mapping[str, Any]]): The roles by public_id; an assignment of a role not among
            them grants and restricts nothing

    Returns:
        list[Mapping[str, Any]]: The roles, in assignment order
    """
    role_ids: dict[Any, None] = dict.fromkeys(assignment.get(AccessAssignmentKey.ROLE_ID.value)
                                              for assignment in assignments)

    return [roles_by_id[role_id] for role_id in role_ids if role_id in roles_by_id]


def viewable_types(assignments: Iterable[Mapping[str, Any]], roles_by_id: Mapping[int, Mapping[str, Any]]
                   ) -> TypeSet:
    """
    The Types some group may view - through an assignment with the unconditional scope whose role lists view

    Args:
        assignments (Iterable[Mapping[str, Any]]): Every stored assignment
        roles_by_id (Mapping[int, Mapping[str, Any]]): The roles by public_id

    Returns:
        TypeSet: The viewable Types
    """
    unconditional: list[Mapping[str, Any]] = [assignment for assignment in assignments
                                              if assignment.get(AccessAssignmentKey.SCOPE.value) == UNCONDITIONAL_SCOPE]

    return TypeSet.union_of(TypeSet.from_role_types(role.get(ScopeRoleKey.TYPES.value))
                            for role in assigned_roles(unconditional, roles_by_id)
                            if ScopeOperation.VIEW in role_operations(role))


def type_states(assignments: Iterable[Mapping[str, Any]], roles_by_id: Mapping[int, Mapping[str, Any]],
                type_ids: Iterable[int]) -> dict[int, TypeAccessState]:
    """
    The state of each Type under the given assignments and roles

    Args:
        assignments (Iterable[Mapping[str, Any]]): Every assignment
        roles_by_id (Mapping[int, Mapping[str, Any]]): The roles by public_id
        type_ids (Iterable[int]): The Types to judge

    Returns:
        dict[int, TypeAccessState]: Each Type's state
    """
    listed: list[Mapping[str, Any]] = list(assignments)
    restricted: TypeSet = restricted_types(assigned_roles(listed, roles_by_id))
    viewable: TypeSet = viewable_types(listed, roles_by_id)
    states: dict[int, TypeAccessState] = {}

    for type_id in type_ids:
        if not restricted.contains(type_id):
            states[type_id] = TypeAccessState.OPEN
        elif viewable.contains(type_id):
            states[type_id] = TypeAccessState.VIEWABLE
        else:
            states[type_id] = TypeAccessState.LOCKED

    return states


def changed_types(before: Mapping[int, TypeAccessState], after: Mapping[int, TypeAccessState]
                  ) -> tuple[list[int], list[int]]:
    """
    The Types a change locks and the Types it opens

    Args:
        before (Mapping[int, TypeAccessState]): The states before the change
        after (Mapping[int, TypeAccessState]): The states after it, for the same Types

    Returns:
        tuple[list[int], list[int]]: The newly locked Types and the newly opened ones, ascending
    """
    locked: list[int] = sorted(type_id for type_id, state in after.items()
                               if state is TypeAccessState.LOCKED and before.get(type_id) is not TypeAccessState.LOCKED)
    opened: list[int] = sorted(type_id for type_id, state in after.items()
                               if state is TypeAccessState.OPEN and before.get(type_id) is not TypeAccessState.OPEN)

    return locked, opened


def newly_restricted(before: Mapping[int, TypeAccessState], after: Mapping[int, TypeAccessState]) -> list[int]:
    """
    The Types a change restricts that were open - every group without an assignment on them loses them (phase 11)

    Args:
        before (Mapping[int, TypeAccessState]): The states before the change
        after (Mapping[int, TypeAccessState]): The states after it, for the same Types

    Returns:
        list[int]: The Types open before and restricted after, ascending
    """
    return sorted(type_id for type_id, state in after.items()
                  if state is not TypeAccessState.OPEN and before.get(type_id) is TypeAccessState.OPEN)


def access_change_problems(locked: list[int], opened: list[int], unrestrict: bool) -> list[str]:
    """
    Refuses a change locking a Type, and one opening a Type unless confirmed

    Args:
        locked (list[int]): The Types the change locks
        opened (list[int]): The Types the change opens
        unrestrict (bool): Whether the caller confirmed opening Types

    Returns:
        list[str]: The problems, empty when the change may be written
    """
    problems: list[str] = []

    if locked:
        problems.append(AccessRuleMessage.TYPES_LOCKED.value.format(ids=locked))

    if opened and not unrestrict:
        problems.append(AccessRuleMessage.TYPES_OPENED.value.format(ids=opened))

    return problems


def involved_types(roles: Iterable[Mapping[str, Any]]) -> TypeSet:
    """
    The Types a change can touch: every Type a role involved in it names

    Args:
        roles (Iterable[Mapping[str, Any]]): The roles of the changed assignments, before and after, or the changed
            role in both versions

    Returns:
        TypeSet: Their Types - every Type when one of them names every Type
    """
    return TypeSet.union_of(TypeSet.from_role_types(role.get(ScopeRoleKey.TYPES.value)) for role in roles)
