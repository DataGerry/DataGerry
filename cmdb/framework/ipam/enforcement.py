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
Server-side enforcement glue called from the CmdbObject insert/update routes

Detects whether the candidate object is an IPAM SpecialType or carries dg-ipam-interface MDS
rows, runs the appropriate validators, and returns the accumulated structured errors. The
route turns those into a 400 abort so an API client cannot bypass the validation that the
frontend pre-check routes also expose
"""
from typing import Any

from cmdb.manager import ObjectsManager, TypesManager
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.special_type_model.ipam_constants import (
    SupernetField,
    SubnetField,
    VlanField,
    InterfaceField,
    IpamSection,
    IpamValidationDetailKey,
)
from cmdb.models.object_model import (
    CmdbObjectKey,
    CmdbObjectFieldKey,
    CmdbObjectMdsKey,
    CmdbObjectMdsRowKey,
    extract_field_value,
)
from cmdb.models.type_model.type_schema_key_enum import TypeSchemaKey
from cmdb.utils import BaseStrEnum, ValidationErrorKey, build_error
from cmdb.framework.ipam.cidr import parse_cidr, parse_ip
from cmdb.framework.ipam.subnet_validator import validate_subnet
from cmdb.framework.ipam.supernet_validator import validate_supernet
from cmdb.framework.ipam.vlan_validator import validate_vlan
from cmdb.framework.ipam.interface_validator import validate_interface_rows
from cmdb.framework.ipam.references import (
    find_subnets_referencing_supernet,
    find_vlans_referencing_subnet,
    find_interfaces_referencing_subnet,
)
# -------------------------------------------------------------------------------------------------------------------- #


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  PURE HELPERS                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
def format_errors_for_abort(errors: list[dict[str, Any]]) -> str:
    """
    Joins a list of structured validation errors into a single human-readable string suitable
    for Flask's abort(400, ...)

    Args:
        errors (list[dict[str, Any]]): The accumulated validator errors

    Returns:
        str: 'IPAM validation failed: <msg1> | <msg2> | ...'
    """
    joined: str = " | ".join(
        e.get(ValidationErrorKey.MESSAGE, e.get(ValidationErrorKey.CODE, 'unknown error'))
        for e in errors
    )

    return f"IPAM validation failed: {joined}"


def _resolve_object_special_type(types_manager: TypesManager, type_id: int) -> SpecialType | None:
    """
    Returns the SpecialType of a CmdbType by id, or None if the type doesn't carry one

    Args:
        types_manager (TypesManager): db interface for CmdbTypes
        type_id (int): The CmdbType public_id

    Returns:
        SpecialType | None: The SpecialType enum value, or None when not a SpecialType
    """
    type_doc: dict[str, Any] | None = types_manager.get_type(type_id)

    if not type_doc:
        return None

    raw: Any = type_doc.get(TypeSchemaKey.SPECIAL_TYPE)

    if raw is None or not SpecialType.is_valid(raw):
        return None

    return SpecialType(raw)


def _coerce_int(value: Any) -> int | None:
    """
    Coerces a stored field value into an int when possible, else None

    Args:
        value (Any): The raw field value

    Returns:
        int | None: The integer form, or None when 'value' is None / not int-coercible
    """
    if value is None or value == '' or value == 0:
        return None

    try:
        return int(value)
    except (TypeError, ValueError):
        return None


# -------------------------------------------------------------------------------------------------------------------- #
#                                            CANONICALISATION (ON STORE)                                               #
# -------------------------------------------------------------------------------------------------------------------- #
def _canonical_cidr(value: Any) -> Any:
    """
    Returns the canonical string form of a CIDR value, or the value unchanged when it doesn't parse

    Args:
        value (Any): The raw 'dg-network-range' field value

    Returns:
        Any: str(parse_cidr(value)) when parsable, otherwise the original value untouched
    """
    parsed = parse_cidr(value) if isinstance(value, str) else None

    return str(parsed) if parsed is not None else value


def _canonical_ip(value: Any) -> Any:
    """
    Returns the canonical string form of a host-IP value, or the value unchanged when it doesn't parse

    Args:
        value (Any): The raw 'dg-interface-ip-address' field value

    Returns:
        Any: str(parse_ip(value)) when parsable, otherwise the original value untouched
    """
    parsed = parse_ip(value) if isinstance(value, str) else None

    return str(parsed) if parsed is not None else value


def _canonicalize_range_field(candidate_object: dict[str, Any], field_name: str) -> None:
    """
    Rewrites the candidate's first flat field named ``field_name`` to its canonical CIDR form, in place

    Args:
        candidate_object (dict[str, Any]): The about-to-be-saved CmdbObject document (mutated)
        field_name (str): The network-range field name to canonicalize
    """
    for field in candidate_object.get(CmdbObjectKey.FIELDS, []) or []:
        if field.get(CmdbObjectFieldKey.NAME) == field_name:
            field[CmdbObjectFieldKey.VALUE] = _canonical_cidr(field.get(CmdbObjectFieldKey.VALUE))
            return


def _canonicalize_interface_ips(candidate_object: dict[str, Any]) -> None:
    """
    Rewrites every dg-ipam-interface MDS row's IP value to its canonical form, in place

    Args:
        candidate_object (dict[str, Any]): The about-to-be-saved CmdbObject document (mutated)
    """
    for section in candidate_object.get(CmdbObjectKey.MULTI_DATA_SECTIONS, []) or []:
        if section.get(CmdbObjectMdsKey.SECTION_ID) != IpamSection.INTERFACE:
            continue

        for row in section.get(CmdbObjectMdsKey.VALUES, []) or []:
            for entry in row.get(CmdbObjectMdsRowKey.DATA, []) or []:
                if entry.get(CmdbObjectFieldKey.NAME) == InterfaceField.IP:
                    entry[CmdbObjectFieldKey.VALUE] = _canonical_ip(entry.get(CmdbObjectFieldKey.VALUE))


def _normalize_ipam_object(candidate_object: dict[str, Any], special_type: SpecialType | None) -> None:
    """
    Rewrites the candidate's IPAM address / CIDR field values to their canonical string form, in place

    Stores canonical values so that family-equivalent but textually-different inputs - notably
    IPv6 (upper/lower case, zero-compression, leading zeros) - cannot evade the exact-match
    interface-IP uniqueness check or collide in the assigned-IP map (which keys by the canonical
    string). Only values that parse are rewritten; unparsable values are left untouched for the
    validators to reject. IPv4 dotted-quad values are already canonical, so this is effectively an
    IPv6 normalisation. Runs before validation so the uniqueness / containment checks see the
    canonical form

    Args:
        candidate_object (dict[str, Any]): The about-to-be-saved CmdbObject document (mutated)
        special_type (SpecialType | None): The candidate's resolved SpecialType, or None
    """
    if special_type == SpecialType.SUPERNET:
        _canonicalize_range_field(candidate_object, SupernetField.NETWORK_RANGE)
    elif special_type == SpecialType.SUBNET:
        _canonicalize_range_field(candidate_object, SubnetField.NETWORK_RANGE)

    _canonicalize_interface_ips(candidate_object)


# -------------------------------------------------------------------------------------------------------------------- #
#                                          PER-SPECIAL-TYPE ENFORCERS                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
def _enforce_subnet_object(
    objects_manager: ObjectsManager,
    types_manager: TypesManager,
    candidate_object: dict[str, Any],
    previous_object: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """
    Runs the SUBNET-object validators against the candidate

    A CIDR change on an existing subnet is permitted even when it would push interface IPs
    outside the new range: those rows surface as is_valid=False in the subnet IP-Übersicht so
    the user can repair or unassign them after the fact, instead of the save being blocked

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        candidate_object (dict[str, Any]): The about-to-be-saved CmdbObject document
        previous_object (dict[str, Any] | None): The pre-edit document on update, else None

    Returns:
        list[dict[str, Any]]: Accumulated structured errors; empty when valid
    """
    network_range: Any = extract_field_value(candidate_object, SubnetField.NETWORK_RANGE)
    parent_supernet_id: int | None = _coerce_int(extract_field_value(candidate_object, SubnetField.PARENT_SUPERNET))
    candidate_id: int | None = _coerce_int(candidate_object.get(CmdbObjectKey.PUBLIC_ID))
    subnet_type: Any = extract_field_value(candidate_object, SubnetField.TYPE)

    return validate_subnet(
        objects_manager,
        types_manager,
        network_range=network_range if isinstance(network_range, str) else '',
        parent_supernet_id=parent_supernet_id,
        exclude_subnet_id=candidate_id if previous_object is not None else None,
        subnet_type=subnet_type if isinstance(subnet_type, str) else None,
    )


def _enforce_supernet_object(candidate_object: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Runs the SUPERNET-object validators against the candidate: canonical-CIDR and the
    'dg-supernet-type' selector matching the CIDR's address family

    A CIDR change that would push child subnets outside the new range is permitted: those
    children surface as is_valid=False in the supernet overview so the user can repair or
    detach them after the fact, instead of the save being blocked

    Args:
        candidate_object (dict[str, Any]): The about-to-be-saved CmdbObject document

    Returns:
        list[dict[str, Any]]: Accumulated structured errors; empty when valid
    """
    network_range: Any = extract_field_value(candidate_object, SupernetField.NETWORK_RANGE)
    supernet_type: Any = extract_field_value(candidate_object, SupernetField.TYPE)

    return validate_supernet(
        network_range=network_range if isinstance(network_range, str) else '',
        supernet_type=supernet_type if isinstance(supernet_type, str) else None,
    )


