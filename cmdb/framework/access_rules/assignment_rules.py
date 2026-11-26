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
The write rules of an assignment: its group and role are stored ones, its scope is stored in one spelling, and one
group, role and scope are stored once
"""
from typing import Any

from cmdb.manager.access_assignments_manager import AccessAssignmentsManager
from cmdb.manager.groups_manager import GroupsManager
from cmdb.manager.scope_roles_manager import ScopeRolesManager
from cmdb.models.access_model import AccessAssignmentKey
from cmdb.framework.access_rules.access_rule_constants import AccessRuleMessage
from cmdb.framework.access_rules.access_rule_reads import clashes
from cmdb.framework.scope_compiler import canonical_blocks, scope_shape_problems
# -------------------------------------------------------------------------------------------------------------------- #


def canonical_scope(scope: Any) -> Any:
    """
    The one spelling a scope is stored in: every document's keys sorted, at every depth, lists kept in their order

    The unique index compares stored scopes by equality, and MongoDB compares documents key by key in order - so two
    spellings of one condition would otherwise both be stored. The unconditional ``*`` is its own spelling; a
    well-formed condition list also has its conditions and its ``in`` / ``not_in`` values sorted
    (``scope_compiler.canonical_blocks``)

    Args:
        scope (Any): The scope as sent

    Returns:
        Any: The scope as stored, new documents and lists throughout
    """
    if isinstance(scope, dict):
        return {key: canonical_scope(scope[key]) for key in sorted(scope)}

    # A well-formed condition list: its conditions and the values of in / not_in sorted too (phase 9, R5)
    if isinstance(scope, list) and scope and not scope_shape_problems(scope):
        return canonical_blocks(scope)

    if isinstance(scope, list):
        return [canonical_scope(item) for item in scope]

    return scope


def assignment_reference_problems(assignment: dict[str, Any], groups_manager: GroupsManager,
                                  roles_manager: ScopeRolesManager) -> list[str]:
    """
    Judges what an assignment names: its user group and its scope role must be stored. One read each, none for a key
    the body leaves out - an update judges only the references it sends

    Args:
        assignment (dict[str, Any]): The references to judge - a create's whole body, an update's sent keys
        groups_manager (GroupsManager): The user groups of the request's database
        roles_manager (ScopeRolesManager): The scope roles of the request's database

    Raises:
        GroupsManagerGetError: When the group read fails
        ScopeRolesManagerGetError: When the role read fails

    Returns:
        list[str]: The problems, empty when both are stored
    """
    problems: list[str] = []
    group_id: int | None = assignment.get(AccessAssignmentKey.GROUP_ID.value)
    role_id: int | None = assignment.get(AccessAssignmentKey.ROLE_ID.value)

    if group_id is not None and not groups_manager.find_existing_public_ids([group_id]):
        problems.append(AccessRuleMessage.UNKNOWN_GROUP.value.format(group_id=group_id))

    if role_id is not None and not roles_manager.find_existing_public_ids([role_id]):
        problems.append(AccessRuleMessage.UNKNOWN_ROLE.value.format(role_id=role_id))

    return problems


def assignment_taken(manager: AccessAssignmentsManager, assignment: dict[str, Any],
                     own_id: int | None = None) -> str | None:
    """
    Refuses an assignment another one already is: the same group, role and (canonical) scope - one count

    Args:
        manager (AccessAssignmentsManager): The assignments of the request's database
        assignment (dict[str, Any]): The validated assignment body, its scope canonical
        own_id (int | None): The assignment being updated; None for a create

    Raises:
        BaseManagerGetError: When the count fails

    Returns:
        str | None: The problem, or None when no other assignment is the same
    """
    group_id: int = assignment[AccessAssignmentKey.GROUP_ID.value]
    role_id: int = assignment[AccessAssignmentKey.ROLE_ID.value]
    criteria: dict[str, Any] = {
        AccessAssignmentKey.GROUP_ID.value: group_id,
        AccessAssignmentKey.ROLE_ID.value: role_id,
        AccessAssignmentKey.SCOPE.value: assignment[AccessAssignmentKey.SCOPE.value],
    }

    if clashes(manager, criteria, own_id):
        return AccessRuleMessage.ASSIGNMENT_TAKEN.value.format(group_id=group_id, role_id=role_id)

    return None
