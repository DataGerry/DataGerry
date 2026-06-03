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

Per-owner write semantics: one ``objects_manager.update_object`` per affected owner. That
preserves ACL checks (the caller must have UPDATE permission on each owner's CmdbType),
per-object versioning bumps and post-update hooks. The trade-off is N round-trips instead
of one bulk write, which is acceptable for a UI-driven multi-select that's bounded in size

Validate-all-or-nothing: if any requested IP is not currently assigned to this subnet, the
orchestrator aborts HTTP 400 with the offending IPs and no write happens. Mirrors the
all-or-nothing semantics of the supernet 'unassign subnets' route
"""
from typing import Any

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
)
from cmdb.models.user_model import CmdbUser
from cmdb.security.acl.permission import AccessControlPermission
from cmdb.framework.ipam.cidr import Network, parse_cidr, parse_ip, ip_in_network
from cmdb.framework.ipam.references import resolve_special_type_id
# -------------------------------------------------------------------------------------------------------------------- #


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  PURE HELPERS                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
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
        abort(400, f"'{IpamUnassignKey.IPS}' must be a non-empty list of IP strings!")

    deduped: list[str] = []
    seen: set[str] = set()

    for entry in raw:
        if not isinstance(entry, str):
            abort(400, f"'{IpamUnassignKey.IPS}' contains a non-string entry: {entry!r}")

        parsed = parse_ip(entry)

        if parsed is None:
            abort(400, f"'{IpamUnassignKey.IPS}' contains an invalid IP address: {entry!r}")

        if not ip_in_network(parsed, network):
            abort(400, f"IP {entry!r} is outside subnet {network}!")

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
    exists. Returns the subnet document on success so the orchestrator can parse its CIDR

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        subnet_public_id (int): public_id the caller named as the subnet to unassign from

    Returns:
        dict[str, Any]: The SUBNET CmdbObject document
    """
    subnet_type_id: int | None = resolve_special_type_id(types_manager, SpecialType.SUBNET)

    if subnet_type_id is None:
        abort(400, "No SUBNET CmdbType is defined; cannot unassign interface rows!")

    candidates: list[dict[str, Any]] = objects_manager.find_objects(
        {CmdbObjectKey.PUBLIC_ID: subnet_public_id},
        as_dict=True,
    )

    if not candidates:
        abort(404, f"Subnet with public_id {subnet_public_id} was not found!")

    candidate: dict[str, Any] = candidates[0]

    if candidate.get(CmdbObjectKey.TYPE_ID) != subnet_type_id:
        abort(400, f"Object with public_id {subnet_public_id} is not a SUBNET!")

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
        abort(400, "Subnet has no network range defined; cannot unassign interface rows!")

    network: Network | None = parse_cidr(raw_cidr)

    if network is None:
        abort(400, f"Subnet network range {raw_cidr!r} is not a canonical CIDR; cannot unassign!")

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
def clear_subnet_ref_in_owners(
    objects_manager: ObjectsManager,
    owner_docs: list[dict[str, Any]],
    subnet_id: int,
    target_ips: set[str],
    request_user: CmdbUser,
) -> int:
    """
    Clears the subnet ref on each owner's matching rows and returns the total cleared-row count

    Iterates the candidate owners, runs ``clear_subnet_ref_in_owner`` to build the post-clear
    doc, and only calls ``objects_manager.update_object`` for owners that actually had at
    least one row's subnet ref cleared (so an owner that referenced this subnet only at non-
    target IPs is skipped and incurs no write). Each ``update_object`` call goes through the
    standard ACL / version / hook path so a user without UPDATE permission on the owner's
    CmdbType fails fast

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        owner_docs (list[dict[str, Any]]): Candidate owners (typically from
            ``load_interface_owners``)
        subnet_id (int): public_id of the subnet whose interface rows should have their ref
            cleared
        target_ips (set[str]): Canonical IPv4 strings flagged for clearing
        request_user (CmdbUser): User making the request; forwarded to update_object for ACL

    Returns:
        int: Total number of dg-ipam-interface rows whose subnet ref was cleared across all
            touched owners
    """
    total_cleared: int = 0

    for owner in owner_docs:
        new_doc, cleared = clear_subnet_ref_in_owner(owner, subnet_id, target_ips)

        if not cleared:
            continue

        objects_manager.update_object(
            owner[CmdbObjectKey.PUBLIC_ID],
            new_doc,
            request_user,
            AccessControlPermission.UPDATE,
        )
        total_cleared += len(cleared)

    return total_cleared


# -------------------------------------------------------------------------------------------------------------------- #
#                                                   ORCHESTRATOR                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
def unassign_ips_from_subnet(
    objects_manager: ObjectsManager,
    types_manager: TypesManager,
    subnet_public_id: int,
    raw_ips: Any,
    request_user: CmdbUser,
) -> dict[str, Any]:
    """
    Validates the payload and clears the subnet reference on the matching dg-ipam-interface rows

    Pipeline:
      1. Confirm ``subnet_public_id`` resolves to a SUBNET CmdbObject and parse its CIDR
         (aborts 400/404 on missing / wrong type / broken CIDR)
      2. Coerce ``raw_ips`` to a deduplicated list of canonical IPv4 strings, each within the
         subnet (aborts 400 on bad shape / non-string / non-canonical / out-of-network)
      3. Load every CmdbObject with a dg-ipam-interface row referencing this subnet
      4. Collect the set of IPs currently assigned within the subnet; if any requested IP is
         absent, abort 400 with the offending IPs - the call is validate-all-or-nothing, so
         no write happens
      5. Otherwise call ``clear_subnet_ref_in_owners`` to flip the ``dg-interface-subnet``
         value to None on each matching row, each via ``objects_manager.update_object`` so
         ACL / versioning / hooks all run. The rows themselves and their IP / MAC values are
         preserved

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        subnet_public_id (int): public_id of the SUBNET to unassign rows from
        raw_ips (Any): The raw value read off the JSON body for the 'ips' key
        request_user (CmdbUser): User making the request; forwarded to update_object for ACL

    Returns:
        dict[str, Any]: {'ips': [str, ...], 'unassigned_count': int} where 'ips' echoes the
            deduplicated request order and 'unassigned_count' is the number of
            dg-ipam-interface rows whose subnet reference was cleared
    """
    subnet_obj: dict[str, Any] = assert_subnet_exists(objects_manager, types_manager, subnet_public_id)
    network: Network = parse_subnet_network(subnet_obj)
    ips: list[str] = normalize_ip_list(raw_ips, network)

    owner_docs: list[dict[str, Any]] = load_interface_owners(objects_manager, subnet_public_id)
    present_ips: set[str] = collect_present_ips(owner_docs, subnet_public_id)
    missing: list[str] = diff_missing_ips(ips, present_ips)

    if missing:
        abort(
            400,
            f"Cannot unassign IPs {missing} - they are not currently assigned to subnet"
            f" {subnet_public_id}!",
        )

    unassigned_count: int = clear_subnet_ref_in_owners(
        objects_manager, owner_docs, subnet_public_id, set(ips), request_user,
    )

    return {
        IpamUnassignKey.IPS: ips,
        IpamUnassignKey.UNASSIGNED_COUNT: unassigned_count,
    }