def _enforce_vlan_object(
    objects_manager: ObjectsManager,
    types_manager: TypesManager,
    candidate_object: dict[str, Any],
) -> list[dict[str, Any]]:
    """
    Runs the VLAN-object validator against the candidate

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        candidate_object (dict[str, Any]): The about-to-be-saved CmdbObject document

    Returns:
        list[dict[str, Any]]: Accumulated structured errors; empty when valid
    """
    subnet_id: int | None = _coerce_int(extract_field_value(candidate_object, VlanField.SUBNET_REF))

    if subnet_id is None:
        return []

    return validate_vlan(objects_manager, types_manager, subnet_id)


# -------------------------------------------------------------------------------------------------------------------- #
#                                          INTERFACE ROW ENFORCEMENT                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
def _extract_interface_rows(
    candidate_object: dict[str, Any],
) -> list[tuple[int, int | None, str | None, str | None]]:
    """
    Walks the candidate's dg-ipam-interface MDS rows and returns one tuple per row

    The interface-type token ('dg-interface-type') is passed through as-is when it is a
    non-empty string and None otherwise; legacy rows without the selector therefore skip the
    type-family consistency check downstream

    Args:
        candidate_object (dict[str, Any]): The about-to-be-saved CmdbObject document

    Returns:
        list[tuple[int, int | None, str | None, str | None]]: (row_index, subnet_ref,
            ip_address, interface_type) tuples
    """
    rows_out: list[tuple[int, int | None, str | None, str | None]] = []

    for section in candidate_object.get(CmdbObjectKey.MULTI_DATA_SECTIONS, []) or []:
        if section.get(CmdbObjectMdsKey.SECTION_ID) != IpamSection.INTERFACE:
            continue

        for row_index, row in enumerate(section.get(CmdbObjectMdsKey.VALUES, []) or []):
            subnet_ref: int | None = None
            ip_address: str | None = None
            interface_type: str | None = None

            for entry in row.get(CmdbObjectMdsRowKey.DATA, []) or []:
                name: Any = entry.get(CmdbObjectFieldKey.NAME)
                value: Any = entry.get(CmdbObjectFieldKey.VALUE)

                if name == InterfaceField.SUBNET:
                    subnet_ref = _coerce_int(value)
                elif name == InterfaceField.IP:
                    ip_address = value if isinstance(value, str) and value else None
                elif name == InterfaceField.TYPE:
                    interface_type = value if isinstance(value, str) and value else None

            rows_out.append((row_index, subnet_ref, ip_address, interface_type))

    return rows_out


