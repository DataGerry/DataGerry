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
The REST route answering who has access to one Type: the assignments whose scope role covers it - what the type
editor shows read-only ("Access to this type: n assignments")
"""
from typing import Any

from flask import abort
from werkzeug import Response

from cmdb.manager import AccessAssignmentsManager, ScopeRolesManager, TypesManager
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.models.access_model import AccessAssignmentKey, ScopeRoleKey
from cmdb.models.type_model.type_schema_key_enum import TypeSchemaKey
from cmdb.models.user_model import CmdbUser
from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.route_utils import handle_route_errors, insert_request_user, verify_api_access
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.rest_api.responses import GetSingleResponse
from cmdb.interface.rest_api.routes.routes_helper import request_wants_body
from cmdb.interface.rest_api.routes.access_routes.access_route_constants import (
    TYPE_LABEL,
    AccessRightName,
    AccessRouteMessage,
    TypeAssignmentsKey,
)
# -------------------------------------------------------------------------------------------------------------------- #

access_types_blueprint = APIBlueprint('access_types', __name__)


def assignments_with_roles(assignments: list[dict[str, Any]], roles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Each assignment with its role under ``role``, in the order given

    Args:
        assignments (list[dict[str, Any]]): The assignments, ascending by public_id as the manager reads them
        roles (list[dict[str, Any]]): Their roles - an assignment whose role is not among them is left out

    Returns:
        list[dict[str, Any]]: The assignments, each a new dict carrying its role
    """
    roles_by_id: dict[int, dict[str, Any]] = {role[ScopeRoleKey.PUBLIC_ID.value]: role for role in roles}

    return [{**assignment, TypeAssignmentsKey.ROLE.value: roles_by_id[assignment[AccessAssignmentKey.ROLE_ID.value]]}
            for assignment in assignments
            if assignment[AccessAssignmentKey.ROLE_ID.value] in roles_by_id]


@access_types_blueprint.route('/<int:public_id>/assignments', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@access_types_blueprint.protect(auth=True, right=AccessRightName.VIEW.value)
@handle_route_errors("while retrieving the assignments of the Type with ID: {public_id}")
def get_type_assignments(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route for the assignments whose scope role covers a Type - by listing it or by covering every
    Type - each with its role, ascending. Unmasked, like every read of the access rules (``base.access.view`` is an
    administrator's view of the whole configuration)

    Args:
        public_id (int): The Type's public_id
        request_user (CmdbUser): The caller

    Raises:
        HTTPException: 404 when the Type does not exist

    Returns:
        GetSingleResponse: ``{type_id, assignments: [{...assignment, role: {...}}]}``
    """
    types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)

    if not types_manager.count_documents({TypeSchemaKey.PUBLIC_ID.value: public_id}):
        abort(404, AccessRouteMessage.NOT_FOUND.value.format(label=TYPE_LABEL, public_id=public_id))

    roles_manager: ScopeRolesManager = ManagerProvider.get_manager(ManagerType.SCOPE_ROLES, request_user)
    assignments_manager: AccessAssignmentsManager = ManagerProvider.get_manager(ManagerType.ACCESS_ASSIGNMENTS,
                                                                                request_user)
    roles: list[dict[str, Any]] = roles_manager.roles_covering_type(public_id)
    assignments: list[dict[str, Any]] = assignments_manager.assignments_of_roles(
        [role[ScopeRoleKey.PUBLIC_ID.value] for role in roles])

    return GetSingleResponse({TypeAssignmentsKey.TYPE_ID.value: public_id,
                              TypeAssignmentsKey.ASSIGNMENTS.value: assignments_with_roles(assignments, roles)},
                             body=request_wants_body()).make_response()
