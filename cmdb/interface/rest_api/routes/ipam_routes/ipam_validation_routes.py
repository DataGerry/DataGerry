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

Four POST routes, one per IPAM candidate shape - ``/validate/subnet``, ``/validate/supernet``,
``/validate/vlan`` and ``/validate/interface`` - each taking a JSON body and answering the same
``{valid: bool, errors: [...]}`` envelope. They **never write**: they answer "would this be valid if
the frontend submitted it?", so the form can refuse a bad value while it is being typed instead of
at save time.

Two things follow from that and shape the whole module:

* **The validators behind them are the same ones the CmdbObject insert / update path calls**, so
  server-side enforcement cannot be bypassed by an API client that skips the pre-check. These
  routes are a second entrance to one rule, never a rule of their own - which is also why they own
  no error messages beyond the ones about the request shape itself
* **A wrong answer is the failure mode to design against, not an exception.** Nothing here writes,
  so the damage a bug does is not corruption - it is telling the customer their valid subnet
  overlaps something, or letting an invalid one through to a save that then refuses it. That is why
  the body readers refuse an unusable value instead of reading it as absent: see
  ``read_optional_object_id``, where an unreadable ``exclude_subnet_id`` would otherwise make the
  candidate collide with itself

A HTTP 400 from these routes therefore always means "your request was malformed", never "your
candidate is invalid" - an invalid candidate is a 200 with ``valid: false`` and the reasons.

