# DATAGERRY - OpenSource Enterprise CMDB
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
The reads of the assignment simulation (phase 11) - ``POST /access/assignments/simulate``

The assignment is judged like a save (the same 400), its reach compiled - per member for up to 20 members when its
scope names a user token (D3) - and counted in ONE aggregation on the query time budget (P1), within the caller's own
view (D2). With ``assignment_id`` the stored assignment's reach is compiled too, for what the change gains and loses
(D4). Beside the counts: the group's members (named only for a caller who may view users, D5), the Types the
assignment newly restricts (the lock guard's states), and the warnings (D6). Nothing is written
"""
from datetime import datetime, timezone
from typing import Any

from flask import abort

from cmdb.database.database_constants import QUERY_TIME_LIMIT_MS
from cmdb.manager import (
    AccessAssignmentsManager,
    GroupsManager,
    ObjectsManager,
    ScopeRolesManager,
    TypesManager,
    UsersManager,
)
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.models.access_model import AccessAssignmentKey, ScopeOperation, ScopeRoleKey, UNCONDITIONAL_SCOPE
from cmdb.models.user_model import CmdbUser, CmdbUserKey
from cmdb.framework.access_engine import scope_filter
from cmdb.framework.access_rules import AccessRuleMessage, canonical_scope, newly_restricted
from cmdb.framework.access_rules.assignment_scope_rules import judge_scope, role_type_documents
from cmdb.framework.access_rules.assignment_simulation import (
    all_of,
    any_of,
    condition_warnings,
    count_warnings,
    facet_by_type,
    facet_count,
    facet_sample_ids,
    member_facet,
    role_clause,
    simulation_pipeline,
)
from cmdb.framework.access_rules.assignment_simulation_constants import (
    MAX_LISTED_MEMBERS,
    MAX_SIMULATED_MEMBERS,
    SimulationFacet,
    SimulationKey,
)
from cmdb.framework.scope_compiler import (
    ScopeContext,
    ScopeField,
    ScopeReferences,
    ScopeResolver,
    compile_scope,
    field_views_of_document,
    resolve_scope_fields,
    scope_field_names,
    scope_references,
)
from cmdb.interface.route_utils import user_has_right
from cmdb.interface.rest_api.routes.routes_helper import abort_on_problems
from cmdb.interface.rest_api.routes.access_routes.access_change_guard import assignment_change, change_states
from cmdb.interface.rest_api.routes.access_routes.access_route_constants import SIMULATION_ASSIGNMENT_ID
from cmdb.interface.rest_api.routes.user_management_routes.users_constants import UserAccessRight
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'simulate_assignment',
]

ASSIGNMENT_NOT_FOUND_MESSAGE: str = "Assignment {assignment_id} does not exist!"
_MEMBER_PROJECTION: dict[str, int] = {'_id': 0, CmdbUserKey.PUBLIC_ID.value: 1, CmdbUserKey.USER_NAME.value: 1,
                                      CmdbUserKey.GROUP_IDS.value: 1}


class _Reach:
    """
    What an assignment reaches: the union over its members, and per member counted one by one

    Attributes:
        union (dict[str, Any]): The objects it reaches for any member (for every one without a user token)
        members (dict[int, dict[str, Any]]): Per simulated member, its reach - empty without a user token
        contexts (dict[int, ScopeContext]): Per simulated member, its resolved tokens
    """
    def __init__(self, union: dict[str, Any], members: dict[int, dict[str, Any]],
                 contexts: dict[int, ScopeContext]) -> None:
        """
        Args:
            union (dict[str, Any]): The union
            members (dict[int, dict[str, Any]]): Per member
            contexts (dict[int, ScopeContext]): Per member, its tokens
        """
        self.union: dict[str, Any] = union
        self.members: dict[int, dict[str, Any]] = members
        self.contexts: dict[int, ScopeContext] = contexts


class _Simulated:
    """
    The simulated assignment, judged, and the stored one a change is simulated against

    Attributes:
        granted_group (int): Its user group
        role (dict[str, Any]): Its scope role
        scope (Any): Its scope, cast and canonical
        type_documents (list[dict[str, Any]]): The role's Types
        stored (dict[str, Any] | None): The stored assignment; None for a create
    """
    def __init__(self, group_id: int, role: dict[str, Any], scope: Any, type_documents: list[dict[str, Any]],
                 stored: dict[str, Any] | None) -> None:
        """
        Args:
            group_id (int): Its user group
            role (dict[str, Any]): Its scope role
            scope (Any): Its cast scope
            type_documents (list[dict[str, Any]]): The role's Types
            stored (dict[str, Any] | None): The stored assignment, or None
        """
        self.granted_group: int = group_id
        self.role: dict[str, Any] = role
        self.scope: Any = scope
        self.type_documents: list[dict[str, Any]] = type_documents
        self.stored: dict[str, Any] | None = stored

    def written(self) -> dict[str, Any]:
        """
        The assignment as it would be stored - what the lock guard's states judge

        Returns:
            dict[str, Any]: ``{group_id, role_id, scope}`` and the stored id for a change
        """
        written: dict[str, Any] = {AccessAssignmentKey.GROUP_ID.value: self.granted_group,
                                   AccessAssignmentKey.ROLE_ID.value: self.role[ScopeRoleKey.PUBLIC_ID.value],
                                   AccessAssignmentKey.SCOPE.value: self.scope}

        if self.stored is not None:
            written[AccessAssignmentKey.PUBLIC_ID.value] = self.stored[AccessAssignmentKey.PUBLIC_ID.value]

        return written


def simulate_assignment(request_user: CmdbUser, data: dict[str, Any]) -> dict[str, Any]:
    """
    Simulates an assignment create, or with ``assignment_id`` the change of a stored one

    Args:
        request_user (CmdbUser): The caller
        data (dict[str, Any]): ``{group_id, role_id, scope, assignment_id?}``

    Raises:
        HTTPException: 400 naming every problem (the group or role missing, the scope's shape, fields, values), 404
            for a stored assignment that is gone
        BaseManagerIterationError: When the count could not be run - its time budget answers 503

    Returns:
        dict[str, Any]: The simulation answer
    """
    simulated: _Simulated = _judged(request_user, data)
    now: datetime = datetime.now(timezone.utc)
    members: list[dict[str, Any]] = _members(request_user, simulated.granted_group)
    fields: dict[str, ScopeField] = _fields(simulated.scope, simulated.type_documents)
    reach: _Reach = _reach(request_user, simulated.role, simulated.scope, fields, members, now)
    role_clauses: list[dict[str, Any]] = [role_clause(simulated.role)]
    stored_reach: dict[str, Any] | None = None

    if simulated.stored is not None:
        stored_role, stored_reach = _stored_reach(request_user, simulated.stored, members, now)
        role_clauses.append(role_clause(stored_role) if stored_role else any_of([]))

    objects: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
    result: dict[str, Any] = objects.aggregate_within_time_limit(
        simulation_pipeline(scope_filter(request_user, ScopeOperation.VIEW), role_clauses, reach.union, stored_reach,
                            reach.members), QUERY_TIME_LIMIT_MS)[0]
    restricted: list[int] = newly_restricted(*change_states(
        request_user, *assignment_change(request_user, simulated.stored, simulated.written())))

    return _answer(request_user, objects, result, simulated, fields, reach, members, restricted)


def _judged(request_user: CmdbUser, data: dict[str, Any]) -> _Simulated:
    """
    The simulated assignment judged like a save

    Args:
        request_user (CmdbUser): The caller
        data (dict[str, Any]): ``{group_id, role_id, scope, assignment_id?}``

    Raises:
        HTTPException: 400 naming every problem, 404 for a gone ``assignment_id``

    Returns:
        _Simulated: The judged assignment
    """
    roles: ScopeRolesManager = ManagerProvider.get_manager(ManagerType.SCOPE_ROLES, request_user)
    types: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)
    group_id: int = data[AccessAssignmentKey.GROUP_ID.value]
    role_id: int = data[AccessAssignmentKey.ROLE_ID.value]
    role: dict[str, Any] | None = roles.get_item(role_id, as_dict=True)
    stored: dict[str, Any] | None = _stored_assignment(request_user, data.get(SIMULATION_ASSIGNMENT_ID))
    group_problems: list[str] = _group_problems(request_user, group_id)

    if not role:
        abort_on_problems([*group_problems, AccessRuleMessage.UNKNOWN_ROLE.value.format(role_id=role_id)])

    type_documents: list[dict[str, Any]] = role_type_documents(role, types)
    judged, problems = judge_scope(data[AccessAssignmentKey.SCOPE.value], type_documents)
    abort_on_problems([*group_problems, *problems])

    return _Simulated(group_id, role, canonical_scope(judged), type_documents, stored)


def _stored_reach(request_user: CmdbUser, stored: dict[str, Any], members: list[dict[str, Any]],
                  now: datetime) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """
    What the stored assignment reaches - nothing when its role is gone

    Args:
        request_user (CmdbUser): The caller
        stored (dict[str, Any]): The stored assignment
        members (list[dict[str, Any]]): Its group's members
        now (datetime): The evaluation instant

    Returns:
        tuple[dict[str, Any] | None, dict[str, Any]]: Its role (None when gone) and its reach
    """
    roles: ScopeRolesManager = ManagerProvider.get_manager(ManagerType.SCOPE_ROLES, request_user)
    types: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)
    role: dict[str, Any] | None = roles.get_item(stored[AccessAssignmentKey.ROLE_ID.value], as_dict=True)

    if not role:
        return None, any_of([])

    scope: Any = stored.get(AccessAssignmentKey.SCOPE.value)

    return role, _reach(request_user, role, scope, _fields(scope, role_type_documents(role, types)), members,
                        now).union


def _stored_assignment(request_user: CmdbUser, assignment_id: Any) -> dict[str, Any] | None:
    """
    The stored assignment a change is simulated against

    Args:
        request_user (CmdbUser): The caller
        assignment_id (Any): Its id, or None for a create

    Raises:
        HTTPException: 404 when it is gone

    Returns:
        dict[str, Any] | None: The stored assignment; None for a create
    """
    if assignment_id is None:
        return None

    assignments: AccessAssignmentsManager = ManagerProvider.get_manager(ManagerType.ACCESS_ASSIGNMENTS, request_user)
    stored: dict[str, Any] | None = assignments.get_item(assignment_id, as_dict=True)

    if not stored:
        abort(404, ASSIGNMENT_NOT_FOUND_MESSAGE.format(assignment_id=assignment_id))

    return stored


def _group_problems(request_user: CmdbUser, group_id: int) -> list[str]:
    """
    Whether the assignment's user group exists

    Args:
        request_user (CmdbUser): The caller
        group_id (int): The group

    Returns:
        list[str]: The problem, or none
    """
    groups: GroupsManager = ManagerProvider.get_manager(ManagerType.GROUPS, request_user)

    return [] if groups.get_group(group_id) else [AccessRuleMessage.UNKNOWN_GROUP.value.format(group_id=group_id)]


def _members(request_user: CmdbUser, group_id: int) -> list[dict[str, Any]]:
    """
    The group's members, ascending by id

    Args:
        request_user (CmdbUser): The caller
        group_id (int): The group

    Returns:
        list[dict[str, Any]]: Their ids, names and groups
    """
    users: UsersManager = ManagerProvider.get_manager(ManagerType.USERS, request_user)

    return users.find(criteria={CmdbUserKey.GROUP_IDS.value: group_id}, projection=_MEMBER_PROJECTION,
                      sort=[(CmdbUserKey.PUBLIC_ID.value, 1)])


def _fields(scope: Any, type_documents: list[dict[str, Any]]) -> dict[str, ScopeField]:
    """
    A scope's fields, resolved across its role's Types

    Args:
        scope (Any): The cast scope
        type_documents (list[dict[str, Any]]): The role's Types

    Returns:
        dict[str, ScopeField]: The fields by name; none for ``"*"``
    """
    if scope == UNCONDITIONAL_SCOPE:
        return {}

    fields, _problems = resolve_scope_fields(scope_field_names({AccessAssignmentKey.SCOPE.value: scope}),
                                             [field_views_of_document(document) for document in type_documents])

    return fields


def _reach(request_user: CmdbUser, role: dict[str, Any], scope: Any, fields: dict[str, ScopeField],
           members: list[dict[str, Any]], now: datetime) -> _Reach:
    """
    What an assignment reaches - per member for up to MAX_SIMULATED_MEMBERS when its scope names a user token

    Args:
        request_user (CmdbUser): The caller
        role (dict[str, Any]): Its scope role
        scope (Any): Its cast scope
        fields (dict[str, ScopeField]): The scope's fields
        members (list[dict[str, Any]]): The group's members
        now (datetime): The evaluation instant

    Raises:
        ScopeResolutionError: When a token could not be read

    Returns:
        _Reach: The reach
    """
    types_clause: dict[str, Any] = role_clause(role)

    if scope == UNCONDITIONAL_SCOPE:
        return _Reach(types_clause, {}, {})

    references: ScopeReferences = scope_references([scope])

    if not (references.person or references.groups):
        return _Reach(all_of(types_clause, compile_scope(scope, fields, now)), {}, {})

    resolver: ScopeResolver = ScopeResolver(ManagerProvider.get_manager(ManagerType.OBJECTS, request_user))
    contexts: dict[int, ScopeContext] = {
        member[CmdbUserKey.PUBLIC_ID.value]: resolver.resolve(
            CmdbUser(public_id=member[CmdbUserKey.PUBLIC_ID.value], user_name=member[CmdbUserKey.USER_NAME.value],
                     active=True, group_ids=member.get(CmdbUserKey.GROUP_IDS.value) or []), references)
        for member in members[:MAX_SIMULATED_MEMBERS]}
    per_member: dict[int, dict[str, Any]] = {user_id: all_of(types_clause, compile_scope(scope, fields, now, context))
                                             for user_id, context in contexts.items()}

    return _Reach(any_of(list(per_member.values())), per_member, contexts)


def _unresolved(scope: Any, contexts: dict[int, ScopeContext]) -> list[int]:
    """
    The simulated members a user token of the scope resolves to nothing for

    Args:
        scope (Any): The cast scope
        contexts (dict[int, ScopeContext]): Per simulated member, its tokens

    Returns:
        list[int]: Those members
    """
    if not contexts:
        return []

    references: ScopeReferences = scope_references([scope])

    return [user_id for user_id, context in contexts.items()
            if (references.person and not context.person_ids) or (references.groups and not context.group_ids)]


def _answer(request_user: CmdbUser, objects: ObjectsManager, result: dict[str, Any], simulated: _Simulated,
            fields: dict[str, ScopeField], reach: _Reach, members: list[dict[str, Any]],
            restricted: list[int]) -> dict[str, Any]:
    """
    The simulation answer

    Args:
        request_user (CmdbUser): The caller
        objects (ObjectsManager): Reads the samples' summary lines
        result (dict[str, Any]): The aggregation's one document
        simulated (_Simulated): The simulated assignment
        fields (dict[str, ScopeField]): Its scope's fields
        reach (_Reach): Its reach
        members (list[dict[str, Any]]): The group's members
        restricted (list[int]): The Types the assignment newly restricts

    Returns:
        dict[str, Any]: The answer
    """
    changed: bool = simulated.stored is not None
    total: int = sum(row[SimulationKey.COUNT.value] for row in facet_by_type(result))
    sample_facets: list[str] = [SimulationFacet.SAMPLES.value]

    if changed:
        sample_facets += [SimulationFacet.GAINED_SAMPLES.value, SimulationFacet.LOST_SAMPLES.value]

    samples: dict[str, list[dict[str, Any]]] = _summarised(objects, {facet: facet_sample_ids(result, facet)
                                                                    for facet in sample_facets})
    answer: dict[str, Any] = {
        SimulationKey.GROUP_ID.value: simulated.granted_group,
        SimulationKey.ROLE_ID.value: simulated.role[ScopeRoleKey.PUBLIC_ID.value],
        SimulationKey.SCOPE.value: simulated.scope,
        SimulationKey.WITHIN_CALLERS_VIEW.value: True,
        SimulationKey.TOTAL.value: total,
        SimulationKey.BY_TYPE.value: facet_by_type(result),
        SimulationKey.SAMPLES.value: samples[SimulationFacet.SAMPLES.value],
        SimulationKey.MEMBERS.value: _members_answer(request_user, members, reach, result),
        SimulationKey.NEWLY_RESTRICTED_TYPES.value: restricted,
        SimulationKey.WARNINGS.value: [
            *condition_warnings(simulated.scope, fields),
            *count_warnings(simulated.scope, total, facet_count(result, SimulationFacet.ROLE_TOTAL.value),
                            _unresolved(simulated.scope, reach.contexts), restricted)],
    }

    if changed:
        answer[SimulationKey.GAINED.value] = {
            SimulationKey.COUNT.value: facet_count(result, SimulationFacet.GAINED.value),
            SimulationKey.SAMPLES.value: samples[SimulationFacet.GAINED_SAMPLES.value]}
        answer[SimulationKey.LOST.value] = {
            SimulationKey.COUNT.value: facet_count(result, SimulationFacet.LOST.value),
            SimulationKey.SAMPLES.value: samples[SimulationFacet.LOST_SAMPLES.value]}

    return answer


def _summarised(objects: ObjectsManager, samples: dict[str, list[dict[str, Any]]]) -> dict[str, list[dict[str, Any]]]:
    """
    The samples with their summary lines - one read for every list

    Args:
        objects (ObjectsManager): Reads the summary lines
        samples (dict[str, list[dict[str, Any]]]): Per facet, its ``{public_id, type_id}`` rows

    Returns:
        dict[str, list[dict[str, Any]]]: The rows with ``summary``
    """
    lines: dict[int, str] = objects.get_summary_lines_lookup(
        sorted({row[SimulationKey.PUBLIC_ID.value] for rows in samples.values() for row in rows}))

    return {facet: [{**row, SimulationKey.SUMMARY.value: lines.get(row[SimulationKey.PUBLIC_ID.value], '')}
                    for row in rows] for facet, rows in samples.items()}


def _members_answer(request_user: CmdbUser, members: list[dict[str, Any]], reach: _Reach,
                    result: dict[str, Any]) -> dict[str, Any]:
    """
    The affected users: how many; named only for a caller who may view users (D5); counted one by one with tokens (D3)

    Args:
        request_user (CmdbUser): The caller
        members (list[dict[str, Any]]): The group's members
        reach (_Reach): The simulated reach
        result (dict[str, Any]): The aggregation's one document

    Returns:
        dict[str, Any]: ``{member_count, members?, simulated_members?}``
    """
    named: bool = user_has_right(UserAccessRight.VIEW.value, request_user)
    answer: dict[str, Any] = {SimulationKey.MEMBER_COUNT.value: len(members)}

    if named:
        answer[SimulationKey.MEMBERS.value] = [
            {SimulationKey.USER_ID.value: member[CmdbUserKey.PUBLIC_ID.value],
             SimulationKey.USER_NAME.value: member[CmdbUserKey.USER_NAME.value]}
            for member in members[:MAX_LISTED_MEMBERS]]

    if reach.members:
        answer[SimulationKey.SIMULATED_MEMBERS.value] = [
            {SimulationKey.USER_ID.value: user_id,
             SimulationKey.COUNT.value: facet_count(result, member_facet(user_id))}
            for user_id in reach.members]

    return answer
