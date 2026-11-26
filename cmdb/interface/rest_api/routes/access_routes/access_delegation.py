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
Delegated assignments: a holder of ``base.access.assignment.delegate`` without ``base.access.assignment.edit`` creates,
changes and deletes assignments only whose scope role stays within their own access - judged on the role before AND
after the write, so an assignment reaching beyond the delegate stays untouchable for them. Measured against everything
the delegate's assignments grant together (``escalation_rules.delegation_problem``), for any user group. A holder of
the edit right and an administrator are not judged here; the own-reach check, the lock / open guard and the hidden-Type
rule apply to everyone as before
"""
from collections.abc import Iterable
from typing import Any

from flask import abort

from cmdb.manager import ScopeRolesManager
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.models.access_model import ScopeRoleKey
from cmdb.models.group_model import in_administrator_group
from cmdb.models.user_model import CmdbUser
from cmdb.framework.access_engine import AccessGrants, load_grants
from cmdb.framework.access_rules import beyond_reach, delegation_problem
from cmdb.interface.route_utils import user_has_right
from cmdb.interface.rest_api.routes.access_routes.access_route_constants import AccessRightName
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'delegates_only',
    'abort_unless_delegable',
    'delegable_role_ids',
]


def delegates_only(request_user: CmdbUser) -> bool:
    """
    Whether the caller writes assignments as a delegate - neither an administrator nor a holder of the edit right

    Args:
        request_user (CmdbUser): The caller

    Raises:
        GroupsManagerGetError: When the caller's groups could not be read

    Returns:
        bool: True when the delegation rule judges the caller's assignment writes
    """
    return not in_administrator_group(request_user.group_ids) and \
        not user_has_right(AccessRightName.ASSIGNMENT_EDIT.value, request_user)


def abort_unless_delegable(request_user: CmdbUser, role_ids: Iterable[int]) -> None:
    """
    Refuses a delegate's assignment write whose scope role - before or after the write - grants beyond the delegate's
    own access. Reads nothing for an editor or an administrator; else the roles (one read) and the delegate's grants
    (request-cached). A role that does not exist is the reference rules' to refuse

    Args:
        request_user (CmdbUser): The caller
        role_ids (Iterable[int]): The role the assignment holds before the write (update, delete) and after it
            (create, update)

    Raises:
        HTTPException: 403 naming the first role beyond the delegate and what it grants beyond
        ScopeRolesManagerGetError | AccessAssignmentsManagerGetError: When a read fails
    """
    ids: list[int] = list(dict.fromkeys(role_ids))

    if not ids or not delegates_only(request_user):
        return

    roles_manager: ScopeRolesManager = ManagerProvider.get_manager(ManagerType.SCOPE_ROLES, request_user)
    roles: dict[int, dict[str, Any]] = {role[ScopeRoleKey.PUBLIC_ID.value]: role
                                        for role in roles_manager.roles_by_ids(sorted(ids))}
    grants: AccessGrants = load_grants(request_user)

    for role_id in ids:
        problem: str | None = delegation_problem(grants, role_id, roles[role_id]) if role_id in roles else None

        if problem:
            abort(403, problem)


def delegable_role_ids(request_user: CmdbUser, roles: list[dict[str, Any]]) -> list[int]:
    """
    The scope roles the caller may hand out - every role for an administrator; else the roles within the caller's
    own access. An editor of assignments is measured the same way: the list answers what the caller's own access
    covers

    Args:
        request_user (CmdbUser): The caller
        roles (list[dict[str, Any]]): The stored scope roles

    Raises:
        AccessAssignmentsManagerGetError | ScopeRolesManagerGetError: When the caller's grants could not be read

    Returns:
        list[int]: Their public_ids, ascending
    """
    if in_administrator_group(request_user.group_ids):
        return sorted(role[ScopeRoleKey.PUBLIC_ID.value] for role in roles)

    grants: AccessGrants = load_grants(request_user)

    return sorted(role[ScopeRoleKey.PUBLIC_ID.value] for role in roles if not beyond_reach(grants, role))
