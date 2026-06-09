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
REST routes for the IPAM sidebar tree

Exposes the initial tree payload (every supernet plus every unassigned subnet in one call),
the per-supernet subtree endpoint used to lazily expand one supernet entry into its full
CIDR-nested subnet tree, and the unassigned-subnets endpoint for targeted refreshes of the
'Unassigned' group. All payloads carry lightweight nodes (public_id, name, cidr, address
family) sorted IPv4 before IPv6 and ascending by CIDR within each family
"""
from logging import Logger, getLogger
from typing import Any

from flask import abort
from werkzeug import Response
from werkzeug.exceptions import HTTPException

from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.manager import ObjectsManager, TypesManager

from cmdb.models.user_model import CmdbUser
from cmdb.framework.ipam.tree_overview import (
    build_ipam_tree,
    build_supernet_subnet_tree,
    build_unassigned_subnets,
)
from cmdb.interface.route_utils import insert_request_user, verify_api_access
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.rest_api.responses import DefaultResponse
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

ipam_tree_blueprint = APIBlueprint('ipam_tree', __name__)


@ipam_tree_blueprint.route('/', methods=['GET'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
def get_ipam_tree(request_user: CmdbUser) -> Response:
    """
    HTTP `GET` route returning the initial sidebar-tree payload in one call

    'supernets' lists every SUPERNET as a flat entry (public_id, name, cidr, type,
    has_children); the subtree of an entry is fetched lazily via the per-supernet endpoint
    when the user expands it. 'unassigned' lists every SUBNET without a parent supernet as a
    flat node (public_id, name, cidr, type). Both blocks are sorted IPv4 before IPv6, then
    ascending by CIDR with prefix length as tiebreaker; nodes with a missing or unparsable
    CIDR trail their family group ordered by name

    Args:
        request_user (CmdbUser): CmdbUser making the request

    Returns:
        Response: {'supernets': [supernet entries], 'unassigned': [subnet nodes]}
    """
    try:
        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
        types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)

        tree: dict[str, Any] = build_ipam_tree(objects_manager, types_manager)

        return DefaultResponse(tree).make_response()
    except HTTPException as http_err:
        raise http_err
    except Exception as err:
        LOGGER.error(
            "[get_ipam_tree] Exception: %s. Type: %s",
            err, type(err).__name__, exc_info=True,
        )
        abort(500, "An internal server error occured while building the IPAM tree!")


@ipam_tree_blueprint.route('/supernets/<int:public_id>', methods=['GET'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
def get_supernet_subnet_tree(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `GET` route returning the full CIDR-nested subnet subtree of one supernet

    Used by the frontend to populate one expanded supernet entry of the sidebar tree. Returns
    every SUBNET referencing the supernet (any nesting depth) as a nested node tree in one
    call; each node carries public_id, name, cidr, type and a 'children' list (empty for
    leaves). Every 'children' array follows the IPv4-before-IPv6, ascending-CIDR order. A
    supernet without subnets returns an empty 'children' list

    Args:
        public_id (int): public_id of the SUPERNET CmdbObject whose subtree is returned
        request_user (CmdbUser): CmdbUser making the request

    Returns:
        Response: {'children': [root nodes, each with nested 'children']}
    """
    try:
        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
        types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)

        subtree: dict[str, Any] = build_supernet_subnet_tree(objects_manager, types_manager, public_id)

        return DefaultResponse(subtree).make_response()
    except HTTPException as http_err:
        raise http_err
    except Exception as err:
        LOGGER.error(
            "[get_supernet_subnet_tree] Exception: %s. Type: %s",
            err, type(err).__name__, exc_info=True,
        )
        abort(
            500,
            f"An internal server error occured while building the subnet tree for Supernet with ID: {public_id}!",
        )


@ipam_tree_blueprint.route('/unassigned', methods=['GET'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
def get_unassigned_subnets(request_user: CmdbUser) -> Response:
    """
    HTTP `GET` route returning the unassigned-subnets block of the sidebar tree alone

    Returns the same flat 'unassigned' list as the initial tree payload - every SUBNET whose
    'dg-supernet-ref' is empty - without reloading the supernet block, for targeted refreshes
    of the 'Unassigned' group. Nodes are sorted IPv4 before IPv6, then ascending by CIDR

    Args:
        request_user (CmdbUser): CmdbUser making the request

    Returns:
        Response: {'unassigned': [subnet nodes]}
    """
    try:
        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
        types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)

        unassigned: dict[str, Any] = build_unassigned_subnets(objects_manager, types_manager)

        return DefaultResponse(unassigned).make_response()
    except HTTPException as http_err:
        raise http_err
    except Exception as err:
        LOGGER.error(
            "[get_unassigned_subnets] Exception: %s. Type: %s",
            err, type(err).__name__, exc_info=True,
        )
        abort(500, "An internal server error occured while loading the unassigned subnets!")
