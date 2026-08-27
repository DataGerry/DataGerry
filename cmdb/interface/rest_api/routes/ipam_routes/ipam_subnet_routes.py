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

Exposes the subnet IP-overview read-side payload that powers the per-subnet IP table view in
the frontend, the per-sector drill-down, a CSV (.csv) export of the IP table, plus the bulk
'unassign IPs' write-side route that clears the subnet reference on one or more dg-ipam-interface
rows. The IP table is paginated and supports an optional case-insensitive substring search against
the canonical IP strings; the search filter does not affect the KPI block or the distributions

Also exposes the paginated subnet-options list backing the dg-ipam-interface subnet picker,
filterable by address family ('type' query param) so the frontend can offer only subnets
matching the family the user selected in the interface row

Two conventions apply across the routes below:

* **The `type` query parameter carries two different meanings on this blueprint.** On `GET /` it is
  an address-family token ('ipv4' / 'ipv6') restricting the picker options; on
  `GET /overview/<public_id>` it is a comma-separated list of CmdbType public_ids filtering the IP
  table by owning type. Both are read through `IpamOverviewKey.TYPE` because that is the wire name
  the frontend sends, so each route binds it to a differently-named local (`family` vs
  `type_filter`) to keep the two apart. Renaming either would break the frontend contract
* **Where a query value is validated depends on what validating it needs.** A self-contained token
  that can be checked against an enum without touching the database is rejected here at the route
  boundary (the address family); a filter whose validity depends on type or schema context is
  validated by the framework-layer builder that consumes it (`sort`, `order`, `status` and the
  type-id filter, all in `framework/ipam/subnet_overview/candidates.py`). Either way the client
  sees an HTTP 400

These routes are transport glue: reading the query string / body, resolving the managers and
mapping failures onto HTTP. The payloads themselves are built by `cmdb.framework.ipam`
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
    IpAddressFamily,
    IpamOverviewKey,
    IpamUnassignKey,
    IpamExport,
    IpamSubnetIpsExport,
)
from cmdb.framework.ipam.subnet_overview import (
    build_subnet_overview,
    build_invalid_ips_overview,
    build_subnet_sector_ips,
)
from cmdb.framework.ipam.subnet_options import build_subnet_options_page
from cmdb.framework.ipam.subnet_unassign import unassign_ips_from_subnet
from cmdb.framework.ipam.subnet_export import build_subnet_ips_csv
from cmdb.framework.exporter.export_filename_helper import build_export_filename_timestamp
from cmdb.interface.rest_api.routes.ipam_routes.ipam_route_helper import (
    read_json_object_body,
    read_pagination_params,
    read_search_param,
)
from cmdb.interface.route_utils import insert_request_user, verify_api_access
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.rest_api.responses import DefaultResponse
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

ipam_subnet_blueprint = APIBlueprint('ipam_subnet', __name__)

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

