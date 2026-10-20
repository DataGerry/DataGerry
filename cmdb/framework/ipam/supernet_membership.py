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
helpers are decomposed so each step (input coercion, batch-size cap, supernet identity check,
ACL check, candidate membership query, batch field clear) is unit-testable in isolation.
``unassign_subnets_from_supernet`` is the single orchestrator the route layer calls

**The detach is a user's direct edit of the SUBNETs it names**, so it records what every object edit
records: the version bump and edit stamp go into the same single-document statement that clears the
reference, and every SUBNET it detached is handed to the orchestrator's ``on_write`` callback
afterwards, which the route turns into the change-log entry and the UPDATE webhook. The write itself
is one unordered bulk write whose statements re-assert the current supernet reference, so a SUBNET a
concurrent writer reassigned in between is skipped rather than clobbered - and is not reported as
detached. The ACL is ``verify_subnet_write_access``, asked once before the write because an ACL lives
on the CmdbType and every target is a SUBNET
"""
from typing import Any

from flask import abort
from pymongo import UpdateOne

from cmdb.manager import ObjectsManager, TypesManager
from cmdb.models.object_model import CmdbObjectKey, CmdbObjectFieldKey
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.special_type_model.ipam_constants import (
    SubnetField,
    IpamUnassignKey,
    IpamUnassignLimits,
)
from cmdb.models.user_model import CmdbUser
from cmdb.framework.ipam.references import resolve_special_type_id, resolve_special_type_document
from cmdb.framework.object_edit import (
    ObjectWriteCallback,
    PlannedEdit,
    build_edit_stamp,
    hand_over_object_writes,
    plan_object_edit,
)
from cmdb.security.acl.helpers import has_type_document_access
from cmdb.security.acl.permission import AccessControlPermission
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
def verify_subnet_write_access(
    types_manager: TypesManager,
    request_user: CmdbUser | None,
) -> None:
    """
    Aborts 403 when the caller may not UPDATE SUBNET CmdbObjects

    **One check covers the whole batch, because an ACL lives on the CmdbType.** Every target of
    ``clear_supernet_ref`` is a SUBNET - ``load_assigned_subnets`` establishes that before anything
    is written - so "may this caller detach these subnets" is a single question about one type, not
    a question per object. That keeps the authorization check without giving up the single atomic
    write or opening a TOCTOU window between the check and the write

    ``clear_supernet_ref`` writes the SUBNETs directly instead of through
    ``ObjectsManager.update_object``, so this is the ACL that method would apply, asked at the one
    place a batch write can ask it

    Args:
        types_manager (TypesManager): db interface for CmdbTypes
        request_user (CmdbUser | None): The CmdbUser performing the detach; None skips the check,
            which is what an internal caller with no request context passes

    Returns:
        None: Returns normally when the caller may write, otherwise aborts the request
    """
    if request_user is None:
        return

    subnet_type_doc: dict[str, Any] | None = resolve_special_type_document(types_manager, SpecialType.SUBNET)

    if not subnet_type_doc:
        return

    if not has_type_document_access(subnet_type_doc, request_user, AccessControlPermission.UPDATE):
        abort(403, "No permission to unassign SUBNETs from a supernet!")


def clear_supernet_ref_in_document(subnet_doc: dict[str, Any], supernet_public_id: int) -> dict[str, Any]:
    """
    Returns a copy of a SUBNET document whose dg-supernet-ref entry no longer names the supernet

    Only the entry that still carries ``supernet_public_id`` is cleared, which is exactly what the
    array filter of the write matches; every other field entry is forwarded unchanged. The input
    document is not modified

    Args:
        subnet_doc (dict[str, Any]): The stored SUBNET CmdbObject document
        supernet_public_id (int): public_id of the supernet being detached from

    Returns:
        dict[str, Any]: The document as the detach leaves it
    """
    fields: list[dict[str, Any]] = [
        {**entry, CmdbObjectFieldKey.VALUE.value: None}
        if entry.get(CmdbObjectFieldKey.NAME) == SubnetField.PARENT_SUPERNET
        and entry.get(CmdbObjectFieldKey.VALUE) == supernet_public_id
        else entry
        for entry in subnet_doc.get(CmdbObjectKey.FIELDS, []) or []
    ]

    return {**subnet_doc, CmdbObjectKey.FIELDS.value: fields}


def plan_subnet_detaches(
    subnet_docs: list[dict[str, Any]],
    supernet_public_id: int,
) -> dict[int, PlannedEdit]:
    """
    Computes the version bump and diff of every detach, before anything is written

    Args:
        subnet_docs (list[dict[str, Any]]): The SUBNETs to detach (from ``load_assigned_subnets``)
        supernet_public_id (int): public_id of the supernet being detached from

    Returns:
        dict[int, PlannedEdit]: One plan per SUBNET, keyed by its public_id
    """
    return {
        doc[CmdbObjectKey.PUBLIC_ID]: plan_object_edit(doc, clear_supernet_ref_in_document(doc, supernet_public_id))
        for doc in subnet_docs
    }


def build_detach_operation(
    subnet_public_id: int,
    supernet_public_id: int,
    new_version: str,
    edit_stamp: dict[str, Any],
) -> UpdateOne:
    """
    Builds the single-document write that detaches one SUBNET from the supernet

    **The filter re-asserts the current supernet reference**, on the document and in the array filter:
    a SUBNET that a concurrent writer reassigned to another supernet after ``load_assigned_subnets``
    read it no longer matches, and its new assignment is left intact. The same statement writes the
    version bump and the edit stamp, so a SUBNET is never detached without them

    Args:
        subnet_public_id (int): public_id of the SUBNET to detach
        supernet_public_id (int): public_id of the supernet the SUBNET must still reference
        new_version (str): The version the detach bumps the SUBNET to
        edit_stamp (dict[str, Any]): ``last_edit_time`` / ``editor_id`` (see ``build_edit_stamp``)

    Returns:
        UpdateOne: The operation for ``ObjectsManager.bulk_write``
    """
    filter_query: dict[str, Any] = {
        CmdbObjectKey.PUBLIC_ID.value: subnet_public_id,
        CmdbObjectKey.FIELDS.value: {
            '$elemMatch': {
                CmdbObjectFieldKey.NAME.value: SubnetField.PARENT_SUPERNET.value,
                CmdbObjectFieldKey.VALUE.value: supernet_public_id,
            },
        },
    }
    # 'f' is the array-filter identifier the positional path below refers back to
    update: dict[str, Any] = {'$set': {
        f'{CmdbObjectKey.FIELDS.value}.$[f].{CmdbObjectFieldKey.VALUE.value}': None,
        CmdbObjectKey.VERSION.value: new_version,
        **edit_stamp,
    }}
    array_filters: list[dict[str, Any]] = [{
        f'f.{CmdbObjectFieldKey.NAME.value}': SubnetField.PARENT_SUPERNET.value,
        f'f.{CmdbObjectFieldKey.VALUE.value}': supernet_public_id,
    }]

    return UpdateOne(filter_query, update, array_filters=array_filters)


def clear_supernet_ref(
    objects_manager: ObjectsManager,
    plans: dict[int, PlannedEdit],
    supernet_public_id: int,
    request_user: CmdbUser | None = None,
) -> int:
    """
    Detaches every planned SUBNET from the supernet in one unordered bulk write

    One ``UpdateOne`` per SUBNET (see ``build_detach_operation``), sent together: one round trip for
    the whole batch, each document written atomically with its version and edit stamp. Like the
    ``update_many`` this replaces, the batch is not a transaction across documents

    Pre-condition: ``plans`` is non-empty - the orchestrator only gets here with at least one SUBNET

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        plans (dict[int, PlannedEdit]): The detaches to write (from ``plan_subnet_detaches``)
        supernet_public_id (int): public_id of the supernet the SUBNETs must currently reference
        request_user (CmdbUser | None): The CmdbUser credited as editor; None stamps only the time

    Returns:
        int: How many SUBNETs were detached; fewer than planned when a concurrent writer moved some
    """
    edit_stamp: dict[str, Any] = build_edit_stamp(request_user)

    return objects_manager.bulk_write([
        build_detach_operation(public_id, supernet_public_id, plan.version, edit_stamp)
        for public_id, plan in plans.items()
    ])


def is_detached_by_this_write(after_doc: dict[str, Any], plan: PlannedEdit) -> bool:
    """
    Tells whether a SUBNET read back after the detach carries this detach

    Needed only when the write modified fewer SUBNETs than it planned, because a bulk write reports a
    count, not which documents. A SUBNET this write detached holds the planned version and a cleared
    dg-supernet-ref; one a concurrent writer moved in between still holds its old version

    Args:
        after_doc (dict[str, Any]): The SUBNET document read back after the write
        plan (PlannedEdit): The detach planned for it

    Returns:
        bool: True when the document carries the planned detach
    """
    if after_doc.get(CmdbObjectKey.VERSION) != plan.version:
        return False

    return all(
        entry.get(CmdbObjectFieldKey.VALUE) is None
        for entry in after_doc.get(CmdbObjectKey.FIELDS, []) or []
        if entry.get(CmdbObjectFieldKey.NAME) == SubnetField.PARENT_SUPERNET
    )


# -------------------------------------------------------------------------------------------------------------------- #
#                                                   ORCHESTRATOR                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
def unassign_subnets_from_supernet(
    objects_manager: ObjectsManager,
    types_manager: TypesManager,
    supernet_public_id: int,
    raw_subnet_ids: Any,
    request_user: CmdbUser | None = None,
    on_write: ObjectWriteCallback | None = None,
) -> dict[str, Any]:
    """
    Validates the request payload and detaches the named SUBNETs from the supernet

    Pipeline:
      1. Coerce ``raw_subnet_ids`` to a deduplicated list of ints (aborts 400 on bad shape) and
         refuse a list longer than ``IpamUnassignLimits.MAX_SUBNET_IDS``
      2. Confirm ``supernet_public_id`` resolves to a SUPERNET CmdbObject (aborts 400/404)
      3. Confirm the caller may update SUBNETs at all (aborts 403); one check for the batch,
         because the ACL is per CmdbType and every target is a SUBNET
      4. Load the SUBNETs that are currently assigned to the supernet AND whose public_id
         is in the requested list
      5. If any requested id is not present in step 4's result, abort 400 with the offending
         ids - the call is validate-all-or-nothing, so no write happens
      6. Otherwise plan every detach (version bump + diff) and write them in one bulk write
      7. Read the detached SUBNETs back in one query and hand each to ``on_write``, best-effort; a
         SUBNET the write skipped because it was moved concurrently is not handed over

    Children of a detached SUBNET are intentionally left attached: if a CIDR-child of one of
    the requested SUBNETs also references this supernet, it stays assigned. Such children
    simply surface as new top-level rows on the next overview load because their CIDR-parent
    has dropped out of the tree

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        supernet_public_id (int): public_id of the SUPERNET to detach from
        raw_subnet_ids (Any): The raw value read off the JSON body for the 'subnet_ids' key
        request_user (CmdbUser | None): The CmdbUser performing the detach, whose group decides
            whether the SUBNET type's ACL permits the write and who is stamped as editor; None skips
            the ACL and stamps only the time
        on_write (ObjectWriteCallback | None): Receives every detached SUBNET after the write - the
            route writes its change log and webhook from it. None skips the read-back

    Returns:
        dict[str, Any]: {'subnet_ids': [int, ...], 'unassigned_count': int} where subnet_ids
            echoes the deduplicated input order and unassigned_count is len(subnet_ids)
    """
    subnet_ids: list[int] = normalize_subnet_id_list(raw_subnet_ids)

    if len(subnet_ids) > IpamUnassignLimits.MAX_SUBNET_IDS:
        abort(
            400,
            f"Cannot unassign more than {IpamUnassignLimits.MAX_SUBNET_IDS} subnets in one request"
            f" (received {len(subnet_ids)})!",
        )

    assert_supernet_exists(objects_manager, types_manager, supernet_public_id)

    # Before the write, not per object: see verify_subnet_write_access
    verify_subnet_write_access(types_manager, request_user)

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

    plans: dict[int, PlannedEdit] = plan_subnet_detaches(assigned_objs, supernet_public_id)
    modified: int = clear_supernet_ref(objects_manager, plans, supernet_public_id, request_user)

    # A full count means every planned SUBNET was detached; a short one needs the check that tells
    # this write's detaches apart from the SUBNETs it skipped
    hand_over_object_writes(
        objects_manager, plans, on_write,
        is_written=None if modified == len(plans) else is_detached_by_this_write,
    )

    return {
        IpamUnassignKey.SUBNET_IDS: subnet_ids,
        IpamUnassignKey.UNASSIGNED_COUNT: len(subnet_ids),
    }
