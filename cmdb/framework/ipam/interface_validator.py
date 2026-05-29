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
from cmdb.models.object_model import (
    CmdbObjectKey,
    CmdbObjectFieldKey,
    CmdbObjectMdsKey,
    CmdbObjectMdsRowKey,
    extract_field_value,
)
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.special_type_model.ipam_constants import (
    SubnetField,
    InterfaceField,
    IpamSection,
    IpamValidationDetailKey,
)
from cmdb.utils import BaseStrEnum, build_error
from cmdb.framework.ipam.cidr import (
    parse_cidr,
    parse_ipv4,
    ip_in_network,
    is_network_or_broadcast,
)
from cmdb.framework.ipam.references import resolve_special_type_id
# -------------------------------------------------------------------------------------------------------------------- #


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  ERROR CODES                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class InterfaceErrorCode(BaseStrEnum):
    """Stable codes for structured interface row validation errors"""
    SUBNET_TYPE_MISSING = 'subnet_type_missing'
    SUBNET_NOT_FOUND = 'subnet_not_found'
    SUBNET_BROKEN_STATE = 'subnet_broken_state'
    SUBNET_WITHOUT_IP = 'subnet_without_ip'
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
        {CmdbObjectKey.PUBLIC_ID: subnet_object_id, CmdbObjectKey.TYPE_ID: subnet_type_id},
        as_dict=True,
    )

    if not matches:
        return None, [build_error(
            InterfaceErrorCode.SUBNET_NOT_FOUND,
            f"Subnet object with id {subnet_object_id} does not exist",
            {IpamValidationDetailKey.SUBNET_OBJECT_ID: subnet_object_id},
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
    raw: Any = extract_field_value(subnet_obj, SubnetField.NETWORK_RANGE)
    parsed: IPv4Network | None = parse_cidr(raw) if isinstance(raw, str) else None

    if parsed is None:
        return None, [build_error(
            InterfaceErrorCode.SUBNET_BROKEN_STATE,
            (
                f"Subnet object {subnet_obj.get(CmdbObjectKey.PUBLIC_ID)} has no valid "
                f"'{SubnetField.NETWORK_RANGE.value}' value"
            ),
            {
                IpamValidationDetailKey.SUBNET_OBJECT_ID: subnet_obj.get(CmdbObjectKey.PUBLIC_ID),
                IpamValidationDetailKey.STORED_VALUE: raw,
            },
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
            {IpamValidationDetailKey.IP_ADDRESS: ip_address},
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
            {
                IpamValidationDetailKey.IP_ADDRESS: str(ip),
                IpamValidationDetailKey.SUBNET_RANGE: str(subnet_net),
            },
        ))
        return errors

    if is_network_or_broadcast(ip, subnet_net):
        errors.append(build_error(
            InterfaceErrorCode.IP_RESERVED,
            f"IP {ip} is the network or broadcast address of {subnet_net}",
            {
                IpamValidationDetailKey.IP_ADDRESS: str(ip),
                IpamValidationDetailKey.SUBNET_RANGE: str(subnet_net),
            },
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
        CmdbObjectKey.MULTI_DATA_SECTIONS: {
            '$elemMatch': {
                CmdbObjectMdsKey.SECTION_ID: IpamSection.INTERFACE,
                CmdbObjectMdsKey.VALUES: {
                    '$elemMatch': {
                        CmdbObjectMdsRowKey.DATA: {
                            '$all': [
                                {'$elemMatch': {
                                    CmdbObjectFieldKey.NAME: InterfaceField.SUBNET,
                                    CmdbObjectFieldKey.VALUE: subnet_object_id,
                                }},
                                {'$elemMatch': {
                                    CmdbObjectFieldKey.NAME: InterfaceField.IP,
                                    CmdbObjectFieldKey.VALUE: ip_address,
                                }},
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
        candidate_id: Any = candidate.get(CmdbObjectKey.PUBLIC_ID)

        for section in candidate.get(CmdbObjectKey.MULTI_DATA_SECTIONS, []) or []:
            if section.get(CmdbObjectMdsKey.SECTION_ID) != IpamSection.INTERFACE:
                continue

            for row_index, row in enumerate(section.get(CmdbObjectMdsKey.VALUES, []) or []):
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
                        IpamValidationDetailKey.IP_ADDRESS: ip_address,
                        IpamValidationDetailKey.SUBNET_OBJECT_ID: subnet_object_id,
                        IpamValidationDetailKey.OBJECT_ID: candidate_id,
                        IpamValidationDetailKey.ROW_INDEX: row_index,
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

    for entry in row.get(CmdbObjectMdsRowKey.DATA, []) or []:
        entry_name: Any = entry.get(CmdbObjectFieldKey.NAME)
        entry_value: Any = entry.get(CmdbObjectFieldKey.VALUE)

        if entry_name == InterfaceField.SUBNET and entry_value == subnet_object_id:
            has_subnet = True
        elif entry_name == InterfaceField.IP and entry_value == ip_address:
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


def find_intra_submission_duplicates(
    rows: list[tuple[int, int | None, str | None]],
) -> list[dict[str, Any]]:
    """
    Reports interface rows in the same submission that share both subnet ref and IP

    Rows missing either the subnet ref or the IP are skipped (treated as incomplete, surfaced
    by the per-row check instead). The first occurrence of a (subnet_ref, ip) pair seeds the
    seen-set; every subsequent matching row is reported as a duplicate against that first row

    Args:
        rows (list[tuple[int, int | None, str | None]]): (row_index, subnet_ref, ip) tuples

    Returns:
        list[dict[str, Any]]: One IP_DUPLICATE error per duplicate occurrence, with details
            carrying both the first and duplicate row indices
    """
    seen: dict[tuple[int, str], int] = {}
    errors: list[dict[str, Any]] = []

    for row_index, subnet_ref, ip in rows:
        if subnet_ref is None or ip is None:
            continue

        key: tuple[int, str] = (subnet_ref, ip)

        if key in seen:
            errors.append(build_error(
                InterfaceErrorCode.IP_DUPLICATE,
                f"IP {ip} is duplicated within submitted interface rows "
                f"(rows {seen[key]} and {row_index})",
                {
                    IpamValidationDetailKey.IP_ADDRESS: ip,
                    IpamValidationDetailKey.SUBNET_OBJECT_ID: subnet_ref,
                    IpamValidationDetailKey.FIRST_ROW_INDEX: seen[key],
                    IpamValidationDetailKey.DUPLICATE_ROW_INDEX: row_index,
                },
            ))
            continue

        seen[key] = row_index

    return errors


def find_subnet_without_ip(
    rows: list[tuple[int, int | None, str | None]],
) -> list[dict[str, Any]]:
    """
    Reports interface rows that have a subnet reference selected but no IP address

    A dg-ipam-interface row is considered incomplete when the user picks a subnet but leaves the
    IP field empty: such a row cannot be checked for CIDR membership, reserved addresses, or
    uniqueness, and would not contribute to any subnet's used-IP roll-up. The inverse case (IP
    without subnet) is intentionally not flagged here - that is the literal request scope, and
    a row with neither field set is treated as a still-empty placeholder row, accepted silently
    by every caller of this batch validator

    Args:
        rows (list[tuple[int, int | None, str | None]]): (row_index, subnet_ref, ip) tuples as
            produced by _extract_interface_rows in cmdb.framework.ipam.enforcement

    Returns:
        list[dict[str, Any]]: One SUBNET_WITHOUT_IP error per offending row, with details
            carrying the row index and the orphaned subnet_object_id
    """
    errors: list[dict[str, Any]] = []

    for row_index, subnet_ref, ip in rows:
        if subnet_ref is None or ip is not None:
            continue

        errors.append(build_error(
            InterfaceErrorCode.SUBNET_WITHOUT_IP,
            f"Interface row {row_index} has a subnet selected but no IP address",
            {
                IpamValidationDetailKey.ROW_INDEX: row_index,
                IpamValidationDetailKey.SUBNET_OBJECT_ID: subnet_ref,
            },
        ))

    return errors


def validate_interface_rows(
    objects_manager: ObjectsManager,
    types_manager: TypesManager,
    rows: list[tuple[int, int | None, str | None]],
    exclude_object_id: int | None = None,
) -> list[dict[str, Any]]:
    """
    Validates a batch of dg-ipam-interface rows belonging to one (in-flight) object

    Performs:
      1. Completeness check via find_subnet_without_ip so a row with a subnet picked but no IP
         is flagged before any DB call. The inverse case (IP without subnet) and entirely empty
         placeholder rows pass through silently
      2. Cross-row duplicate detection via find_intra_submission_duplicates so two rows on the
         same form sharing a (subnet, IP) pair are flagged before they hit the DB
      3. Per-row validation via validate_interface for each row that has both subnet_ref and IP
         set; the row's index is injected into every per-row error's 'details.row_index' so the
         caller can map errors back to the originating row

    This function is the single source of truth for interface-row enforcement: save-time
    enforcement and the inline pre-validation REST route both delegate to it

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        rows (list[tuple[int, int | None, str | None]]): (row_index, subnet_ref, ip) tuples
        exclude_object_id (int | None): public_id of the editing object so its own pre-edit
            row is not flagged as a collision against itself

    Returns:
        list[dict[str, Any]]: Accumulated structured errors; empty when the batch is valid
    """
    if not rows:
        return []

    errors: list[dict[str, Any]] = find_subnet_without_ip(rows)
    errors.extend(find_intra_submission_duplicates(rows))

    for row_index, subnet_ref, ip in rows:
        if subnet_ref is None or ip is None:
            continue

        row_errors: list[dict[str, Any]] = validate_interface(
            objects_manager,
            types_manager,
            subnet_object_id=subnet_ref,
            ip_address=ip,
            exclude_object_id=exclude_object_id,
            exclude_row_index=row_index,
        )

        for err in row_errors:
            err.setdefault('details', {})['row_index'] = row_index

        errors.extend(row_errors)

    return errors
