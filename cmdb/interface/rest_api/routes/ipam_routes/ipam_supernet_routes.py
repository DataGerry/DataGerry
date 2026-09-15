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

Exposes the paginated top-level supernet overview that powers the supernet overview view,
a per-subnet 'direct children' endpoint used to lazily expand a subnet row in that view, the
paginated invalid-subnets-only overview that lists subnets whose CIDR no longer fits inside
the supernet, and the batch 'unassign subnets' endpoint that clears dg-supernet-ref on
multiple SUBNETs at once

Three things here deliberately differ from the sibling SUBNET routes; none of them is an
oversight, and each is tracked so the asymmetry stays visible:

* **The unassign write is a single raw Mongo update, not a per-object write.**
  ``supernet_membership.clear_supernet_ref`` issues one ``update_many_raw`` whose document filter
  and array filter both re-assert the current supernet reference, which closes the TOCTOU window
  between validation and write and keeps the whole batch in one write. The cost is that it does
  **not** go through ``ObjectsManager.update_object``: no object-level ACL check, no entry in the
  objects' change history, no version bump and no webhook - unlike the SUBNET unassign route,
  which writes each owner individually and gets all four. Recorded as discussion-backlog #152
* **The subnets CSV export is uncapped.** Its SUBNET counterpart refuses an export above
  ``IpamSubnetIpsExport.MAX_EXPORT_ROWS``; ``IpamExport`` defines no such limit, so a supernet with
  very many subnets builds the whole file in memory. Recorded as #153
* **The children endpoint is unpaginated.** Every other route on this blueprint pages its rows;
  this one returns all direct CIDR-children of the expanded subnet in a single response, which is
  also what the frontend expects today. Recorded as #154

These routes are transport glue: reading the query string / body, resolving the managers and
mapping failures onto HTTP. The payloads themselves are built by ``cmdb.framework.ipam``
"""
from logging import Logger, getLogger
from typing import Any

from flask import abort
from werkzeug import Response
from werkzeug.exceptions import HTTPException

from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.manager import ObjectsManager, TypesManager

from cmdb.models.user_model import CmdbUser
from cmdb.models.special_type_model.ipam_constants import (
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

ipam_supernet_blueprint = APIBlueprint('ipam_supernet', __name__)

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

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

    Raises:
        HTTPException: 404 when no object with this public_id exists, 400 when it is not a SUPERNET
                       or no SUPERNET / SUBNET CmdbType is defined

    Returns:
        Response: {'supernet': {...summary, public_id}, 'subnets': {page, page_size, total,
            rows: [...subnet rows with has_children]}}
    """
    try:
        page, page_size = read_pagination_params()
        search: str = read_search_param()

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

    The row list is NOT paginated - every direct child comes back in one response, which is what
    the frontend expects when it expands a row (see discussion-backlog #154)

    Raises:
        HTTPException: 404 when the supernet does not exist, 400 when the public_id is not a
                       SUPERNET, when no SUPERNET / SUBNET CmdbType is defined, or when subnet_id is
                       not a SUBNET assigned to this supernet

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

    The export is **uncapped**: unlike the SUBNET IP export, which refuses anything above
    ``IpamSubnetIpsExport.MAX_EXPORT_ROWS``, every assigned subnet is written out however many there
    are (see discussion-backlog #153)

    Raises:
        HTTPException: 404 when the supernet does not exist, 400 when the public_id is not a
                       SUPERNET or no SUPERNET / SUBNET CmdbType is defined

    Returns:
        Response: The .csv file as an attachment download
    """
    try:
        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
        types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)

        content: bytes = build_supernet_subnets_csv(objects_manager, types_manager, public_id)

        filename: str = IpamExport.FILENAME_TEMPLATE.format(
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

    Raises:
        HTTPException: 404 when no object with this public_id exists, 400 when it is not a SUPERNET
                       or no SUPERNET / SUBNET CmdbType is defined

    Returns:
        Response: {'supernet': {...summary, public_id}, 'subnets': {page, page_size, total,
            rows: [...invalid subnet rows]}, 'invalid_count': int}
    """
    try:
        page, page_size = read_pagination_params()
        search: str = read_search_param()

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


# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

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

    **How the write happens matters here.** The whole batch is applied as ONE raw
    ``update_many_raw`` whose filters re-assert the current supernet reference, so a SUBNET that a
    concurrent writer reassigned in between is skipped rather than clobbered. That write does not go
    through ``ObjectsManager.update_object``, which means the detach is **not checked against the
    SUBNETs' object ACL and leaves no history entry, no version bump and no webhook** - the sibling
    SUBNET unassign route, which writes per owner, does all four. `request_user` is therefore not
    forwarded. Recorded as discussion-backlog #152

    Body:
        subnet_ids (list[int]): public_ids of SUBNETs to detach; must be a non-empty list,
            duplicates are silently collapsed while preserving input order

    Args:
        public_id (int): public_id of the SUPERNET CmdbObject the subnets are detached from
        request_user (CmdbUser): CmdbUser making the request; used only for manager resolution -
                                 the write itself is not user-scoped (see above)

    Raises:
        HTTPException: 400 when the body is not a JSON object, when 'subnet_ids' is missing / empty /
                       malformed, when an id is not a SUBNET assigned to this supernet, when the
                       public_id is not a SUPERNET or no SUPERNET / SUBNET CmdbType is defined;
                       404 when the supernet does not exist

    Returns:
        Response: {'subnet_ids': [int, ...], 'unassigned_count': int}; subnet_ids echoes the
            deduplicated request order
    """
    try:
        payload: dict[str, Any] = read_json_object_body()

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
