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

Confirms the referenced subnet exists and has SpecialType SUBNET, the IP parses as IPv4 or
IPv6 and sits inside the subnet (and is neither the network nor the broadcast address), and
the IP is not already in use by another interface row anywhere in the system that references
the same subnet
"""
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
from cmdb.utils import BaseStrEnum, ValidationErrorKey, build_error
from cmdb.framework.ipam.cidr import (
    Network,
    Address,
    address_family,
    network_family,
    parse_cidr,
    parse_ip,
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
    TYPE_MISSING = 'type_missing'
    TYPE_FAMILY_MISMATCH = 'type_family_mismatch'


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


def _extract_subnet_network(subnet_obj: dict[str, Any]) -> tuple[Network | None, list[dict[str, Any]]]:
    """
    Reads and parses the 'dg-network-range' field of a subnet object

    Args:
        subnet_obj (dict[str, Any]): The subnet CmdbObject document

    Returns:
        tuple[Network | None, list[dict[str, Any]]]: (parsed network or None, errors)
    """
    raw: Any = extract_field_value(subnet_obj, SubnetField.NETWORK_RANGE)
    parsed: Network | None = parse_cidr(raw) if isinstance(raw, str) else None

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
def _check_ip_format(ip_address: str) -> tuple[Address | None, list[dict[str, Any]]]:
    """
    Validates that the candidate IP parses as IPv4 or IPv6

    Args:
        ip_address (str): The candidate IP address string

    Returns:
        tuple[Address | None, list[dict[str, Any]]]: (parsed address or None, errors)
    """
    parsed: Address | None = parse_ip(ip_address)

    if parsed is None:
        return None, [build_error(
            InterfaceErrorCode.IP_INVALID,
            f"'{ip_address}' is not a valid IPv4/IPv6 address",
            {IpamValidationDetailKey.IP_ADDRESS: ip_address},
        )]

    return parsed, []


def _check_ip_membership(ip: Address, subnet_net: Network) -> list[dict[str, Any]]:
    """
    Validates that the IP sits inside the subnet and is neither the network nor broadcast address

    Args:
        ip (Address): The parsed candidate IP (IPv4 or IPv6)
        subnet_net (Network): The subnet's parsed network (IPv4 or IPv6)

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


