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
The ``/access/assignments`` routes: assignments of the access rules - create, read, list, update, delete

Reads ask ``base.access.view`` at the ADMIN level, writes ``base.access.assignment.edit`` at SUPER_ADMIN
(the tenant's setup; the cloud API key cannot write). Nothing decides access from assignments yet: the type ACL
still does
"""
from typing import Any

from werkzeug import Response

from cmdb.manager import AccessAssignmentsManager, GroupsManager, ScopeRolesManager, TypesManager
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.models.user_model import CmdbUser
from cmdb.models.access_model import AccessAssignmentKey, CmdbAccessAssignment
from cmdb.utils import keep_omitted_keys
from cmdb.framework.access_rules import AccessRuleMessage
from cmdb.interface.rest_api.routes.access_routes.access_change_guard import (
    assignment_delete_effect,
    guard_assignment_write,
)
from cmdb.interface.rest_api.routes.access_routes.access_delegation import abort_unless_delegable
from cmdb.interface.rest_api.routes.access_routes.assignment_simulation_helper import simulate_assignment
from cmdb.interface.rest_api.routes.access_routes.field_rule_guard import guard_scope_rule_fields
from cmdb.interface.rest_api.routes.access_routes.access_payloads import (
    checked_scope,
    abort_if_beyond_own_reach,
    assignment_payload,
)
from cmdb.models.access_model import HistoryKind
from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.rest_api.routes.access_routes.access_history_helper import (
    ChangeContext,
    query_comment,
    take_comment,
)
from cmdb.interface.route_utils import handle_route_errors, insert_request_user, verify_api_access
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.rest_api.responses import GetSingleResponse
from cmdb.interface.rest_api.responses.response_parameters import CollectionParameters
from cmdb.interface.rest_api.routes.routes_helper import request_wants_body
from cmdb.interface.rest_api.routes.access_routes.access_route_constants import (
    ASSIGNMENT_CHECK_SCHEMA,
    ASSIGNMENT_CREATE_SCHEMA,
    ASSIGNMENT_SEARCHABLE_FIELDS,
    ASSIGNMENT_SIMULATE_SCHEMA,
    ASSIGNMENT_UPDATE_SCHEMA,
    AccessRightName,
    AccessUsageKey,
)
from cmdb.interface.rest_api.routes.access_routes.access_routes_helper import (
    create_response,
    delete_response,
    list_response,
    load_or_404,
    update_response,
)
# -------------------------------------------------------------------------------------------------------------------- #

assignments_blueprint = APIBlueprint('assignments', __name__)

# What the 404 calls the document
LABEL: str = 'Assignment'
# An assignment write is open to its editors and its delegates - the delegation rule then judges a delegate's
ASSIGNMENT_WRITE_RIGHTS: tuple[str, str] = (AccessRightName.ASSIGNMENT_EDIT.value,
                                            AccessRightName.ASSIGNMENT_DELEGATE.value)


def _manager(request_user: CmdbUser) -> AccessAssignmentsManager:
    """
    The assignments of the caller's database

    Args:
        request_user (CmdbUser): The caller

    Returns:
        AccessAssignmentsManager: The manager
    """
    return ManagerProvider.get_manager(ManagerType.ACCESS_ASSIGNMENTS, request_user)


def _judged(manager: AccessAssignmentsManager, request_user: CmdbUser, assignment: dict[str, Any],
            own_id: int | None = None, sent: dict[str, Any] | None = None) -> dict[str, Any]:
    """
    Judges an assignment as it would be stored against the caller's user groups and scope roles - and, for a group
    the caller is in, against the caller's own reach

    Args:
        manager (AccessAssignmentsManager): The assignments of the caller's database
        request_user (CmdbUser): The caller
        assignment (dict[str, Any]): The assignment as it would be stored
        own_id (int | None): The assignment being updated; None for a create
        sent (dict[str, Any] | None): An update's body - only its references are judged

    Raises:
        HTTPException: 400 naming every problem; 403 when the role would give the caller's own group more than the
            caller holds

    Returns:
        dict[str, Any]: The document to store, its scope canonical
    """
    groups: GroupsManager = ManagerProvider.get_manager(ManagerType.GROUPS, request_user)
    roles: ScopeRolesManager = ManagerProvider.get_manager(ManagerType.SCOPE_ROLES, request_user)
    types: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)
    payload: dict[str, Any] = assignment_payload(manager, groups, roles, assignment, own_id, sent, types)
    guard_scope_rule_fields(request_user, roles, payload[AccessAssignmentKey.ROLE_ID.value],
                            payload[AccessAssignmentKey.SCOPE.value])
    group_id: int = payload[AccessAssignmentKey.GROUP_ID.value]

    if group_id in request_user.group_ids:
        role_id: int = payload[AccessAssignmentKey.ROLE_ID.value]
        abort_if_beyond_own_reach(request_user, role_id, roles.get_item(role_id, as_dict=True) or {}, [group_id])

    return payload


def _taken(assignment: dict[str, Any]) -> str:
    """
    What an assignment write losing the uniqueness race says

    Args:
        assignment (dict[str, Any]): The assignment written

    Returns:
        str: The message
    """
    return AccessRuleMessage.ASSIGNMENT_TAKEN.value.format(group_id=assignment[AccessAssignmentKey.GROUP_ID.value],
                                                           role_id=assignment[AccessAssignmentKey.ROLE_ID.value])

# --------------------------------------------------- CRUD - CREATE -------------------------------------------------- #

@assignments_blueprint.route('', methods=['POST'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.SUPER_ADMIN)
@assignments_blueprint.protect(auth=True, right=ASSIGNMENT_WRITE_RIGHTS)
@assignments_blueprint.validate(ASSIGNMENT_CREATE_SCHEMA)
@handle_route_errors("while creating a assignment")
def create_assignment(data: dict[str, Any], request_user: CmdbUser) -> Response:
    """
    HTTP `POST` route storing a new assignment

    Args:
        data (dict[str, Any]): The validated body
        request_user (CmdbUser): The caller

    Raises:
        HTTPException: 400 for a body failing the schema or the write rules, or locking a Type; 403 for a group of
            the caller's given more than the caller holds, or a delegate's role beyond their own access

    Returns:
        InsertSingleResponse: 201 with the stored assignment and its public_id
    """
    change: ChangeContext = ChangeContext(request_user, HistoryKind.ASSIGNMENT, take_comment(data))
    manager: AccessAssignmentsManager = _manager(request_user)
    payload: dict[str, Any] = _judged(manager, request_user, data)
    abort_unless_delegable(request_user, [payload[AccessAssignmentKey.ROLE_ID.value]])
    guard_assignment_write(request_user, None, payload)

    return create_response(manager, CmdbAccessAssignment, payload, _taken(payload), change)

@assignments_blueprint.route('/check', methods=['POST'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@assignments_blueprint.protect(auth=True, right=AccessRightName.VIEW.value)
@assignments_blueprint.validate(ASSIGNMENT_CHECK_SCHEMA)
@handle_route_errors("while checking a scope")
def check_assignment_scope(data: dict[str, Any], request_user: CmdbUser) -> Response:
    """
    HTTP `POST` route judging a scope against a scope role's Types without writing anything - what the scope builder
    flags in the dialog (phase 9, R30)

    Args:
        data (dict[str, Any]): ``{role_id, scope}``
        request_user (CmdbUser): The caller

    Raises:
        HTTPException: 400 naming every problem - the role missing, the scope's shape, its fields, its values

    Returns:
        GetSingleResponse: ``{role_id, scope}`` - the scope as it would be stored (cast, canonical)
    """
    roles: ScopeRolesManager = ManagerProvider.get_manager(ManagerType.SCOPE_ROLES, request_user)
    types: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)
    role_id: int = data[AccessAssignmentKey.ROLE_ID.value]
    scope: Any = checked_scope(roles, types, role_id, data[AccessAssignmentKey.SCOPE.value])
    guard_scope_rule_fields(request_user, roles, role_id, scope)

    return GetSingleResponse({AccessAssignmentKey.ROLE_ID.value: role_id, AccessAssignmentKey.SCOPE.value: scope},
                             body=True).make_response()


@assignments_blueprint.route('/simulate', methods=['POST'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@assignments_blueprint.protect(auth=True, right=AccessRightName.VIEW.value)
@assignments_blueprint.validate(ASSIGNMENT_SIMULATE_SCHEMA)
@handle_route_errors("while simulating an assignment")
def simulate_assignment_route(data: dict[str, Any], request_user: CmdbUser) -> Response:
    """
    HTTP `POST` route simulating an assignment before it is saved - what it would reach, per Type, with samples, who it
    affects, what a change gains and loses, and the warnings; nothing written (phase 11)

    Args:
        data (dict[str, Any]): ``{group_id, role_id, scope, assignment_id?}``
        request_user (CmdbUser): The caller

    Raises:
        HTTPException: 400 naming every problem (as a save), 404 for a gone ``assignment_id``, 503 past the query
            time budget

    Returns:
        GetSingleResponse: The simulation, counted within the caller's own view
    """
    return GetSingleResponse(simulate_assignment(request_user, data), body=True).make_response()

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

@assignments_blueprint.route('', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@assignments_blueprint.protect(auth=True, right=AccessRightName.VIEW.value)
@assignments_blueprint.parse_collection_parameters()
@handle_route_errors("while retrieving the assignments")
def get_assignments(params: CollectionParameters, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route for one page of the assignments - ``?filter=``, ``?search=``, ``?sort=``, paging

    Args:
        params (CollectionParameters): The collection parameters
        request_user (CmdbUser): The caller

    Returns:
        GetMultiResponse: The page and its total
    """
    return list_response(_manager(request_user), CmdbAccessAssignment, params, ASSIGNMENT_SEARCHABLE_FIELDS)


@assignments_blueprint.route('/<int:public_id>', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@assignments_blueprint.protect(auth=True, right=AccessRightName.VIEW.value)
@handle_route_errors("while retrieving the assignment with ID: {public_id}")
def get_assignment(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route for one assignment

    Args:
        public_id (int): The assignment's public_id
        request_user (CmdbUser): The caller

    Raises:
        HTTPException: 404 when it does not exist

    Returns:
        GetSingleResponse: The assignment as stored
    """
    stored: dict[str, Any] = load_or_404(_manager(request_user), public_id, LABEL)

    return GetSingleResponse(stored, body=request_wants_body()).make_response()

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

@assignments_blueprint.route('/<int:public_id>', methods=['PUT'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.SUPER_ADMIN)
@assignments_blueprint.protect(auth=True, right=ASSIGNMENT_WRITE_RIGHTS)
@assignments_blueprint.validate(ASSIGNMENT_UPDATE_SCHEMA)
@handle_route_errors("while updating the assignment with ID: {public_id}")
def update_assignment(public_id: int, data: dict[str, Any], request_user: CmdbUser) -> Response:
    """
    HTTP `PUT` route updating a assignment: what the body sends replaces the stored value, what it leaves out is kept

    Args:
        public_id (int): The assignment's public_id
        data (dict[str, Any]): The validated body
        request_user (CmdbUser): The caller

    Raises:
        HTTPException: 404 when it does not exist; 400 for a body failing the schema or the write rules, locking a
            Type or opening one without ``unrestrict=true``; 403 for a group of the caller's given more than the caller
            holds, or a delegate's role - before or after - beyond their own access

    Returns:
        UpdateSingleResponse: 202 with the assignment as stored
    """
    change: ChangeContext = ChangeContext(request_user, HistoryKind.ASSIGNMENT, take_comment(data))
    manager: AccessAssignmentsManager = _manager(request_user)
    stored: dict[str, Any] = load_or_404(manager, public_id, LABEL)
    payload: dict[str, Any] = _judged(manager, request_user, keep_omitted_keys(data, stored), public_id, data)
    abort_unless_delegable(request_user, [stored[AccessAssignmentKey.ROLE_ID.value],
                                          payload[AccessAssignmentKey.ROLE_ID.value]])
    guard_assignment_write(request_user, stored, payload)

    return update_response(manager, CmdbAccessAssignment, public_id, payload, _taken(payload), change, stored)

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

@assignments_blueprint.route('/<int:public_id>', methods=['DELETE'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.SUPER_ADMIN)
@assignments_blueprint.protect(auth=True, right=ASSIGNMENT_WRITE_RIGHTS)
@handle_route_errors("while deleting the assignment with ID: {public_id}")
def delete_assignment(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `DELETE` route deleting an assignment - refused when it would lock a Type, or open one without
    ``unrestrict=true`` (``GET .../usage`` tells which beforehand)

    Args:
        public_id (int): The assignment's public_id
        request_user (CmdbUser): The caller

    Raises:
        HTTPException: 404 when it does not exist; 400 naming the Types it would lock or open

    Returns:
        DeleteSingleResponse: 202 with the assignment as it was stored
    """
    change: ChangeContext = ChangeContext(request_user, HistoryKind.ASSIGNMENT, query_comment())
    manager: AccessAssignmentsManager = _manager(request_user)
    stored: dict[str, Any] = load_or_404(manager, public_id, LABEL)
    abort_unless_delegable(request_user, [stored[AccessAssignmentKey.ROLE_ID.value]])
    guard_assignment_write(request_user, stored, None)

    return delete_response(manager, stored, change)


@assignments_blueprint.route('/<int:public_id>/usage', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@assignments_blueprint.protect(auth=True, right=AccessRightName.VIEW.value)
@handle_route_errors("while retrieving the usage of the assignment with ID: {public_id}")
def get_assignment_usage(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route for what deleting an assignment would do: the Types it would leave readable by no group
    (the delete is refused) and the Types it would open to every group (the delete needs ``unrestrict=true``)

    Args:
        public_id (int): The assignment's public_id
        request_user (CmdbUser): The caller

    Raises:
        HTTPException: 404 when it does not exist

    Returns:
        GetSingleResponse: ``{locked_type_ids: [...], opened_type_ids: [...]}``, ascending
    """
    stored: dict[str, Any] = load_or_404(_manager(request_user), public_id, LABEL)
    locked, opened = assignment_delete_effect(request_user, stored)

    return GetSingleResponse({AccessUsageKey.LOCKED_TYPE_IDS.value: locked,
                              AccessUsageKey.OPENED_TYPE_IDS.value: opened}, body=request_wants_body()).make_response()
