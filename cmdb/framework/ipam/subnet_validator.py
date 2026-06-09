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
from typing import Any

from cmdb.manager import ObjectsManager, TypesManager
from cmdb.models.object_model import CmdbObjectKey, CmdbObjectFieldKey, extract_field_value
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.special_type_model.ipam_constants import (
    SubnetField,
    SupernetField,
)
from cmdb.utils import build_error
from cmdb.framework.ipam.cidr import (
    Network,
    parse_cidr,
    contains,
    overlaps,
    network_family,
    validate_canonical_cidr_value,
    validate_family_selector,
)
from cmdb.framework.ipam.references import resolve_special_type_id
# -------------------------------------------------------------------------------------------------------------------- #


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
def _check_canonical_cidr(network_range: str) -> tuple[Network | None, list[dict[str, Any]]]:
    """
    Validates the candidate CIDR is a strict (canonical) IPv4 or IPv6 CIDR

    Thin domain-specific alias over the shared validate_canonical_cidr_value

    Args:
        network_range (str): The candidate CIDR

    Returns:
        tuple[Network | None, list[dict[str, Any]]]: (parsed network or None, list of errors)
    """
    return validate_canonical_cidr_value(network_range)


def _check_type_matches_family(candidate: Network, subnet_type: str | None) -> list[dict[str, Any]]:
    """
    Validates the SUBNET's 'dg-subnet-type' selector is set and agrees with the CIDR's actual
    address family

    Thin domain-specific binding of the shared ``validate_family_selector`` core (see that
    helper for the required-selector / mismatch semantics) to the SUBNET selector field

    Args:
        candidate (Network): The parsed candidate CIDR
        subnet_type (str | None): The 'dg-subnet-type' value ('ipv4' / 'ipv6'), or None when
            the candidate carries no selector value

    Returns:
        list[dict[str, Any]]: A single-element error list on a missing selector or a mismatch,
            empty when consistent
    """
    return validate_family_selector(
        candidate,
        subnet_type,
        selector_field_name=SubnetField.TYPE.value,
        subject_label='Subnet',
    )


def _check_in_supernet(
    objects_manager: ObjectsManager,
    types_manager: TypesManager,
    candidate: Network,
    supernet_object_id: int,
) -> list[dict[str, Any]]:
    """
    Validates the candidate is a subnet of the referenced SUPERNET object's network range

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        candidate (Network): The parsed candidate CIDR
        supernet_object_id (int): public_id of the referenced SUPERNET CmdbObject

    Returns:
        list[dict[str, Any]]: Validation errors found, empty when containment holds
    """
    supernet_type_id: int | None = resolve_special_type_id(types_manager, SpecialType.SUPERNET)

    if supernet_type_id is None:
        return [build_error(
            "No SUPERNET CmdbType is defined; cannot validate parent supernet",
        )]

    supernet_obj: dict[str, Any] | None = _load_object_by_id(objects_manager, supernet_object_id)

    if not supernet_obj or supernet_obj.get(CmdbObjectKey.TYPE_ID) != supernet_type_id:
        return [build_error(
            f"Supernet object with id {supernet_object_id} does not exist",
        )]

    supernet_range_raw: Any = extract_field_value(supernet_obj, SupernetField.NETWORK_RANGE)
    supernet_net: Network | None = parse_cidr(supernet_range_raw) if isinstance(supernet_range_raw, str) else None

    if supernet_net is None:
        return [build_error(
            f"Supernet object {supernet_object_id} has no valid '{SupernetField.NETWORK_RANGE.value}' value",
        )]

    if supernet_net.version != candidate.version:
        return [build_error(
            f"Candidate {candidate} ({network_family(candidate)}) does not match the address family "
            f"'{network_family(supernet_net)}' of supernet {supernet_net}",
        )]

    if not contains(supernet_net, candidate):
        return [build_error(
            f"Candidate {candidate} is not contained in supernet {supernet_net}",
        )]

    return []


def _check_sibling_overlap(
    objects_manager: ObjectsManager,
    types_manager: TypesManager,
    candidate: Network,
    parent_supernet_id: int,
    exclude_subnet_id: int | None,
) -> list[dict[str, Any]]:
    """
    Validates the candidate does not overlap with siblings sharing the same parent_supernet

    Standalone candidates (no parent_supernet) have no sibling check per project policy. A
    sibling of a different address family never overlaps (overlaps() guards on family), so
    mixed-family siblings under the same supernet do not flag each other

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        candidate (Network): The parsed candidate CIDR
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
        sibling_net: Network | None = parse_cidr(sibling_range_raw) if isinstance(sibling_range_raw, str) else None

        if sibling_net is None:
            continue

        if overlaps(candidate, sibling_net):
            errors.append(build_error(
                f"Candidate {candidate} overlaps with sibling subnet {sibling_net}",
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
    subnet_type: str | None = None,
) -> list[dict[str, Any]]:
    """
    Validates a candidate SUBNET CmdbObject's network range, address family and parent supernet
    reference

    Returns the accumulated list of errors so the caller can render or abort. An empty list
    means valid. The ``subnet_type`` selector is required once the CIDR parses: a missing value
    is rejected and a supplied value must agree with the CIDR's actual family.
    When a ``parent_supernet_id`` is supplied the candidate's family must match the parent
    supernet's family

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        network_range (str): The candidate IPv4 or IPv6 CIDR (must be canonical, host bits zeroed)
        parent_supernet_id (int | None): Chosen SUPERNET object id when applicable
        exclude_subnet_id (int | None): Self-id during edits, so the candidate doesn't trip
            sibling-overlap checks against its own pre-edit state
        subnet_type (str | None): The 'dg-subnet-type' selector ('ipv4' / 'ipv6'); required -
            None is rejected, a given value is cross-checked against the CIDR
            family

    Returns:
        list[dict[str, Any]]: Structured validation errors; empty when the candidate is valid
    """
    candidate, errors = _check_canonical_cidr(network_range)

    if candidate is None:
        return errors

    errors.extend(_check_type_matches_family(candidate, subnet_type))

    if parent_supernet_id is not None:
        errors.extend(_check_in_supernet(objects_manager, types_manager, candidate, parent_supernet_id))
        errors.extend(_check_sibling_overlap(
            objects_manager, types_manager, candidate, parent_supernet_id, exclude_subnet_id,
        ))

    return errors
