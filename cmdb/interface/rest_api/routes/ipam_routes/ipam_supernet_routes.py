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

Exposes the paginated top-level supernet overview that powers the 'Supernet Übersicht' view,
a per-subnet 'direct children' endpoint used to lazily expand a subnet row in that view, the
paginated invalid-subnets-only overview that lists subnets whose CIDR no longer fits inside
the supernet, and the batch 'unassign subnets' endpoint that clears dg-supernet-ref on
multiple SUBNETs at once
"""
from logging import Logger, getLogger
from typing import Any
from datetime import datetime, timezone

from flask import abort, request
from werkzeug import Response
from werkzeug.exceptions import HTTPException

from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.manager import ObjectsManager, TypesManager

from cmdb.models.user_model import CmdbUser
from cmdb.models.special_type_model.ipam_constants import (
    IpamPagination,
    IpamSearch,
    IpamOverviewKey,
    IpamUnassignKey,
    IpamExport,
)
from cmdb.framework.ipam.supernet_overview import (
    build_invalid_subnets_overview,
    build_supernet_overview,
    build_supernet_subnet_children,
)
from cmdb.framework.ipam.subnet_export import build_supernet_subnets_csv
from cmdb.framework.ipam.supernet_membership import unassign_subnets_from_supernet
from cmdb.interface.route_utils import insert_request_user, verify_api_access
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.rest_api.responses import DefaultResponse
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

ipam_supernet_blueprint = APIBlueprint('ipam_supernet', __name__)


@ipam_supernet_blueprint.route('/overview/<int:public_id>', methods=['GET'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
def get_supernet_overview(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `GET` route returning the paginated supernet overview payload

    The KPI strip in 'supernet' is computed against every subnet under the supernet regardless
    of nesting depth, so totals stay stable as the user paginates or filters. The 'subnets'
    block lists rows paginated with the same page / page_size semantics used by the subnet
    overview. Every row carries 'has_children: bool' so the frontend can render an expand
    caret without a probe request

    Without 'search' the block lists only top-level subnets - those whose CIDR is not strictly
    contained by any sibling. With a non-empty 'search', the tree shape is dropped and the
    block returns a flat list of every subnet under the supernet (any nesting depth) whose
    'network' property contains the query as a case-insensitive substring, still paginated

    Query params:
        page (int, default=1): 1-based page number; clamped into the valid range server-side
        page_size (int, default=50): page size; clamped into [1, 500] server-side
        search (str, optional): case-insensitive substring filter against each subnet's
            'network' property; empty / whitespace and queries shorter than
            IpamSearch.MIN_QUERY_LENGTH are ignored, queries longer than
            IpamSearch.MAX_QUERY_LENGTH are truncated at the route boundary

    Args:
        public_id (int): public_id of the SUPERNET CmdbObject to summarise
        request_user (CmdbUser): CmdbUser making the request

    Returns:
        Response: {'supernet': {...summary, public_id}, 'subnets': {page, page_size, total,
            rows: [...subnet rows with has_children]}}
    """
    try:
        page: int = request.args.get(IpamOverviewKey.PAGE, default=1, type=int) or 1
        page_size: int = (
            request.args.get(IpamOverviewKey.PAGE_SIZE, default=IpamPagination.DEFAULT_PAGE_SIZE, type=int)
            or IpamPagination.DEFAULT_PAGE_SIZE
        )
        raw_search: str = request.args.get(IpamOverviewKey.SEARCH, default='', type=str) or ''
        search: str = raw_search[:IpamSearch.MAX_QUERY_LENGTH]

        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
        types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)

        overview: dict[str, Any] = build_supernet_overview(
            objects_manager,
            types_manager,
            public_id,
            page=page,
            page_size=page_size,
            search=search,
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
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
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


@ipam_supernet_blueprint.route('/overview/<int:public_id>/subnets/export', methods=['GET'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
def export_supernet_subnets(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `GET` route exporting all assigned subnets of a supernet as a CSV (.csv) file

    Returns every subnet referencing the supernet (any nesting depth) as a single CSV table
    with the columns CIDR, IP range, used IPs, free IPs and usage percent. The file is returned
    as an attachment download.

    Args:
        public_id (int): public_id of the SUPERNET CmdbObject whose subnets are exported
        request_user (CmdbUser): CmdbUser making the request

    Returns:
        Response: The .csv file as an attachment download
    """
    try:
        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
        types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)

        content: bytes = build_supernet_subnets_csv(objects_manager, types_manager, public_id)

        timestamp: str = datetime.now(timezone.utc).strftime('%Y_%m_%d-%H_%M_%S')
        filename: str = IpamExport.FILENAME_TEMPLATE.format(public_id=public_id, timestamp=timestamp)

        return Response(
            content,
            mimetype=IpamExport.MIMETYPE,
            headers={'Content-Disposition': f'attachment; filename={filename}'},
        )
    except HTTPException as http_err:
        raise http_err
    except Exception as err:
        LOGGER.error(
            "[export_supernet_subnets] Exception: %s. Type: %s",
            err, type(err).__name__, exc_info=True,
        )
        abort(
            500,
            f"An internal server error occured while exporting subnets for Supernet with ID: {public_id}!",
        )


@ipam_supernet_blueprint.route('/overview/<int:public_id>/subnets/invalid', methods=['GET'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
def get_invalid_subnet_overview(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `GET` route returning the paginated invalid-subnets-only overview payload

    Same envelope as ``get_supernet_overview`` ('supernet' summary block, 'subnets' page block,
    top-level 'invalid_count'), but 'subnets.rows' is a flat list (no tree shape) of every
    subnet under the supernet whose CIDR does NOT sit strictly inside the supernet's current
    CIDR. Each row carries the same shape as the main overview rows so the FE can reuse its
    row template; invalid rows ordered by ascending CIDR with unparsable-CIDR rows trailing

    Query params:
        page (int, default=1): 1-based page number; clamped into the valid range server-side
        page_size (int, default=50): page size; clamped into [1, 500] server-side
        search (str, optional): case-insensitive substring filter against each invalid subnet's
            'network' property; empty / whitespace and queries shorter than
            IpamSearch.MIN_QUERY_LENGTH are ignored, queries longer than
            IpamSearch.MAX_QUERY_LENGTH are truncated at the route boundary

    Args:
        public_id (int): public_id of the SUPERNET CmdbObject whose invalid subnets are listed
        request_user (CmdbUser): CmdbUser making the request

    Returns:
        Response: {'supernet': {...summary, public_id}, 'subnets': {page, page_size, total,
            rows: [...invalid subnet rows]}, 'invalid_count': int}
    """
    try:
        page: int = request.args.get(IpamOverviewKey.PAGE, default=1, type=int) or 1
        page_size: int = (
            request.args.get(IpamOverviewKey.PAGE_SIZE, default=IpamPagination.DEFAULT_PAGE_SIZE, type=int)
            or IpamPagination.DEFAULT_PAGE_SIZE
        )
        raw_search: str = request.args.get(IpamOverviewKey.SEARCH, default='', type=str) or ''
        search: str = raw_search[:IpamSearch.MAX_QUERY_LENGTH]

        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
        types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)

        overview: dict[str, Any] = build_invalid_subnets_overview(
            objects_manager,
            types_manager,
            public_id,
            page=page,
            page_size=page_size,
            search=search,
        )

        return DefaultResponse(overview).make_response()
    except HTTPException as http_err:
        raise http_err
    except Exception as err:
        LOGGER.error(
            "[get_invalid_subnet_overview] Exception: %s. Type: %s",
            err, type(err).__name__, exc_info=True,
        )
        abort(
            500,
            f"An internal server error occured while building the invalid-subnets overview"
            f" for Supernet with ID: {public_id}!",
        )


@ipam_supernet_blueprint.route('/overview/<int:public_id>/subnets/unassign', methods=['POST'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
def unassign_subnets_route(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `POST` route that detaches one or more SUBNETs from the supernet

    Clears the 'dg-supernet-ref' field value to None on every SUBNET CmdbObject named in the
    request body, validate-all-or-nothing: if any id is not a SUBNET currently assigned to
    the supernet, the route aborts 400 with the offending ids and no write happens. CIDR-
    children of detached SUBNETs are left attached - they keep their own dg-supernet-ref and
    will surface as new top-level rows on the next overview load

    Body:
        subnet_ids (list[int]): public_ids of SUBNETs to detach; must be a non-empty list,
            duplicates are silently collapsed while preserving input order

    Args:
        public_id (int): public_id of the SUPERNET CmdbObject the subnets are detached from
        request_user (CmdbUser): CmdbUser making the request

    Returns:
        Response: {'subnet_ids': [int, ...], 'unassigned_count': int}; subnet_ids echoes the
            deduplicated request order
    """
    try:
        payload: dict[str, Any] = request.get_json(silent=True) or {}

        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
        types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)

        result: dict[str, Any] = unassign_subnets_from_supernet(
            objects_manager,
            types_manager,
            public_id,
            payload.get(IpamUnassignKey.SUBNET_IDS),
        )

        return DefaultResponse(result).make_response()
    except HTTPException as http_err:
        raise http_err
    except Exception as err:
        LOGGER.error(
            "[unassign_subnets_route] Exception: %s. Type: %s",
            err, type(err).__name__, exc_info=True,
        )
        abort(
            500,
            f"An internal server error occured while unassigning subnets from Supernet"
            f" with ID: {public_id}!",
        )
