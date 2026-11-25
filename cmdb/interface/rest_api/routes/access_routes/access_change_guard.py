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
The guard against a change of the access rules that locks a Type or - unconfirmed - opens one

Every assignment and the roles they grant are read (an administrator's write, small collections), the change is
applied in memory, and the Types it can touch are judged before and after (``access_rules.type_access_states``): a
newly locked Type is refused, a newly opened Type is refused unless the request sends ``unrestrict=true``. A write
racing another is not seen - the accepted race of every in-use guard here
"""
from collections.abc import Iterable
from typing import Any, NamedTuple

from cmdb.manager import AccessAssignmentsManager, ScopeRolesManager, TypesManager
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.models.access_model import AccessAssignmentKey, ScopeRoleKey
from cmdb.models.user_model import CmdbUser
from cmdb.framework.access_engine import TypeSet
from cmdb.framework.access_rules import access_change_problems, changed_types, involved_types, type_states
from cmdb.interface.rest_api.routes.routes_helper import abort_on_problems, read_boolean_query_param
from cmdb.interface.rest_api.routes.access_routes.access_route_constants import UNRESTRICT_PARAM
# -------------------------------------------------------------------------------------------------------------------- #

AccessState = tuple[list[dict[str, Any]], dict[int, dict[str, Any]]]


class GroupDeleteEffect(NamedTuple):
    """
    What deleting a user group does to the access rules

    Attributes:
        assignment_ids (list[int]): The group's assignments - deleted with it, in stored order
        locked (list[int]): The Types the delete would lock, ascending
        opened (list[int]): The Types the delete would open, ascending
    """
    assignment_ids: list[int]
    locked: list[int]
    opened: list[int]


def read_access_state(request_user: CmdbUser, extra_role_ids: Iterable[int] = ()) -> AccessState:
    """
    Every assignment and the roles they grant, plus further roles a change names

    Args:
        request_user (CmdbUser): The caller
        extra_role_ids (Iterable[int]): Roles to read beside the assigned ones

    Raises:
        AccessAssignmentsManagerGetError | ScopeRolesManagerGetError: When a read fails

    Returns:
        AccessState: The assignments and the roles by public_id
    """
    assignments_manager: AccessAssignmentsManager = ManagerProvider.get_manager(ManagerType.ACCESS_ASSIGNMENTS,
                                                                                request_user)
    roles_manager: ScopeRolesManager = ManagerProvider.get_manager(ManagerType.SCOPE_ROLES, request_user)
    assignments: list[dict[str, Any]] = assignments_manager.all_assignments()
    role_ids: set[int] = {assignment[AccessAssignmentKey.ROLE_ID.value] for assignment in assignments}
    roles: list[dict[str, Any]] = roles_manager.roles_by_ids(sorted(role_ids | set(extra_role_ids)))

    return assignments, {role[ScopeRoleKey.PUBLIC_ID.value]: role for role in roles}


def change_effect(request_user: CmdbUser, before: AccessState, after: AccessState,
                  involved_role_ids: Iterable[int]) -> tuple[list[int], list[int]]:
    """
    The Types a change locks and opens, judged on the Types the involved roles name in either version

    Args:
        request_user (CmdbUser): The caller - the Types are read only when an involved role names every Type
        before (AccessState): The assignments and roles before the change
        after (AccessState): The assignments and roles after it
        involved_role_ids (Iterable[int]): The roles of the changed assignments, or the changed role

    Raises:
        TypesManagerGetError: When the Types could not be read

    Returns:
        tuple[list[int], list[int]]: The newly locked and the newly opened Types, ascending
    """
    role_ids: list[int] = list(involved_role_ids)
    involved: TypeSet = involved_types([version[role_id] for version in (before[1], after[1]) for role_id in role_ids
                                        if role_id in version])

    if involved.every_type:
        types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)
        type_ids: list[int] = types_manager.get_all_type_ids()
    else:
        type_ids = sorted(involved.ids)

    return changed_types(type_states(before[0], before[1], type_ids), type_states(after[0], after[1], type_ids))


def abort_if_change_refused(request_user: CmdbUser, before: AccessState, after: AccessState,
                            involved_role_ids: Iterable[int]) -> None:
    """
    Refuses a change locking a Type, and one opening a Type unless the request sends ``unrestrict=true``

    Args:
        request_user (CmdbUser): The caller
        before (AccessState): The assignments and roles before the change
        after (AccessState): The assignments and roles after it
        involved_role_ids (Iterable[int]): The roles of the changed assignments, or the changed role

    Raises:
        HTTPException: 400 naming the Types (and for a wrong ``unrestrict`` value)
    """
    abort_if_effect_refused(*change_effect(request_user, before, after, involved_role_ids))


def abort_if_effect_refused(locked: list[int], opened: list[int]) -> None:
    """
    Refuses the Types a change locks, and those it opens unless the request sends ``unrestrict=true``

    Args:
        locked (list[int]): The Types the change locks
        opened (list[int]): The Types the change opens

    Raises:
        HTTPException: 400 naming the Types (and for a wrong ``unrestrict`` value)
    """
    abort_on_problems(access_change_problems(locked, opened, read_boolean_query_param(UNRESTRICT_PARAM, False)))


def without_assignments(state: AccessState, public_ids: Iterable[int]) -> AccessState:
    """
    The state with some assignments removed

    Args:
        state (AccessState): The assignments and roles
        public_ids (Iterable[int]): The assignments to remove

    Returns:
        AccessState: A new state; the roles shared
    """
    removed: set[int] = set(public_ids)

    return ([assignment for assignment in state[0] if assignment[AccessAssignmentKey.PUBLIC_ID.value] not in removed],
            state[1])


def guard_assignment_write(request_user: CmdbUser, stored: dict[str, Any] | None,
                           written: dict[str, Any] | None) -> None:
    """
    Judges an assignment create (no stored), update or delete (nothing written)

    Args:
        request_user (CmdbUser): The caller
        stored (dict[str, Any] | None): The assignment as stored; None for a create
        written (dict[str, Any] | None): The assignment as it would be stored; None for a delete

    Raises:
        HTTPException: 400 naming the Types locked or opened
    """
    role_ids: list[int] = [document[AccessAssignmentKey.ROLE_ID.value] for document in (stored, written) if document]
    before: AccessState = read_access_state(request_user, role_ids)
    after: AccessState = without_assignments(before, [stored[AccessAssignmentKey.PUBLIC_ID.value]] if stored else [])

    if written is not None:
        after = (after[0] + [written], after[1])

    abort_if_change_refused(request_user, before, after, role_ids)


def guard_role_update(request_user: CmdbUser, role_id: int, written: dict[str, Any]) -> None:
    """
    Judges a scope role update - only a role some assignment grants can change a Type's state

    Args:
        request_user (CmdbUser): The caller
        role_id (int): The role's public_id
        written (dict[str, Any]): The role as it would be stored

    Raises:
        HTTPException: 400 naming the Types locked or opened
    """
    before: AccessState = read_access_state(request_user, [role_id])

    if not any(assignment[AccessAssignmentKey.ROLE_ID.value] == role_id for assignment in before[0]):
        return

    abort_if_change_refused(request_user, before, (before[0], {**before[1], role_id: written}), [role_id])


def group_delete_effect(request_user: CmdbUser, group_id: int) -> GroupDeleteEffect:
    """
    What deleting a user group - with its assignments - would do: its assignments, the Types locked and opened

    Args:
        request_user (CmdbUser): The caller
        group_id (int): The group's public_id

    Raises:
        AccessAssignmentsManagerGetError | ScopeRolesManagerGetError | TypesManagerGetError: When a read fails

    Returns:
        GroupDeleteEffect: The group's assignment ids and the newly locked and opened Types
    """
    before: AccessState = read_access_state(request_user)
    removed: list[dict[str, Any]] = [assignment for assignment in before[0]
                                     if assignment[AccessAssignmentKey.GROUP_ID.value] == group_id]
    removed_ids: list[int] = [assignment[AccessAssignmentKey.PUBLIC_ID.value] for assignment in removed]
    after: AccessState = without_assignments(before, removed_ids)
    locked, opened = change_effect(request_user, before, after,
                                   {assignment[AccessAssignmentKey.ROLE_ID.value] for assignment in removed})

    return GroupDeleteEffect(removed_ids, locked, opened)


def guard_group_delete(request_user: CmdbUser, group_id: int) -> None:
    """
    Judges a user group delete, which takes the group's assignments along

    Args:
        request_user (CmdbUser): The caller
        group_id (int): The group's public_id

    Raises:
        HTTPException: 400 naming the Types locked or opened
    """
    effect: GroupDeleteEffect = group_delete_effect(request_user, group_id)
    abort_if_effect_refused(effect.locked, effect.opened)


def assignment_delete_effect(request_user: CmdbUser, stored: dict[str, Any]) -> tuple[list[int], list[int]]:
    """
    The Types deleting one assignment would lock and open - the delete's pre-check

    Args:
        request_user (CmdbUser): The caller
        stored (dict[str, Any]): The assignment as stored

    Returns:
        tuple[list[int], list[int]]: The newly locked and the newly opened Types, ascending
    """
    role_id: int = stored[AccessAssignmentKey.ROLE_ID.value]
    before: AccessState = read_access_state(request_user, [role_id])
    after: AccessState = without_assignments(before, [stored[AccessAssignmentKey.PUBLIC_ID.value]])

    return change_effect(request_user, before, after, [role_id])
