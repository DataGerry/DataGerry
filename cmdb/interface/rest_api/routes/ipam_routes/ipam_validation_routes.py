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
from cmdb.models.special_type_model.ipam_constants import (
    IpamValidationRequestKey,
    IpamValidationResponseKey,
)
from cmdb.framework.ipam.subnet_validator import validate_subnet
from cmdb.framework.ipam.supernet_validator import validate_supernet
from cmdb.framework.ipam.vlan_validator import validate_vlan
from cmdb.framework.ipam.interface_validator import validate_interface_rows
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
    return {
        IpamValidationResponseKey.VALID: not errors,
        IpamValidationResponseKey.ERRORS: errors,
    }


def _parse_interface_rows_payload(
    raw_rows: list[Any],
) -> list[tuple[int, int | None, str | None, str | None]]:
    """
    Normalizes the inline `/validate/interface` row list into the tuple shape the batch
    validator expects

    Each entry must be a dict carrying an integer 'row_index'; non-integer or missing
    'row_index' fails the request because the response must echo the index back so the
    frontend can map errors to form rows. Missing / non-coercible 'subnet_id' or
    'ip_address' are treated as None — those rows still get cross-row dupe scrutiny but
    are skipped by the per-row DB check, matching save-time semantics for incomplete rows.
    A missing / empty 'interface_type' is treated as None so the type-family consistency
    check is skipped for that row, matching save-time semantics for legacy rows

    Args:
        raw_rows (list[Any]): The 'rows' field straight off the JSON payload

    Returns:
        list[tuple[int, int | None, str | None, str | None]]: (row_index, subnet_ref, ip,
            interface_type) tuples
    """
    rows: list[tuple[int, int | None, str | None, str | None]] = []

    for index, raw in enumerate(raw_rows):
        if not isinstance(raw, dict):
            abort(400, f"rows[{index}] must be an object")

        row_index_raw: Any = raw.get(IpamValidationRequestKey.ROW_INDEX)

        try:
            row_index: int = int(row_index_raw)
        except (TypeError, ValueError):
            abort(400, f"rows[{index}].{IpamValidationRequestKey.ROW_INDEX.value} is required and must be an integer")

        subnet_ref: int | None = _coerce_optional_int(raw.get(IpamValidationRequestKey.SUBNET_ID))

        ip_raw: Any = raw.get(IpamValidationRequestKey.IP_ADDRESS)
        ip_address: str | None = ip_raw if isinstance(ip_raw, str) and ip_raw else None

        type_raw: Any = raw.get(IpamValidationRequestKey.INTERFACE_TYPE)
        interface_type: str | None = type_raw if isinstance(type_raw, str) and type_raw else None

        rows.append((row_index, subnet_ref, ip_address, interface_type))

    return rows


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
        network_range (str): The candidate IPv4 or IPv6 CIDR
        parent_supernet_id (int, optional): Chosen SUPERNET object id
        exclude_subnet_id (int, optional): Self-id when editing, so the sibling check
            doesn't compare the candidate against its own pre-edit state
        subnet_type (str, optional): The 'dg-subnet-type' selector ('ipv4' / 'ipv6'); when
            supplied it is cross-checked against the candidate CIDR's actual address family

    Args:
        request_user (CmdbUser): CmdbUser making the request

    Returns:
        Response: {'valid': bool, 'errors': list[{code, message, details}]}
    """
    try:
        payload: dict[str, Any] = request.get_json(silent=True) or {}

        network_range: Any = payload.get(IpamValidationRequestKey.NETWORK_RANGE)

        if not isinstance(network_range, str) or not network_range:
            abort(400, "'network_range' is required and must be a string")

        subnet_type: Any = payload.get(IpamValidationRequestKey.SUBNET_TYPE)

        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
        types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)

        errors: list[dict[str, Any]] = validate_subnet(
            objects_manager,
            types_manager,
            network_range=network_range,
            parent_supernet_id=_coerce_optional_int(payload.get(IpamValidationRequestKey.PARENT_SUPERNET_ID)),
            exclude_subnet_id=_coerce_optional_int(payload.get(IpamValidationRequestKey.EXCLUDE_SUBNET_ID)),
            subnet_type=subnet_type if isinstance(subnet_type, str) else None,
        )

        return DefaultResponse(_build_validation_response(errors)).make_response()
    except HTTPException as http_err:
        raise http_err
    except Exception as err:
        LOGGER.error("[validate_subnet_route] Exception: %s. Type: %s", err, type(err).__name__, exc_info=True)
        abort(500, "An internal server error occured while validating the subnet candidate!")


@ipam_validation_blueprint.route('/supernet', methods=['POST'])
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@insert_request_user
def validate_supernet_route(request_user: CmdbUser) -> Response:  # pylint: disable=unused-argument
    """
    HTTP `POST` route that pre-validates a supernet candidate without writing anything

    request_user is injected by the auth decorator but unused: supernet validation is stateless
    (no parent / sibling lookups), so no managers are needed

    Body:
        network_range (str): The candidate IPv4 or IPv6 CIDR
        supernet_type (str, optional): The 'dg-supernet-type' selector ('ipv4' / 'ipv6'); when
            supplied it is cross-checked against the candidate CIDR's actual address family

    Args:
        request_user (CmdbUser): CmdbUser making the request (unused; see above)

    Returns:
        Response: {'valid': bool, 'errors': list[{code, message, details}]}
    """
    try:
        payload: dict[str, Any] = request.get_json(silent=True) or {}

        network_range: Any = payload.get(IpamValidationRequestKey.NETWORK_RANGE)

        if not isinstance(network_range, str) or not network_range:
            abort(400, "'network_range' is required and must be a string")

        supernet_type: Any = payload.get(IpamValidationRequestKey.SUPERNET_TYPE)

        errors: list[dict[str, Any]] = validate_supernet(
            network_range=network_range,
            supernet_type=supernet_type if isinstance(supernet_type, str) else None,
        )

        return DefaultResponse(_build_validation_response(errors)).make_response()
    except HTTPException as http_err:
        raise http_err
    except Exception as err:
        LOGGER.error("[validate_supernet_route] Exception: %s. Type: %s", err, type(err).__name__, exc_info=True)
        abort(500, "An internal server error occured while validating the supernet candidate!")


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

        subnet_id: int | None = _coerce_optional_int(payload.get(IpamValidationRequestKey.SUBNET_ID))

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
    HTTP `POST` route that pre-validates a batch of dg-ipam-interface rows without writing

    The batch shape mirrors save-time enforcement so an in-flight collision between two rows
    on the same in-progress object is reported the same way the persistence path would report
    it. Each row's index is echoed back in error 'details' so the caller can map errors to
    the originating row in the form

    Body:
        rows (list[dict]): One entry per interface row currently entered on the form. Each
            entry must carry:
              row_index (int): Position of the row in the MDS section
              subnet_id (int): The id of the subnet the row references
              ip_address (str): The interface IP
              interface_type (str, optional): The row's 'dg-interface-type' selector
                ('ipv4' / 'ipv6'); when supplied it is cross-checked against the IP's
                address family and the referenced subnet's CIDR family
            Rows missing either subnet_id or ip_address are still accepted but skipped by the
            per-row check (so a half-typed row does not produce noise); rows without
            interface_type skip the type-family consistency check
        exclude_object_id (int, optional): Self-id when editing an existing object, so the
            object's own pre-edit rows are not flagged as collisions against the candidate

    Args:
        request_user (CmdbUser): CmdbUser making the request

    Returns:
        Response: {'valid': bool, 'errors': list[{code, message, details}]}
    """
    try:
        payload: dict[str, Any] = request.get_json(silent=True) or {}

        raw_rows: Any = payload.get(IpamValidationRequestKey.ROWS)

        if not isinstance(raw_rows, list):
            abort(400, "'rows' is required and must be a list of {row_index, subnet_id, ip_address}")

        rows: list[tuple[int, int | None, str | None, str | None]] = _parse_interface_rows_payload(raw_rows)

        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
        types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)

        errors: list[dict[str, Any]] = validate_interface_rows(
            objects_manager,
            types_manager,
            rows,
            exclude_object_id=_coerce_optional_int(payload.get(IpamValidationRequestKey.EXCLUDE_OBJECT_ID)),
        )

        return DefaultResponse(_build_validation_response(errors)).make_response()
    except HTTPException as http_err:
        raise http_err
    except Exception as err:
        LOGGER.error("[validate_interface_route] Exception: %s. Type: %s", err, type(err).__name__, exc_info=True)
        abort(500, "An internal server error occured while validating the interface candidates!")
