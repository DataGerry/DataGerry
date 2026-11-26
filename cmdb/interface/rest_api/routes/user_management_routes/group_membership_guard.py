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
Nobody puts a user into a user group that holds more than they do (T579)

Three writes add groups to users: a user create, a user update and a group delete moving its members (``MOVE``). Each
judges only the groups it ADDS - a group a user keeps, and every removal, is never escalation. A group is beyond the
caller when it holds a functional right the caller does not (``groups_helper.unheld_rights``) or one of its
assignments grants beyond the caller's access (``escalation_rules.beyond_reach``, as for an assignment write). Judged
for every target account - limiting it to the caller's own would be undone by creating a second account.
Administrators are exempt, as for the access rule writes: they must always be able to administer every group
"""
from collections.abc import Iterable
from typing import Any

from flask import abort

from cmdb.manager import AccessAssignmentsManager, GroupsManager, ScopeRolesManager
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.models.access_model import AccessAssignmentKey, ScopeRoleKey
from cmdb.models.group_model import CmdbUserGroup, EffectiveRights, in_administrator_group
from cmdb.models.user_model import CmdbUser
from cmdb.framework.access_engine import AccessGrants, load_grants
from cmdb.framework.access_rules import beyond_reach
from cmdb.interface.route_utils import request_groups
from cmdb.interface.rest_api.routes.user_management_routes.cmdb_groups.groups_helper import unheld_rights
from cmdb.interface.rest_api.routes.user_management_routes.users_constants import (
    MEMBERSHIP_BEYOND_MSG,
    MEMBERSHIP_GROUP_PART,
    MEMBERSHIP_GROUP_SEPARATOR,
    MEMBERSHIP_PART_SEPARATOR,
    MEMBERSHIP_RIGHTS_PART,
)
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'added_group_ids',
    'group_beyond_caller',
    'abort_if_adding_groups_beyond',
]


def added_group_ids(before: Iterable[int], after: Iterable[int]) -> list[int]:
    """
    The groups a write adds to a user

    Args:
        before (Iterable[int]): The user's groups before the write - empty for a create
        after (Iterable[int]): The user's groups after the write

    Returns:
        list[int]: The groups in ``after`` and not in ``before``, ascending
    """
    return sorted(set(after) - set(before))


def group_beyond_caller(held: EffectiveRights, grants: AccessGrants | None, rights: list[str],
                        roles: list[dict[str, Any]]) -> list[str]:
    """
    What one group holds beyond the caller

    Args:
        held (EffectiveRights): The caller's functional rights
        grants (AccessGrants | None): The caller's access grants - None when the group holds no assignment
        rights (list[str]): The group's right names
        roles (list[dict[str, Any]]): The scope roles of the group's assignments

    Returns:
        list[str]: The rights part (when it holds rights the caller lacks), then each role's reach beyond the caller,
            each once, in order; empty when the group holds nothing beyond the caller
    """
    parts: list[str] = []
    unheld: list[str] = unheld_rights(held, rights)

    if unheld:
        parts.append(MEMBERSHIP_RIGHTS_PART.format(names=unheld))

    if grants is not None:
        for role in roles:
            parts.extend(part for part in beyond_reach(grants, role) if part not in parts)

    return parts


def abort_if_adding_groups_beyond(request_user: CmdbUser, group_ids: Iterable[int]) -> None:
    """
    Refuses a write adding users to user groups that hold more than the caller

    Reads nothing for an administrator or when no group is added; else the added groups (one read), their
    assignments and roles (one read each, only when there are any), and the caller's rights and grants (request-cached)

    Args:
        request_user (CmdbUser): The caller
        group_ids (Iterable[int]): The groups the write adds - ``added_group_ids`` of an update, every group of a
            create, the target of a ``MOVE``

    Raises:
        HTTPException: 403 naming each group and what it holds beyond the caller
        GroupsManagerGetError | AccessAssignmentsManagerGetError | ScopeRolesManagerGetError: When a read fails
    """
    added: list[int] = sorted(set(group_ids))

    if not added or in_administrator_group(request_user.group_ids):
        return

    groups_manager: GroupsManager = ManagerProvider.get_manager(ManagerType.GROUPS, request_user)
    groups: list[CmdbUserGroup] = groups_manager.get_groups(added)
    roles_by_group: dict[int, list[dict[str, Any]]] = _roles_by_group(request_user, added)
    grants: AccessGrants | None = load_grants(request_user) if roles_by_group else None
    held: EffectiveRights = request_groups(request_user)
    details: list[str] = []

    for group in groups:
        parts: list[str] = group_beyond_caller(held, grants, [right.name for right in group.rights],
                                               roles_by_group.get(group.public_id, []))

        if parts:
            details.append(MEMBERSHIP_GROUP_PART.format(group_id=group.public_id,
                                                        beyond=MEMBERSHIP_PART_SEPARATOR.join(parts)))

    if details:
        abort(403, MEMBERSHIP_BEYOND_MSG.format(details=MEMBERSHIP_GROUP_SEPARATOR.join(details)))


def _roles_by_group(request_user: CmdbUser, group_ids: list[int]) -> dict[int, list[dict[str, Any]]]:
    """
    The scope roles each group holds through its assignments

    Args:
        request_user (CmdbUser): The caller - whose database is read
        group_ids (list[int]): The groups

    Raises:
        AccessAssignmentsManagerGetError | ScopeRolesManagerGetError: When a read fails

    Returns:
        dict[int, list[dict[str, Any]]]: Per group holding assignments, its roles in assignment order; a group without
            one is absent
    """
    assignments_manager: AccessAssignmentsManager = ManagerProvider.get_manager(ManagerType.ACCESS_ASSIGNMENTS,
                                                                                request_user)
    assignments: list[dict[str, Any]] = assignments_manager.assignments_of_groups(group_ids)

    if not assignments:
        return {}

    roles_manager: ScopeRolesManager = ManagerProvider.get_manager(ManagerType.SCOPE_ROLES, request_user)
    role_ids: list[int] = sorted({assignment[AccessAssignmentKey.ROLE_ID.value] for assignment in assignments})
    roles: dict[int, dict[str, Any]] = {role[ScopeRoleKey.PUBLIC_ID.value]: role
                                        for role in roles_manager.roles_by_ids(role_ids)}
    by_group: dict[int, list[dict[str, Any]]] = {}

    for assignment in assignments:
        role: dict[str, Any] | None = roles.get(assignment[AccessAssignmentKey.ROLE_ID.value])

        if role is not None:
            by_group.setdefault(assignment[AccessAssignmentKey.GROUP_ID.value], []).append(role)

    return by_group