def _find_uniqueness_candidates(
    objects_manager: ObjectsManager,
    pairs: list[tuple[int, str]],
) -> list[dict[str, Any]]:
    """
    Loads every CmdbObject that could collide with ANY of the given (subnet_ref, IP) pairs

    One query for the whole batch: a document qualifies when at least one of its
    dg-ipam-interface rows carries a subnet ref from the pair set AND an IP from the pair
    set. That is a superset of the true per-pair collisions (a row matching subnet A and the
    IP of pair B also qualifies) - ``_collect_collision_errors`` filters down to exact
    (subnet, IP) row matches per pair, so the over-fetch never produces a false error

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        pairs (list[tuple[int, str]]): The (subnet_ref, ip_address) pairs of the submission's
            complete rows

    Returns:
        list[dict[str, Any]]: Candidate CmdbObject documents; empty when no pair was given
    """
    if not pairs:
        return []

    subnet_ids: list[int] = sorted({subnet_ref for subnet_ref, _ in pairs})
    ip_addresses: list[str] = sorted({ip for _, ip in pairs})

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
                                    CmdbObjectFieldKey.VALUE: {'$in': subnet_ids},
                                }},
                                {'$elemMatch': {
                                    CmdbObjectFieldKey.NAME: InterfaceField.IP,
                                    CmdbObjectFieldKey.VALUE: {'$in': ip_addresses},
                                }},
                            ],
                        },
                    },
                },
            },
        },
    }

    return objects_manager.find_objects(criteria, as_dict=True)


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
    rows: list[tuple[int, int | None, str | None, str | None]],
) -> list[dict[str, Any]]:
    """
    Reports interface rows in the same submission that share both subnet ref and IP

    Rows missing either the subnet ref or the IP are skipped (treated as incomplete, surfaced
    by the per-row check instead); the row's interface-type token plays no role here. The
    first occurrence of a (subnet_ref, ip) pair seeds the seen-set; every subsequent matching
    row is reported as a duplicate against that first row

    Args:
        rows (list[tuple[int, int | None, str | None, str | None]]): (row_index, subnet_ref,
            ip, interface_type) tuples

    Returns:
        list[dict[str, Any]]: One IP_DUPLICATE error per duplicate occurrence, with details
            carrying both the first and duplicate row indices
    """
    seen: dict[tuple[int, str], int] = {}
    errors: list[dict[str, Any]] = []

    for row_index, subnet_ref, ip, _ in rows:
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
    rows: list[tuple[int, int | None, str | None, str | None]],
) -> list[dict[str, Any]]:
    """
    Reports interface rows that have a subnet reference selected but no IP address

    A dg-ipam-interface row is considered incomplete when the user picks a subnet but leaves the
    IP field empty: such a row cannot be checked for CIDR membership, reserved addresses, or
    uniqueness, and would not contribute to any subnet's used-IP roll-up. The inverse case (IP
    without subnet) is intentionally not flagged here - that is the literal request scope, and
    a row with neither field set is treated as a still-empty placeholder row, accepted silently
    by every caller of this batch validator. The row's interface-type token plays no role here

    Args:
        rows (list[tuple[int, int | None, str | None, str | None]]): (row_index, subnet_ref,
            ip, interface_type) tuples as produced by _extract_interface_rows in
            cmdb.framework.ipam.enforcement

    Returns:
        list[dict[str, Any]]: One SUBNET_WITHOUT_IP error per offending row, with details
            carrying the row index and the orphaned subnet_object_id
    """
    errors: list[dict[str, Any]] = []

    for row_index, subnet_ref, ip, _ in rows:
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


def _load_subnets_by_ids(
    objects_manager: ObjectsManager,
    types_manager: TypesManager,
    subnet_ids: list[int],
) -> dict[int, dict[str, Any]]:
    """
    Loads the SUBNET CmdbObjects for the given public_ids in one query, keyed by public_id

    Ids that match no SUBNET object are simply absent from the result - the per-row check
    (``_load_subnet_object``) is responsible for reporting unknown subnet references, so this
    batch loader stays silent about them. Returns an empty dict when no SUBNET CmdbType is
    defined or the id list is empty

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        subnet_ids (list[int]): public_ids of the referenced subnets (deduplicated by caller)

    Returns:
        dict[int, dict[str, Any]]: {public_id: subnet document} for every id that resolved
    """
    if not subnet_ids:
        return {}

    subnet_type_id: int | None = resolve_special_type_id(types_manager, SpecialType.SUBNET)

    if subnet_type_id is None:
        return {}

    matches: list[dict[str, Any]] = objects_manager.find_objects(
        {CmdbObjectKey.PUBLIC_ID: {'$in': subnet_ids}, CmdbObjectKey.TYPE_ID: subnet_type_id},
        as_dict=True,
    )

    return {m[CmdbObjectKey.PUBLIC_ID]: m for m in matches if CmdbObjectKey.PUBLIC_ID in m}


def _check_row_type_against_ip(row_index: int, interface_type: str, ip_address: str) -> list[dict[str, Any]]:
    """
    Validates the row's interface-type token agrees with the address family of the row's IP

    Skipped (no error) when the IP does not parse - an unparsable IP is reported as IP_INVALID
    by the per-row check when the row is complete, and a half-typed IP should not produce
    family noise on top. An unrecognised token (anything but the IpAddressFamily values) can
    never equal the parsed family, so it is reported as a mismatch

    Args:
        row_index (int): Position of the row in the MDS section, echoed in the error details
        interface_type (str): The row's 'dg-interface-type' token
        ip_address (str): The row's IP address string

    Returns:
        list[dict[str, Any]]: A single-element error list on mismatch, empty when consistent
            or when the IP is unparsable
    """
    parsed: Address | None = parse_ip(ip_address)

    if parsed is None:
        return []

    ip_family: str = address_family(parsed)

    if interface_type == ip_family:
        return []

    return [build_error(
        InterfaceErrorCode.TYPE_FAMILY_MISMATCH,
        f"Interface row {row_index}: type '{interface_type}' does not match the address family "
        f"'{ip_family}' of IP {ip_address}",
        {
            IpamValidationDetailKey.ROW_INDEX: row_index,
            IpamValidationDetailKey.INTERFACE_TYPE: interface_type,
            IpamValidationDetailKey.IP_ADDRESS: ip_address,
            IpamValidationDetailKey.IP_FAMILY: ip_family,
        },
    )]


