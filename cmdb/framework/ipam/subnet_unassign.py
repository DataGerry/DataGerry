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
Clears the subnet reference on dg-ipam-interface MDS rows

The subnet overview's 'unassign' action lets a user pick one or more assigned IPs of a
subnet and detach them. Detach means clearing the 'dg-interface-subnet' field value to None
on the matching dg-ipam-interface row; the row itself stays, the IP and MAC values are
preserved, and the owner CmdbObject keeps living. Mirrors the supernet 'unassign subnets'
flow, which clears 'dg-supernet-ref' on the SUBNET CmdbObject rather than deleting it. The
detached IP becomes 'free' on the next subnet-overview load because the overview index
filters rows by their subnet reference

Per-owner write semantics: one ``objects_manager.update_object`` per affected owner, which applies
the ACL (the caller must have UPDATE permission on each owner's CmdbType, read once per type for the
request). ``update_object`` itself writes nothing else, so the rest of what an object edit records is
built here: the version bump and edit stamp travel in the same write, and every written owner is handed
to the orchestrator's ``on_write`` callback, which the route turns into the change-log entry and the
UPDATE webhook. The write is a targeted ``$set`` of ``multi_data_sections`` plus the version and stamp -
an edit of any other part of the owner saved concurrently survives it.

**The sections themselves are written by compare-and-swap.** The new ``multi_data_sections`` are built
from the owner as read, so the write only lands while the owner still holds those sections, that
version and that type (``owner_write_guard``): an interface row (or any section) another edit saved in
between makes the write miss instead of being overwritten - also an edit that does not bump the version,
as the type-update propagation's. A miss re-reads that owner and plans the unassign again from what is
stored now, up to ``MAX_OWNER_WRITE_ATTEMPTS`` times; an owner that kept changing stops the request with a
400 naming it (``write_owner_unassign``). The version bump and the change-log diff are always those of the
write that landed. The trade-off is N round-trips instead of one bulk write, which is acceptable for a
UI-driven multi-select that is bounded in size (``IpamUnassignLimits.MAX_IPS``)