def _enforce_interface_rows(
    objects_manager: ObjectsManager,
    types_manager: TypesManager,
    candidate_object: dict[str, Any],
    previous_object: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """
    Validates each dg-ipam-interface row on the candidate object via the shared batch
    validator (cross-row duplicate detection plus per-row DB checks)

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        candidate_object (dict[str, Any]): The about-to-be-saved CmdbObject document
        previous_object (dict[str, Any] | None): The pre-edit document on update, else None

    Returns:
        list[dict[str, Any]]: Accumulated structured errors; empty when all rows are valid
    """
    rows: list[tuple[int, int | None, str | None, str | None]] = _extract_interface_rows(candidate_object)

    if not rows:
        return []

    exclude_object_id: int | None = (
        _coerce_int(candidate_object.get(CmdbObjectKey.PUBLIC_ID)) if previous_object is not None else None
    )

    return validate_interface_rows(objects_manager, types_manager, rows, exclude_object_id)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  ORCHESTRATOR                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
def enforce_object_invariants(
    objects_manager: ObjectsManager,
    types_manager: TypesManager,
    candidate_object: dict[str, Any],
    previous_object: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """
    Runs every IPAM validator that applies to the candidate CmdbObject and returns the merged
    structured error list

    Dispatches by the candidate type's SpecialType (SUPERNET / SUBNET / VLAN) and additionally
    validates dg-ipam-interface MDS rows on any object that carries them. Caller is expected to
    abort 400 with format_errors_for_abort(errors) when the returned list is non-empty

    Before validating, the candidate's IPAM address / CIDR field values are canonicalised in
    place (see _normalize_ipam_object), so the persisted object - which both routes save from the
    same dict passed here - always stores canonical (notably IPv6-canonical) values

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        candidate_object (dict[str, Any]): The about-to-be-saved CmdbObject document
        previous_object (dict[str, Any] | None): The pre-edit document for updates; None on insert

    Returns:
        list[dict[str, Any]]: Accumulated structured errors; empty when the candidate is valid
    """
    type_id: Any = candidate_object.get(CmdbObjectKey.TYPE_ID)

    if not isinstance(type_id, int):
        return []

    errors: list[dict[str, Any]] = []

    special_type: SpecialType | None = _resolve_object_special_type(types_manager, type_id)

    _normalize_ipam_object(candidate_object, special_type)

    if special_type == SpecialType.SUPERNET:
        errors.extend(_enforce_supernet_object(candidate_object))
    elif special_type == SpecialType.SUBNET:
        errors.extend(_enforce_subnet_object(objects_manager, types_manager, candidate_object, previous_object))
    elif special_type == SpecialType.VLAN:
        errors.extend(_enforce_vlan_object(objects_manager, types_manager, candidate_object))

    errors.extend(_enforce_interface_rows(objects_manager, types_manager, candidate_object, previous_object))

    return errors


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  DELETE GUARDS                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
class DeleteGuardErrorCode(BaseStrEnum):
    """Stable codes for IPAM deletion-guard errors"""
    SUPERNET_HAS_REFERENCING_SUBNETS = 'supernet_has_referencing_subnets'
    SUBNET_HAS_REFERENCING_VLANS = 'subnet_has_referencing_vlans'
    SUBNET_HAS_REFERENCING_INTERFACES = 'subnet_has_referencing_interfaces'


def _format_id_list(refs: list[dict[str, Any]]) -> str:
    """
    Joins reference dicts into a short comma-separated id list for error messages

    Args:
        refs (list[dict[str, Any]]): Lightweight reference dicts with 'public_id'

    Returns:
        str: 'id, id, id'
    """
    return ", ".join(str(r.get(CmdbObjectKey.PUBLIC_ID)) for r in refs)


def _build_delete_guard_error(code: str, message: str, refs: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Constructs a structured deletion-guard error including the offending reference list

    Args:
        code (str): Stable machine-readable error code
        message (str): Human-readable explanation
        refs (list[dict[str, Any]]): The lightweight reference dicts that block the delete

    Returns:
        dict[str, Any]: The error dict with 'code', 'message', and 'details.references'
    """
    return build_error(code, message, {IpamValidationDetailKey.REFERENCES: refs})


def enforce_delete_guards(
    objects_manager: ObjectsManager,
    types_manager: TypesManager,
    target_object: dict[str, Any],
) -> list[dict[str, Any]]:
    """
    Returns errors when deleting the given CmdbObject would orphan IPAM references

    SUPERNET: refuse if any subnet references it. SUBNET: refuse if any child subnet, vlan or
    interface row references it. VLAN: no IPAM references point at it, so deletion is allowed.
    Non-IPAM objects pass through unaffected

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        target_object (dict[str, Any]): The CmdbObject document being deleted

    Returns:
        list[dict[str, Any]]: Structured guard errors; empty when deletion is allowed
    """
    type_id: Any = target_object.get(CmdbObjectKey.TYPE_ID)
    object_id: Any = target_object.get(CmdbObjectKey.PUBLIC_ID)

    if not isinstance(type_id, int) or not isinstance(object_id, int):
        return []

    special_type: SpecialType | None = _resolve_object_special_type(types_manager, type_id)

    if special_type == SpecialType.SUPERNET:
        return _guard_supernet_delete(objects_manager, types_manager, object_id)

    if special_type == SpecialType.SUBNET:
        return _guard_subnet_delete(objects_manager, types_manager, object_id)

    return []


def _guard_supernet_delete(
    objects_manager: ObjectsManager,
    types_manager: TypesManager,
    supernet_object_id: int,
) -> list[dict[str, Any]]:
    """
    Returns a guard error when at least one subnet references the supernet

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        supernet_object_id (int): public_id of the supernet being deleted

    Returns:
        list[dict[str, Any]]: Single-element list with the guard error, else []
    """
    refs: list[dict[str, Any]] = find_subnets_referencing_supernet(
        objects_manager, types_manager, supernet_object_id,
    )

    if not refs:
        return []

    return [_build_delete_guard_error(
        DeleteGuardErrorCode.SUPERNET_HAS_REFERENCING_SUBNETS,
        f"Supernet is referenced by subnets: {_format_id_list(refs)}",
        refs,
    )]


def _guard_subnet_delete(
    objects_manager: ObjectsManager,
    types_manager: TypesManager,
    subnet_object_id: int,
) -> list[dict[str, Any]]:
    """
    Returns guard errors per kind of remaining reference to the subnet

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        subnet_object_id (int): public_id of the subnet being deleted

    Returns:
        list[dict[str, Any]]: One error per blocking reference category
    """
    errors: list[dict[str, Any]] = []

    vlans: list[dict[str, Any]] = find_vlans_referencing_subnet(
        objects_manager, types_manager, subnet_object_id,
    )

    if vlans:
        errors.append(_build_delete_guard_error(
            DeleteGuardErrorCode.SUBNET_HAS_REFERENCING_VLANS,
            f"Subnet is referenced by vlans: {_format_id_list(vlans)}",
            vlans,
        ))

    interfaces: list[dict[str, Any]] = find_interfaces_referencing_subnet(objects_manager, subnet_object_id)

    if interfaces:
        errors.append(_build_delete_guard_error(
            DeleteGuardErrorCode.SUBNET_HAS_REFERENCING_INTERFACES,
            f"Subnet is referenced by interface rows on objects: {_format_id_list(interfaces)}",
            interfaces,
        ))

    return errors
