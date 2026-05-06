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
Validator for a single dg-ipam-interface MDS row

Confirms the referenced subnet exists and has SpecialType SUBNET, the IP parses as IPv4 and
sits inside the subnet (and is neither the network nor the broadcast address), and the IP is
not already in use by another interface row anywhere in the system that references the same
subnet
"""
from ipaddress import IPv4Address, IPv4Network
from typing import Any

from cmdb.manager import ObjectsManager, TypesManager
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.framework.ipam.cidr import (
    parse_cidr,
    parse_ipv4,
    ip_in_network,
    is_network_or_broadcast,
)
from cmdb.framework.ipam.references import resolve_special_type_id
from cmdb.framework.ipam.subnet_validator import build_error, extract_field_value, SUBNET_RANGE_FIELD
# -------------------------------------------------------------------------------------------------------------------- #


INTERFACE_SECTION_NAME: str = 'dg-ipam-interface'
INTERFACE_SUBNET_FIELD: str = 'dg-interface-subnet'
INTERFACE_IP_FIELD: str = 'dg-interface-ip-address'


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  ERROR CODES                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class InterfaceErrorCode:
    """Stable codes for structured interface row validation errors"""
    SUBNET_TYPE_MISSING = 'subnet_type_missing'
    SUBNET_NOT_FOUND = 'subnet_not_found'
    SUBNET_BROKEN_STATE = 'subnet_broken_state'
    IP_INVALID = 'ip_invalid'
    IP_NOT_IN_SUBNET = 'ip_not_in_subnet'
    IP_RESERVED = 'ip_reserved'
    IP_DUPLICATE = 'ip_duplicate'


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  PURE HELPERS                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
def _load_subnet_object(
    objects_manager: ObjectsManager,
    types_manager: TypesManager,
    subnet_object_id: int,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """
    Loads the SUBNET CmdbObject by id, returning errors when the type or object is missing

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        subnet_object_id (int): public_id of the referenced subnet

    Returns:
        tuple[dict[str, Any] | None, list[dict[str, Any]]]: (subnet doc or None, errors)
    """
    subnet_type_id: int | None = resolve_special_type_id(types_manager, SpecialType.SUBNET)

    if subnet_type_id is None:
        return None, [build_error(
            InterfaceErrorCode.SUBNET_TYPE_MISSING,
            "No SUBNET CmdbType is defined; cannot validate interface subnet reference",
        )]

    matches: list[dict[str, Any]] = objects_manager.find_objects(
        {'public_id': subnet_object_id, 'type_id': subnet_type_id},
        as_dict=True,
    )

    if not matches:
        return None, [build_error(
            InterfaceErrorCode.SUBNET_NOT_FOUND,
            f"Subnet object with id {subnet_object_id} does not exist",
            {'subnet_object_id': subnet_object_id},
        )]

    return matches[0], []


def _extract_subnet_network(subnet_obj: dict[str, Any]) -> tuple[IPv4Network | None, list[dict[str, Any]]]:
    """
    Reads and parses the 'dg-network-range' field of a subnet object

    Args:
        subnet_obj (dict[str, Any]): The subnet CmdbObject document

    Returns:
        tuple[IPv4Network | None, list[dict[str, Any]]]: (parsed network or None, errors)
    """
    raw: Any = extract_field_value(subnet_obj, SUBNET_RANGE_FIELD)
    parsed: IPv4Network | None = parse_cidr(raw) if isinstance(raw, str) else None

    if parsed is None:
        return None, [build_error(
            InterfaceErrorCode.SUBNET_BROKEN_STATE,
            f"Subnet object {subnet_obj.get('public_id')} has no valid '{SUBNET_RANGE_FIELD}' value",
            {'subnet_object_id': subnet_obj.get('public_id'), 'stored_value': raw},
        )]

    return parsed, []


# -------------------------------------------------------------------------------------------------------------------- #
#                                                INDIVIDUAL CHECKS                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
def _check_ip_format(ip_address: str) -> tuple[IPv4Address | None, list[dict[str, Any]]]:
    """
    Validates that the candidate IP parses as IPv4

    Args:
        ip_address (str): The candidate IP address string

    Returns:
        tuple[IPv4Address | None, list[dict[str, Any]]]: (parsed address or None, errors)
    """
    parsed: IPv4Address | None = parse_ipv4(ip_address)

    if parsed is None:
        return None, [build_error(
            InterfaceErrorCode.IP_INVALID,
            f"'{ip_address}' is not a valid IPv4 address",
            {'ip_address': ip_address},
        )]

    return parsed, []


def _check_ip_membership(ip: IPv4Address, subnet_net: IPv4Network) -> list[dict[str, Any]]:
    """
    Validates that the IP sits inside the subnet and is neither the network nor broadcast address

    Args:
        ip (IPv4Address): The parsed candidate IP
        subnet_net (IPv4Network): The subnet's parsed network

    Returns:
        list[dict[str, Any]]: Errors found, empty when membership is valid
    """
    errors: list[dict[str, Any]] = []

    if not ip_in_network(ip, subnet_net):
        errors.append(build_error(
            InterfaceErrorCode.IP_NOT_IN_SUBNET,
            f"IP {ip} is not part of subnet {subnet_net}",
            {'ip_address': str(ip), 'subnet_range': str(subnet_net)},
        ))
        return errors

    if is_network_or_broadcast(ip, subnet_net):
        errors.append(build_error(
            InterfaceErrorCode.IP_RESERVED,
            f"IP {ip} is the network or broadcast address of {subnet_net}",
            {'ip_address': str(ip), 'subnet_range': str(subnet_net)},
        ))

    return errors


def _check_ip_uniqueness(
    objects_manager: ObjectsManager,
    subnet_object_id: int,
    ip_address: str,
    exclude_object_id: int | None,
    exclude_row_index: int | None,
) -> list[dict[str, Any]]:
    """
    Validates that no other interface row in the same subnet already uses the candidate IP

    Searches every CmdbObject that has at least one dg-ipam-interface row containing both the
    subnet ref and the candidate IP. Then walks the rows to locate the collision and skips the
    pair (exclude_object_id, exclude_row_index) which represents the candidate's own pre-edit
    row when editing

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        subnet_object_id (int): public_id of the referenced subnet
        ip_address (str): The candidate IP address as string
        exclude_object_id (int | None): public_id of the candidate's own object when editing
        exclude_row_index (int | None): row position of the candidate within its MDS section
            when editing

    Returns:
        list[dict[str, Any]]: One error per collision found, empty when the IP is unique
    """
    criteria: dict[str, Any] = {
        'multi_data_sections': {
            '$elemMatch': {
                'name': INTERFACE_SECTION_NAME,
                'values': {
                    '$elemMatch': {
                        'data': {
                            '$all': [
                                {'$elemMatch': {'name': INTERFACE_SUBNET_FIELD, 'value': subnet_object_id}},
                                {'$elemMatch': {'name': INTERFACE_IP_FIELD, 'value': ip_address}},
                            ],
                        },
                    },
                },
            },
        },
    }

    candidates: list[dict[str, Any]] = objects_manager.find_objects(criteria, as_dict=True)

    return _collect_collision_errors(
        candidates,
        subnet_object_id,
        ip_address,
        exclude_object_id,
        exclude_row_index,
    )


def _collect_collision_errors(
    candidates: list[dict[str, Any]],
    subnet_object_id: int,
    ip_address: str,
    exclude_object_id: int | None,
    exclude_row_index: int | None,
) -> list[dict[str, Any]]:
    """
    Walks the candidate documents' interface rows and reports collisions, honoring the row
    exclusion pair so the candidate's own pre-edit row is not flagged against itself

    Args:
        candidates (list[dict[str, Any]]): CmdbObject documents pre-filtered by the Mongo query
        subnet_object_id (int): public_id of the subnet being checked
        ip_address (str): The candidate IP as string
        exclude_object_id (int | None): public_id to skip per (object, row) exclusion
        exclude_row_index (int | None): row index to skip per (object, row) exclusion

    Returns:
        list[dict[str, Any]]: One error per remaining collision
    """
    errors: list[dict[str, Any]] = []

    for candidate in candidates:
        candidate_id: Any = candidate.get('public_id')

        for section in candidate.get('multi_data_sections', []) or []:
            if section.get('name') != INTERFACE_SECTION_NAME:
                continue

            for row_index, row in enumerate(section.get('values', []) or []):
                if not _row_matches(row, subnet_object_id, ip_address):
                    continue

                if (
                    exclude_object_id is not None
                    and exclude_row_index is not None
                    and candidate_id == exclude_object_id
                    and row_index == exclude_row_index
                ):
                    continue

                errors.append(build_error(
                    InterfaceErrorCode.IP_DUPLICATE,
                    f"IP {ip_address} is already used in subnet {subnet_object_id} "
                    f"by object {candidate_id} (interface row {row_index})",
                    {
                        'ip_address': ip_address,
                        'subnet_object_id': subnet_object_id,
                        'object_id': candidate_id,
                        'row_index': row_index,
                    },
                ))

    return errors


def _row_matches(row: dict[str, Any], subnet_object_id: int, ip_address: str) -> bool:
    """
    Reports whether an MDS row's data array contains both the candidate subnet ref and IP

    Args:
        row (dict[str, Any]): One entry from an MDS section's 'values' list
        subnet_object_id (int): The subnet id to match against the row's dg-interface-subnet
        ip_address (str): The IP to match against the row's dg-interface-ip-address

    Returns:
        bool: True when both fields match in this row, False otherwise
    """
    has_subnet: bool = False
    has_ip: bool = False

    for entry in row.get('data', []) or []:
        if entry.get('name') == INTERFACE_SUBNET_FIELD and entry.get('value') == subnet_object_id:
            has_subnet = True
        elif entry.get('name') == INTERFACE_IP_FIELD and entry.get('value') == ip_address:
            has_ip = True

    return has_subnet and has_ip


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  ORCHESTRATOR                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
def validate_interface(
    objects_manager: ObjectsManager,
    types_manager: TypesManager,
    subnet_object_id: int,
    ip_address: str,
    exclude_object_id: int | None = None,
    exclude_row_index: int | None = None,
) -> list[dict[str, Any]]:
    """
    Validates a single dg-ipam-interface row's subnet reference and IP

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        subnet_object_id (int): public_id of the subnet the interface references
        ip_address (str): The interface IP address
        exclude_object_id (int | None): Self-id for editing, so the candidate doesn't collide
            with its own pre-edit state
        exclude_row_index (int | None): Self row index for editing, paired with exclude_object_id

    Returns:
        list[dict[str, Any]]: Structured validation errors; empty when the row is valid
    """
    subnet_obj, errors = _load_subnet_object(objects_manager, types_manager, subnet_object_id)

    if subnet_obj is None:
        return errors

    subnet_net, range_errors = _extract_subnet_network(subnet_obj)
    errors.extend(range_errors)

    ip, ip_errors = _check_ip_format(ip_address)
    errors.extend(ip_errors)

    if subnet_net is not None and ip is not None:
        errors.extend(_check_ip_membership(ip, subnet_net))

    if ip is not None:
        errors.extend(_check_ip_uniqueness(
            objects_manager, subnet_object_id, ip_address,
            exclude_object_id, exclude_row_index,
        ))

    return errors
