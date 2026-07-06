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
Mutates the SUBNET <-> SUPERNET membership relation

The frontend's supernet overview lets a user pick one or more rows and detach them from the
supernet. Detach means clearing the SUBNET CmdbObject's 'dg-supernet-ref' field value to
None; the subnet (and any of its CIDR-children that still reference the same supernet) stay
in the database. CIDR-children are not auto-detached: a child that was nested under one of
the selected subnets keeps its own dg-supernet-ref and simply surfaces as a new top-level
row on the next overview load

This module is intentionally read/write-split from supernet_overview.py: the overview module
only shapes payloads, while every mutation against the membership relation lives here. The
helpers are decomposed so each step (input coercion, supernet identity check, candidate
membership query, batch field clear) is unit-testable in isolation. ``unassign_subnets_from_supernet``
is the single orchestrator the route layer calls
"""
from typing import Any

from flask import abort

from cmdb.manager import ObjectsManager, TypesManager
from cmdb.models.object_model import CmdbObjectKey, CmdbObjectFieldKey
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.special_type_model.ipam_constants import SubnetField, IpamUnassignKey
from cmdb.framework.ipam.references import resolve_special_type_id
# -------------------------------------------------------------------------------------------------------------------- #


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  PURE HELPERS                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
def normalize_subnet_id_list(raw: Any) -> list[int]:
    """
    Coerces the request payload's ``subnet_ids`` value into a deduplicated list of ints

    The payload field is rejected with HTTP 400 when it is missing, not a list, empty, or
    contains a non-integer (booleans are rejected even though Python treats them as ints,
    so a stray ``true`` cannot silently target subnet id ``1``). Duplicates are removed
    while preserving the order of the first occurrence so the response payload echoes the
    list back in the caller's original order

    Args:
        raw (Any): The raw value read off the JSON body for the 'subnet_ids' key

    Returns:
        list[int]: The deduplicated, integer-typed subnet public_ids in input order
    """
    if not isinstance(raw, list) or not raw:
        abort(400, f"'{IpamUnassignKey.SUBNET_IDS}' must be a non-empty list of integers!")

    deduped: list[int] = []
    seen: set[int] = set()

    for entry in raw:
        if isinstance(entry, bool) or not isinstance(entry, int):
            abort(
                400,
                f"'{IpamUnassignKey.SUBNET_IDS}' contains a non-integer entry: {entry!r}",
            )

        if entry in seen:
            continue

        seen.add(entry)
        deduped.append(entry)

    return deduped


def diff_missing_ids(requested: list[int], present_objs: list[dict[str, Any]]) -> list[int]:
    """
    Returns the requested public_ids that were not present in ``present_objs``

    Used by the validate-all-or-nothing flow: ``present_objs`` is the result of querying the
    DB for SUBNET CmdbObjects that are assigned to the supernet and whose public_id is in
    ``requested``. Anything in ``requested`` that does not come back is either not a SUBNET,
    does not exist, or is not currently assigned to the supernet. The order of ``requested``
    is preserved in the returned list so error messages echo the caller's input order

    Args:
        requested (list[int]): The public_ids the caller asked to unassign
        present_objs (list[dict[str, Any]]): SUBNET CmdbObject documents that came back from
            the membership query

    Returns:
        list[int]: The subset of ``requested`` not represented in ``present_objs``,
            in input order
    """
    present_ids: set[Any] = {obj.get(CmdbObjectKey.PUBLIC_ID) for obj in present_objs}

    return [sid for sid in requested if sid not in present_ids]


# -------------------------------------------------------------------------------------------------------------------- #
#                                                   DATA LOADING                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
def assert_supernet_exists(
    objects_manager: ObjectsManager,
    types_manager: TypesManager,
    supernet_public_id: int,
) -> None:
    """
    Aborts the request when the public_id does not resolve to a SUPERNET CmdbObject

    Aborts HTTP 400 when no SUPERNET CmdbType is defined or when the public_id refers to a
    CmdbObject of a different type; aborts HTTP 404 when no CmdbObject with the public_id
    exists. Returns nothing on success - the caller does not need the supernet document
    itself for the unassign flow

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        supernet_public_id (int): public_id the caller named as the supernet to detach from
    """
    supernet_type_id: int | None = resolve_special_type_id(types_manager, SpecialType.SUPERNET)

    if supernet_type_id is None:
        abort(400, "No SUPERNET CmdbType is defined; cannot unassign subnets!")

    candidates: list[dict[str, Any]] = objects_manager.find_objects(
        {CmdbObjectKey.PUBLIC_ID: supernet_public_id},
        as_dict=True,
    )

    if not candidates:
        abort(404, f"Supernet with public_id {supernet_public_id} was not found!")

    if candidates[0].get(CmdbObjectKey.TYPE_ID) != supernet_type_id:
        abort(400, f"Object with public_id {supernet_public_id} is not a SUPERNET!")


def load_assigned_subnets(
    objects_manager: ObjectsManager,
    types_manager: TypesManager,
    supernet_public_id: int,
    subnet_ids: list[int],
) -> list[dict[str, Any]]:
    """
    Returns SUBNET CmdbObject documents that are currently assigned to the supernet and
    whose public_id is in ``subnet_ids``

    A single Mongo query enforces three conditions at once: type is SUBNET, public_id is in
    the requested set, and the dg-supernet-ref field value equals ``supernet_public_id``. Any
    requested id that is not a SUBNET, does not exist, or is not assigned to this supernet is
    simply absent from the result - callers use ``diff_missing_ids`` to surface them

    Returns an empty list when no SUBNET CmdbType is defined yet so a virgin install cannot
    falsely report unassignable ids; the caller's downstream diff will then report every
    requested id as missing, which is still the correct outcome

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        supernet_public_id (int): public_id of the SUPERNET to check membership against
        subnet_ids (list[int]): SUBNET public_ids the caller asked to unassign

    Returns:
        list[dict[str, Any]]: SUBNET CmdbObject documents matching all three conditions
    """
    subnet_type_id: int | None = resolve_special_type_id(types_manager, SpecialType.SUBNET)

    if subnet_type_id is None:
        return []

    criteria: dict[str, Any] = {
        CmdbObjectKey.PUBLIC_ID: {'$in': subnet_ids},
        CmdbObjectKey.TYPE_ID: subnet_type_id,
        CmdbObjectKey.FIELDS: {
            '$elemMatch': {
                CmdbObjectFieldKey.NAME: SubnetField.PARENT_SUPERNET,
                CmdbObjectFieldKey.VALUE: supernet_public_id,
            },
        },
    }

    return objects_manager.find_objects(criteria, as_dict=True)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                      WRITES                                                          #
# -------------------------------------------------------------------------------------------------------------------- #
def clear_supernet_ref(
    objects_manager: ObjectsManager,
    subnet_ids: list[int],
    supernet_public_id: int,
) -> None:
    """
    Sets the dg-supernet-ref field value to None on every SUBNET CmdbObject whose public_id
    is in ``subnet_ids`` AND that still references the supernet

    Uses a single ``update_many_raw`` with an array filter so all updates land in one Mongo
    write. The match conditions are deliberately strict on both the doc filter and the array
    filter: both require ``dg-supernet-ref`` to be present with value equal to
    ``supernet_public_id``. This closes the TOCTOU window between identity validation in
    ``load_assigned_subnets`` and this write - if a concurrent writer reassigned one of the
    requested SUBNETs to a different supernet in between, that SUBNET no longer matches and
    its (new) assignment is left intact

    Pre-condition: ``subnet_ids`` is non-empty - the orchestrator enforces this upstream via
    ``normalize_subnet_id_list``, so passing an empty list is a programming error

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        subnet_ids (list[int]): SUBNET public_ids whose dg-supernet-ref should be cleared
        supernet_public_id (int): public_id of the supernet the SUBNETs must currently
            reference; SUBNETs no longer referencing this supernet are skipped
    """
    filter_query: dict[str, Any] = {
        CmdbObjectKey.PUBLIC_ID: {'$in': subnet_ids},
        CmdbObjectKey.FIELDS: {
            '$elemMatch': {
                CmdbObjectFieldKey.NAME: SubnetField.PARENT_SUPERNET,
                CmdbObjectFieldKey.VALUE: supernet_public_id,
            },
        },
    }
    # 'f' is the array-filter identifier the positional path below refers back to
    update: dict[str, Any] = {'$set': {
        f'{CmdbObjectKey.FIELDS.value}.$[f].{CmdbObjectFieldKey.VALUE.value}': None,
    }}
    array_filters: list[dict[str, Any]] = [{
        f'f.{CmdbObjectFieldKey.NAME.value}': SubnetField.PARENT_SUPERNET,
        f'f.{CmdbObjectFieldKey.VALUE.value}': supernet_public_id,
    }]

    objects_manager.update_many_raw(
        filter_query=filter_query,
        update=update,
        array_filters=array_filters,
    )


# -------------------------------------------------------------------------------------------------------------------- #
#                                                   ORCHESTRATOR                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
def unassign_subnets_from_supernet(
    objects_manager: ObjectsManager,
    types_manager: TypesManager,
    supernet_public_id: int,
    raw_subnet_ids: Any,
) -> dict[str, Any]:
    """
    Validates the request payload and detaches the named SUBNETs from the supernet

    Pipeline:
      1. Coerce ``raw_subnet_ids`` to a deduplicated list of ints (aborts 400 on bad shape)
      2. Confirm ``supernet_public_id`` resolves to a SUPERNET CmdbObject (aborts 400/404)
      3. Load the SUBNETs that are currently assigned to the supernet AND whose public_id
         is in the requested list
      4. If any requested id is not present in step 3's result, abort 400 with the offending
         ids - the call is validate-all-or-nothing, so no write happens
      5. Otherwise clear dg-supernet-ref on every requested SUBNET in one Mongo update_many

    Children of a detached SUBNET are intentionally left attached: if a CIDR-child of one of
    the requested SUBNETs also references this supernet, it stays assigned. Such children
    simply surface as new top-level rows on the next overview load because their CIDR-parent
    has dropped out of the tree

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        supernet_public_id (int): public_id of the SUPERNET to detach from
        raw_subnet_ids (Any): The raw value read off the JSON body for the 'subnet_ids' key

    Returns:
        dict[str, Any]: {'subnet_ids': [int, ...], 'unassigned_count': int} where subnet_ids
            echoes the deduplicated input order and unassigned_count is len(subnet_ids)
    """
    subnet_ids: list[int] = normalize_subnet_id_list(raw_subnet_ids)
    assert_supernet_exists(objects_manager, types_manager, supernet_public_id)

    assigned_objs: list[dict[str, Any]] = load_assigned_subnets(
        objects_manager, types_manager, supernet_public_id, subnet_ids,
    )

    missing: list[int] = diff_missing_ids(subnet_ids, assigned_objs)

    if missing:
        abort(
            400,
            f"Cannot unassign subnets {missing} - they are not SUBNETs assigned to supernet"
            f" {supernet_public_id}!",
        )

    clear_supernet_ref(objects_manager, subnet_ids, supernet_public_id)

    return {
        IpamUnassignKey.SUBNET_IDS: subnet_ids,
        IpamUnassignKey.UNASSIGNED_COUNT: len(subnet_ids),
    }
