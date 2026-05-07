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
Validator for SUBNET CmdbObjects

Surfaces canonical-CIDR, parent-existence, containment, sibling-overlap and parent-chain-cycle
errors. Each check is decomposed into a small helper to remain unit-testable
"""
from ipaddress import IPv4Network
from typing import Any

from cmdb.manager import ObjectsManager, TypesManager
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.special_type_model.ipam_constants import SubnetField, SupernetField
from cmdb.framework.ipam.cidr import parse_cidr, contains, overlaps
from cmdb.framework.ipam.references import resolve_special_type_id
# -------------------------------------------------------------------------------------------------------------------- #


MAX_PARENT_CHAIN_DEPTH: int = 64


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  ERROR CODES                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class SubnetErrorCode:
    """Stable codes for structured subnet validation errors"""
    CIDR_INVALID = 'cidr_invalid'
    PARENT_SUPERNET_TYPE_MISSING = 'parent_supernet_type_missing'
    PARENT_SUPERNET_NOT_FOUND = 'parent_supernet_not_found'
    PARENT_SUPERNET_BROKEN_STATE = 'parent_supernet_broken_state'
    NOT_IN_PARENT_SUPERNET = 'not_in_parent_supernet'
    PARENT_SUBNET_TYPE_MISSING = 'parent_subnet_type_missing'
    PARENT_SUBNET_NOT_FOUND = 'parent_subnet_not_found'
    PARENT_SUBNET_BROKEN_STATE = 'parent_subnet_broken_state'
    NOT_IN_PARENT_SUBNET = 'not_in_parent_subnet'
    PARENT_CHAIN_CYCLE = 'parent_chain_cycle'
    SIBLING_OVERLAP = 'sibling_overlap'


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  PURE HELPERS                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
def extract_field_value(obj_dict: dict[str, Any], field_name: str) -> Any:
    """
    Returns the 'value' of the first entry in obj_dict['fields'] whose 'name' matches

    Args:
        obj_dict (dict[str, Any]): A CmdbObject document loaded from the DB
        field_name (str): The field name to look up

    Returns:
        Any: The field's 'value', or None if no matching field exists
    """
    for field in obj_dict.get('fields', []) or []:
        if field.get('name') == field_name:
            return field.get('value')

    return None


def build_error(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    """
    Constructs a structured validation error dict

    Args:
        code (str): A stable machine-readable error code
        message (str): A human-readable explanation
        details (dict[str, Any] | None): Optional context fields the frontend can render

    Returns:
        dict[str, Any]: The error dict with keys 'code', 'message', and 'details' (always present)
    """
    return {'code': code, 'message': message, 'details': details or {}}


# -------------------------------------------------------------------------------------------------------------------- #
#                                                 OBJECT LOADERS                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
def _load_object_by_id(objects_manager: ObjectsManager, object_id: int) -> dict[str, Any] | None:
    """
    Loads a single CmdbObject as a dict by its public_id

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        object_id (int): The CmdbObject public_id

    Returns:
        dict[str, Any] | None: The CmdbObject document, or None if not found
    """
    matches: list[dict[str, Any]] = objects_manager.find_objects({'public_id': object_id}, as_dict=True)

    return matches[0] if matches else None


def _find_subnets_by_field(
    objects_manager: ObjectsManager,
    subnet_type_id: int,
    field_name: str,
    field_value: Any,
) -> list[dict[str, Any]]:
    """
    Returns full subnet CmdbObject documents whose 'fields' array contains a matching entry

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        subnet_type_id (int): public_id of the SUBNET CmdbType
        field_name (str): The field 'name' to match
        field_value (Any): The field 'value' to match

    Returns:
        list[dict[str, Any]]: Full subnet documents (not stripped) — needed for sibling overlap
    """
    criteria: dict[str, Any] = {
        'type_id': subnet_type_id,
        'fields': {
            '$elemMatch': {
                'name': field_name,
                'value': field_value,
            },
        },
    }

    return objects_manager.find_objects(criteria, as_dict=True)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                INDIVIDUAL CHECKS                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
def _check_canonical_cidr(network_range: str) -> tuple[IPv4Network | None, list[dict[str, Any]]]:
    """
    Validates the candidate CIDR is a strict (canonical) IPv4 CIDR

    Args:
        network_range (str): The candidate CIDR

    Returns:
        tuple[IPv4Network | None, list[dict[str, Any]]]: (parsed network or None, list of errors)
    """
    parsed: IPv4Network | None = parse_cidr(network_range)

    if parsed is None:
        return None, [build_error(
            SubnetErrorCode.CIDR_INVALID,
            f"'{network_range}' is not a canonical IPv4 CIDR (host bits must be zero)",
            {'network_range': network_range},
        )]

    return parsed, []


def _check_in_supernet(
    objects_manager: ObjectsManager,
    types_manager: TypesManager,
    candidate: IPv4Network,
    supernet_object_id: int,
) -> list[dict[str, Any]]:
    """
    Validates the candidate is a subnet of the referenced SUPERNET object's network range

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        candidate (IPv4Network): The parsed candidate CIDR
        supernet_object_id (int): public_id of the referenced SUPERNET CmdbObject

    Returns:
        list[dict[str, Any]]: Validation errors found, empty when containment holds
    """
    supernet_type_id: int | None = resolve_special_type_id(types_manager, SpecialType.SUPERNET)

    if supernet_type_id is None:
        return [build_error(
            SubnetErrorCode.PARENT_SUPERNET_TYPE_MISSING,
            "No SUPERNET CmdbType is defined; cannot validate parent supernet",
        )]

    supernet_obj: dict[str, Any] | None = _load_object_by_id(objects_manager, supernet_object_id)

    if not supernet_obj or supernet_obj.get('type_id') != supernet_type_id:
        return [build_error(
            SubnetErrorCode.PARENT_SUPERNET_NOT_FOUND,
            f"Supernet object with id {supernet_object_id} does not exist",
            {'supernet_object_id': supernet_object_id},
        )]

    supernet_range_raw: Any = extract_field_value(supernet_obj, SupernetField.NETWORK_RANGE)
    supernet_net: IPv4Network | None = parse_cidr(supernet_range_raw) if isinstance(supernet_range_raw, str) else None

    if supernet_net is None:
        return [build_error(
            SubnetErrorCode.PARENT_SUPERNET_BROKEN_STATE,
            f"Supernet object {supernet_object_id} has no valid '{SupernetField.NETWORK_RANGE.value}' value",
            {'supernet_object_id': supernet_object_id, 'stored_value': supernet_range_raw},
        )]

    if not contains(supernet_net, candidate):
        return [build_error(
            SubnetErrorCode.NOT_IN_PARENT_SUPERNET,
            f"Candidate {candidate} is not contained in supernet {supernet_net}",
            {
                'candidate': str(candidate),
                'supernet_object_id': supernet_object_id,
                'supernet_range': str(supernet_net),
            },
        )]

    return []


def _check_in_parent_subnet(
    objects_manager: ObjectsManager,
    types_manager: TypesManager,
    candidate: IPv4Network,
    parent_subnet_object_id: int,
) -> list[dict[str, Any]]:
    """
    Validates the candidate is a subnet of the referenced parent subnet's network range

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        candidate (IPv4Network): The parsed candidate CIDR
        parent_subnet_object_id (int): public_id of the referenced parent SUBNET CmdbObject

    Returns:
        list[dict[str, Any]]: Validation errors found, empty when containment holds
    """
    subnet_type_id: int | None = resolve_special_type_id(types_manager, SpecialType.SUBNET)

    if subnet_type_id is None:
        return [build_error(
            SubnetErrorCode.PARENT_SUBNET_TYPE_MISSING,
            "No SUBNET CmdbType is defined; cannot validate parent subnet",
        )]

    parent_obj: dict[str, Any] | None = _load_object_by_id(objects_manager, parent_subnet_object_id)

    if not parent_obj or parent_obj.get('type_id') != subnet_type_id:
        return [build_error(
            SubnetErrorCode.PARENT_SUBNET_NOT_FOUND,
            f"Parent subnet object with id {parent_subnet_object_id} does not exist",
            {'parent_subnet_object_id': parent_subnet_object_id},
        )]

    parent_range_raw: Any = extract_field_value(parent_obj, SubnetField.NETWORK_RANGE)
    parent_net: IPv4Network | None = parse_cidr(parent_range_raw) if isinstance(parent_range_raw, str) else None

    if parent_net is None:
        return [build_error(
            SubnetErrorCode.PARENT_SUBNET_BROKEN_STATE,
            f"Parent subnet object {parent_subnet_object_id} has no valid '{SubnetField.NETWORK_RANGE.value}' value",
            {'parent_subnet_object_id': parent_subnet_object_id, 'stored_value': parent_range_raw},
        )]

    if not contains(parent_net, candidate):
        return [build_error(
            SubnetErrorCode.NOT_IN_PARENT_SUBNET,
            f"Candidate {candidate} is not contained in parent subnet {parent_net}",
            {
                'candidate': str(candidate),
                'parent_subnet_object_id': parent_subnet_object_id,
                'parent_subnet_range': str(parent_net),
            },
        )]

    return []


def _check_no_cycle(
    objects_manager: ObjectsManager,
    types_manager: TypesManager,
    candidate_subnet_id: int,
    proposed_parent_subnet_id: int,
) -> list[dict[str, Any]]:
    """
    Validates that setting the candidate subnet's parent to 'proposed_parent_subnet_id' would
    not create a cycle in the parent chain

    Walks the chain upward from the proposed parent and aborts if the candidate appears, or if
    a pre-existing cycle is detected, or if the chain exceeds MAX_PARENT_CHAIN_DEPTH

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        candidate_subnet_id (int): public_id of the subnet being edited
        proposed_parent_subnet_id (int): public_id the user is trying to set as parent

    Returns:
        list[dict[str, Any]]: Single-element list with a cycle error when one is found, else []
    """
    if candidate_subnet_id == proposed_parent_subnet_id:
        return [build_error(
            SubnetErrorCode.PARENT_CHAIN_CYCLE,
            "A subnet cannot be its own parent",
            {'candidate_subnet_id': candidate_subnet_id},
        )]

    subnet_type_id: int | None = resolve_special_type_id(types_manager, SpecialType.SUBNET)

    if subnet_type_id is None:
        return []

    visited: set[int] = set()
    current_id: int | None = proposed_parent_subnet_id

    for _ in range(MAX_PARENT_CHAIN_DEPTH):
        if current_id is None:
            return []

        if current_id in visited:
            return [build_error(
                SubnetErrorCode.PARENT_CHAIN_CYCLE,
                "Existing parent chain already contains a cycle",
                {'cycle_at_subnet_id': current_id},
            )]
        visited.add(current_id)

        if current_id == candidate_subnet_id:
            return [build_error(
                SubnetErrorCode.PARENT_CHAIN_CYCLE,
                "Setting this parent would create a cycle in the parent chain",
                {'candidate_subnet_id': candidate_subnet_id, 'parent_subnet_id': proposed_parent_subnet_id},
            )]

        ancestor: dict[str, Any] | None = _load_object_by_id(objects_manager, current_id)

        if not ancestor or ancestor.get('type_id') != subnet_type_id:
            return []

        current_id = extract_field_value(ancestor, SubnetField.PARENT_SUBNET) or None

    return [build_error(
        SubnetErrorCode.PARENT_CHAIN_CYCLE,
        f"Parent chain exceeds maximum depth of {MAX_PARENT_CHAIN_DEPTH}",
        {'max_depth': MAX_PARENT_CHAIN_DEPTH},
    )]


def _check_sibling_overlap(
    objects_manager: ObjectsManager,
    types_manager: TypesManager,
    candidate: IPv4Network,
    parent_supernet_id: int | None,
    parent_subnet_id: int | None,
    exclude_subnet_id: int | None,
) -> list[dict[str, Any]]:
    """
    Validates the candidate does not overlap with siblings sharing the same direct parent

    'Direct parent' is the parent_subnet when set; otherwise the parent_supernet (with siblings
    further filtered to those that themselves have no parent_subnet, so deeply-nested subnets
    are not treated as siblings of top-level children). Standalone candidates (no parent at all)
    have no sibling check per project policy

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        candidate (IPv4Network): The parsed candidate CIDR
        parent_supernet_id (int | None): public_id of chosen SUPERNET, or None
        parent_subnet_id (int | None): public_id of chosen parent SUBNET, or None
        exclude_subnet_id (int | None): public_id of the candidate itself when editing

    Returns:
        list[dict[str, Any]]: One error per overlapping sibling, empty list when no overlap
    """
    subnet_type_id: int | None = resolve_special_type_id(types_manager, SpecialType.SUBNET)

    if subnet_type_id is None:
        return []

    siblings: list[dict[str, Any]] = _collect_siblings(
        objects_manager, subnet_type_id, parent_supernet_id, parent_subnet_id,
    )

    errors: list[dict[str, Any]] = []

    for sibling in siblings:
        sibling_id: int = sibling.get('public_id')

        if exclude_subnet_id is not None and sibling_id == exclude_subnet_id:
            continue

        sibling_range_raw: Any = extract_field_value(sibling, SubnetField.NETWORK_RANGE)
        sibling_net: IPv4Network | None = parse_cidr(sibling_range_raw) if isinstance(sibling_range_raw, str) else None

        if sibling_net is None:
            continue

        if overlaps(candidate, sibling_net):
            errors.append(build_error(
                SubnetErrorCode.SIBLING_OVERLAP,
                f"Candidate {candidate} overlaps with sibling subnet {sibling_net}",
                {
                    'candidate': str(candidate),
                    'sibling_subnet_id': sibling_id,
                    'sibling_range': str(sibling_net),
                },
            ))

    return errors


def _collect_siblings(
    objects_manager: ObjectsManager,
    subnet_type_id: int,
    parent_supernet_id: int | None,
    parent_subnet_id: int | None,
) -> list[dict[str, Any]]:
    """
    Returns subnet objects sharing the candidate's direct parent

    When 'parent_subnet_id' is set, siblings share that parent_subnet ref. Otherwise siblings
    share the parent_supernet ref AND have no parent_subnet ref themselves (so nested subnets
    are excluded from top-level sibling checks)

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        subnet_type_id (int): public_id of the SUBNET CmdbType
        parent_supernet_id (int | None): public_id of chosen SUPERNET, or None
        parent_subnet_id (int | None): public_id of chosen parent SUBNET, or None

    Returns:
        list[dict[str, Any]]: Full sibling subnet documents (with their 'fields' array)
    """
    if parent_subnet_id is not None:
        return _find_subnets_by_field(
            objects_manager, subnet_type_id, SubnetField.PARENT_SUBNET, parent_subnet_id,
        )

    if parent_supernet_id is not None:
        candidates: list[dict[str, Any]] = _find_subnets_by_field(
            objects_manager, subnet_type_id, SubnetField.PARENT_SUPERNET, parent_supernet_id,
        )
        # Exclude nested subnets — only direct children of the supernet are siblings
        return [s for s in candidates if not extract_field_value(s, SubnetField.PARENT_SUBNET)]

    return []


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  ORCHESTRATOR                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
def validate_subnet(
    objects_manager: ObjectsManager,
    types_manager: TypesManager,
    network_range: str,
    parent_supernet_id: int | None = None,
    parent_subnet_id: int | None = None,
    exclude_subnet_id: int | None = None,
) -> list[dict[str, Any]]:
    """
    Validates a candidate SUBNET CmdbObject's network range and parent references

    Returns the accumulated list of errors so the caller can render or abort. An empty list
    means valid

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        network_range (str): The candidate IPv4 CIDR (must be canonical, host bits zeroed)
        parent_supernet_id (int | None): Chosen SUPERNET object id when applicable
        parent_subnet_id (int | None): Chosen parent SUBNET object id when applicable
        exclude_subnet_id (int | None): Self-id during edits, so the candidate doesn't trip
            cycle / sibling-overlap checks against its own pre-edit state

    Returns:
        list[dict[str, Any]]: Structured validation errors; empty when the candidate is valid
    """
    candidate, errors = _check_canonical_cidr(network_range)

    if candidate is None:
        return errors

    if parent_supernet_id is not None:
        errors.extend(_check_in_supernet(objects_manager, types_manager, candidate, parent_supernet_id))

    if parent_subnet_id is not None:
        errors.extend(_check_in_parent_subnet(objects_manager, types_manager, candidate, parent_subnet_id))

        if exclude_subnet_id is not None:
            errors.extend(_check_no_cycle(
                objects_manager, types_manager, exclude_subnet_id, parent_subnet_id,
            ))

    if parent_supernet_id is not None or parent_subnet_id is not None:
        errors.extend(_check_sibling_overlap(
            objects_manager, types_manager, candidate,
            parent_supernet_id, parent_subnet_id, exclude_subnet_id,
        ))

    return errors