def _check_row_type_against_subnet(
    row_index: int,
    interface_type: str,
    subnet_obj: dict[str, Any],
) -> list[dict[str, Any]]:
    """
    Validates the row's interface-type token agrees with the referenced subnet's CIDR family

    Skipped (no error) when the subnet's 'dg-network-range' is missing or unparsable - that
    degenerate state is reported as SUBNET_BROKEN_STATE by the per-row check when the row is
    complete. An unrecognised token can never equal the parsed family, so it is reported as a
    mismatch

    Args:
        row_index (int): Position of the row in the MDS section, echoed in the error details
        interface_type (str): The row's 'dg-interface-type' token
        subnet_obj (dict[str, Any]): The referenced SUBNET CmdbObject document

    Returns:
        list[dict[str, Any]]: A single-element error list on mismatch, empty when consistent
            or when the subnet's CIDR is unparsable
    """
    raw_range: Any = extract_field_value(subnet_obj, SubnetField.NETWORK_RANGE)
    network: Network | None = parse_cidr(raw_range) if isinstance(raw_range, str) else None

    if network is None:
        return []

    subnet_fam: str = network_family(network)

    if interface_type == subnet_fam:
        return []

    return [build_error(
        InterfaceErrorCode.TYPE_FAMILY_MISMATCH,
        f"Interface row {row_index}: type '{interface_type}' does not match the address family "
        f"'{subnet_fam}' of subnet {network} (object {subnet_obj.get(CmdbObjectKey.PUBLIC_ID)})",
        {
            IpamValidationDetailKey.ROW_INDEX: row_index,
            IpamValidationDetailKey.INTERFACE_TYPE: interface_type,
            IpamValidationDetailKey.SUBNET_OBJECT_ID: subnet_obj.get(CmdbObjectKey.PUBLIC_ID),
            IpamValidationDetailKey.SUBNET_RANGE: str(network),
            IpamValidationDetailKey.SUBNET_FAMILY: subnet_fam,
        },
    )]


