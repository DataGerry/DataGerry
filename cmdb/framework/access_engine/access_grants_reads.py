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
The reads behind a user's access grants: the assignments of the user's groups, every assigned scope role - three small
indexed reads - kept for the rest of the request under the tenant database and the user's group ids. Beside them,
every assignment with its roles (``load_access_rules``) - what the synthesised ``acl`` answers read - kept in the same
place, so ``forget_grants`` drops both
"""
from collections.abc import Collection
from typing import Any

from cmdb.utils import request_cache
from cmdb.manager import AccessAssignmentsManager, ScopeRolesManager
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.models.access_model import AccessAssignmentKey
from cmdb.models.user_model import CmdbUser
from cmdb.framework.access_engine.access_grants import AccessGrants, build_grants
# -------------------------------------------------------------------------------------------------------------------- #

# The request attribute holding the grants read in this request
GRANTS_CACHE_KEY: str = 'dg_access_grants'

# The second part of the key every assignment with its roles is kept under, beside the tenant database - never a
# group id tuple, so it cannot meet a user's grants
EVERY_ASSIGNMENT_KEY: str = 'every-assignment'

AccessRules = tuple[list[dict[str, Any]], list[dict[str, Any]]]


def read_grants(assignments: AccessAssignmentsManager, roles: ScopeRolesManager,
                group_ids: Collection[int]) -> AccessGrants:
    """
    Reads the assignments and scope roles and works out the grants of a user in the given groups

    Three reads: the assignments of the groups (``group_id`` index), the role ids of every assignment (``role_id``
    index) and those roles. Nothing is read twice; an assignment whose role vanished between the reads grants nothing

    Args:
        assignments (AccessAssignmentsManager): The assignments of the user's database
        roles (ScopeRolesManager): The scope roles of the user's database
        group_ids (Collection[int]): The user's group ids

    Raises:
        AccessAssignmentsManagerGetError: When an assignment read fails
        ScopeRolesManagerGetError: When the role read fails

    Returns:
        AccessGrants: The restricted Types and the user's grants on them
    """
    groups: list[int] = sorted(set(group_ids))
    user_assignments: list[dict[str, Any]] = assignments.assignments_of_groups(groups)
    assigned_roles: list[dict[str, Any]] = roles.roles_by_ids(assignments.assigned_role_ids())

    return build_grants(user_assignments, assigned_roles, groups)


def grants_cache_key(user: CmdbUser) -> tuple[str | None, tuple[int, ...]]:
    """
    The key a user's grants are kept under: the tenant database and the user's group ids - so an entry can never
    answer for another tenant or another membership

    Args:
        user (CmdbUser): The user

    Returns:
        tuple[str | None, tuple[int, ...]]: The key
    """
    return ManagerProvider.tenant_database(user), tuple(sorted(set(user.group_ids)))


def load_grants(user: CmdbUser) -> AccessGrants:
    """
    The grants of a user, read once per request

    A failed read is not kept: it raises, and a later call reads again. Outside a request (a unit test, a CLI path)
    nothing is kept and every call reads

    Args:
        user (CmdbUser): The user the request is made for

    Raises:
        AccessAssignmentsManagerGetError: When an assignment read fails
        ScopeRolesManagerGetError: When the role read fails

    Returns:
        AccessGrants: The restricted Types and the user's grants on them
    """
    cache: dict[Any, Any] | None = request_cache(GRANTS_CACHE_KEY)
    key: tuple[str | None, tuple[int, ...]] = grants_cache_key(user)

    if cache is not None and key in cache:
        return cache[key]

    assignments: AccessAssignmentsManager = ManagerProvider.get_manager(ManagerType.ACCESS_ASSIGNMENTS, user)
    roles: ScopeRolesManager = ManagerProvider.get_manager(ManagerType.SCOPE_ROLES, user)
    grants: AccessGrants = read_grants(assignments, roles, user.group_ids)

    if cache is not None:
        cache[key] = grants

    return grants


def load_access_rules(user: CmdbUser) -> AccessRules:
    """
    Every stored assignment and the roles they grant, read once per request for the user's tenant

    Two reads: every assignment, then the roles they name. A failed read is not kept

    Args:
        user (CmdbUser): The user the request is made for - it names the tenant

    Raises:
        AccessAssignmentsManagerGetError: When the assignment read fails
        ScopeRolesManagerGetError: When the role read fails

    Returns:
        AccessRules: The assignments and their roles, each ascending by public_id
    """
    cache: dict[Any, Any] | None = request_cache(GRANTS_CACHE_KEY)
    key: tuple[str | None, str] = (ManagerProvider.tenant_database(user), EVERY_ASSIGNMENT_KEY)

    if cache is not None and key in cache:
        return cache[key]

    assignments: AccessAssignmentsManager = ManagerProvider.get_manager(ManagerType.ACCESS_ASSIGNMENTS, user)
    roles: ScopeRolesManager = ManagerProvider.get_manager(ManagerType.SCOPE_ROLES, user)
    every_assignment: list[dict[str, Any]] = assignments.all_assignments()
    role_ids: list[int] = sorted({assignment[AccessAssignmentKey.ROLE_ID.value] for assignment in every_assignment})
    rules: AccessRules = (every_assignment, roles.roles_by_ids(role_ids))

    if cache is not None:
        cache[key] = rules

    return rules


def forget_grants() -> None:
    """
    Drops every grant kept in this request - for a request that changes assignments or scope roles and decides
    access afterwards

    Outside a request there is nothing to drop
    """
    cache: dict[Any, Any] | None = request_cache(GRANTS_CACHE_KEY)

    if cache is not None:
        cache.clear()
