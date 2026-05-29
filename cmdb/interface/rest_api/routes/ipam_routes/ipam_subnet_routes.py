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

Exposes the subnet IP-Übersicht read-side payload that powers the per-subnet IP table view in
the frontend, plus the bulk 'unassign IPs' write-side route that clears the subnet reference
on one or more dg-ipam-interface rows. The IP table is paginated and supports an optional
case-insensitive substring search against the canonical IP strings; the search filter does
not affect the KPI block or the distributions
"""
from logging import Logger, getLogger
from typing import Any

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
)
from cmdb.framework.ipam.subnet_overview import build_subnet_overview, build_invalid_subnet_overview
from cmdb.framework.ipam.subnet_unassign import unassign_ips_from_subnet
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
    referencing object id, summary line, type label and stored MAC) or 'free'. The response
    also carries a 'type_distribution' summary spanning the entire subnet (not just the current
    page) that powers the chart breakdown of used types vs. free capacity

    Query params:
        page (int, default=1): 1-based page number; clamped into the valid range server-side
        page_size (int, default=50): page size; clamped into [1, 500] server-side
        search (str, optional): case-insensitive substring filter against each canonical IP
            string; empty / whitespace and queries shorter than IpamSearch.MIN_QUERY_LENGTH
            are ignored, queries longer than IpamSearch.MAX_QUERY_LENGTH are truncated at the
            route boundary. The filter applies to both assigned and free IPs; the KPI block,
            type_distribution, and ip_distribution stay invariant under search
        sort (str, optional): IpamSortColumn value (ip / status / type / assigned_to /
            mac_address); empty restores the natural ascending-IP order
        order (str, optional): IpamSortDirection value ('1' for ascending, '-1' for
            descending - matches the project-wide Mongo direction convention). Defaults to
            '1' when sort is provided without an explicit order. Rows missing a value for
            the chosen column trail in either direction (NULLS LAST). Aborts 400 on unknown
            sort or order values
        status (str, optional): IpamRowStatus value ('assigned' / 'free') filtering the IP
            table to rows of the chosen status; empty / whitespace skips the status filter.
            Aborts 400 on unknown values
        type (str, optional): Comma-separated list of CmdbType public_ids filtering the IP
            table to assigned rows whose owning type is in the set (e.g. ``type=50,51,52``).
            Whitespace around elements is stripped, empty entries are skipped and duplicates
            are collapsed. Empty or whitespace skips the type filter. Combines with
            ``status`` via AND; ``status=free`` with any non-empty ``type`` yields an empty
            page since free rows carry no owner type. Aborts 400 on a non-integer element.
            The KPI block, type_distribution, ip_distribution and vlans stay invariant under
            both filters

    Args:
        public_id (int): public_id of the SUBNET CmdbObject to summarise
        request_user (CmdbUser): CmdbUser making the request

    Returns:
        Response: {'subnet': {...summary, public_id}, 'ips': {page, page_size, total, rows},
            'type_distribution': [{public_id, label, count, percentage}, ...]}
    """
    try:
        page: int = request.args.get(IpamOverviewKey.PAGE, default=1, type=int) or 1
        page_size: int = (
            request.args.get(IpamOverviewKey.PAGE_SIZE, default=IpamPagination.DEFAULT_PAGE_SIZE, type=int)
            or IpamPagination.DEFAULT_PAGE_SIZE
        )
        raw_search: str = request.args.get(IpamOverviewKey.SEARCH, default='', type=str) or ''
        search: str = raw_search[:IpamSearch.MAX_QUERY_LENGTH]
        sort: str = request.args.get(IpamOverviewKey.SORT, default='', type=str) or ''
        order: str = request.args.get(IpamOverviewKey.ORDER, default='', type=str) or ''
        status: str = request.args.get(IpamOverviewKey.STATUS, default='', type=str) or ''
        type_filter: str = request.args.get(IpamOverviewKey.TYPE, default='', type=str) or ''

        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
        types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)

        overview: dict[str, Any] = build_subnet_overview(
            objects_manager,
            types_manager,
            public_id,
            page=page,
            page_size=page_size,
            search=search,
            sort=sort,
            order=order,
            status=status,
            type_filter=type_filter,
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


@ipam_subnet_blueprint.route('/overview/<int:public_id>/unassign', methods=['POST'])
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@insert_request_user
def unassign_ips_route(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `POST` route that clears the subnet reference on one or more dg-ipam-interface rows

    Each entry in the request's ``ips`` list identifies one currently-assigned IP of the
    subnet; the route locates its owner CmdbObject, flips the row's ``dg-interface-subnet``
    value to None and writes the owner back through ``ObjectsManager.update_object`` so ACL,
    versioning and post-update hooks all run per-owner. The row itself stays on the owner
    along with its IP and MAC values - only the subnet reference is cleared. Other interface
    rows on the same owner (referencing other subnets or non-target IPs of the same subnet)
    are left untouched

    Validate-all-or-nothing: if any requested IP is not currently assigned within the subnet,
    the route aborts 400 with the offending IPs and no write happens. Bad input shape (missing
    list, empty list, non-string entry, non-canonical IPv4, IP outside the subnet) also aborts
    400 before any database read. Aborts 404 when the subnet does not exist and 400 when the
    public_id refers to a non-subnet object, no SUBNET CmdbType is defined, or the subnet's
    network-range field is missing / unparsable

    Body:
        ips (list[str]): canonical IPv4 dotted-quad strings whose row should have its subnet
            reference cleared; must be non-empty, each parseable, each within the subnet.
            Duplicates are silently collapsed while preserving input order

    Args:
        public_id (int): public_id of the SUBNET CmdbObject to unassign rows from
        request_user (CmdbUser): CmdbUser making the request

    Returns:
        Response: {'ips': [str, ...], 'unassigned_count': int}; 'ips' echoes the deduplicated
            request order and 'unassigned_count' is the number of dg-ipam-interface rows
            whose subnet reference was cleared across all touched owners
    """
    try:
        payload: dict[str, Any] = request.get_json(silent=True) or {}

        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
        types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)

        result: dict[str, Any] = unassign_ips_from_subnet(
            objects_manager,
            types_manager,
            public_id,
            payload.get(IpamUnassignKey.IPS),
            request_user,
        )

        return DefaultResponse(result).make_response()
    except HTTPException as http_err:
        raise http_err
    except Exception as err:
        LOGGER.error(
            "[unassign_ips_route] Exception: %s. Type: %s",
            err, type(err).__name__, exc_info=True,
        )
        abort(
            500,
            f"An internal server error occured while unassigning IPs from Subnet with ID: {public_id}!",
        )


@ipam_subnet_blueprint.route('/overview/<int:public_id>/invalid', methods=['GET'])
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@insert_request_user
def get_invalid_subnet_overview(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `GET` route returning the invalid-IPs-only subnet overview payload

    Same envelope as ``get_subnet_overview`` ('subnet' KPI block, 'ips' page block,
    'type_distribution', 'ip_distribution', 'vlans', top-level 'invalid_count'), but the
    'ips.rows' list is restricted to dg-ipam-interface rows whose IP falls outside the
    subnet's current CIDR (each row carries is_valid=False). The KPI block, distributions
    and vlans stay invariant - they always cover the whole subnet so the FE can render the
    same chrome on either view

    Query params:
        page (int, default=1): 1-based page number; clamped into the valid range server-side
        page_size (int, default=50): page size; clamped into [1, 500] server-side
        search (str, optional): case-insensitive substring filter against each invalid IP's
            canonical dotted-quad string; empty / whitespace and queries shorter than
            IpamSearch.MIN_QUERY_LENGTH are ignored, queries longer than
            IpamSearch.MAX_QUERY_LENGTH are truncated at the route boundary

    Args:
        public_id (int): public_id of the SUBNET CmdbObject whose invalid rows are listed
        request_user (CmdbUser): CmdbUser making the request

    Returns:
        Response: same envelope as ``get_subnet_overview`` with ips.rows filtered to invalid
            rows only and ips.total equal to the invalid count after the search filter
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

        overview: dict[str, Any] = build_invalid_subnet_overview(
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
            f"An internal server error occured while building the invalid-only overview"
            f" for Subnet with ID: {public_id}!",
        )
