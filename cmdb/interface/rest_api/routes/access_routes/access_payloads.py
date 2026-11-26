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
The payloads the access rule writes store: an update completed from the stored document, a scope in its canonical
spelling, and every write rule judged - all problems of one write refused together
"""
from collections.abc import Collection
from typing import Any

from flask import abort

from cmdb.utils import keep_omitted_keys
from cmdb.manager import (
    AccessAssignmentsManager,
    FieldClassesManager,
    GroupsManager,
    ScopeRolesManager,
    TypesManager,
)
from cmdb.models.access_model import AccessAssignmentKey, FieldClassKey, ScopeRoleKey
from cmdb.models.group_model import in_administrator_group
from cmdb.models.user_model import CmdbUser
from cmdb.framework.access_engine import load_grants
from cmdb.framework.access_rules.assignment_scope_rules import judge_scope, role_type_documents
from cmdb.framework.access_rules import (
    AccessRuleMessage,
    own_reach_problem,
    assignment_reference_problems,
    assignment_taken,
    canonical_scope,
    field_class_name_change,
    field_class_name_taken,
    scope_role_name_taken,
    scope_role_reference_problems,
)
from cmdb.interface.rest_api.routes.routes_helper import abort_on_problems
# -------------------------------------------------------------------------------------------------------------------- #


def field_class_create_payload(manager: FieldClassesManager, data: dict[str, Any]) -> dict[str, Any]:
    """
    Judges a new field class: its name is free

    Args:
        manager (FieldClassesManager): The field classes of the request's database
        data (dict[str, Any]): The validated body

    Raises:
        HTTPException: 400 when the name is taken

    Returns:
        dict[str, Any]: The document to store
    """
    abort_on_problems([field_class_name_taken(manager, data[FieldClassKey.NAME.value])])

    return dict(data)


def field_class_update_payload(stored: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    """
    Judges a field class update - the name stays - and completes it from the stored class

    Args:
        stored (dict[str, Any]): The class as stored
        data (dict[str, Any]): The validated body

    Raises:
        HTTPException: 400 when the body renames the class

    Returns:
        dict[str, Any]: The document to store
    """
    abort_on_problems([field_class_name_change(stored, data)])

    return keep_omitted_keys(data, stored)


def scope_role_payload(roles: ScopeRolesManager, types: TypesManager, classes: FieldClassesManager,
                       request_user: CmdbUser, role: dict[str, Any], own_id: int | None = None,
                       sent: dict[str, Any] | None = None) -> dict[str, Any]:
    """
    Judges a scope role as it would be stored: its name is free, the Types it sends are stored ones the caller may
    read, the field classes it sends stored ones

    Args:
        roles (ScopeRolesManager): The scope roles of the request's database
        types (TypesManager): Its Types
        classes (FieldClassesManager): Its field classes
        request_user (CmdbUser): The caller
        role (dict[str, Any]): The role as it would be stored - an update already completed
        own_id (int | None): The role being updated; None for a create
        sent (dict[str, Any] | None): An update's body - only its references are judged; None judges the whole role

    Raises:
        HTTPException: 400 naming every problem

    Returns:
        dict[str, Any]: The document to store
    """
    abort_on_problems([
        scope_role_name_taken(roles, role[ScopeRoleKey.NAME.value], own_id),
        *scope_role_reference_problems(role if sent is None else sent, types, classes, request_user),
    ])

    return dict(role)


def assignment_payload(assignments: AccessAssignmentsManager, groups: GroupsManager, roles: ScopeRolesManager,
                       assignment: dict[str, Any], own_id: int | None = None,
                       sent: dict[str, Any] | None = None, types: TypesManager | None = None) -> dict[str, Any]:
    """
    Judges an assignment as it would be stored: its scope canonical, its group and role stored ones, no other
    assignment the same - and a scope condition list judged against the role's Types whenever the role or the scope
    changes (phase 9, R29: shape, field resolution, casting; the cast scope is stored)

    Args:
        assignments (AccessAssignmentsManager): The assignments of the request's database
        groups (GroupsManager): Its user groups
        roles (ScopeRolesManager): Its scope roles
        assignment (dict[str, Any]): The assignment as it would be stored - an update already completed
        own_id (int | None): The assignment being updated; None for a create
        sent (dict[str, Any] | None): An update's body - only its references are judged; None judges the whole
            assignment
        types (TypesManager | None): The Types of the request's database - the scope is judged with them; None
            judges no scope (an internal caller)

    Raises:
        HTTPException: 400 naming every problem

    Returns:
        dict[str, Any]: The document to store, its scope canonical
    """
    scope: Any = assignment[AccessAssignmentKey.SCOPE.value]
    scope_problems: list[str] = []
    judged_keys: set[str] = {AccessAssignmentKey.SCOPE.value, AccessAssignmentKey.ROLE_ID.value}

    if types is not None and (sent is None or judged_keys & set(sent)):
        role: dict[str, Any] | None = roles.get_item(assignment[AccessAssignmentKey.ROLE_ID.value], as_dict=True)

        if role:
            scope, scope_problems = judge_scope(scope, role_type_documents(role, types))

    payload: dict[str, Any] = {**assignment, AccessAssignmentKey.SCOPE.value: canonical_scope(scope)}
    abort_on_problems([
        *assignment_reference_problems(payload if sent is None else sent, groups, roles),
        *scope_problems,
        assignment_taken(assignments, payload, own_id),
    ])

    return payload


def abort_if_beyond_own_reach(request_user: CmdbUser, role_id: int, role: dict[str, Any],
                              group_ids: Collection[int]) -> None:
    """
    Refuses a scope role reaching one of the caller's own user groups with more than the caller holds - nobody
    assigns themselves beyond their own rights, not through a group they are in either. The caller's grants are read
    only when one of its groups is reached. An administrator (a member of the administrator group) is exempt: they
    must always be able to re-grant themselves a Type an assignment hid from them, or one the migration locked

    Args:
        request_user (CmdbUser): The caller
        role_id (int): The role's public_id
        role (dict[str, Any]): The role as it would be stored
        group_ids (Collection[int]): The groups the role is (to be) assigned to

    Raises:
        HTTPException: 403 naming what the role grants beyond the caller's reach
        AccessAssignmentsManagerGetError | ScopeRolesManagerGetError: When the caller's grants could not be read
    """
    if in_administrator_group(request_user.group_ids) or not set(group_ids) & set(request_user.group_ids):
        return

    problem: str | None = own_reach_problem(load_grants(request_user), role_id, role, group_ids,
                                            request_user.group_ids)

    if problem:
        abort(403, problem)


def checked_scope(roles: ScopeRolesManager, types: TypesManager, role_id: int, scope: Any) -> Any:
    """
    The dry run of a scope against a role's Types - nothing written (phase 9, R30)

    Args:
        roles (ScopeRolesManager): The scope roles of the request's database
        types (TypesManager): Its Types
        role_id (int): The scope role the assignment would grant
        scope (Any): The scope as sent

    Raises:
        HTTPException: 400 naming every problem - the role missing, the scope's shape, fields, values

    Returns:
        Any: The scope as it would be stored - cast and canonical
    """
    role: dict[str, Any] | None = roles.get_item(role_id, as_dict=True)

    if not role:
        abort_on_problems([AccessRuleMessage.UNKNOWN_ROLE.value.format(role_id=role_id)])

    judged, problems = judge_scope(scope, role_type_documents(role, types))
    abort_on_problems(problems)

    return canonical_scope(judged)
