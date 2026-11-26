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
The ``/access/field_protection`` routes (phase 12): every field of every Type and global section template with its
class, audit flag, required and pattern - read, changed where the field is defined, and a pattern tested
"""
from typing import Any

from werkzeug import Response

from cmdb.models.user_model import CmdbUser
from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.route_utils import handle_route_errors, insert_request_user, verify_api_access
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.rest_api.responses import GetListResponse, GetSingleResponse, UpdateSingleResponse
from cmdb.interface.rest_api.routes.routes_helper import read_id_query_param, request_wants_body
from cmdb.interface.rest_api.routes.access_routes.access_route_constants import (
    FIELD_PROTECTION_PATTERN_TEST_SCHEMA,
    FIELD_PROTECTION_QUERY_GROUP_ID,
    FIELD_PROTECTION_QUERY_TYPE_ID,
    FIELD_PROTECTION_UPDATE_SCHEMA,
    AccessRightName,
    PatternTestBodyKey,
)
from cmdb.interface.rest_api.routes.access_routes.field_protection_helper import (
    field_protection_rows,
    test_pattern,
    update_field_protection,
)
# -------------------------------------------------------------------------------------------------------------------- #

field_protection_blueprint = APIBlueprint('field_protection', __name__)


@field_protection_blueprint.route('', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@field_protection_blueprint.protect(auth=True, right=AccessRightName.VIEW.value)
@handle_route_errors("while retrieving the field protection")
def get_field_protection(request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route for every field where it is defined - its class, audit flag, required, pattern and reach;
    ``?type_id=`` only the fields on one Type, ``?group_id=`` adds what that user group may do with each

    Args:
        request_user (CmdbUser): The caller

    Raises:
        HTTPException: 400 for a parameter that is no id, 404 for an unknown user group

    Returns:
        GetListResponse: The rows
    """
    rows: list[dict[str, Any]] = field_protection_rows(
        request_user, read_id_query_param(FIELD_PROTECTION_QUERY_TYPE_ID),
        read_id_query_param(FIELD_PROTECTION_QUERY_GROUP_ID))

    return GetListResponse(rows, body=request_wants_body()).make_response()


@field_protection_blueprint.route('', methods=['PUT'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.SUPER_ADMIN)
@field_protection_blueprint.protect(auth=True, right=AccessRightName.FIELD_EDIT.value)
@field_protection_blueprint.validate(FIELD_PROTECTION_UPDATE_SCHEMA)
@handle_route_errors("while changing the field protection")
def update_field_protection_route(data: dict[str, Any], request_user: CmdbUser) -> Response:
    """
    HTTP `PUT` route changing one field's class, audit flag, required and pattern where it is defined - a global
    template's field on the template and every Type carrying it

    Args:
        data (dict[str, Any]): ``{source, source_id, name, protection?, audit_relevant?, required?, regex?}``
        request_user (CmdbUser): The caller

    Raises:
        HTTPException: 400 / 404 as ``field_protection_helper.update_field_protection`` names them

    Returns:
        UpdateSingleResponse: 202 with the field's row as stored
    """
    return UpdateSingleResponse(update_field_protection(request_user, data)).make_response()


@field_protection_blueprint.route('/regex_test', methods=['POST'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@field_protection_blueprint.protect(auth=True, right=AccessRightName.VIEW.value)
@field_protection_blueprint.validate(FIELD_PROTECTION_PATTERN_TEST_SCHEMA)
@handle_route_errors("while testing a pattern")
def test_field_pattern(data: dict[str, Any], request_user: CmdbUser) -> Response:
    """
    HTTP `POST` route testing a field pattern against sample values, the way an object write would

    Args:
        data (dict[str, Any]): ``{regex, samples}``
        request_user (CmdbUser): The caller (the right and the level are checked on it)

    Raises:
        HTTPException: 400 for a pattern the field pattern rule refuses

    Returns:
        GetSingleResponse: ``[{value, verdict}]``
    """
    return GetSingleResponse(test_pattern(data[PatternTestBodyKey.REGEX.value],
                                          data[PatternTestBodyKey.SAMPLES.value]), body=True).make_response()
