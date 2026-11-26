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
The REST route of the scope builder's catalogue: what an assignment's scope may say (phase 9, R30)
"""
from werkzeug import Response

from cmdb.models.user_model import CmdbUser
from cmdb.framework.scope_compiler.scope_catalogue import scope_catalogue
from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.route_utils import handle_route_errors, insert_request_user, verify_api_access
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.rest_api.responses import GetSingleResponse
from cmdb.interface.rest_api.routes.routes_helper import request_wants_body
from cmdb.interface.rest_api.routes.access_routes.access_route_constants import AccessRightName
# -------------------------------------------------------------------------------------------------------------------- #

scope_catalogue_blueprint = APIBlueprint('scope_catalogue', __name__)


@scope_catalogue_blueprint.route('', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@scope_catalogue_blueprint.protect(auth=True, right=AccessRightName.VIEW.value)
@handle_route_errors("while retrieving the scope catalogue")
def get_scope_catalogue(request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route for the scope catalogue - the operators per field kind, the blocks, the tokens and the
    caps, read from the code

    Args:
        request_user (CmdbUser): The caller (the right and the level are checked on it)

    Returns:
        GetSingleResponse: The catalogue
    """
    return GetSingleResponse(scope_catalogue(), body=request_wants_body()).make_response()