Validate-all-or-nothing: if any requested IP is not currently assigned to this subnet, the
orchestrator aborts HTTP 400 with the offending IPs and no write happens. Mirrors the
all-or-nothing semantics of the supernet 'unassign subnets' route
"""
from typing import Any, Callable

from flask import abort

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
    IpamUnassignKey,
    IpamUnassignLimits,
    IpamUnassignMode,
)
from cmdb.models.type_model import CmdbType
from cmdb.models.user_model import CmdbUser
from cmdb.security.acl.permission import AccessControlPermission
from cmdb.framework.ipam.cidr import Network, parse_cidr, parse_ip, ip_in_network
from cmdb.framework.ipam.references import resolve_special_type_id
from cmdb.framework.ipam.references_constants import IPAM_OBJECT_CHECK_PROJECTION
from cmdb.framework.object_edit import (
    ObjectWriteCallback,
    PlannedEdit,
    build_edit_stamp,
    hand_over_object_writes,
    plan_object_edit,
)
from cmdb.framework.ipam.subnet_unassign_constants import (
    IP_OUTSIDE_SUBNET_MSG,
    IPS_INVALID_ENTRY_MSG,
    IPS_NON_STRING_ENTRY_MSG,
    IPS_NOT_A_LIST_MSG,
    IPS_NOT_ASSIGNED_MSG,
    IPS_TOO_MANY_MSG,
    MAX_OWNER_WRITE_ATTEMPTS,
    NO_SUBNET_TYPE_MSG,
    NOT_A_SUBNET_MSG,
    OWNER_KEPT_CHANGING_MSG,
    SUBNET_NOT_FOUND_MSG,
    SUBNET_RANGE_MISSING_MSG,
    SUBNET_RANGE_NOT_CANONICAL_MSG,
    UNASSIGN_MODE_INVALID_MSG,
)
# -------------------------------------------------------------------------------------------------------------------- #


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  PURE HELPERS                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
def abort_if_too_many_ips(raw: Any) -> None:
    """
    Refuses a request naming more IPs than ``IpamUnassignLimits.MAX_IPS``, before anything is read

    Counts the entries as sent - duplicates included, since every one is parsed. A value that is not a list is left
    to ``normalize_ip_list``, which refuses it with its own message

    Args:
        raw (Any): The raw value read off the JSON body for the 'ips' key

    Raises:
        HTTPException: 400 when the list holds more than ``IpamUnassignLimits.MAX_IPS`` entries
    """
    if isinstance(raw, list) and len(raw) > IpamUnassignLimits.MAX_IPS:
        abort(400, IPS_TOO_MANY_MSG.format(max_ips=IpamUnassignLimits.MAX_IPS, count=len(raw)))


def normalize_ip_list(raw: Any, network: Network) -> list[str]:
    """
    Coerces the request payload's ``ips`` value into a deduplicated list of canonical IP strings

    The payload field is rejected with HTTP 400 when it is missing, not a list, empty, or
    contains a non-string entry. Each entry must parse as a canonical IPv4 dotted-quad or IPv6
    address via ``parse_ip`` (rejecting integer-formatted '3232235521' style strings) AND fall
    inside ``network`` (an entry of a different family than the subnet is treated as outside).
    Duplicates are removed while preserving the order of the first occurrence so the response
    payload echoes the list back in the caller's input order

    Args:
        raw (Any): The raw value read off the JSON body for the 'ips' key
        network (Network): The parsed subnet network; entries outside this network are
            rejected so a typo cannot accidentally target an unrelated subnet's interface rows

    Returns:
        list[str]: The deduplicated, canonical IP strings in input order
    """
    if not isinstance(raw, list) or not raw:
        abort(400, IPS_NOT_A_LIST_MSG.format(ips_key=IpamUnassignKey.IPS.value))

    deduped: list[str] = []
    seen: set[str] = set()

    for entry in raw:
        if not isinstance(entry, str):
            abort(400, IPS_NON_STRING_ENTRY_MSG.format(ips_key=IpamUnassignKey.IPS.value, entry=entry))

        parsed = parse_ip(entry)

        if parsed is None:
            abort(400, IPS_INVALID_ENTRY_MSG.format(ips_key=IpamUnassignKey.IPS.value, entry=entry))

        if not ip_in_network(parsed, network):
            abort(400, IP_OUTSIDE_SUBNET_MSG.format(entry=entry, network=network))

        canonical: str = str(parsed)

        if canonical in seen:
            continue

        seen.add(canonical)
        deduped.append(canonical)

    return deduped


def diff_missing_ips(requested: list[str], present_ips: set[str]) -> list[str]:
    """
    Returns the requested canonical IPs that are not currently assigned within the subnet

    Used by the validate-all-or-nothing flow: ``present_ips`` is the set of canonical IP
    strings actually found on dg-ipam-interface rows referencing this subnet. Anything in
    ``requested`` that is not in ``present_ips`` is either a typo, a stale FE selection
    (the row was just deleted by another user), or a drift artifact. The order of
    ``requested`` is preserved in the returned list so error messages echo input order

    Args:
        requested (list[str]): The IPs the caller asked to unassign, post-normalization
        present_ips (set[str]): Canonical IPs found on interface rows referencing this subnet

    Returns:
        list[str]: The subset of ``requested`` not represented in ``present_ips``,
            in input order
    """
    return [ip for ip in requested if ip not in present_ips]


def clear_subnet_ref_in_rows(
    rows: list[dict[str, Any]],
    subnet_id: int,
    target_ips: set[str],
) -> tuple[list[dict[str, Any]], set[str]]:
    """
    Returns the row list with each target row's subnet-ref entry cleared, plus the cleared IPs

    A row is considered a target when it references this subnet AND its IP is in ``target_ips``.
    For each target row a fresh data list is built where the dg-interface-subnet entry's value
    becomes None; every other entry (IP, MAC, and any future fields) is forwarded verbatim, so
    the row keeps its IP / MAC but is no longer associated with the subnet. Non-target rows
    pass through unchanged. The set of cleared IPs is built from rows that were actually
    rewritten so an empty ``target_ips`` or rows referencing a different subnet do not inflate
    the cleared count

    Args:
        rows (list[dict[str, Any]]): The 'values' list of a dg-ipam-interface MDS section
        subnet_id (int): public_id of the subnet whose rows should have their ref cleared
        target_ips (set[str]): Canonical IPv4 strings flagged for clearing

    Returns:
        tuple[list[dict[str, Any]], set[str]]: (new rows list with subnet refs cleared on
            target rows, set of canonical IPs whose row was cleared)
    """
    new_rows: list[dict[str, Any]] = []
    cleared: set[str] = set()

    for row in rows:
        data: list[dict[str, Any]] = row.get(CmdbObjectMdsRowKey.DATA, []) or []

        row_subnet: Any = None
        row_ip: Any = None

        for entry in data:
            name: Any = entry.get(CmdbObjectFieldKey.NAME)

            if name == InterfaceField.SUBNET:
                row_subnet = entry.get(CmdbObjectFieldKey.VALUE)
            elif name == InterfaceField.IP:
                row_ip = entry.get(CmdbObjectFieldKey.VALUE)

        is_target: bool = (
            row_subnet == subnet_id and isinstance(row_ip, str) and row_ip in target_ips
        )

        if not is_target:
            new_rows.append(row)
            continue

        new_data: list[dict[str, Any]] = [
            {**entry, CmdbObjectFieldKey.VALUE: None}
            if entry.get(CmdbObjectFieldKey.NAME) == InterfaceField.SUBNET
            else entry
            for entry in data
        ]

        new_row: dict[str, Any] = {**row, CmdbObjectMdsRowKey.DATA: new_data}
        new_rows.append(new_row)
        cleared.add(row_ip)

    return new_rows, cleared


def clear_subnet_ref_in_owner(
    owner_doc: dict[str, Any],
    subnet_id: int,
    target_ips: set[str],
) -> tuple[dict[str, Any], set[str]]:
    """
    Returns a copy of the owner with every matching dg-ipam-interface row's subnet-ref cleared

    Walks the owner's ``multi_data_sections`` and replaces every dg-ipam-interface section's
    'values' with the rewritten list from ``clear_subnet_ref_in_rows``. Other sections (and
    rows within the dg-ipam-interface section that don't match the target tuple) pass through
    unchanged. The row count is preserved - only matching rows have their subnet-ref entry's
    value flipped to None

    Operates on shallow copies (new doc dict, new section dicts, new rewritten rows). Non-
    target rows are forwarded by reference because they're not mutated. Callers must not
    mutate the returned doc's nested lists in place if they still hold a reference to the
    original

    Args:
        owner_doc (dict[str, Any]): The CmdbObject document to clear from
        subnet_id (int): public_id of the subnet whose rows should have their ref cleared
        target_ips (set[str]): Canonical IPv4 strings flagged for clearing

    Returns:
        tuple[dict[str, Any], set[str]]: (new owner doc, set of canonical IPs whose row had
            its subnet-ref cleared on this owner)
    """
    new_doc: dict[str, Any] = dict(owner_doc)
    new_sections: list[dict[str, Any]] = []
    total_cleared: set[str] = set()

    for section in owner_doc.get(CmdbObjectKey.MULTI_DATA_SECTIONS, []) or []:
        if section.get(CmdbObjectMdsKey.SECTION_ID) != IpamSection.INTERFACE:
            new_sections.append(section)
            continue

        new_values, cleared_ips = clear_subnet_ref_in_rows(
            section.get(CmdbObjectMdsKey.VALUES, []) or [],
            subnet_id,
            target_ips,
        )
        total_cleared |= cleared_ips

        new_section: dict[str, Any] = dict(section)
        new_section[CmdbObjectMdsKey.VALUES] = new_values
        new_sections.append(new_section)

    new_doc[CmdbObjectKey.MULTI_DATA_SECTIONS] = new_sections

    return new_doc, total_cleared


def delete_subnet_rows(
    rows: list[dict[str, Any]],
    subnet_id: int,
    target_ips: set[str],
) -> tuple[list[dict[str, Any]], set[str]]:
    """
    Returns the row list with each target row removed entirely, plus the set of removed IPs

    A row is a target when it references this subnet AND its IP is in ``target_ips`` (the same
    predicate ``clear_subnet_ref_in_rows`` uses). Target rows are dropped from the returned list
    rather than rewritten, so the whole dg-ipam-interface entry (IP, MAC and all) disappears.
    Non-target rows pass through unchanged. The removed-IP set is built from rows actually
    dropped, so an empty ``target_ips`` or rows referencing a different subnet do not inflate it

    Args:
        rows (list[dict[str, Any]]): The 'values' list of a dg-ipam-interface MDS section
        subnet_id (int): public_id of the subnet whose rows should be removed
        target_ips (set[str]): Canonical IP strings flagged for removal

    Returns:
        tuple[list[dict[str, Any]], set[str]]: (new rows list without the target rows, set of
            canonical IPs whose row was removed)
    """
    new_rows: list[dict[str, Any]] = []
    removed: set[str] = set()

    for row in rows:
        row_subnet: Any = None
        row_ip: Any = None

        for entry in row.get(CmdbObjectMdsRowKey.DATA, []) or []:
            name: Any = entry.get(CmdbObjectFieldKey.NAME)

            if name == InterfaceField.SUBNET:
                row_subnet = entry.get(CmdbObjectFieldKey.VALUE)
            elif name == InterfaceField.IP:
                row_ip = entry.get(CmdbObjectFieldKey.VALUE)

        if row_subnet == subnet_id and isinstance(row_ip, str) and row_ip in target_ips:
            removed.add(row_ip)
            continue

        new_rows.append(row)

    return new_rows, removed


def delete_subnet_rows_in_owner(
    owner_doc: dict[str, Any],
    subnet_id: int,
    target_ips: set[str],
) -> tuple[dict[str, Any], set[str]]:
    """
    Returns a copy of the owner with every matching dg-ipam-interface row removed

    Parallel to ``clear_subnet_ref_in_owner`` but uses ``delete_subnet_rows`` so the matched rows
    are dropped from each dg-ipam-interface section's 'values' rather than having their subnet ref
    blanked. Other sections and non-target rows pass through unchanged. Operates on shallow copies
    (new doc, new section dicts); surviving rows are forwarded by reference

    Args:
        owner_doc (dict[str, Any]): The CmdbObject document to delete rows from
        subnet_id (int): public_id of the subnet whose rows should be removed
        target_ips (set[str]): Canonical IP strings flagged for removal

    Returns:
        tuple[dict[str, Any], set[str]]: (new owner doc, set of canonical IPs whose row was
            removed on this owner)
    """
    new_doc: dict[str, Any] = dict(owner_doc)
    new_sections: list[dict[str, Any]] = []
    total_removed: set[str] = set()

    for section in owner_doc.get(CmdbObjectKey.MULTI_DATA_SECTIONS, []) or []:
        if section.get(CmdbObjectMdsKey.SECTION_ID) != IpamSection.INTERFACE:
            new_sections.append(section)
            continue

        new_values, removed_ips = delete_subnet_rows(
            section.get(CmdbObjectMdsKey.VALUES, []) or [],
            subnet_id,
            target_ips,
        )
        total_removed |= removed_ips

        new_section: dict[str, Any] = dict(section)
        new_section[CmdbObjectMdsKey.VALUES] = new_values
        new_sections.append(new_section)

    new_doc[CmdbObjectKey.MULTI_DATA_SECTIONS] = new_sections

    return new_doc, total_removed


def collect_present_ips(
    owner_docs: list[dict[str, Any]],
    subnet_id: int,
) -> set[str]:
    """
    Returns the set of canonical IPs currently assigned to ``subnet_id`` across all owners

    Walks every owner's dg-ipam-interface section and harvests the IP value from each row
    whose subnet reference matches ``subnet_id``. Used by the orchestrator's validate-all-
    or-nothing check before any write: if any requested IP is absent from this set, the call
    aborts 400 and the writes are skipped

    Args:
        owner_docs (list[dict[str, Any]]): CmdbObject documents with a dg-ipam-interface row
            referencing this subnet (typically from ``load_interface_owners``)
        subnet_id (int): public_id of the subnet whose assigned IPs should be collected

    Returns:
        set[str]: Canonical IPv4 strings currently assigned within the subnet
    """
    present: set[str] = set()

    for owner in owner_docs:
        for section in owner.get(CmdbObjectKey.MULTI_DATA_SECTIONS, []) or []:
            if section.get(CmdbObjectMdsKey.SECTION_ID) != IpamSection.INTERFACE:
                continue

            for row in section.get(CmdbObjectMdsKey.VALUES, []) or []:
                row_subnet: Any = None
                row_ip: Any = None

                for entry in row.get(CmdbObjectMdsRowKey.DATA, []) or []:
                    name: Any = entry.get(CmdbObjectFieldKey.NAME)

                    if name == InterfaceField.SUBNET:
                        row_subnet = entry.get(CmdbObjectFieldKey.VALUE)
                    elif name == InterfaceField.IP:
                        row_ip = entry.get(CmdbObjectFieldKey.VALUE)

                if row_subnet == subnet_id and isinstance(row_ip, str):
                    present.add(row_ip)

    return present


# -------------------------------------------------------------------------------------------------------------------- #
#                                                   DATA LOADING                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
def assert_subnet_exists(
    objects_manager: ObjectsManager,
    types_manager: TypesManager,
    subnet_public_id: int,
) -> dict[str, Any]:
    """
    Loads the SUBNET CmdbObject named by ``subnet_public_id`` or aborts with a structured error

    Aborts HTTP 400 when no SUBNET CmdbType is defined or when the public_id refers to a
    CmdbObject of a different type; aborts HTTP 404 when no CmdbObject with the public_id
    exists. Returns the subnet document on success so the orchestrator can parse its CIDR - read through
    ``IPAM_OBJECT_CHECK_PROJECTION`` (id, type, fields), all that is read of it

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        subnet_public_id (int): public_id the caller named as the subnet to unassign from

    Returns:
        dict[str, Any]: The partial SUBNET document (public_id, type_id, fields)
    """
    subnet_type_id: int | None = resolve_special_type_id(types_manager, SpecialType.SUBNET)

    if subnet_type_id is None:
        abort(400, NO_SUBNET_TYPE_MSG)

    candidates: list[dict[str, Any]] = objects_manager.find_objects(
        {CmdbObjectKey.PUBLIC_ID: subnet_public_id},
        as_dict=True,
        projection=IPAM_OBJECT_CHECK_PROJECTION,
    )

    if not candidates:
        abort(404, SUBNET_NOT_FOUND_MSG.format(subnet_id=subnet_public_id))

    candidate: dict[str, Any] = candidates[0]

    if candidate.get(CmdbObjectKey.TYPE_ID) != subnet_type_id:
        abort(400, NOT_A_SUBNET_MSG.format(subnet_id=subnet_public_id))

    return candidate


def parse_subnet_network(subnet_obj: dict[str, Any]) -> Network:
    """
    Returns the parsed network of a SUBNET CmdbObject or aborts when the CIDR is broken

    Reads the subnet's 'dg-network-range' field via ``extract_field_value`` and runs
    ``parse_cidr`` against it. A missing, non-string, or unparsable CIDR aborts HTTP 400 -
    the unassign flow cannot validate IP-in-subnet constraints without a parsed network

    Args:
        subnet_obj (dict[str, Any]): The SUBNET CmdbObject document

    Returns:
        Network: Parsed IPv4 or IPv6 network
    """
    raw_cidr: Any = extract_field_value(subnet_obj, SubnetField.NETWORK_RANGE)

    if not isinstance(raw_cidr, str):
        abort(400, SUBNET_RANGE_MISSING_MSG)

    network: Network | None = parse_cidr(raw_cidr)

    if network is None:
        abort(400, SUBNET_RANGE_NOT_CANONICAL_MSG.format(raw_cidr=raw_cidr))

    return network


def load_interface_owners(
    objects_manager: ObjectsManager,
    subnet_public_id: int,
) -> list[dict[str, Any]]:
    """
    Loads every CmdbObject that has a dg-ipam-interface row referencing the subnet

    Spans every CmdbType because the dg-ipam-interface section template is global. The Mongo
    filter nests $elemMatch through multi_data_sections -> values -> data so only documents
    that actually carry a matching row are returned, even though the section template lives
    on many object types

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        subnet_public_id (int): public_id of the subnet whose interface owners should be loaded

    **Read whole, deliberately**: each document is rewritten (its interface rows cleared) and planned through
    ``plan_object_edit``, whose diff over the whole document is the version bump and the edit-log ``changes`` - a
    partial document would diff wrong

    Returns:
        list[dict[str, Any]]: Full CmdbObject documents (one per owner) carrying at least one
            dg-ipam-interface row that references this subnet
    """
    criteria: dict[str, Any] = {
        CmdbObjectKey.MULTI_DATA_SECTIONS: {
            '$elemMatch': {
                CmdbObjectMdsKey.SECTION_ID: IpamSection.INTERFACE,
                CmdbObjectMdsKey.VALUES: {
                    '$elemMatch': {
                        CmdbObjectMdsRowKey.DATA: {
                            '$elemMatch': {
                                CmdbObjectFieldKey.NAME: InterfaceField.SUBNET,
                                CmdbObjectFieldKey.VALUE: subnet_public_id,
                            },
                        },
                    },
                },
            },
        },
    }

    return objects_manager.find_objects(criteria, as_dict=True)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                      WRITES                                                          #
# -------------------------------------------------------------------------------------------------------------------- #
# Per-owner mutators keyed by unassign mode: each takes (owner_doc, subnet_id, target_ips) and
# returns (new_owner_doc, set_of_affected_ips). REFERENCE blanks the subnet ref; ROW drops the row
_OWNER_MUTATORS = {
    IpamUnassignMode.REFERENCE: clear_subnet_ref_in_owner,
    IpamUnassignMode.ROW: delete_subnet_rows_in_owner,
}


def build_owner_update(
    new_doc: dict[str, Any],
    new_version: str,
    edit_stamp: dict[str, Any],
) -> dict[str, Any]:
    """
    Builds the top-level keys an unassign writes onto one owner

    Only what the unassign changes: the owner's ``multi_data_sections``, its bumped version and the
    edit stamp. Written as a partial update, so the rest of the stored owner is left as it is

    Args:
        new_doc (dict[str, Any]): The owner with the unassign applied (from the mode's mutator)
        new_version (str): The version the unassign bumps the owner to
        edit_stamp (dict[str, Any]): ``last_edit_time`` / ``editor_id`` (see ``build_edit_stamp``)

    Returns:
        dict[str, Any]: The keys to ``$set`` on the stored owner
    """
    return {
        CmdbObjectKey.MULTI_DATA_SECTIONS.value: new_doc.get(CmdbObjectKey.MULTI_DATA_SECTIONS, []),
        CmdbObjectKey.VERSION.value: new_version,
        **edit_stamp,
    }


def owner_write_guard(owner: dict[str, Any]) -> dict[str, Any]:
    """
    The stored values an owner's unassign write requires, so it only lands on the owner it was planned from

    The write replaces the owner's whole ``multi_data_sections``, built from the read. Requiring the sections as read
    makes a concurrent edit of any row, by any writer, a miss rather than an overwrite - including a writer that does
    not bump ``version`` (the type-update propagation rewrites rows without it). Requiring the version as read keeps
    the bump and the change-log diff exact: they were computed from that version

    Args:
        owner (dict[str, Any]): The owner document as read

    Returns:
        dict[str, Any]: The ``expected`` values for ``ObjectsManager.update_object``
    """
    return {
        CmdbObjectKey.MULTI_DATA_SECTIONS.value: owner.get(CmdbObjectKey.MULTI_DATA_SECTIONS.value),
        CmdbObjectKey.VERSION.value: owner.get(CmdbObjectKey.VERSION.value),
    }


def resolve_owner_type(
    objects_manager: ObjectsManager,
    type_cache: dict[int, CmdbType | None],
    type_id: int,
) -> CmdbType | None:
    """
    The owner's CmdbType for the write guard, read once per type for the whole request

    Owners are of arbitrary types, but a request usually touches few of them

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects (and their types)
        type_cache (dict[int, CmdbType | None]): The types read so far in this request, filled here
        type_id (int): The owner's type_id

    Returns:
        CmdbType | None: The type, or None when it no longer exists (the guard then refuses the write)
    """
    if type_id not in type_cache:
        type_cache[type_id] = objects_manager.get_object_type(type_id)

    return type_cache[type_id]


def write_owner_unassign(
    objects_manager: ObjectsManager,
    owner: dict[str, Any],
    mutate: Callable[[dict[str, Any], int, set[str]], tuple[dict[str, Any], set[str]]],
    subnet_id: int,
    target_ips: set[str],
    request_user: CmdbUser,
    edit_stamp: dict[str, Any],
    type_cache: dict[int, CmdbType | None],
) -> tuple[PlannedEdit | None, set[str]]:
    """
    Unassigns the target rows of one owner with a compare-and-swap, planning again after a concurrent edit

    Each attempt plans the edit from the owner as last read and writes it only while the owner still holds what that
    plan was made from (``owner_write_guard``). A miss means another edit got there first: the owner is read again
    and the unassign planned again from what is stored now - which may leave nothing to do (another request
    unassigned the rows already, or the owner is gone). Past ``MAX_OWNER_WRITE_ATTEMPTS`` misses the request stops

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        owner (dict[str, Any]): The owner as first read
        mutate (Callable[...]): The mode's per-owner mutator (see ``_OWNER_MUTATORS``)
        subnet_id (int): public_id of the subnet whose interface rows are unassigned
        target_ips (set[str]): Canonical IP strings flagged for unassigning
        request_user (CmdbUser): User making the request (ACL and editor stamp)
        edit_stamp (dict[str, Any]): ``last_edit_time`` / ``editor_id`` for the write
        type_cache (dict[int, CmdbType | None]): The types read so far in this request

    Raises:
        HTTPException: 400 when the owner changed under every attempt (``OWNER_KEPT_CHANGING_MSG``)
        ObjectsManagerUpdateError: If the write failed
        AccessDeniedError: If the caller may not UPDATE the owner's type

    Returns:
        tuple[PlannedEdit | None, set[str]]: The plan that was written and the IPs it unassigned, or (None, empty)
            when nothing was left to write
    """
    public_id: int = owner[CmdbObjectKey.PUBLIC_ID]
    current: dict[str, Any] | None = owner

    for _attempt in range(MAX_OWNER_WRITE_ATTEMPTS):
        if current is None:
            return None, set()

        new_doc, affected = mutate(current, subnet_id, target_ips)

        if not affected:
            return None, set()

        plan: PlannedEdit = plan_object_edit(current, new_doc)
        type_id: int = current[CmdbObjectKey.TYPE_ID]

        written: bool = objects_manager.update_object(
            public_id,
            build_owner_update(new_doc, plan.version, edit_stamp),
            request_user,
            AccessControlPermission.UPDATE,
            partial=True,
            object_type=resolve_owner_type(objects_manager, type_cache, type_id),
            expected=owner_write_guard(current),
            stored_type_id=type_id,
        )

        if written:
            return plan, affected

        current = objects_manager.get_one(public_id)

    abort(400, OWNER_KEPT_CHANGING_MSG.format(owner_id=public_id, attempts=MAX_OWNER_WRITE_ATTEMPTS))


def apply_unassign_to_owners(
    objects_manager: ObjectsManager,
    owner_docs: list[dict[str, Any]],
    subnet_id: int,
    target_ips: set[str],
    request_user: CmdbUser,
    mode: str,
    on_write: ObjectWriteCallback | None = None,
) -> int:
    """
    Applies the chosen unassign ``mode`` to each owner's matching rows and returns the affected count

    Iterates the candidate owners and writes each through ``write_owner_unassign``: the mode's mutator
    (REFERENCE -> ``clear_subnet_ref_in_owner``, ROW -> ``delete_subnet_rows_in_owner``) builds the owner's new
    ``multi_data_sections``, and a partial, compare-and-swap ``update_object`` writes them with the version bump and
    the edit stamp - only while the owner still holds the sections and version the plan was made from, re-planned
    from a fresh read after a concurrent edit. An owner with nothing left to unassign incurs no write.
    ``update_object`` applies the ACL with the owner's type, read once per type for the request, so a user without
    UPDATE permission on an owner's CmdbType fails on that owner.

    **The per-owner writes are sequential and not wrapped in a cross-owner transaction**, so a
    failure part-way leaves the owners before it written. Those owners are still handed to
    ``on_write`` - from a ``finally`` - so the edits that did happen get their change log and webhook

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        owner_docs (list[dict[str, Any]]): Candidate owners (typically from ``load_interface_owners``)
        subnet_id (int): public_id of the subnet whose interface rows are unassigned
        target_ips (set[str]): Canonical IP strings flagged for unassigning
        request_user (CmdbUser): User making the request; forwarded to update_object for ACL and
            stamped as editor
        mode (str): An IpamUnassignMode value selecting the per-owner mutation
        on_write (ObjectWriteCallback | None): Receives every written owner after the writes. None
            skips the read-back

    Returns:
        int: Total number of dg-ipam-interface rows affected across all touched owners
    """
    mutate = _OWNER_MUTATORS[mode]
    total_affected: int = 0
    edit_stamp: dict[str, Any] = build_edit_stamp(request_user)
    type_cache: dict[int, CmdbType | None] = {}
    written: dict[int, PlannedEdit] = {}

    try:
        for owner in owner_docs:
            plan, affected = write_owner_unassign(
                objects_manager, owner, mutate, subnet_id, target_ips, request_user, edit_stamp, type_cache,
            )

            if plan is None:
                continue

            written[owner[CmdbObjectKey.PUBLIC_ID]] = plan
            total_affected += len(affected)
    finally:
        hand_over_object_writes(objects_manager, written, on_write)

    return total_affected


def clear_subnet_ref_in_owners(
    objects_manager: ObjectsManager,
    owner_docs: list[dict[str, Any]],
    subnet_id: int,
    target_ips: set[str],
    request_user: CmdbUser,
    on_write: ObjectWriteCallback | None = None,
) -> int:
    """
    Clears the subnet ref on each owner's matching rows (the REFERENCE mode of unassign)

    Thin wrapper over ``apply_unassign_to_owners`` bound to IpamUnassignMode.REFERENCE; see that
    helper for the per-owner write semantics

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        owner_docs (list[dict[str, Any]]): Candidate owners (typically from ``load_interface_owners``)
        subnet_id (int): public_id of the subnet whose interface rows should have their ref cleared
        target_ips (set[str]): Canonical IP strings flagged for clearing
        request_user (CmdbUser): User making the request; forwarded to update_object for ACL
        on_write (ObjectWriteCallback | None): Receives every written owner. Defaults to None

    Returns:
        int: Total number of dg-ipam-interface rows whose subnet ref was cleared
    """
    return apply_unassign_to_owners(
        objects_manager, owner_docs, subnet_id, target_ips, request_user, IpamUnassignMode.REFERENCE,
        on_write,
    )


# -------------------------------------------------------------------------------------------------------------------- #
#                                                   ORCHESTRATOR                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
def _resolve_unassign_mode(raw_mode: Any) -> str:
    """
    Normalizes the request 'mode' value to an IpamUnassignMode, defaulting to REFERENCE

    A missing / empty mode falls back to REFERENCE (clear the subnet ref),
    a recognised value is returned as-is, and any other value aborts HTTP 400

    Args:
        raw_mode (Any): The raw value read off the JSON body for the 'mode' key

    Returns:
        str: A valid IpamUnassignMode value
    """
    if raw_mode is None or raw_mode == '':
        return IpamUnassignMode.REFERENCE

    if not IpamUnassignMode.is_valid(raw_mode):
        abort(400, UNASSIGN_MODE_INVALID_MSG.format(
            raw_mode=raw_mode, reference=IpamUnassignMode.REFERENCE.value, row=IpamUnassignMode.ROW.value,
        ))

    return IpamUnassignMode(raw_mode)


def unassign_ips_from_subnet(
    objects_manager: ObjectsManager,
    types_manager: TypesManager,
    subnet_public_id: int,
    raw_ips: Any,
    request_user: CmdbUser,
    raw_mode: Any = None,
    on_write: ObjectWriteCallback | None = None,
) -> dict[str, Any]:
    """
    Validates the payload and unassigns the matching dg-ipam-interface rows in the chosen mode

    Pipeline:
      1. Confirm ``subnet_public_id`` resolves to a SUBNET CmdbObject and parse its CIDR
         (aborts 400/404 on missing / wrong type / broken CIDR)
      2. Resolve ``raw_mode`` to an IpamUnassignMode (default REFERENCE; aborts 400 on an
         unknown value)
      3. Coerce ``raw_ips`` to a deduplicated list of canonical IP strings, each within the
         subnet (aborts 400 on bad shape / non-string / non-canonical / out-of-network)
      4. Load every CmdbObject with a dg-ipam-interface row referencing this subnet
      5. Collect the set of IPs currently assigned within the subnet; if any requested IP is
         absent, abort 400 with the offending IPs - the call is validate-all-or-nothing, so
         no write happens
      6. Otherwise apply the mode via ``apply_unassign_to_owners``: REFERENCE flips each matching
         row's ``dg-interface-subnet`` value to None (the row, IP and MAC are kept); ROW deletes
         the whole matching row. Each owner is written via a partial ``update_object`` (the
         ACL) carrying its version bump and edit stamp, and handed to ``on_write`` afterwards. The
         mode applies to every IP, not per row

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        subnet_public_id (int): public_id of the SUBNET to unassign rows from
        raw_ips (Any): The raw value read off the JSON body for the 'ips' key
        request_user (CmdbUser): User making the request; forwarded to update_object for ACL
        raw_mode (Any): The raw value read off the JSON body for the 'mode' key (default REFERENCE)
        on_write (ObjectWriteCallback | None): Receives every written owner after the writes - the
            route writes its change log and webhook from it. None skips the read-back

    Returns:
        dict[str, Any]: {'ips': [str, ...], 'mode': str, 'unassigned_count': int} where 'ips'
            echoes the deduplicated request order, 'mode' echoes the resolved mode and
            'unassigned_count' is the number of dg-ipam-interface rows affected
    """
    abort_if_too_many_ips(raw_ips)

    subnet_obj: dict[str, Any] = assert_subnet_exists(objects_manager, types_manager, subnet_public_id)
    network: Network = parse_subnet_network(subnet_obj)
    mode: str = _resolve_unassign_mode(raw_mode)
    ips: list[str] = normalize_ip_list(raw_ips, network)

    owner_docs: list[dict[str, Any]] = load_interface_owners(objects_manager, subnet_public_id)
    present_ips: set[str] = collect_present_ips(owner_docs, subnet_public_id)
    missing: list[str] = diff_missing_ips(ips, present_ips)

    if missing:
        abort(400, IPS_NOT_ASSIGNED_MSG.format(missing=missing, subnet_id=subnet_public_id))

    unassigned_count: int = apply_unassign_to_owners(
        objects_manager, owner_docs, subnet_public_id, set(ips), request_user, mode, on_write,
    )

    return {
        IpamUnassignKey.IPS: ips,
        IpamUnassignKey.MODE: mode,
        IpamUnassignKey.UNASSIGNED_COUNT: unassigned_count,
    }