def find_type_family_mismatches(
    objects_manager: ObjectsManager,
    types_manager: TypesManager,
    rows: list[tuple[int, int | None, str | None, str | None]],
    subnets_by_id: dict[int, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """
    Reports interface rows whose 'dg-interface-type' token contradicts the row's data

    For every row carrying a type token, the token is checked against the address family of
    the row's IP (when an IP is present) and against the CIDR family of the referenced subnet
    (when a subnet ref is present), so a token can produce up to two mismatch errors per row.
    Rows without a token are skipped here - their absence is reported as TYPE_MISSING by
    ``find_missing_types`` when the row carries data. Unknown subnet refs, unparsable IPs and
    unparsable subnet CIDRs are skipped here because the per-row check reports those states
    under their own codes

    The referenced subnets of all typed rows are loaded in one batch query when the caller
    does not supply ``subnets_by_id``, so the check adds at most one DB round-trip
    regardless of row count; the batch orchestrator passes its already-loaded map so the
    whole submission shares a single subnet load

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        rows (list[tuple[int, int | None, str | None, str | None]]): (row_index, subnet_ref,
            ip, interface_type) tuples
        subnets_by_id (dict[int, dict[str, Any]] | None): Pre-loaded {public_id: subnet doc}
            map covering the rows' subnet refs; None loads the referenced subnets here

    Returns:
        list[dict[str, Any]]: One TYPE_FAMILY_MISMATCH error per contradiction found
    """
    typed_rows: list[tuple[int, int | None, str | None, str]] = [
        (row_index, subnet_ref, ip, interface_type)
        for row_index, subnet_ref, ip, interface_type in rows
        if interface_type is not None
    ]

    if not typed_rows:
        return []

    if subnets_by_id is None:
        subnet_ids: list[int] = sorted({
            subnet_ref for _, subnet_ref, _, _ in typed_rows if subnet_ref is not None
        })
        subnets_by_id = _load_subnets_by_ids(objects_manager, types_manager, subnet_ids)

    errors: list[dict[str, Any]] = []

    for row_index, subnet_ref, ip, interface_type in typed_rows:
        if ip is not None:
            errors.extend(_check_row_type_against_ip(row_index, interface_type, ip))

        if subnet_ref is not None and subnet_ref in subnets_by_id:
            errors.extend(_check_row_type_against_subnet(row_index, interface_type, subnets_by_id[subnet_ref]))

    return errors


def find_missing_types(
    rows: list[tuple[int, int | None, str | None, str | None]],
) -> list[dict[str, Any]]:
    """
    Reports interface rows that carry data but no 'dg-interface-type' token

    The type selector is required on every row that holds a subnet reference and/or an IP -
    the field is a required SELECT in the dg-ipam-interface template and the family drives the
    subnet picker, so a data-carrying row without it must be repaired on its next save (the
    stored-data backfill is part of the planned baseline migration). Completely empty
    placeholder rows stay silent, consistent with the completeness policy of
    ``find_subnet_without_ip``. Token validity is not judged here - an unrecognised token is
    surfaced by ``find_type_family_mismatches`` against the row's actual data

    Args:
        rows (list[tuple[int, int | None, str | None, str | None]]): (row_index, subnet_ref,
            ip, interface_type) tuples

    Returns:
        list[dict[str, Any]]: One TYPE_MISSING error per data-carrying row without a token,
            with details carrying the row index
    """
    errors: list[dict[str, Any]] = []

    for row_index, subnet_ref, ip, interface_type in rows:
        if interface_type is not None:
            continue

        if subnet_ref is None and ip is None:
            continue

        errors.append(build_error(
            InterfaceErrorCode.TYPE_MISSING,
            f"Interface row {row_index}: type ('{InterfaceField.TYPE.value}') is required",
            {IpamValidationDetailKey.ROW_INDEX: row_index},
        ))

    return errors


def validate_interface_rows(
    objects_manager: ObjectsManager,
    types_manager: TypesManager,
    rows: list[tuple[int, int | None, str | None, str | None]],
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
      3. Required-type check via find_missing_types so a data-carrying row without a
         'dg-interface-type' token is flagged; empty placeholder rows stay silent
      4. Type-family consistency via find_type_family_mismatches so a row whose
         'dg-interface-type' token contradicts its IP's family or its subnet's CIDR family is
         flagged
      5. Per-row validation (subnet existence, broken-range, IP format, membership,
         uniqueness) for each row that has both subnet_ref and IP set; the row's index is
         injected into every per-row error's 'details.row_index' so the caller can map errors
         back to the originating row

    The DB work is batched across the whole submission: ONE subnet load covers the
    type-family check and every per-row subnet lookup, and ONE uniqueness-candidate query
    covers every (subnet, IP) pair - the per-row error semantics are identical to running
    ``validate_interface`` row by row, without the per-row round-trips

    This function is the single source of truth for interface-row enforcement: save-time
    enforcement and the inline pre-validation REST route both delegate to it

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        rows (list[tuple[int, int | None, str | None, str | None]]): (row_index, subnet_ref,
            ip, interface_type) tuples
        exclude_object_id (int | None): public_id of the editing object so its own pre-edit
            row is not flagged as a collision against itself

    Returns:
        list[dict[str, Any]]: Accumulated structured errors; empty when the batch is valid
    """
    if not rows:
        return []

    errors: list[dict[str, Any]] = find_subnet_without_ip(rows)
    errors.extend(find_intra_submission_duplicates(rows))
    errors.extend(find_missing_types(rows))

    subnet_type_id: int | None = resolve_special_type_id(types_manager, SpecialType.SUBNET)
    referenced_ids: list[int] = sorted({
        subnet_ref for _, subnet_ref, _, _ in rows if subnet_ref is not None
    })
    subnets_by_id: dict[int, dict[str, Any]] = _load_subnets_by_ids(
        objects_manager, types_manager, referenced_ids,
    )

    errors.extend(find_type_family_mismatches(objects_manager, types_manager, rows, subnets_by_id))

    complete_rows: list[tuple[int, int, str]] = [
        (row_index, subnet_ref, ip)
        for row_index, subnet_ref, ip, _ in rows
        if subnet_ref is not None and ip is not None
    ]

    if not complete_rows:
        return errors

    candidates: list[dict[str, Any]] = _find_uniqueness_candidates(
        objects_manager,
        sorted({(subnet_ref, ip) for _, subnet_ref, ip in complete_rows}),
    )

    for row_index, subnet_ref, ip in complete_rows:
        row_errors: list[dict[str, Any]] = _validate_complete_row(
            subnet_type_id,
            subnets_by_id,
            candidates,
            subnet_ref,
            ip,
            exclude_object_id,
            row_index,
        )

        for err in row_errors:
            err.setdefault(ValidationErrorKey.DETAILS, {})[IpamValidationDetailKey.ROW_INDEX] = row_index

        errors.extend(row_errors)

    return errors


def _validate_complete_row(
    subnet_type_id: int | None,
    subnets_by_id: dict[int, dict[str, Any]],
    candidates: list[dict[str, Any]],
    subnet_ref: int,
    ip: str,
    exclude_object_id: int | None,
    row_index: int,
) -> list[dict[str, Any]]:
    """
    Runs the per-row checks of one complete (subnet_ref + IP) row against pre-batched data

    Mirrors ``validate_interface`` exactly, answered from the batch context instead of
    per-row queries: a missing SUBNET CmdbType or an unknown subnet ref short-circuits with
    its own error (no IP checks run, matching the single-row path); otherwise the broken-
    range, IP-format, membership and uniqueness checks accumulate

    Args:
        subnet_type_id (int | None): Resolved SUBNET CmdbType id, or None when undefined
        subnets_by_id (dict[int, dict[str, Any]]): Batch-loaded {public_id: subnet doc} map
        candidates (list[dict[str, Any]]): Batch-loaded uniqueness candidates (see
            ``_find_uniqueness_candidates``)
        subnet_ref (int): The row's referenced subnet public_id
        ip (str): The row's IP address string
        exclude_object_id (int | None): public_id of the editing object for the (object, row)
            collision exclusion
        row_index (int): Position of the row in its MDS section (used for the exclusion pair)

    Returns:
        list[dict[str, Any]]: Structured errors for this row; empty when the row is valid
    """
    if subnet_type_id is None:
        return [build_error(
            InterfaceErrorCode.SUBNET_TYPE_MISSING,
            "No SUBNET CmdbType is defined; cannot validate interface subnet reference",
        )]

    subnet_obj: dict[str, Any] | None = subnets_by_id.get(subnet_ref)

    if subnet_obj is None:
        return [build_error(
            InterfaceErrorCode.SUBNET_NOT_FOUND,
            f"Subnet object with id {subnet_ref} does not exist",
            {IpamValidationDetailKey.SUBNET_OBJECT_ID: subnet_ref},
        )]

    subnet_net, errors = _extract_subnet_network(subnet_obj)

    parsed_ip, ip_errors = _check_ip_format(ip)
    errors.extend(ip_errors)

    if subnet_net is not None and parsed_ip is not None:
        errors.extend(_check_ip_membership(parsed_ip, subnet_net))

    if parsed_ip is not None:
        errors.extend(_collect_collision_errors(
            candidates, subnet_ref, ip, exclude_object_id, row_index,
        ))

    return errors
