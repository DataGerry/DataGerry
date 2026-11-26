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
The explain routes: ``GET /access/explain?user_id=&object_id=`` - why a user may (not) view, create, edit and delete an
object - and ``GET /access/objects/<id>/explain`` - what each user group may do on it

Both read: ``base.access.view`` at the ADMIN level, and the caller must be able to view the object (403). Explaining a
user also needs ``base.user-management.user.view`` - the answer names the user's groups
"""
from flask import abort
from werkzeug import Response

from cmdb.models.user_model import CmdbUser
from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.route_utils import handle_route_errors, insert_request_user, verify_api_access
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.rest_api.responses import GetSingleResponse
from cmdb.interface.rest_api.routes.routes_helper import read_id_query_param, request_wants_body
from cmdb.interface.rest_api.routes.user_management_routes.users_constants import UserAccessRight
from cmdb.interface.rest_api.routes.access_routes.access_route_constants import (
    EXPLAIN_QUERY_OBJECT_ID,
    EXPLAIN_QUERY_USER_ID,
    AccessRightName,
    AccessRouteMessage,
)
from cmdb.interface.rest_api.routes.access_routes.explain_helper import explain_group_access, explain_user_access
# -------------------------------------------------------------------------------------------------------------------- #

explain_blueprint = APIBlueprint('access_explain', __name__)


@explain_blueprint.route('/explain', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@explain_blueprint.protect(auth=True, right=AccessRightName.VIEW.value)
@explain_blueprint.protect(auth=True, right=UserAccessRight.VIEW.value)
@handle_route_errors("while explaining the access of a user to an object")
def explain_user(request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route explaining why a user may (not) view, create, edit and delete an object

    Raises:
        HTTPException: 400 for a missing or malformed ``user_id`` / ``object_id``; 403 when the caller may not view
            the object; 404 for a missing user, object or Type

    Returns:
        GetSingleResponse: ``{user, object, operations, assignments, fields}``
    """
    user_id: int | None = read_id_query_param(EXPLAIN_QUERY_USER_ID)
    object_id: int | None = read_id_query_param(EXPLAIN_QUERY_OBJECT_ID)

    if user_id is None or object_id is None:
        abort(400, AccessRouteMessage.EXPLAIN_PARAMETERS.value)

    return GetSingleResponse(explain_user_access(request_user, user_id, object_id),
                             body=request_wants_body()).make_response()


@explain_blueprint.route('/objects/<int:public_id>/explain', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@explain_blueprint.protect(auth=True, right=AccessRightName.VIEW.value)
@handle_route_errors("while explaining who may do what on the object with ID: {public_id}")
def explain_object(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route answering what each user group, by itself, may do on an object

    Args:
        public_id (int): The object's public_id

    Raises:
        HTTPException: 403 when the caller may not view the object; 404 for a missing object or Type

    Returns:
        GetSingleResponse: ``{object, restricted, groups: [{group_id, name, operations, assignments}]}``
    """
    return GetSingleResponse(explain_group_access(request_user, public_id),
                             body=request_wants_body()).make_response()
