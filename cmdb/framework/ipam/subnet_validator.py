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

Surfaces canonical-CIDR, parent-supernet-existence, containment and sibling-overlap errors.
Each check is decomposed into a small helper to remain unit-testable
"""
from ipaddress import IPv4Network
from typing import Any

from cmdb.manager import ObjectsManager, TypesManager
from cmdb.models.object_model import CmdbObjectKey, CmdbObjectFieldKey, extract_field_value
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.special_type_model.ipam_constants import (
    SubnetField,
    SupernetField,
    IpamValidationDetailKey,
)
from cmdb.utils import BaseStrEnum, build_error
from cmdb.framework.ipam.cidr import parse_cidr, contains, overlaps, validate_canonical_cidr_value
from cmdb.framework.ipam.references import resolve_special_type_id
# -------------------------------------------------------------------------------------------------------------------- #


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  ERROR CODES                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class SubnetErrorCode(BaseStrEnum):
    """Stable codes for structured subnet validation errors"""
    CIDR_INVALID = 'cidr_invalid'
    PARENT_SUPERNET_TYPE_MISSING = 'parent_supernet_type_missing'
    PARENT_SUPERNET_NOT_FOUND = 'parent_supernet_not_found'
    PARENT_SUPERNET_BROKEN_STATE = 'parent_supernet_broken_state'
    NOT_IN_PARENT_SUPERNET = 'not_in_parent_supernet'
    SIBLING_OVERLAP = 'sibling_overlap'


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
    matches: list[dict[str, Any]] = objects_manager.find_objects(
        {CmdbObjectKey.PUBLIC_ID: object_id},
        as_dict=True,
    )

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
        CmdbObjectKey.TYPE_ID: subnet_type_id,
        CmdbObjectKey.FIELDS: {
            '$elemMatch': {
                CmdbObjectFieldKey.NAME: field_name,
                CmdbObjectFieldKey.VALUE: field_value,
            },
        },
    }

    return objects_manager.find_objects(criteria, as_dict=True)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                INDIVIDUAL CHECKS                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
def _check_canonical_cidr(network_range: str) -> tuple[IPv4Network | None, list[dict[str, Any]]]:
    """
    Validates the candidate CIDR is a strict (canonical) IPv4 CIDR, emitting CIDR_INVALID on
    failure

    Thin domain-specific alias over validate_canonical_cidr_value that binds the error code to
    SubnetErrorCode.CIDR_INVALID

    Args:
        network_range (str): The candidate CIDR

    Returns:
        tuple[IPv4Network | None, list[dict[str, Any]]]: (parsed network or None, list of errors)
    """
    return validate_canonical_cidr_value(network_range, SubnetErrorCode.CIDR_INVALID)


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

    if not supernet_obj or supernet_obj.get(CmdbObjectKey.TYPE_ID) != supernet_type_id:
        return [build_error(
            SubnetErrorCode.PARENT_SUPERNET_NOT_FOUND,
            f"Supernet object with id {supernet_object_id} does not exist",
            {IpamValidationDetailKey.SUPERNET_OBJECT_ID: supernet_object_id},
        )]

    supernet_range_raw: Any = extract_field_value(supernet_obj, SupernetField.NETWORK_RANGE)
    supernet_net: IPv4Network | None = parse_cidr(supernet_range_raw) if isinstance(supernet_range_raw, str) else None

    if supernet_net is None:
        return [build_error(
            SubnetErrorCode.PARENT_SUPERNET_BROKEN_STATE,
            f"Supernet object {supernet_object_id} has no valid '{SupernetField.NETWORK_RANGE.value}' value",
            {
                IpamValidationDetailKey.SUPERNET_OBJECT_ID: supernet_object_id,
                IpamValidationDetailKey.STORED_VALUE: supernet_range_raw,
            },
        )]

    if not contains(supernet_net, candidate):
        return [build_error(
            SubnetErrorCode.NOT_IN_PARENT_SUPERNET,
            f"Candidate {candidate} is not contained in supernet {supernet_net}",
            {
                IpamValidationDetailKey.CANDIDATE: str(candidate),
                IpamValidationDetailKey.SUPERNET_OBJECT_ID: supernet_object_id,
                IpamValidationDetailKey.SUPERNET_RANGE: str(supernet_net),
            },
        )]

    return []


def _check_sibling_overlap(
    objects_manager: ObjectsManager,
    types_manager: TypesManager,
    candidate: IPv4Network,
    parent_supernet_id: int,
    exclude_subnet_id: int | None,
) -> list[dict[str, Any]]:
    """
    Validates the candidate does not overlap with siblings sharing the same parent_supernet

    Standalone candidates (no parent_supernet) have no sibling check per project policy

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        candidate (IPv4Network): The parsed candidate CIDR
        parent_supernet_id (int): public_id of chosen SUPERNET
        exclude_subnet_id (int | None): public_id of the candidate itself when editing

    Returns:
        list[dict[str, Any]]: One error per overlapping sibling, empty list when no overlap
    """
    subnet_type_id: int | None = resolve_special_type_id(types_manager, SpecialType.SUBNET)

    if subnet_type_id is None:
        return []

    siblings: list[dict[str, Any]] = _find_subnets_by_field(
        objects_manager, subnet_type_id, SubnetField.PARENT_SUPERNET, parent_supernet_id,
    )

    errors: list[dict[str, Any]] = []

    for sibling in siblings:
        sibling_id: int = sibling.get(CmdbObjectKey.PUBLIC_ID)

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
                    IpamValidationDetailKey.CANDIDATE: str(candidate),
                    IpamValidationDetailKey.SIBLING_SUBNET_ID: sibling_id,
                    IpamValidationDetailKey.SIBLING_RANGE: str(sibling_net),
                },
            ))

    return errors


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  ORCHESTRATOR                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
def validate_subnet(
    objects_manager: ObjectsManager,
    types_manager: TypesManager,
    network_range: str,
    parent_supernet_id: int | None = None,
    exclude_subnet_id: int | None = None,
) -> list[dict[str, Any]]:
    """
    Validates a candidate SUBNET CmdbObject's network range and parent supernet reference

    Returns the accumulated list of errors so the caller can render or abort. An empty list
    means valid

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        network_range (str): The candidate IPv4 CIDR (must be canonical, host bits zeroed)
        parent_supernet_id (int | None): Chosen SUPERNET object id when applicable
        exclude_subnet_id (int | None): Self-id during edits, so the candidate doesn't trip
            sibling-overlap checks against its own pre-edit state

    Returns:
        list[dict[str, Any]]: Structured validation errors; empty when the candidate is valid
    """
    candidate, errors = _check_canonical_cidr(network_range)

    if candidate is None:
        return errors

    if parent_supernet_id is not None:
        errors.extend(_check_in_supernet(objects_manager, types_manager, candidate, parent_supernet_id))
        errors.extend(_check_sibling_overlap(
            objects_manager, types_manager, candidate, parent_supernet_id, exclude_subnet_id,
        ))

    return errors