The whole surface sits behind the licensed IPAM feature (the blueprint is gated in
``init_rest_api``) and, like the rest of the folder, carries no per-user ACL right yet -
discussion-backlog #149
"""
from logging import Logger, getLogger
from typing import Any

from flask import abort
from werkzeug import Response
from werkzeug.exceptions import HTTPException

from cmdb.models.user_model import CmdbUser
from cmdb.models.special_type_model.ipam_constants import (
    IpamValidationRequestKey,
    IpamValidationResponseKey,
)
from cmdb.framework.ipam.subnet_validator import validate_subnet
from cmdb.framework.ipam.supernet_validator import validate_supernet
from cmdb.framework.ipam.vlan_validator import validate_vlan
from cmdb.framework.ipam.interface_validator import validate_interface_rows
from cmdb.interface.rest_api.routes.ipam_routes.ipam_route_helper import (
    parse_interface_rows_payload,
    read_ipam_managers,
    read_json_object_body,
    read_optional_object_id,
    read_required_object_id,
    read_required_string,
)
from cmdb.interface.rest_api.routes.ipam_routes.ipam_route_constants import (
    VALIDATION_ROWS_NOT_A_LIST_MESSAGE,
)
from cmdb.interface.route_utils import insert_request_user, verify_api_access
from cmdb.interface.rest_api.api_level_enum import ApiLevel

from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.rest_api.responses import DefaultResponse
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

ipam_validation_blueprint = APIBlueprint('ipam_validation', __name__)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                 RESPONSE ENVELOPE                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
def _build_validation_response(errors: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Wraps a validator's error list into the response envelope used by every IPAM pre-check route

    Args:
        errors (list[dict[str, Any]]): The validator's structured error list

    Returns:
        dict[str, Any]: {'valid': bool, 'errors': list[...]}
    """
    return {
        IpamValidationResponseKey.VALID.value: not errors,
        IpamValidationResponseKey.ERRORS.value: errors,
    }


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       ROUTES                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
@ipam_validation_blueprint.route('/subnet', methods=['POST'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
def validate_subnet_route(request_user: CmdbUser) -> Response:
    """
    HTTP `POST` route that pre-validates a subnet candidate without writing anything

    Body:
        network_range (str): The candidate IPv4 or IPv6 CIDR
        parent_supernet_id (int, optional): Chosen SUPERNET object id
        exclude_subnet_id (int, optional): Self-id when editing, so the sibling check
            doesn't compare the candidate against its own pre-edit state
        subnet_type (str): The 'dg-subnet-type' selector ('ipv4' / 'ipv6'); required - when
            omitted the validator reports an error, when supplied it is cross-checked
            against the candidate CIDR's actual address family

    Args:
        request_user (CmdbUser): CmdbUser making the request

    Raises:
        HTTPException: 400 when the body is not a JSON object, when 'network_range' is absent or not a
                       non-empty string, or when 'parent_supernet_id' / 'exclude_subnet_id' is present
                       but is not a whole number; 500 on an unexpected error. An INVALID candidate is
                       not an error here - it is a 200 carrying valid: false

    Returns:
        Response: {'valid': bool, 'errors': list[{message}]}
    """
    try:
        payload: dict[str, Any] = read_json_object_body()

        network_range: str = read_required_string(payload, IpamValidationRequestKey.NETWORK_RANGE.value)
        subnet_type: Any = payload.get(IpamValidationRequestKey.SUBNET_TYPE.value)

        objects_manager, types_manager = read_ipam_managers(request_user)

        errors: list[dict[str, Any]] = validate_subnet(
            objects_manager,
            types_manager,
            network_range=network_range,
            parent_supernet_id=read_optional_object_id(
                payload, IpamValidationRequestKey.PARENT_SUPERNET_ID.value,
            ),
            exclude_subnet_id=read_optional_object_id(
                payload, IpamValidationRequestKey.EXCLUDE_SUBNET_ID.value,
            ),
            subnet_type=subnet_type if isinstance(subnet_type, str) else None,
        )

        return DefaultResponse(_build_validation_response(errors)).make_response()
    except HTTPException as http_err:
        raise http_err
    except Exception as err:
        LOGGER.error("[validate_subnet_route] Exception: %s. Type: %s", err, type(err).__name__, exc_info=True)
        abort(500, "An internal server error occured while validating the subnet candidate!")


@ipam_validation_blueprint.route('/supernet', methods=['POST'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
def validate_supernet_route(request_user: CmdbUser) -> Response:  # pylint: disable=unused-argument
    """
    HTTP `POST` route that pre-validates a supernet candidate without writing anything

    request_user is injected by the auth decorator but unused: supernet validation is stateless
    (no parent / sibling lookups), so no managers are needed

    Body:
        network_range (str): The candidate IPv4 or IPv6 CIDR
        supernet_type (str): The 'dg-supernet-type' selector ('ipv4' / 'ipv6'); required - when
            omitted the validator reports an error, when supplied it is cross-checked
            against the candidate CIDR's actual address family

    Args:
        request_user (CmdbUser): CmdbUser making the request (unused; see above)

    Raises:
        HTTPException: 400 when the body is not a JSON object or 'network_range' is absent / not a
                       non-empty string; 500 on an unexpected error. An INVALID candidate is not an
                       error here - it is a 200 carrying valid: false

    Returns:
        Response: {'valid': bool, 'errors': list[{message}]}
    """
    try:
        payload: dict[str, Any] = read_json_object_body()

        network_range: str = read_required_string(payload, IpamValidationRequestKey.NETWORK_RANGE.value)
        supernet_type: Any = payload.get(IpamValidationRequestKey.SUPERNET_TYPE.value)

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
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
def validate_vlan_route(request_user: CmdbUser) -> Response:
    """
    HTTP `POST` route that pre-validates a vlan candidate without writing anything

    Body:
        subnet_id (int): The id of the subnet the vlan would reference. Required - unlike the
            interface route's per-row subnet_id, which tolerates a half-typed row

    Args:
        request_user (CmdbUser): CmdbUser making the request

    Raises:
        HTTPException: 400 when the body is not a JSON object or 'subnet_id' is absent / not a whole
                       number; 500 on an unexpected error. An INVALID candidate is not an error here -
                       it is a 200 carrying valid: false

    Returns:
        Response: {'valid': bool, 'errors': list[{message}]}
    """
    try:
        payload: dict[str, Any] = read_json_object_body()

        subnet_id: int = read_required_object_id(payload, IpamValidationRequestKey.SUBNET_ID.value)

        objects_manager, types_manager = read_ipam_managers(request_user)

        errors: list[dict[str, Any]] = validate_vlan(objects_manager, types_manager, subnet_id)

        return DefaultResponse(_build_validation_response(errors)).make_response()
    except HTTPException as http_err:
        raise http_err
    except Exception as err:
        LOGGER.error("[validate_vlan_route] Exception: %s. Type: %s", err, type(err).__name__, exc_info=True)
        abort(500, "An internal server error occured while validating the vlan candidate!")


@ipam_validation_blueprint.route('/interface', methods=['POST'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
def validate_interface_route(request_user: CmdbUser) -> Response:
    """
    HTTP `POST` route that pre-validates a batch of dg-ipam-interface rows without writing

    The batch shape mirrors save-time enforcement so an in-flight collision between two rows
    on the same in-progress object is reported the same way the persistence path would report
    it. Each row's index is echoed back in error 'details' (the only structured payload that
    survives) so the caller can map errors to the originating row in the form

    Body:
        rows (list[dict]): One entry per interface row currently entered on the form. Each
            entry must carry:
              row_index (int): Position of the row in the MDS section
              subnet_id (int): The id of the subnet the row references
              ip_address (str): The interface IP
              interface_type (str): The row's 'dg-interface-type' selector
                ('ipv4' / 'ipv6'); required on every row carrying a subnet_id and/or an
                ip_address - missing is rejected - and cross-checked against the IP's address
                family and the referenced subnet's CIDR family
            Rows missing either subnet_id or ip_address are still accepted but skipped by the
            per-row check (so a half-typed row does not produce noise); completely empty
            placeholder rows are accepted silently
        exclude_object_id (int, optional): Self-id when editing an existing object, so the
            object's own pre-edit rows are not flagged as collisions against the candidate

    Args:
        request_user (CmdbUser): CmdbUser making the request

    Raises:
        HTTPException: 400 when the body is not a JSON object, when 'rows' is absent or not a list,
                       when an entry is not an object or carries no readable 'row_index', or when
                       'exclude_object_id' is present but is not a whole number; 500 on an unexpected
                       error. Rows that are merely INVALID are not errors here - they come back in the
                       200's error list, each tagged with its row_index

    Returns:
        Response: {'valid': bool, 'errors': list[{message, details: {row_index}}]}
    """
    try:
        payload: dict[str, Any] = read_json_object_body()

        raw_rows: Any = payload.get(IpamValidationRequestKey.ROWS.value)

        if not isinstance(raw_rows, list):
            abort(400, VALIDATION_ROWS_NOT_A_LIST_MESSAGE.format(
                field=IpamValidationRequestKey.ROWS.value,
            ))

        rows: list[tuple[int, int | None, str | None, str | None]] = parse_interface_rows_payload(raw_rows)

        objects_manager, types_manager = read_ipam_managers(request_user)

        errors: list[dict[str, Any]] = validate_interface_rows(
            objects_manager,
            types_manager,
            rows,
            exclude_object_id=read_optional_object_id(
                payload, IpamValidationRequestKey.EXCLUDE_OBJECT_ID.value,
            ),
        )

        return DefaultResponse(_build_validation_response(errors)).make_response()
    except HTTPException as http_err:
        raise http_err
    except Exception as err:
        LOGGER.error("[validate_interface_route] Exception: %s. Type: %s", err, type(err).__name__, exc_info=True)
        abort(500, "An internal server error occured while validating the interface candidates!")
