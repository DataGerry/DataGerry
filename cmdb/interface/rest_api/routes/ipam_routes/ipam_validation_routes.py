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
Pre-check REST routes for IPAM validation

These routes never write — they answer "would this be valid if the frontend submitted it?"
The same validators are also called from the CmdbObject insert/update path so server-side
enforcement cannot be bypassed by an API client
"""
from logging import Logger, getLogger
from typing import Any

from flask import abort, request
from werkzeug import Response
from werkzeug.exceptions import HTTPException

from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.manager import ObjectsManager, TypesManager

from cmdb.models.user_model import CmdbUser
from cmdb.framework.ipam.subnet_validator import validate_subnet
from cmdb.framework.ipam.vlan_validator import validate_vlan
from cmdb.framework.ipam.interface_validator import validate_interface
from cmdb.interface.route_utils import insert_request_user, verify_api_access
from cmdb.interface.rest_api.api_level_enum import ApiLevel

from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.rest_api.responses import DefaultResponse
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

ipam_validation_blueprint = APIBlueprint('ipam_validation', __name__)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  PURE HELPERS                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
def _coerce_optional_int(value: Any) -> int | None:
    """
    Coerces a request payload value to an int when possible

    Args:
        value (Any): The raw payload value (typically int, str, or None)

    Returns:
        int | None: The integer form, or None when 'value' is None / not int-coercible
    """
    if value is None:
        return None

    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _build_validation_response(errors: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Wraps a validator's error list into the response envelope used by every IPAM pre-check route

    Args:
        errors (list[dict[str, Any]]): The validator's structured error list

    Returns:
        dict[str, Any]: {'valid': bool, 'errors': list[...]}
    """
    return {'valid': not errors, 'errors': errors}


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       ROUTES                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
@ipam_validation_blueprint.route('/subnet', methods=['POST'])
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@insert_request_user
def validate_subnet_route(request_user: CmdbUser) -> Response:
    """
    HTTP `POST` route that pre-validates a subnet candidate without writing anything

    Body:
        network_range (str): The candidate IPv4 CIDR
        parent_supernet_id (int, optional): Chosen SUPERNET object id
        parent_subnet_id (int, optional): Chosen parent SUBNET object id
        exclude_subnet_id (int, optional): Self-id when editing, so cycle / sibling checks
            don't compare the candidate against its own pre-edit state

    Args:
        request_user (CmdbUser): CmdbUser making the request

    Returns:
        Response: {'valid': bool, 'errors': list[{code, message, details}]}
    """
    try:
        payload: dict[str, Any] = request.get_json(silent=True) or {}

        network_range: Any = payload.get('network_range')

        if not isinstance(network_range, str) or not network_range:
            abort(400, "'network_range' is required and must be a string")

        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
        types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)

        errors: list[dict[str, Any]] = validate_subnet(
            objects_manager,
            types_manager,
            network_range=network_range,
            parent_supernet_id=_coerce_optional_int(payload.get('parent_supernet_id')),
            parent_subnet_id=_coerce_optional_int(payload.get('parent_subnet_id')),
            exclude_subnet_id=_coerce_optional_int(payload.get('exclude_subnet_id')),
        )

        return DefaultResponse(_build_validation_response(errors)).make_response()
    except HTTPException as http_err:
        raise http_err
    except Exception as err:
        LOGGER.error("[validate_subnet_route] Exception: %s. Type: %s", err, type(err).__name__, exc_info=True)
        abort(500, "An internal server error occured while validating the subnet candidate!")


@ipam_validation_blueprint.route('/vlan', methods=['POST'])
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@insert_request_user
def validate_vlan_route(request_user: CmdbUser) -> Response:
    """
    HTTP `POST` route that pre-validates a vlan candidate without writing anything

    Body:
        subnet_id (int): The id of the subnet the vlan would reference

    Args:
        request_user (CmdbUser): CmdbUser making the request

    Returns:
        Response: {'valid': bool, 'errors': list[{code, message, details}]}
    """
    try:
        payload: dict[str, Any] = request.get_json(silent=True) or {}

        subnet_id: int | None = _coerce_optional_int(payload.get('subnet_id'))

        if subnet_id is None:
            abort(400, "'subnet_id' is required and must be an integer")

        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
        types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)

        errors: list[dict[str, Any]] = validate_vlan(objects_manager, types_manager, subnet_id)

        return DefaultResponse(_build_validation_response(errors)).make_response()
    except HTTPException as http_err:
        raise http_err
    except Exception as err:
        LOGGER.error("[validate_vlan_route] Exception: %s. Type: %s", err, type(err).__name__, exc_info=True)
        abort(500, "An internal server error occured while validating the vlan candidate!")


@ipam_validation_blueprint.route('/interface', methods=['POST'])
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@insert_request_user
def validate_interface_route(request_user: CmdbUser) -> Response:
    """
    HTTP `POST` route that pre-validates a single dg-ipam-interface row without writing

    Body:
        subnet_id (int): The id of the subnet the interface row would reference
        ip_address (str): The interface IP
        exclude_object_id (int, optional): Self-id when editing an existing object
        exclude_row_index (int, optional): Row position of the row being edited

    Args:
        request_user (CmdbUser): CmdbUser making the request

    Returns:
        Response: {'valid': bool, 'errors': list[{code, message, details}]}
    """
    try:
        payload: dict[str, Any] = request.get_json(silent=True) or {}

        subnet_id: int | None = _coerce_optional_int(payload.get('subnet_id'))
        ip_address: Any = payload.get('ip_address')

        if subnet_id is None:
            abort(400, "'subnet_id' is required and must be an integer")

        if not isinstance(ip_address, str) or not ip_address:
            abort(400, "'ip_address' is required and must be a string")

        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
        types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)

        errors: list[dict[str, Any]] = validate_interface(
            objects_manager,
            types_manager,
            subnet_object_id=subnet_id,
            ip_address=ip_address,
            exclude_object_id=_coerce_optional_int(payload.get('exclude_object_id')),
            exclude_row_index=_coerce_optional_int(payload.get('exclude_row_index')),
        )

        return DefaultResponse(_build_validation_response(errors)).make_response()
    except HTTPException as http_err:
        raise http_err
    except Exception as err:
        LOGGER.error("[validate_interface_route] Exception: %s. Type: %s", err, type(err).__name__, exc_info=True)
        abort(500, "An internal server error occured while validating the interface candidate!")
