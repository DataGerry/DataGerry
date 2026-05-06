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
REST routes for SUPERNET-centric IPAM views

Currently exposes the supernet overview payload that powers the 'Supernet Übersicht' view
in the frontend
"""
from logging import Logger, getLogger
from typing import Any

from flask import abort
from werkzeug import Response
from werkzeug.exceptions import HTTPException

from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.manager import ObjectsManager, TypesManager

from cmdb.models.user_model import CmdbUser
from cmdb.framework.ipam.supernet_overview import build_supernet_overview
from cmdb.interface.route_utils import insert_request_user, verify_api_access
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.rest_api.responses import DefaultResponse
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

ipam_supernet_blueprint = APIBlueprint('ipam_supernet', __name__)


@ipam_supernet_blueprint.route('/overview/<int:public_id>', methods=['GET'])
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@insert_request_user
def get_supernet_overview(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `GET` route returning the supernet overview payload

    Returns the supernet-wide KPI strip values plus one row per SUBNET that references the
    supernet. The frontend is responsible for rendering / grouping the table; this endpoint
    only provides the data

    Args:
        public_id (int): public_id of the SUPERNET CmdbObject to summarise
        request_user (CmdbUser): CmdbUser making the request

    Returns:
        Response: {'supernet': {...summary, public_id}, 'subnets': [...]}
    """
    try:
        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
        types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)

        overview: dict[str, Any] = build_supernet_overview(objects_manager, types_manager, public_id)

        return DefaultResponse(overview).make_response()
    except HTTPException as http_err:
        raise http_err
    except Exception as err:
        LOGGER.error(
            "[get_supernet_overview] Exception: %s. Type: %s",
            err, type(err).__name__, exc_info=True,
        )
        abort(
            500,
            f"An internal server error occured while building the overview for Supernet with ID: {public_id}!",
        )
