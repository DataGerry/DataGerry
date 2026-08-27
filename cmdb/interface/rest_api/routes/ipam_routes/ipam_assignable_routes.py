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
REST routes for the IPAM 'assignable objects' picker

Exposes a single GET route that returns the paginated list of CmdbObjects whose owner CmdbType
declares the dg-ipam-interface MDS section, i.e. every object that can carry an interface row
referencing a SUBNET and an IP. The route powers the subnet IP-Übersicht FE picker for
'assign an object to a free IP'; the listing is global (not scoped to one subnet) because an
object may carry multiple interface rows across different subnets and is never 'consumed' by
a single assignment
"""
from logging import Logger, getLogger
from typing import Any

from flask import abort
from werkzeug import Response
from werkzeug.exceptions import HTTPException

from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.manager import ObjectsManager, TypesManager

from cmdb.models.user_model import CmdbUser
from cmdb.framework.ipam.assignable_objects import build_assignable_objects_page
from cmdb.interface.rest_api.routes.ipam_routes.ipam_route_helper import (
    read_pagination_params,
    read_search_param,
)
from cmdb.interface.route_utils import insert_request_user, verify_api_access
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.rest_api.responses import DefaultResponse
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

ipam_assignable_blueprint = APIBlueprint('ipam_assignable', __name__)


@ipam_assignable_blueprint.route('/', methods=['GET'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
def get_assignable_objects(request_user: CmdbUser) -> Response:
    """
    HTTP `GET` route returning the paginated assignable-objects picker payload

    Returns every CmdbObject whose owner CmdbType declares the dg-ipam-interface MDS section,
    one row per object, with the row carrying the object's public_id, a small ``type_info``
    sub-dict ({public_id, label}) and the rendered summary line. The listing is global
    across the tenant: the FE filters / sorts client-side or via the ``search`` query param

    Query params:
        page (int, default=1): 1-based page number; clamped into the valid range server-side
        page_size (int, default=50): page size; clamped into [IpamPagination.MIN_PAGE_SIZE,
            IpamPagination.MAX_PAGE_SIZE] server-side
        search (str, optional): case-insensitive substring filter against each row's rendered
            summary line; empty / whitespace and queries shorter than
            IpamSearch.MIN_QUERY_LENGTH are ignored, queries longer than
            IpamSearch.MAX_QUERY_LENGTH are truncated at the route boundary. The filter
            shrinks ``total`` to the post-filter count

    Args:
        request_user (CmdbUser): CmdbUser making the request

    Returns:
        Response: {'page', 'page_size', 'total', 'search', 'rows': [...]} where each row is
            {'public_id', 'type_info': {'public_id', 'label'}, 'summary_line'}
    """
    try:
        page, page_size = read_pagination_params()
        search: str = read_search_param()

        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
        types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)

        payload: dict[str, Any] = build_assignable_objects_page(
            objects_manager,
            types_manager,
            page=page,
            page_size=page_size,
            search=search,
        )

        return DefaultResponse(payload).make_response()
    except HTTPException as http_err:
        raise http_err
    except Exception as err:
        LOGGER.error(
            "[get_assignable_objects] Exception: %s. Type: %s",
            err, type(err).__name__, exc_info=True,
        )
        abort(500, "An internal server error occured while listing assignable IPAM objects!")
