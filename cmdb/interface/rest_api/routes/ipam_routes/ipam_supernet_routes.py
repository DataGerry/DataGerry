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

Exposes the paginated top-level supernet overview that powers the 'Supernet Übersicht' view
and a per-subnet 'direct children' endpoint used to lazily expand a subnet row in that view
"""
from logging import Logger, getLogger
from typing import Any

from flask import abort, request
from werkzeug import Response
from werkzeug.exceptions import HTTPException

from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.manager import ObjectsManager, TypesManager

from cmdb.models.user_model import CmdbUser
from cmdb.models.special_type_model.ipam_constants import IpamPagination
from cmdb.framework.ipam.supernet_overview import (
    build_supernet_overview,
    build_supernet_subnet_children,
)
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
    HTTP `GET` route returning the paginated top-level supernet overview payload

    The KPI strip in 'supernet' is computed against every subnet under the supernet regardless
    of nesting depth, so totals stay stable as the user paginates. The 'subnets' block lists
    only top-level subnets - those whose CIDR is not strictly contained by any sibling -
    paginated with the same page / page_size semantics used by the subnet overview. Every row
    carries 'has_children: bool' so the frontend can render an expand caret without a probe
    request

    Query params:
        page (int, default=1): 1-based page number; clamped into the valid range server-side
        page_size (int, default=50): page size; clamped into [1, 500] server-side

    Args:
        public_id (int): public_id of the SUPERNET CmdbObject to summarise
        request_user (CmdbUser): CmdbUser making the request

    Returns:
        Response: {'supernet': {...summary, public_id}, 'subnets': {page, page_size, total,
            rows: [...top-level rows with has_children]}}
    """
    try:
        page: int = request.args.get('page', default=1, type=int) or 1
        page_size: int = (
            request.args.get('page_size', default=IpamPagination.DEFAULT_PAGE_SIZE, type=int)
            or IpamPagination.DEFAULT_PAGE_SIZE
        )

        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
        types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)

        overview: dict[str, Any] = build_supernet_overview(
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
            "[get_supernet_overview] Exception: %s. Type: %s",
            err, type(err).__name__, exc_info=True,
        )
        abort(
            500,
            f"An internal server error occured while building the overview for Supernet with ID: {public_id}!",
        )


@ipam_supernet_blueprint.route(
    '/overview/<int:public_id>/subnets/children/<int:subnet_id>',
    methods=['GET'],
)
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@insert_request_user
def get_supernet_subnet_children(public_id: int, subnet_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `GET` route returning the direct CIDR-children of a subnet under the given supernet

    Used by the frontend to lazily populate one expanded row in the supernet overview. Returns
    one level of nesting only; nested expansions issue further requests against this endpoint
    against the child's id. Children are returned in ascending CIDR order and each row carries
    'has_children: bool'

    Args:
        public_id (int): public_id of the SUPERNET CmdbObject the subnet lives under
        subnet_id (int): public_id of the parent SUBNET whose direct children are returned
        request_user (CmdbUser): CmdbUser making the request

    Returns:
        Response: {'parent': {'public_id': subnet_id}, 'rows': [child_row, ...]}
    """
    try:
        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
        types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)

        children: dict[str, Any] = build_supernet_subnet_children(
            objects_manager,
            types_manager,
            public_id,
            subnet_id,
        )

        return DefaultResponse(children).make_response()
    except HTTPException as http_err:
        raise http_err
    except Exception as err:
        LOGGER.error(
            "[get_supernet_subnet_children] Exception: %s. Type: %s",
            err, type(err).__name__, exc_info=True,
        )
        abort(
            500,
            f"An internal server error occured while loading children of Subnet {subnet_id}"
            f" under Supernet {public_id}!",
        )