@ipam_subnet_blueprint.route('/', methods=['GET'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
def get_subnet_options(request_user: CmdbUser) -> Response:
    """
    HTTP `GET` route returning the paginated subnet-options list for the interface picker

    Backs the dg-ipam-interface section's subnet reference dropdown: when the user selects an
    address family in the interface row, the frontend reloads the options from this route with
    the matching 'type' so only same-family subnets are offered. Each row carries the
    lightweight node shape (public_id, name, cidr, address family under 'type'); rows are
    sorted ascending by network address with prefix length as tiebreaker (IPv4 before IPv6 in
    the unfiltered list), subnets with unparsable CIDRs trailing their family ordered by name.
    The family of each subnet is resolved CIDR-first with the 'dg-subnet-type' selector as
    fallback and IPv4 as legacy default, matching every other IPAM view

    Query params:
        type (str, optional): IpAddressFamily token ('ipv4' / 'ipv6') restricting the rows to
            one family; absent or empty returns both families, any other value aborts 400
        page (int, default=1): 1-based page number; clamped into the valid range server-side
        page_size (int, default=50): page size; clamped into [1, 500] server-side
        search (str, optional): case-insensitive substring filter against each subnet's name
            and CIDR; empty / whitespace and queries shorter than IpamSearch.MIN_QUERY_LENGTH
            are ignored, queries longer than IpamSearch.MAX_QUERY_LENGTH are truncated at the
            route boundary

    Args:
        request_user (CmdbUser): CmdbUser making the request

    Raises:
        HTTPException: 400 when 'type' is not a valid address-family token

    Returns:
        Response: {'page', 'page_size', 'total', 'search', 'type',
            'rows': [{public_id, name, cidr, type}, ...]}
    """
    try:
        page, page_size = read_pagination_params()
        search: str = read_search_param()
        # 'type' on THIS route is the address family, not the type-id filter of /overview - see
        # the module docstring
        family: str = request.args.get(IpamOverviewKey.TYPE, default='', type=str) or ''

        if family and not IpAddressFamily.is_valid(family):
            abort(
                400,
                f"'{family}' is not a valid address family; allowed values:"
                f" {IpAddressFamily.IPV4.value}, {IpAddressFamily.IPV6.value}!",
            )

        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
        types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)

        options: dict[str, Any] = build_subnet_options_page(
            objects_manager,
            types_manager,
            page=page,
            page_size=page_size,
            search=search,
            family=family,
        )

        return DefaultResponse(options).make_response()
    except HTTPException as http_err:
        raise http_err
    except Exception as err:
        LOGGER.error(
            "[get_subnet_options] Exception: %s. Type: %s",
            err, type(err).__name__, exc_info=True,
        )
        abort(500, "An internal server error occured while loading the subnet options!")


@ipam_subnet_blueprint.route('/overview/<int:public_id>', methods=['GET'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
def get_subnet_overview(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `GET` route returning the subnet IP-overview payload

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

    Raises:
        HTTPException: 404 when no object with this public_id exists, 400 when it is not a SUBNET,
                       when no SUBNET CmdbType is defined, or on an unknown sort / order / status /
                       type filter value

    Returns:
        Response: {'subnet': {...summary, public_id}, 'ips': {page, page_size, total, rows},
            'type_distribution': [{public_id, label, count, percentage}, ...]}
    """
    try:
        page, page_size = read_pagination_params()
        search: str = read_search_param()
        sort: str = request.args.get(IpamOverviewKey.SORT, default='', type=str) or ''
        order: str = request.args.get(IpamOverviewKey.ORDER, default='', type=str) or ''
        status: str = request.args.get(IpamOverviewKey.STATUS, default='', type=str) or ''
        # 'type' on THIS route is a comma-separated CmdbType public_id list, not the address family
        # of the options route - see the module docstring
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


# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

@ipam_subnet_blueprint.route('/overview/<int:public_id>/unassign', methods=['POST'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
def unassign_ips_route(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `POST` route that unassigns one or more dg-ipam-interface rows from the subnet

    Each entry in the request's ``ips`` list identifies one currently-assigned IP of the subnet;
    the route locates its owner CmdbObject(s) and applies the chosen ``mode`` to the matching
    rows, then writes each owner back through ``ObjectsManager.update_object`` so ACL, versioning
    and post-update hooks all run per-owner. The ``mode`` is a single selection for the whole
    request (not per IP):
      - 'reference' (default): flip the row's ``dg-interface-subnet`` value to None - the row, its
        IP and MAC are kept; it is just detached from the subnet
      - 'row': delete the whole matching dg-ipam-interface row (this edits the owner object to
        drop the row; it does not delete the owner CmdbObject)
    Other interface rows on the same owner (referencing other subnets or non-target IPs of the
    same subnet) are left untouched

    **Validation** is all-or-nothing: if any requested IP is not currently assigned within the
    subnet, the route aborts 400 with the offending IPs and no write happens. Bad input shape (a
    body that is not a JSON object, missing list, empty list, non-string entry, non-canonical IP, IP
    outside the subnet, unknown mode) also aborts 400 before any database write. Aborts 404 when the
    subnet does not exist and 400 when the public_id refers to a non-subnet object, no SUBNET
    CmdbType is defined, or the subnet's network-range field is missing / unparsable

    **The write phase is NOT atomic.** Once validation passes, each affected owner is written
    separately through ``ObjectsManager.update_object`` and there is no cross-owner transaction, so a
    failure part-way leaves the already-written owners unassigned while the response carries the
    error instead of a count. The most likely trigger is object-level ACL: ``update_object`` enforces
    UPDATE permission per owner, so a user allowed to edit some owners but not others gets the
    allowed ones unassigned and a 403 for the first one they may not touch. Callers that need an
    exact picture after an error must re-read the subnet overview

    Body:
        ips (list[str]): canonical IPv4 / IPv6 strings to unassign; must be non-empty, each
            parseable, each within the subnet. Duplicates are silently collapsed while preserving
            input order
        mode (str, optional): 'reference' (clear the subnet ref, default) or 'row' (delete the
            whole row); applies to every IP in the request

    Args:
        public_id (int): public_id of the SUBNET CmdbObject to unassign rows from
        request_user (CmdbUser): CmdbUser making the request

    Returns:
        Response: {'ips': [str, ...], 'mode': str, 'unassigned_count': int}; 'ips' echoes the
            deduplicated request order, 'mode' echoes the resolved mode and 'unassigned_count' is
            the number of dg-ipam-interface rows affected across all touched owners
    """
    try:
        payload: dict[str, Any] = read_json_object_body()

        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
        types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)

        result: dict[str, Any] = unassign_ips_from_subnet(
            objects_manager,
            types_manager,
            public_id,
            payload.get(IpamUnassignKey.IPS),
            request_user,
            raw_mode=payload.get(IpamUnassignKey.MODE),
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


# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

@ipam_subnet_blueprint.route('/overview/<int:public_id>/sector', methods=['GET'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
def get_subnet_sector_ips(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `GET` route returning the paginated IP list of a single IP-distribution sector

    Backs the 'click a heatmap sector' drill-down: only the IPs of the clicked sector are loaded
    instead of the whole subnet. The sector is identified by its start address (the ``ip_start``
    the overview's ip_distribution emitted for that cell). For IPv4 the page lists the sector's
    assignable addresses (free + assigned, network / broadcast excluded); for IPv6 it lists only
    the assigned addresses inside the sector. Response carries just the 'ips' page block plus the
    resolved sector range - the KPI block and distributions are not recomputed

    Query params:
        sector_start (str): The clicked sector's start address (its ip_start). Required
        page (int, default=1): 1-based page number; clamped into the valid range server-side
        page_size (int, default=50): page size; clamped into [1, 500] server-side

    Args:
        public_id (int): public_id of the SUBNET CmdbObject
        request_user (CmdbUser): CmdbUser making the request

    Raises:
        HTTPException: 400 when 'sector_start' is missing, when the object is not a SUBNET or the
                       subnet is too small to expose a distribution grid; 404 when no object with
                       this public_id exists

    Returns:
        Response: {'sector': {ip_start, ip_end}, 'ips': {page, page_size, total, rows}}
    """
    try:
        sector_start: str = request.args.get(IpamOverviewKey.SECTOR_START, default='', type=str) or ''

        if not sector_start:
            abort(400, "'sector_start' query parameter is required")

        page, page_size = read_pagination_params()

        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
        types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)

        result: dict[str, Any] = build_subnet_sector_ips(
            objects_manager,
            types_manager,
            public_id,
            sector_start,
            page=page,
            page_size=page_size,
        )

        return DefaultResponse(result).make_response()
    except HTTPException as http_err:
        raise http_err
    except Exception as err:
        LOGGER.error(
            "[get_subnet_sector_ips] Exception: %s. Type: %s",
            err, type(err).__name__, exc_info=True,
        )
        abort(
            500,
            f"An internal server error occured while loading the sector IPs for Subnet with ID: {public_id}!",
        )


@ipam_subnet_blueprint.route('/overview/<int:public_id>/invalid', methods=['GET'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
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

    Raises:
        HTTPException: 404 when no object with this public_id exists, 400 when it is not a SUBNET or
                       no SUBNET CmdbType is defined

    Returns:
        Response: same envelope as ``get_subnet_overview`` with ips.rows filtered to invalid
            rows only and ips.total equal to the invalid count after the search filter
    """
    try:
        page, page_size = read_pagination_params()
        search: str = read_search_param()

        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
        types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)

        overview: dict[str, Any] = build_invalid_ips_overview(
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


@ipam_subnet_blueprint.route('/overview/<int:public_id>/export', methods=['GET'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
def export_subnet_ips(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `GET` route exporting a subnet's IP rows as a CSV (.csv) file

    Returns the subnet's IP table as a single CSV table with the columns IP, type, status,
    assigned-to and MAC address. An IPv4 subnet exports all assignable addresses (free + assigned);
    an IPv6 subnet exports only the assigned addresses. The file is returned as an attachment
    download.

    The export is capped at IpamSubnetIpsExport.MAX_EXPORT_ROWS rows: a subnet whose export would
    exceed it aborts 400 ('too big') and no file is built. Aborts 404 when the subnet does not
    exist and 400 when the public_id refers to a non-subnet object or the subnet's network range is
    missing / unparsable

    Args:
        public_id (int): public_id of the SUBNET CmdbObject whose IPs are exported
        request_user (CmdbUser): CmdbUser making the request

    Returns:
        Response: The .csv file as an attachment download
    """
    try:
        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
        types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)

        content: bytes = build_subnet_ips_csv(objects_manager, types_manager, public_id)

        filename: str = IpamSubnetIpsExport.FILENAME_TEMPLATE.format(
            public_id=public_id,
            timestamp=build_export_filename_timestamp(),
        )

        return Response(
            content,
            mimetype=IpamExport.MIMETYPE,
            # Quoted like every other export in the repo: an unquoted filename is only safe as long
            # as the template never yields a space or a separator character
            headers={'Content-Disposition': f'attachment; filename="{filename}"'},
        )
    except HTTPException as http_err:
        raise http_err
    except Exception as err:
        LOGGER.error(
            "[export_subnet_ips] Exception: %s. Type: %s",
            err, type(err).__name__, exc_info=True,
        )
        abort(
            500,
            f"An internal server error occured while exporting IPs for Subnet with ID: {public_id}!",
        )
