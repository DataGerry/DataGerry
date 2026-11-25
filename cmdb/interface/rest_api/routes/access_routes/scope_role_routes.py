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
The ``/access/scope_roles`` routes: scope roles of the access rules - create, read, list, update, delete, usage

Reads ask ``base.access.view`` at the ADMIN level, writes ``base.access.scoperole.edit`` at SUPER_ADMIN
(the tenant's setup; the cloud API key cannot write). Nothing decides access from scope roles yet: the type ACL
still does
"""
from typing import Any

from werkzeug import Response

from cmdb.manager import AccessAssignmentsManager, FieldClassesManager, ScopeRolesManager, TypesManager
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.models.user_model import CmdbUser
from cmdb.models.access_model import AccessAssignmentKey, CmdbAccessAssignment, CmdbScopeRole, ScopeRoleKey
from cmdb.utils import keep_omitted_keys
from cmdb.framework.access_rules import AccessRuleMessage, scope_role_in_use
from cmdb.interface.rest_api.routes.access_routes.access_change_guard import guard_role_update
from cmdb.interface.rest_api.routes.access_routes.access_payloads import abort_if_beyond_own_reach, scope_role_payload
from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.route_utils import handle_route_errors, insert_request_user, verify_api_access
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.rest_api.responses import GetSingleResponse
from cmdb.interface.rest_api.responses.response_parameters import CollectionParameters
from cmdb.interface.rest_api.routes.routes_helper import abort_on_problems, request_wants_body
from cmdb.interface.rest_api.routes.access_routes.access_route_constants import (
    SCOPE_ROLE_CREATE_SCHEMA,
    SCOPE_ROLE_SEARCHABLE_FIELDS,
    SCOPE_ROLE_UPDATE_SCHEMA,
    AccessRightName,
    AccessUsageKey,
)
from cmdb.interface.rest_api.routes.access_routes.access_routes_helper import (
    as_model_json,
    create_response,
    delete_response,
    list_response,
    load_or_404,
    update_response,
)
# -------------------------------------------------------------------------------------------------------------------- #

scope_roles_blueprint = APIBlueprint('scope_roles', __name__)

# What the 404 calls the document
LABEL: str = 'Scope role'


def _manager(request_user: CmdbUser) -> ScopeRolesManager:
    """
    The scope roles of the caller's database

    Args:
        request_user (CmdbUser): The caller

    Returns:
        ScopeRolesManager: The manager
    """
    return ManagerProvider.get_manager(ManagerType.SCOPE_ROLES, request_user)


def _judged(manager: ScopeRolesManager, request_user: CmdbUser, role: dict[str, Any],
            own_id: int | None = None, sent: dict[str, Any] | None = None) -> dict[str, Any]:
    """
    Judges a scope role as it would be stored against the caller's Types and field classes

    Args:
        manager (ScopeRolesManager): The scope roles of the caller's database
        request_user (CmdbUser): The caller
        role (dict[str, Any]): The role as it would be stored
        own_id (int | None): The role being updated; None for a create
        sent (dict[str, Any] | None): An update's body - only its references are judged

    Raises:
        HTTPException: 400 naming every problem

    Returns:
        dict[str, Any]: The document to store
    """
    types: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)
    classes: FieldClassesManager = ManagerProvider.get_manager(ManagerType.FIELD_CLASSES, request_user)

    return scope_role_payload(manager, types, classes, request_user, role, own_id, sent)


def _name_taken(role: dict[str, Any]) -> str:
    """
    What a scope role write losing the uniqueness race says

    Args:
        role (dict[str, Any]): The role written

    Returns:
        str: The message
    """
    return AccessRuleMessage.SCOPE_ROLE_NAME_TAKEN.value.format(name=role[ScopeRoleKey.NAME.value])

# --------------------------------------------------- CRUD - CREATE -------------------------------------------------- #

@scope_roles_blueprint.route('', methods=['POST'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.SUPER_ADMIN)
@scope_roles_blueprint.protect(auth=True, right=AccessRightName.SCOPE_ROLE_EDIT.value)
@scope_roles_blueprint.validate(SCOPE_ROLE_CREATE_SCHEMA)
@handle_route_errors("while creating a scope role")
def create_scope_role(data: dict[str, Any], request_user: CmdbUser) -> Response:
    """
    HTTP `POST` route storing a new scope role

    Args:
        data (dict[str, Any]): The validated body
        request_user (CmdbUser): The caller

    Raises:
        HTTPException: 400 for a body failing the schema or the write rules

    Returns:
        InsertSingleResponse: 201 with the stored scope role and its public_id
    """
    manager: ScopeRolesManager = _manager(request_user)
    payload: dict[str, Any] = _judged(manager, request_user, data)

    return create_response(manager, CmdbScopeRole, payload, _name_taken(payload))

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

@scope_roles_blueprint.route('', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@scope_roles_blueprint.protect(auth=True, right=AccessRightName.VIEW.value)
@scope_roles_blueprint.parse_collection_parameters()
@handle_route_errors("while retrieving the scope roles")
def get_scope_roles(params: CollectionParameters, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route for one page of the scope roles - ``?filter=``, ``?search=``, ``?sort=``, paging

    Args:
        params (CollectionParameters): The collection parameters
        request_user (CmdbUser): The caller

    Returns:
        GetMultiResponse: The page and its total
    """
    return list_response(_manager(request_user), CmdbScopeRole, params, SCOPE_ROLE_SEARCHABLE_FIELDS)


@scope_roles_blueprint.route('/<int:public_id>', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@scope_roles_blueprint.protect(auth=True, right=AccessRightName.VIEW.value)
@handle_route_errors("while retrieving the scope role with ID: {public_id}")
def get_scope_role(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route for one scope role

    Args:
        public_id (int): The scope role's public_id
        request_user (CmdbUser): The caller

    Raises:
        HTTPException: 404 when it does not exist

    Returns:
        GetSingleResponse: The scope role as stored
    """
    stored: dict[str, Any] = load_or_404(_manager(request_user), public_id, LABEL)

    return GetSingleResponse(stored, body=request_wants_body()).make_response()


@scope_roles_blueprint.route('/<int:public_id>/usage', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@scope_roles_blueprint.protect(auth=True, right=AccessRightName.VIEW.value)
@handle_route_errors("while retrieving the usage of the scope role with ID: {public_id}")
def get_scope_role_usage(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route for what holds a scope role - the assignments granting it - so a screen can tell before
    a delete

    Args:
        public_id (int): The scope role's public_id
        request_user (CmdbUser): The caller

    Raises:
        HTTPException: 404 when it does not exist

    Returns:
        GetSingleResponse: ``{assignments: [documents as stored]}``, ascending by public_id; empty when nothing holds it
    """
    load_or_404(_manager(request_user), public_id, LABEL)
    assignments: AccessAssignmentsManager = ManagerProvider.get_manager(ManagerType.ACCESS_ASSIGNMENTS, request_user)
    holders: list[dict[str, Any]] = as_model_json(CmdbAccessAssignment, assignments.assignments_of_role(public_id))

    return GetSingleResponse({AccessUsageKey.ASSIGNMENTS.value: holders}, body=request_wants_body()).make_response()

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

@scope_roles_blueprint.route('/<int:public_id>', methods=['PUT'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.SUPER_ADMIN)
@scope_roles_blueprint.protect(auth=True, right=AccessRightName.SCOPE_ROLE_EDIT.value)
@scope_roles_blueprint.validate(SCOPE_ROLE_UPDATE_SCHEMA)
@handle_route_errors("while updating the scope role with ID: {public_id}")
def update_scope_role(public_id: int, data: dict[str, Any], request_user: CmdbUser) -> Response:
    """
    HTTP `PUT` route updating a scope role: what the body sends replaces the stored value, what it leaves out is kept

    Args:
        public_id (int): The scope role's public_id
        data (dict[str, Any]): The validated body
        request_user (CmdbUser): The caller

    Raises:
        HTTPException: 404 when it does not exist; 400 for a body failing the schema or the write rules, locking a
            Type or opening one without ``unrestrict=true``; 403 when the role, assigned to a group the caller is in,
            would grant more than the caller holds

    Returns:
        UpdateSingleResponse: 202 with the scope role as stored
    """
    manager: ScopeRolesManager = _manager(request_user)
    stored: dict[str, Any] = load_or_404(manager, public_id, LABEL)
    payload: dict[str, Any] = _judged(manager, request_user, keep_omitted_keys(data, stored), public_id, data)
    assignments: AccessAssignmentsManager = ManagerProvider.get_manager(ManagerType.ACCESS_ASSIGNMENTS, request_user)
    holders: list[int] = [assignment[AccessAssignmentKey.GROUP_ID.value]
                          for assignment in assignments.assignments_of_role(public_id)]
    abort_if_beyond_own_reach(request_user, public_id, payload, holders)
    guard_role_update(request_user, public_id, payload)

    return update_response(manager, CmdbScopeRole, public_id, payload, _name_taken(payload))

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

@scope_roles_blueprint.route('/<int:public_id>', methods=['DELETE'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.SUPER_ADMIN)
@scope_roles_blueprint.protect(auth=True, right=AccessRightName.SCOPE_ROLE_EDIT.value)
@handle_route_errors("while deleting the scope role with ID: {public_id}")
def delete_scope_role(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `DELETE` route deleting a scope role

    Args:
        public_id (int): The scope role's public_id
        request_user (CmdbUser): The caller

    Raises:
        HTTPException: 404 when it does not exist; 400 while an assignment grants it (``/usage`` names who)

    Returns:
        DeleteSingleResponse: 202 with the scope role as it was stored
    """
    manager: ScopeRolesManager = _manager(request_user)
    stored: dict[str, Any] = load_or_404(manager, public_id, LABEL)
    assignments: AccessAssignmentsManager = ManagerProvider.get_manager(ManagerType.ACCESS_ASSIGNMENTS, request_user)
    abort_on_problems([scope_role_in_use(assignments, public_id)])

    return delete_response(manager, stored)
