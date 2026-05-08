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
REST routes for SUBNET-centric IPAM views

Currently exposes the subnet IP-Übersicht payload that powers the per-subnet IP table view in
the frontend
"""
from logging import Logger, getLogger
from typing import Any

from flask import abort, request
from werkzeug import Response
from werkzeug.exceptions import HTTPException

from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.manager import ObjectsManager, TypesManager

from cmdb.models.user_model import CmdbUser
from cmdb.framework.ipam.subnet_overview import build_subnet_overview, DEFAULT_PAGE_SIZE
from cmdb.interface.route_utils import insert_request_user, verify_api_access
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.rest_api.responses import DefaultResponse
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

ipam_subnet_blueprint = APIBlueprint('ipam_subnet', __name__)


@ipam_subnet_blueprint.route('/overview/<int:public_id>', methods=['GET'])
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@insert_request_user
def get_subnet_overview(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `GET` route returning the subnet IP-Übersicht payload

    Returns the subnet's KPI counters (total / used / free) plus a paginated, IP-sorted list of
    rows, one per usable address in the subnet. Rows are either 'assigned' (carrying the
    referencing object id, summary line, type label and stored MAC) or 'free'

    Query params:
        page (int, default=1): 1-based page number; clamped into the valid range server-side
        page_size (int, default=50): page size; clamped into [1, 500] server-side

    Args:
        public_id (int): public_id of the SUBNET CmdbObject to summarise
        request_user (CmdbUser): CmdbUser making the request

    Returns:
        Response: {'subnet': {...summary, public_id}, 'ips': {page, page_size, total, rows}}
    """
    try:
        page: int = request.args.get('page', default=1, type=int) or 1
        page_size: int = request.args.get('page_size', default=DEFAULT_PAGE_SIZE, type=int) or DEFAULT_PAGE_SIZE

        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
        types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)

        overview: dict[str, Any] = build_subnet_overview(
            objects_manager,
            types_manager,
            public_id,
            page=page,
            page_size=page_size,
        )

        return DefaultResponse(overview).make_response()
    except HTTPException as http_err:
        raise http_err
    except Exception as err:
        LOGGER.error(
            "[get_subnet_overview] Exception: %s. Type: %s",
            err, type(err).__name__, exc_info=True,
        )
        abort(
            500,
            f"An internal server error occured while building the overview for Subnet with ID: {public_id}!",
        )
