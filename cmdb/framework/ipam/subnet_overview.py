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
Builds the data payload for the SUBNET 'IP-Übersicht' view

The frontend renders KPI counters (total / used / free) plus a paginated, IP-sorted table
where each address of the subnet appears as either an 'assigned' or 'free' row. This module
exposes pure helpers (CIDR math, page slicing, row shaping) plus a thin DB orchestrator that
loads the subnet, the interface rows that reference it, and the type labels / summary lines
needed for the page slice
"""
from ipaddress import IPv4Address, IPv4Network
from typing import Any

from flask import abort

from cmdb.manager import ObjectsManager, TypesManager
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.special_type_model.ipam_constants import (
    SubnetField,
    InterfaceField,
    IpamSection,
    IpamDistributionLimits,
    IpamPagination,
    IpamOverviewKey,
    IpamRowStatus,
    IpamBucketLabel,
    IpamSortColumn,
    IpamSortDirection,
)
from cmdb.framework.ipam.cidr import (
    parse_cidr,
    parse_ipv4,
    ip_in_network,
    total_address_count,
    assignable_address_count,
    first_assignable_int,
)
from cmdb.models.object_model import (
    CmdbObjectKey,
    CmdbObjectFieldKey,
    CmdbObjectMdsKey,
    CmdbObjectMdsRowKey,
    extract_field_value,
)
from cmdb.framework.ipam.pagination import clamp_page
from cmdb.framework.ipam.references import resolve_special_type_id, load_vlans_by_subnets
from cmdb.framework.ipam.search import active_search
# -------------------------------------------------------------------------------------------------------------------- #


class _AssignedField:
    """
    Internal dict keys for the per-IP map produced by _load_assigned_rows_map

    Not part of the JSON output shape (the orchestrator translates these into the
    IpamOverviewKey-keyed wire format at the assembly step) so they don't belong in
    IpamOverviewKey. Kept here to avoid bare string literals in this module
    """
    OBJECT_ID: str = 'object_id'
    TYPE_ID: str = 'type_id'
    MAC: str = 'mac'


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  PURE HELPERS                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
def _page_slice_ips(network: IPv4Network, page: int, page_size: int) -> list[str]:
    """
    Returns the IP strings for one page of a subnet's assignable addresses

    The slice covers exactly the addresses the interface validator would accept: for /30 and
    shorter the network and broadcast addresses are skipped, for /31 both endpoints are
    included (RFC 3021 point-to-point), and for /32 the single host address is included. The
    slice is computed in O(page_size) without iterating the whole subnet, so /16 and larger
    subnets paginate cheaply

    Args:
        network (IPv4Network): The parsed subnet network
        page (int): 1-based page number
        page_size (int): Number of IPs per page

    Returns:
        list[str]: IP strings for the requested page; empty when the page is past the end of
            the assignable range
    """
    first: int = first_assignable_int(network)
    total: int = assignable_address_count(network)
    start_offset: int = (page - 1) * page_size

    if start_offset >= total:
        return []

    end_offset: int = min(start_offset + page_size, total)

    return [str(IPv4Address(first + i)) for i in range(start_offset, end_offset)]


def _resolve_assigned_summary_lines(
    candidate_ips: list[str],
    assigned: dict[str, dict[str, Any]],
    objects_manager: ObjectsManager,
) -> dict[str, str]:
    """
    Batch-resolves summary lines for the assigned IPs among the candidates, keyed by IP

    Pulled out as its own helper because the bulk lookup is only needed when sort by
    assigned_to is active. Collects the distinct owner public_ids referenced by the assigned
    candidates and forwards them to ``ObjectsManager.get_summary_lines_lookup`` in one
    round-trip, then maps the resolved summary line back onto every IP that pointed at the
    same owner. Free IPs are skipped silently. Owners that no longer resolve (deleted /
    drifted) leave the IP out of the returned mapping; callers downstream treat a missing
    key as "no summary line available", which slots into the NULLS-LAST sort policy

    Args:
        candidate_ips (list[str]): Canonical IP strings under consideration
        assigned (dict[str, dict[str, Any]]): {ip_str: row_info} as produced by
            ``_load_assigned_rows_map``
        objects_manager (ObjectsManager): db interface for CmdbObjects

    Returns:
        dict[str, str]: {ip_str: summary_line} for every candidate IP whose owner resolved
    """
    owner_ids: list[int] = [
        assigned[ip][_AssignedField.OBJECT_ID]
        for ip in candidate_ips
        if ip in assigned and isinstance(assigned[ip].get(_AssignedField.OBJECT_ID), int)
    ]

    if not owner_ids:
        return {}

    summaries: dict[int, str] = objects_manager.get_summary_lines_lookup(owner_ids, with_type=True)

    return {
        ip: summaries[assigned[ip][_AssignedField.OBJECT_ID]]
        for ip in candidate_ips
        if ip in assigned and assigned[ip].get(_AssignedField.OBJECT_ID) in summaries
    }


def _compute_sort_key(
    ip_str: str,
    sort_col: IpamSortColumn,
    assigned: dict[str, dict[str, Any]],
    type_meta: dict[int, dict[str, Any]],
    summary_lines: dict[str, str],
) -> Any:
    """
    Returns the comparison key for one IP under the chosen sort column, or None when absent

    Returning None signals "this row has no value for the requested column" - the calling
    sorter places those rows in the NULLS LAST partition regardless of direction. String
    keys (type label, summary line, MAC) are lower-cased so the alphabetic sort is case-
    insensitive; IP and STATUS keys preserve their natural comparable form (IP as integer
    so 10.0.0.10 sorts after 10.0.0.2, STATUS as the wire-format string)

    Args:
        ip_str (str): Canonical IP string of the row being keyed
        sort_col (IpamSortColumn): The chosen sort column (must not be None - the orchestrator
            short-circuits before calling this helper when sort is off)
        assigned (dict[str, dict[str, Any]]): {ip_str: row_info} as produced by
            ``_load_assigned_rows_map``
        type_meta (dict[int, dict[str, Any]]): {type_id: {'label', 'ci_explorer_color'}} as
            produced by ``_resolve_type_meta``
        summary_lines (dict[str, str]): {ip_str: summary_line} produced by
            ``_resolve_assigned_summary_lines``; empty when the sort column is not ASSIGNED_TO

    Returns:
        Any: Comparable key value, or None when the row has no value for the requested column
    """
    info: dict[str, Any] | None = assigned.get(ip_str)

    if sort_col == IpamSortColumn.IP:
        return int(IPv4Address(ip_str))

    if sort_col == IpamSortColumn.STATUS:
        return IpamRowStatus.ASSIGNED if info is not None else IpamRowStatus.FREE

    if sort_col == IpamSortColumn.TYPE:
        if info is None:
            return None

        type_id: Any = info.get(_AssignedField.TYPE_ID)
        meta: dict[str, Any] | None = type_meta.get(type_id) if isinstance(type_id, int) else None
        label: Any = meta.get(IpamOverviewKey.LABEL) if meta else None

        return label.lower() if isinstance(label, str) else None

    if sort_col == IpamSortColumn.ASSIGNED_TO:
        summary: Any = summary_lines.get(ip_str)

        return summary.lower() if isinstance(summary, str) and summary else None

    if sort_col == IpamSortColumn.MAC_ADDRESS:
        if info is None:
            return None

        mac: Any = info.get(_AssignedField.MAC)

        return mac.lower() if isinstance(mac, str) and mac else None

    return None


def _sort_candidate_ips(
    candidate_ips: list[str],
    sort_col: IpamSortColumn,
    sort_dir: IpamSortDirection,
    assigned: dict[str, dict[str, Any]],
    type_meta: dict[int, dict[str, Any]],
    objects_manager: ObjectsManager,
) -> list[str]:
    """
    Sorts the candidate IPs by the chosen column and direction, NULLS LAST in either direction

    The generic path computes the sort key for every candidate once, splits the candidates
    into a 'has value' partition and a 'no value' partition, sorts the first by its key
    (reversed when DESC), then concatenates so rows missing a value always trail. Two
    optimizations short-circuit the generic path:

      * Sort by IP uses a direct ``sorted(..., key=int(IPv4Address(ip)))`` call. Every
        candidate IP is by definition a valid canonical address, so no NULLS LAST split is
        needed and the per-IP integer conversion happens exactly once
      * Sort by ASSIGNED_TO skips the summary-line batch fetch entirely when no candidate
        is currently assigned. The batch call (and the find_objects /
        get_many_from_other_collection pair it issues) is bypassed - the generic loop then
        produces an all-NULL partition that sorts to the same final order

    For other columns the keys are answered from the in-memory ``assigned`` / ``type_meta``
    maps so no extra DB work happens

    Args:
        candidate_ips (list[str]): Canonical IP strings to order
        sort_col (IpamSortColumn): The chosen sort column
        sort_dir (IpamSortDirection): The chosen sort direction
        assigned (dict[str, dict[str, Any]]): {ip_str: row_info} as produced by
            ``_load_assigned_rows_map``
        type_meta (dict[int, dict[str, Any]]): {type_id: {'label', 'ci_explorer_color'}} as
            produced by ``_resolve_type_meta``
        objects_manager (ObjectsManager): db interface for CmdbObjects, used only to batch
            summary lines when sort_col == ASSIGNED_TO and at least one candidate is assigned

    Returns:
        list[str]: Candidate IPs ordered by key with NULL-keyed rows trailing the partition
    """
    reverse: bool = sort_dir == IpamSortDirection.DESC

    if sort_col == IpamSortColumn.IP:
        return sorted(candidate_ips, key=lambda ip: int(IPv4Address(ip)), reverse=reverse)

    summary_lines: dict[str, str] = (
        _resolve_assigned_summary_lines(candidate_ips, assigned, objects_manager)
        if sort_col == IpamSortColumn.ASSIGNED_TO and any(ip in assigned for ip in candidate_ips)
        else {}
    )

    has_value: list[tuple[Any, str]] = []
    no_value: list[str] = []

    for ip in candidate_ips:
        key: Any = _compute_sort_key(ip, sort_col, assigned, type_meta, summary_lines)

        if key is None:
            no_value.append(ip)
        else:
            has_value.append((key, ip))

    has_value.sort(key=lambda kv: kv[0], reverse=reverse)

    return [ip for _, ip in has_value] + no_value


def _resolve_candidate_ips(
    network: IPv4Network,
    search: str,
    sort_col: IpamSortColumn | None,
    sort_dir: IpamSortDirection,
    assigned: dict[str, dict[str, Any]],
    type_meta: dict[int, dict[str, Any]],
    objects_manager: ObjectsManager,
) -> list[str] | None:
    """
    Selects the candidate IP list for the IP-table page, or None to signal the lazy path

    Returning None means "no search is active AND the chosen sort is the natural ascending IP
    order (or no sort is requested)" - the orchestrator then paginates straight from
    ``_page_slice_ips`` without materializing the full assignable range. Otherwise the helper
    builds the candidate list explicitly (search-filtered if a search is active, otherwise
    the full assignable list) and applies the sort when ``sort_col`` is not None

    Args:
        network (IPv4Network): The parsed subnet network
        search (str): Raw search query as received by the caller
        sort_col (IpamSortColumn | None): Chosen sort column, or None when no sort is requested
        sort_dir (IpamSortDirection): Chosen sort direction (ASC when sort_col is None)
        assigned (dict[str, dict[str, Any]]): {ip_str: row_info} as produced by
            ``_load_assigned_rows_map``
        type_meta (dict[int, dict[str, Any]]): {type_id: {'label', 'ci_explorer_color'}} as
            produced by ``_resolve_type_meta``
        objects_manager (ObjectsManager): db interface for CmdbObjects (used by the
            assigned_to summary-line batch when that sort is active)

    Returns:
        list[str] | None: Candidate IPs in final order, or None to signal the lazy path
    """
    needle: str | None = active_search(search)
    natural_order: bool = sort_col is None or (
        sort_col == IpamSortColumn.IP and sort_dir == IpamSortDirection.ASC
    )

    if needle is None and natural_order:
        return None

    candidates: list[str] = (
        list_assignable_ips_matching_substring(network, needle)
        if needle is not None
        else list_all_assignable_ips(network)
    )

    if sort_col is None:
        return candidates

    return _sort_candidate_ips(candidates, sort_col, sort_dir, assigned, type_meta, objects_manager)


def _compose_ip_row(
    ip_str: str,
    assigned: dict[str, dict[str, Any]],
    type_meta: dict[int, dict[str, Any]],
    objects_manager: ObjectsManager,
) -> dict[str, Any]:
    """
    Shapes one IP-table row, returning either the assigned or the free variant

    Branches once on the presence of the IP in the assigned map. For an assigned IP the
    helper resolves the summary line via ``objects_manager.get_summary_line`` and shapes the
    type_info triple from ``type_meta`` (any missing label / color comes through as None).
    For a free IP it returns the free-row shape directly. Keeping this composition in one
    function lets ``build_subnet_overview`` build the page-rows as a single list comprehension

    Args:
        ip_str (str): The canonical IP string this row represents
        assigned (dict[str, dict[str, Any]]): {ip_str: row_info} as produced by
            ``_load_assigned_rows_map``
        type_meta (dict[int, dict[str, Any]]): {type_id: {'label', 'ci_explorer_color'}} as
            produced by ``_resolve_type_meta``
        objects_manager (ObjectsManager): db interface for CmdbObjects (used to fetch the
            summary line for assigned rows)

    Returns:
        dict[str, Any]: An assigned or free row shape as produced by ``_compose_assigned_row``
            / ``_compose_free_row``
    """
    info: dict[str, Any] | None = assigned.get(ip_str)

    if info is None:
        return _compose_free_row(ip_str)

    summary_line: str = objects_manager.get_summary_line(info[_AssignedField.OBJECT_ID], with_type=True)

    type_id: Any = info[_AssignedField.TYPE_ID]
    type_entry: dict[str, Any] | None = type_meta.get(type_id) if type_id is not None else None
    type_info: dict[str, Any] | None = (
        {
            CmdbObjectKey.PUBLIC_ID: type_id,
            IpamOverviewKey.LABEL: type_entry.get(IpamOverviewKey.LABEL) if type_entry else None,
            IpamOverviewKey.CI_EXPLORER_COLOR: (
                type_entry.get(IpamOverviewKey.CI_EXPLORER_COLOR) if type_entry else None
            ),
        }
        if type_id is not None
        else None
    )

    return _compose_assigned_row(
        ip_str,
        type_info,
        {
            CmdbObjectKey.PUBLIC_ID: info[_AssignedField.OBJECT_ID],
            IpamOverviewKey.SUMMARY_LINE: summary_line,
        },
        info[_AssignedField.MAC],
    )


def _build_ips_block(
    network: IPv4Network,
    assignable: int,
    page: int,
    page_size: int,
    candidates: list[str] | None,
    assigned: dict[str, dict[str, Any]],
    type_meta: dict[int, dict[str, Any]],
    objects_manager: ObjectsManager,
) -> dict[str, Any]:
    """
    Builds the 'ips' page block (page, page_size, total, rows) for the IP-Übersicht payload

    Splits on whether the caller pre-resolved the candidate IP list. ``candidates is None``
    signals the lazy path: pagination uses ``_page_slice_ips`` against the full assignable
    range so a large subnet does not materialize its IPs in memory, and 'total' equals the
    subnet's assignable count. A non-None ``candidates`` is the final candidate order
    (after search filtering and / or sort) and pagination slices it directly with 'total'
    set to the candidate count. Either way each IP on the page is shaped via
    ``_compose_ip_row`` so the assigned-vs-free row composition stays encapsulated

    Args:
        network (IPv4Network): The parsed subnet network
        assignable (int): Assignable address count of the subnet (used only on the lazy path)
        page (int): 1-based page number; clamped server-side
        page_size (int): Page size; clamped server-side
        candidates (list[str] | None): Pre-resolved candidate IP list (search-filtered and / or
            sorted) or None to signal the lazy ascending-IP path
        assigned (dict[str, dict[str, Any]]): {ip_str: row_info} as produced by
            ``_load_assigned_rows_map``
        type_meta (dict[int, dict[str, Any]]): {type_id: {'label', 'ci_explorer_color'}} as
            produced by ``_resolve_type_meta``
        objects_manager (ObjectsManager): db interface for CmdbObjects (used by
            ``_compose_ip_row`` for assigned-row summary lines)

    Returns:
        dict[str, Any]: {page, page_size, total, rows} block ready to drop under the 'ips'
            key of the overview payload
    """
    if candidates is None:
        safe_page, safe_size = clamp_page(page, page_size, assignable)
        page_ips: list[str] = _page_slice_ips(network, safe_page, safe_size)
        ips_total: int = assignable
    else:
        safe_page, safe_size = clamp_page(page, page_size, len(candidates))
        start: int = (safe_page - 1) * safe_size
        page_ips = candidates[start:start + safe_size]
        ips_total = len(candidates)

    return {
        IpamOverviewKey.PAGE: safe_page,
        IpamOverviewKey.PAGE_SIZE: safe_size,
        IpamOverviewKey.TOTAL: ips_total,
        IpamOverviewKey.ROWS: [
            _compose_ip_row(ip, assigned, type_meta, objects_manager) for ip in page_ips
        ],
    }


def _parse_sort_args(
    raw_sort: str,
    raw_order: str,
) -> tuple[IpamSortColumn | None, IpamSortDirection]:
    """
    Validates and normalizes the route's 'sort' and 'order' query parameter strings

    Empty / whitespace ``raw_sort`` means "no sort param provided" - the helper returns
    ``(None, ASC)`` so the orchestrator stays on the lazy IP-ascending path. When a sort
    column is provided the order defaults to ASC if ``raw_order`` is empty / whitespace.
    Unknown sort column or unknown direction values are rejected with HTTP 400 so a FE
    typo surfaces immediately rather than silently degrading

    Args:
        raw_sort (str): Raw value of the ?sort= query param
        raw_order (str): Raw value of the ?order= query param

    Returns:
        tuple[IpamSortColumn | None, IpamSortDirection]: (sort column, sort direction).
            sort column is None when ``raw_sort`` is empty / whitespace; direction is the
            parsed value otherwise ASC
    """
    sort_value: str = (raw_sort or '').strip()
    order_value: str = (raw_order or '').strip()

    if not sort_value:
        return None, IpamSortDirection.ASC

    if not IpamSortColumn.is_valid(sort_value):
        abort(400, f"Unknown sort column: '{sort_value}'!")

    if order_value and not IpamSortDirection.is_valid(order_value):
        abort(400, f"Unknown sort direction: '{order_value}'!")

    direction: IpamSortDirection = (
        IpamSortDirection(order_value) if order_value else IpamSortDirection.ASC
    )

    return IpamSortColumn(sort_value), direction


def list_all_assignable_ips(network: IPv4Network) -> list[str]:
    """
    Returns every assignable IP address of a subnet as a canonical string in ascending order

    Same address-skipping policy as ``_page_slice_ips`` and
    ``list_assignable_ips_matching_substring``: /30 and shorter skip the network and
    broadcast addresses, /31 includes both endpoints, /32 includes the single host. The
    returned list materializes the full range; callers should reach for this only when sort
    or other operations need the whole set in memory

    Args:
        network (IPv4Network): The parsed subnet network

    Returns:
        list[str]: Canonical IP strings in ascending order; length equals
            ``assignable_address_count(network)``
    """
    first: int = first_assignable_int(network)
    total: int = assignable_address_count(network)

    return [str(IPv4Address(first + offset)) for offset in range(total)]


def list_assignable_ips_matching_substring(network: IPv4Network, needle: str) -> list[str]:
    """
    Returns the canonical IP strings of a subnet's assignable addresses that contain ``needle``

    Walks the subnet's assignable range exactly once. The same address-skipping policy
    ``_page_slice_ips`` uses applies here: for /30 and shorter the network and broadcast
    addresses are skipped, /31 includes both endpoints, /32 includes the single host. The
    matcher is a case-insensitive substring test against the canonical dotted-quad string,
    so "10.0.0" matches every 10.0.0.x address and also any other address whose canonical
    form contains "10.0.0" as a substring

    For a /16 the scan is ~65k iterations, sub-millisecond on modern hardware; very large
    subnets pay proportional cost but the matcher is only invoked when search is active.
    The caller is responsible for stripping / length-gating the raw search query (see
    ``active_search``) - this helper takes the already-normalized needle

    Args:
        network (IPv4Network): The parsed subnet network
        needle (str): The substring to match against canonical IP strings; already stripped
            and known to be active

    Returns:
        list[str]: Matching canonical IP strings in ascending IP order; empty when no
            assignable address contains the needle
    """
    first: int = first_assignable_int(network)
    total: int = assignable_address_count(network)
    lowered_needle: str = needle.lower()

    matches: list[str] = []

    for offset in range(total):
        ip_str: str = str(IPv4Address(first + offset))

        if lowered_needle in ip_str.lower():
            matches.append(ip_str)

    return matches


def _compose_assigned_row(
    ip_str: str,
    type_info: dict[str, Any] | None,
    assigned_to: dict[str, Any],
    mac_address: str | None,
) -> dict[str, Any]:
    """
    Shapes one 'assigned' row of the IP table

    'type_info' carries the owning CmdbObject's CmdbType as a
    {public_id, label, ci_explorer_color} triple so two distinct types sharing the
    same label remain distinguishable on the frontend and the row can be tinted
    with the user-chosen CI-Explorer colour. The dict is built by the orchestrator:
    public_id is the raw type_id stored on the CmdbObject, label and
    ci_explorer_color come from the bulk type lookup and may be None when the type
    can no longer be resolved (e.g. it was deleted after the interface row was
    written) or when the type has no color set

    Args:
        ip_str (str): The IP address as canonical string
        type_info (dict[str, Any] | None): {'public_id', 'label', 'ci_explorer_color'}
            for the owning CmdbObject's CmdbType, or None when the type_id is missing
        assigned_to (dict[str, Any]): {'public_id', 'summary_line'} for the owning CmdbObject
        mac_address (str | None): MAC stored on the interface row, or None when absent

    Returns:
        dict[str, Any]: Row with keys ip, status, type_info, assigned_to, mac_address
    """
    return {
        IpamOverviewKey.IP: ip_str,
        IpamOverviewKey.STATUS: IpamRowStatus.ASSIGNED,
        IpamOverviewKey.TYPE_INFO: type_info,
        IpamOverviewKey.ASSIGNED_TO: assigned_to,
        IpamOverviewKey.MAC_ADDRESS: mac_address,
    }


def _compose_free_row(ip_str: str) -> dict[str, Any]:
    """
    Shapes one 'free' row of the IP table

    Args:
        ip_str (str): The IP address as canonical string

    Returns:
        dict[str, Any]: Row with status='free' and the assignment-related fields nulled
    """
    return {
        IpamOverviewKey.IP: ip_str,
        IpamOverviewKey.STATUS: IpamRowStatus.FREE,
        IpamOverviewKey.TYPE_INFO: None,
        IpamOverviewKey.ASSIGNED_TO: None,
        IpamOverviewKey.MAC_ADDRESS: None,
    }


def _extract_row_fields(row: dict[str, Any]) -> tuple[Any, Any, Any]:
    """
    Reads the (subnet_ref, ip, mac) triple from one dg-ipam-interface MDS row

    Args:
        row (dict[str, Any]): One entry from an MDS section's 'values' list

    Returns:
        tuple[Any, Any, Any]: (subnet ref, ip value, mac value); any field absent from the row
            comes back as None
    """
    subnet_ref: Any = None
    ip_value: Any = None
    mac_value: Any = None

    for entry in row.get(CmdbObjectMdsRowKey.DATA, []) or []:
        name: Any = entry.get(CmdbObjectFieldKey.NAME)

        if name == InterfaceField.SUBNET:
            subnet_ref = entry.get(CmdbObjectFieldKey.VALUE)
        elif name == InterfaceField.IP:
            ip_value = entry.get(CmdbObjectFieldKey.VALUE)
        elif name == InterfaceField.MAC:
            mac_value = entry.get(CmdbObjectFieldKey.VALUE)

    return subnet_ref, ip_value, mac_value


def _compute_grid_dimensions(total: int) -> tuple[int, int, int]:
    """
    Computes the grid layout (ranges, sectors per range, addresses per sector) for a subnet

    The grid scales to fit the subnet while honoring the IpamDistributionLimits caps. For
    subnets large enough to fill the cap the layout is the maximum 4 x 16 and only the sector
    size grows; for smaller subnets the column count and then the row count shrink so that no
    cell ever covers fewer than one address. The function assumes 'total' is a power of two
    (which holds for every valid IPv4 prefix), so the integer divisions are exact

    Args:
        total (int): Total address count of the subnet (network + broadcast included)

    Returns:
        tuple[int, int, int]: (ranges_count, sectors_per_range, sector_size); all zero when
            'total' is zero
    """
    if total <= 0:
        return 0, 0, 0

    ranges_count: int = min(IpamDistributionLimits.MAX_RANGES, total)
    sectors_per_range: int = min(IpamDistributionLimits.MAX_SECTORS_PER_RANGE, total // ranges_count)
    sector_size: int = total // (ranges_count * sectors_per_range)

    return ranges_count, sectors_per_range, sector_size


def _bucket_used_counts(
    assigned: dict[str, dict[str, Any]],
    network: IPv4Network,
    sector_size: int,
    total_cells: int,
) -> list[int]:
    """
    Tallies how many assigned IPs fall into each grid cell, indexed by global cell position

    Walks the assigned map once, computes each IP's offset from the subnet's network address,
    and integer-divides by 'sector_size' to land in the owning cell. IPs outside the subnet
    or unparsable are skipped defensively (the caller already filters in
    _load_assigned_rows_map but this stays robust against future drift). Complexity is O(used)
    not O(total_cells), so /1 stays cheap

    Args:
        assigned (dict[str, dict[str, Any]]): {ip_str: row_info} as produced by
            _load_assigned_rows_map
        network (IPv4Network): The parsed subnet network
        sector_size (int): Number of addresses each cell covers
        total_cells (int): Number of cells in the grid (ranges_count * sectors_per_range)

    Returns:
        list[int]: Used-IP count per cell, length == total_cells
    """
    counts: list[int] = [0] * total_cells

    if total_cells == 0 or sector_size <= 0:
        return counts

    base_int: int = int(network.network_address)
    span: int = total_cells * sector_size

    for ip_str in assigned:
        parsed: IPv4Address | None = parse_ipv4(ip_str)

        if parsed is None:
            continue

        offset: int = int(parsed) - base_int

        if offset < 0 or offset >= span:
            continue

        counts[offset // sector_size] += 1

    return counts


def _compose_sector(
    first_ip_int: int,
    sector_size: int,
    used_count: int,
) -> dict[str, Any]:
    """
    Shapes one sector entry of the 'ip_distribution' grid

    The percentage is the per-cell saturation ('used_count / sector_size * 100'), rounded to
    two decimals; this matches the frontend's heatmap colouring convention. Position-implied
    fields (sector index, sector size) are omitted: the consumer reads the index from the
    sector's position in its parent range's 'sectors' array, and derives the size from
    ip_end - ip_start + 1

    Args:
        first_ip_int (int): Integer of the first address the sector covers
        sector_size (int): Number of addresses the sector covers (used only for the percentage
            denominator and to compute ip_end)
        used_count (int): Number of assigned IPs inside the sector

    Returns:
        dict[str, Any]: Sector entry with ip_start, ip_end, used_count, percentage
    """
    return {
        IpamOverviewKey.IP_START: str(IPv4Address(first_ip_int)),
        IpamOverviewKey.IP_END: str(IPv4Address(first_ip_int + sector_size - 1)),
        IpamOverviewKey.USED_COUNT: used_count,
        IpamOverviewKey.PERCENTAGE: round((used_count / sector_size) * 100, 2),
    }


def _build_ip_distribution(
    network: IPv4Network | None,
    assigned: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """
    Builds the 'IP-Verteilung' grid payload for one subnet, or an empty dict when no grid is rendered

    The grid is only emitted at its full size (MAX_RANGES x MAX_SECTORS_PER_RANGE = 64 cells),
    which corresponds to /26 and shorter prefixes. For /27 and narrower subnets the resulting
    grid would have fewer cells; in that case (and when the CIDR is missing or unparsable) the
    function returns an empty dict so the frontend can omit the visualisation entirely. When
    rendered, every cell covers an equal slice of the subnet (network + broadcast included)
    and carries the count of assigned IPs plus a per-cell saturation percentage that drives
    the heatmap colouring

    The returned structure is intentionally minimal: position-implied fields (range index,
    sector index, sector size, top-level grid dimensions) are omitted because the grid
    dimensions are fixed and the indexes follow array order. Range-level ip_start / ip_end are
    kept because the frontend renders them as row labels next to each range

    Args:
        network (IPv4Network | None): The parsed subnet network, or None when the subnet's
            CIDR is missing or unparsable
        assigned (dict[str, dict[str, Any]]): {ip_str: row_info} as produced by
            _load_assigned_rows_map; only used to bucket-count, the row metadata is ignored
            here

    Returns:
        dict[str, Any]: {'sector_size': N, 'ranges': [...]} when the subnet qualifies for the
            full grid, where 'sector_size' is the number of addresses each cell covers (same
            for every cell since the grid is uniform) and each range carries ip_start, ip_end,
            and a nested 'sectors' list of cells with ip_start, ip_end, used_count,
            percentage. Empty dict ({}) otherwise
    """
    if network is None:
        return {}

    total: int = total_address_count(network)
    ranges_count, sectors_per_range, sector_size = _compute_grid_dimensions(total)
    total_cells: int = ranges_count * sectors_per_range
    max_grid_cells: int = (
        IpamDistributionLimits.MAX_RANGES * IpamDistributionLimits.MAX_SECTORS_PER_RANGE
    )

    if total_cells < max_grid_cells:
        return {}

    counts: list[int] = _bucket_used_counts(assigned, network, sector_size, total_cells)

    base_int: int = int(network.network_address)
    range_span: int = sectors_per_range * sector_size

    ranges: list[dict[str, Any]] = []

    for range_index in range(ranges_count):
        range_first_int: int = base_int + range_index * range_span
        sectors: list[dict[str, Any]] = []

        for sector_index in range(sectors_per_range):
            sector_first_int: int = range_first_int + sector_index * sector_size
            global_cell: int = range_index * sectors_per_range + sector_index
            sectors.append(_compose_sector(
                sector_first_int,
                sector_size,
                counts[global_cell],
            ))

        ranges.append({
            IpamOverviewKey.IP_START: str(IPv4Address(range_first_int)),
            IpamOverviewKey.IP_END: str(IPv4Address(range_first_int + range_span - 1)),
            IpamOverviewKey.SECTORS: sectors,
        })

    return {
        IpamOverviewKey.SECTOR_SIZE: sector_size,
        IpamOverviewKey.RANGES: ranges,
    }


def _build_type_distribution(
    assigned: dict[str, dict[str, Any]],
    type_meta: dict[int, dict[str, Any]],
    total: int,
) -> list[dict[str, Any]]:
    """
    Builds the whole-subnet IP-usage distribution that feeds the frontend pie chart

    Aggregates the assigned-IP map by owning CmdbType, appends a synthetic 'Free' bucket for
    unused capacity, and collapses every orphaned assignment (type_id missing on the interface
    row or no longer resolvable because the CmdbType was deleted) into a single 'Unknown'
    bucket so the chart never grows a slice per stale type_id. Percentages are computed
    against the subnet's assignable address count (so the 'Free' bucket matches the
    'free_ips' KPI and the IP table's row count) and rounded to two decimals. An empty list is
    returned when the subnet has zero assignable addresses or the CIDR is unparsable, so the
    frontend can render a placeholder

    Args:
        assigned (dict[str, dict[str, Any]]): {ip_str: {'object_id', 'type_id', 'mac'}} as
            produced by _load_assigned_rows_map; one entry per used IP across the whole subnet
        type_meta (dict[int, dict[str, Any]]): {type_id: {'label', 'ci_explorer_color'}} for
            every CmdbType referenced by the assigned map; type_ids absent from this mapping
            fall through to the Unknown bucket
        total (int): Assignable address count of the subnet (denominator for percentages)

    Returns:
        list[dict[str, Any]]: One entry per type bucket with keys public_id, label,
            ci_explorer_color, count, percentage, followed by the Unknown bucket (only when
            non-empty) and the Free bucket; the Unknown / Free buckets carry
            ci_explorer_color=None. Empty list when total is 0
    """
    if total <= 0:
        return []

    by_type: dict[int, int] = {}
    unknown_count: int = 0

    for info in assigned.values():
        type_id: Any = info.get(_AssignedField.TYPE_ID)

        if isinstance(type_id, int) and type_id in type_meta:
            by_type[type_id] = by_type.get(type_id, 0) + 1
        else:
            unknown_count += 1

    free_count: int = max(0, total - len(assigned))

    distribution: list[dict[str, Any]] = [
        {
            CmdbObjectKey.PUBLIC_ID: type_id,
            IpamOverviewKey.LABEL: type_meta[type_id][IpamOverviewKey.LABEL],
            IpamOverviewKey.CI_EXPLORER_COLOR: type_meta[type_id].get(IpamOverviewKey.CI_EXPLORER_COLOR),
            IpamOverviewKey.COUNT: count,
            IpamOverviewKey.PERCENTAGE: round((count / total) * 100, 2),
        }
        for type_id, count in by_type.items()
    ]

    if unknown_count > 0:
        distribution.append({
            CmdbObjectKey.PUBLIC_ID: None,
            IpamOverviewKey.LABEL: IpamBucketLabel.UNKNOWN,
            IpamOverviewKey.CI_EXPLORER_COLOR: None,
            IpamOverviewKey.COUNT: unknown_count,
            IpamOverviewKey.PERCENTAGE: round((unknown_count / total) * 100, 2),
        })

    distribution.append({
        CmdbObjectKey.PUBLIC_ID: None,
        IpamOverviewKey.LABEL: IpamBucketLabel.FREE,
        IpamOverviewKey.CI_EXPLORER_COLOR: None,
        IpamOverviewKey.COUNT: free_count,
        IpamOverviewKey.PERCENTAGE: round((free_count / total) * 100, 2),
    })

    return distribution


# -------------------------------------------------------------------------------------------------------------------- #
#                                                   DATA LOADING                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
def _load_subnet_object(
    objects_manager: ObjectsManager,
    types_manager: TypesManager,
    public_id: int,
) -> dict[str, Any]:
    """
    Loads the SUBNET CmdbObject by public_id, aborting with structured HTTP errors when the
    SUBNET CmdbType is undefined, the object does not exist, or the object exists but is of a
    different CmdbType

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        public_id (int): public_id of the candidate subnet object

    Returns:
        dict[str, Any]: The subnet CmdbObject document
    """
    subnet_type_id: int | None = resolve_special_type_id(types_manager, SpecialType.SUBNET)

    if subnet_type_id is None:
        abort(400, "No SUBNET CmdbType is defined; cannot build subnet overview!")

    candidates: list[dict[str, Any]] = objects_manager.find_objects(
        {CmdbObjectKey.PUBLIC_ID: public_id},
        as_dict=True,
    )

    if not candidates:
        abort(404, f"Subnet with public_id {public_id} was not found!")

    candidate: dict[str, Any] = candidates[0]

    if candidate.get(CmdbObjectKey.TYPE_ID) != subnet_type_id:
        abort(400, f"Object with public_id {public_id} is not a SUBNET!")

    return candidate


def _load_assigned_rows_map(
    objects_manager: ObjectsManager,
    subnet_object_id: int,
    network: IPv4Network,
) -> dict[str, dict[str, Any]]:
    """
    Loads every dg-ipam-interface row referencing the subnet and indexes them by canonical IP

    Returns one entry per assigned IP. Rows whose IP is unparsable or falls outside the given
    network are skipped (defensive against legacy / drifted state). Per the interface
    validator's pre-save uniqueness check there is at most one row per IP within a subnet, so
    the map is well-defined

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        subnet_object_id (int): public_id of the subnet
        network (IPv4Network): The parsed subnet network, used to filter out-of-range rows

    Returns:
        dict[str, dict[str, Any]]: {ip_str: {'object_id', 'type_id', 'mac'}}; mac is None when
            the field is absent or empty
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
                                CmdbObjectFieldKey.VALUE: subnet_object_id,
                            },
                        },
                    },
                },
            },
        },
    }

    candidates: list[dict[str, Any]] = objects_manager.find_objects(criteria, as_dict=True)

    out: dict[str, dict[str, Any]] = {}

    for candidate in candidates:
        candidate_id: Any = candidate.get(CmdbObjectKey.PUBLIC_ID)
        candidate_type_id: Any = candidate.get(CmdbObjectKey.TYPE_ID)

        for section in candidate.get(CmdbObjectKey.MULTI_DATA_SECTIONS, []) or []:
            if section.get(CmdbObjectMdsKey.SECTION_ID) != IpamSection.INTERFACE:
                continue

            for row in section.get(CmdbObjectMdsKey.VALUES, []) or []:
                row_subnet, row_ip, row_mac = _extract_row_fields(row)

                if row_subnet != subnet_object_id or not isinstance(row_ip, str):
                    continue

                parsed_ip: IPv4Address | None = parse_ipv4(row_ip)

                if parsed_ip is None or not ip_in_network(parsed_ip, network):
                    continue

                out[str(parsed_ip)] = {
                    _AssignedField.OBJECT_ID: candidate_id,
                    _AssignedField.TYPE_ID: candidate_type_id,
                    _AssignedField.MAC: row_mac if isinstance(row_mac, str) and row_mac else None,
                }

    return out


def _resolve_type_meta(
    types_manager: TypesManager,
    type_ids: list[int],
) -> dict[int, dict[str, Any]]:
    """
    Bulk-resolves a list of CmdbType public_ids to the metadata the overview needs

    Returns the label plus the CI-Explorer color so the frontend can render type chips and
    pie-chart slices with the same colour the user picked under 'Type Settings'. A single bulk
    lookup is issued and the projection happens client-side, so this stays cheap even when a
    subnet has assignments across dozens of distinct types

    Args:
        types_manager (TypesManager): db interface for CmdbTypes
        type_ids (list[int]): The CmdbType ids to resolve (duplicates allowed)

    Returns:
        dict[int, dict[str, Any]]: {type_id: {'label': str, 'ci_explorer_color': str | None}};
            types that no longer exist are absent so callers can route them into the Unknown
            bucket
    """
    if not type_ids:
        return {}

    lookup = types_manager.get_types_lookup(list(set(type_ids)))

    return {
        tid: {IpamOverviewKey.LABEL: t.label, IpamOverviewKey.CI_EXPLORER_COLOR: t.ci_explorer_color}
        for tid, t in lookup.items()
    }


# -------------------------------------------------------------------------------------------------------------------- #
#                                                   ORCHESTRATOR                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
def _parse_subnet_network(subnet_obj: dict[str, Any]) -> IPv4Network | None:
    """
    Returns the parsed IPv4Network of a SUBNET CmdbObject, or None when unparsable / missing

    Reads the subnet's 'dg-network-range' field via ``extract_field_value`` and runs
    ``parse_cidr`` over it only when the value is a string, so a degenerate field value
    (None / non-string) does not crash the orchestrator

    Args:
        subnet_obj (dict[str, Any]): The SUBNET CmdbObject document

    Returns:
        IPv4Network | None: Parsed network, or None when the CIDR is missing or unparsable
    """
    raw_cidr: Any = extract_field_value(subnet_obj, SubnetField.NETWORK_RANGE)

    if not isinstance(raw_cidr, str):
        return None

    return parse_cidr(raw_cidr)


def _build_broken_state_payload(
    subnet_obj: dict[str, Any],
    page: int,
    page_size: int,
) -> dict[str, Any]:
    """
    Builds the degenerate payload returned when the subnet's CIDR is missing or unparsable

    Mirrors the happy-path envelope so the FE can render the response unconditionally: every
    counter is zeroed, the 'ips' block ships an empty page (page / page_size clamped via
    ``clamp_page(..., 0)``), both distributions are empty, and the 'vlans' list is empty.
    The 'cidr' field echoes the raw value when it is a string (so the user can see the broken
    input they need to fix) and is None otherwise

    Args:
        subnet_obj (dict[str, Any]): The SUBNET CmdbObject document
        page (int): 1-based page number requested by the caller
        page_size (int): Page size requested by the caller

    Returns:
        dict[str, Any]: Degenerate payload matching the happy-path key set
    """
    raw_cidr: Any = extract_field_value(subnet_obj, SubnetField.NETWORK_RANGE)
    safe_page, safe_size = clamp_page(page, page_size, 0)

    return {
        IpamOverviewKey.SUBNET: {
            CmdbObjectKey.PUBLIC_ID: subnet_obj.get(CmdbObjectKey.PUBLIC_ID),
            IpamOverviewKey.CIDR: raw_cidr if isinstance(raw_cidr, str) else None,
            IpamOverviewKey.TOTAL_IPS: 0,
            IpamOverviewKey.ASSIGNABLE_IPS: 0,
            IpamOverviewKey.USED_IPS: 0,
            IpamOverviewKey.FREE_IPS: 0,
        },
        IpamOverviewKey.IPS: {
            IpamOverviewKey.PAGE: safe_page,
            IpamOverviewKey.PAGE_SIZE: safe_size,
            IpamOverviewKey.TOTAL: 0,
            IpamOverviewKey.ROWS: [],
        },
        IpamOverviewKey.TYPE_DISTRIBUTION: [],
        IpamOverviewKey.IP_DISTRIBUTION: {},
        IpamOverviewKey.VLANS: [],
    }


def build_subnet_overview(
    objects_manager: ObjectsManager,
    types_manager: TypesManager,
    public_id: int,
    page: int = 1,
    page_size: int = IpamPagination.DEFAULT_PAGE_SIZE,
    search: str = '',
    sort: str = '',
    order: str = '',
) -> dict[str, Any]:
    """
    Builds the full IP-Übersicht payload for the SUBNET CmdbObject identified by public_id

    Aborts HTTP 404 when the subnet does not exist and HTTP 400 when the public_id refers to a
    non-subnet CmdbObject or no SUBNET CmdbType is defined, an unknown sort column, or an
    unknown sort direction. When the subnet's 'dg-network-range' is missing or unparsable,
    returns the KPI block with zeroed counters and an empty page (broken state is observable
    but does not 500)

    The KPI block uses two related denominators: 'total_ips' is the full address count
    (network + broadcast included, matching the IP-Verteilung grid) and 'assignable_ips' is
    the subset the interface validator would accept (network and broadcast excluded for /≤30,
    full count for /31, /32). 'free_ips' is computed against 'assignable_ips' so it matches
    what the user sees in the paginated IP table

    Summary lines for the page are resolved one-per-IP through ``_compose_ip_row``. When
    ``sort`` is ASSIGNED_TO they are additionally batch-resolved up front via
    ``ObjectsManager.get_summary_lines_lookup`` so the ordering decision uses the visible
    label

    When ``search`` is empty / whitespace or shorter than IpamSearch.MIN_QUERY_LENGTH after
    stripping, the IP table paginates every assignable address ('ips.total' equals
    'assignable_ips'). When ``search`` is active, the IP table lists only the assignable
    addresses whose canonical dotted-quad string contains the query as a case-insensitive
    substring; 'ips.total' shrinks to the match count

    When ``sort`` is provided the candidate IPs are ordered by the chosen column and
    direction with NULLS LAST (rows missing a value for the column trail in either direction).
    The 'subnet' KPI block, 'type_distribution', 'ip_distribution', and 'vlans' are invariant
    under both search and sort - they always cover the whole subnet

    The 'vlans' list carries every VLAN CmdbObject whose 'dg-subnet-ref' points at this subnet
    as a {'public_id', 'name'} dict, sorted by ascending public_id. Empty list when no VLAN
    references the subnet or when no VLAN CmdbType is defined yet

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        public_id (int): public_id of the subnet to summarise
        page (int): 1-based page number (clamped into the valid range)
        page_size (int): Page size (clamped to [IpamPagination.MIN_PAGE_SIZE,
            IpamPagination.MAX_PAGE_SIZE])
        search (str): Optional case-insensitive substring filter against each canonical IP
            string; empty / whitespace and queries shorter than IpamSearch.MIN_QUERY_LENGTH
            after stripping are ignored and restore the unfiltered page
        sort (str): Optional sort column name; one of IpamSortColumn values. Empty or
            whitespace keeps the natural ascending-IP order
        order (str): Optional sort direction ('1' for ascending, '-1' for descending);
            ignored when ``sort`` is empty, defaults to '1' when ``sort`` is provided
            without an explicit order. Matches the project-wide Mongo direction convention
            used by CollectionParameters and the base managers

    Returns:
        dict[str, Any]: {'subnet': {public_id, cidr, total_ips, assignable_ips,
            used_ips, free_ips},
            'ips': {page, page_size, total, rows: [...]},
            'type_distribution': [{public_id, label, ci_explorer_color, count, percentage},
            ...],
            'ip_distribution': {'sector_size': N, 'ranges': [...]} | {},
            'vlans': [{public_id, name}, ...]} where
            'type_distribution' covers the
            whole subnet (not just the current page) and includes 'Unknown' (when present)
            and 'Free' buckets after the type buckets, 'ip_distribution' is the
            IP-Verteilung heatmap grid covering the full address space (network + broadcast
            included). The grid is emitted only at its full 4 x 16 size (/26 and shorter
            prefixes); for /27 and narrower, or when the CIDR is unparsable, ip_distribution
            is an empty dict. 'ips.total' equals 'assignable_ips' under no search and no
            sort (lazy path), or the candidate-list length otherwise. 'vlans' lists every
            VLAN whose 'dg-subnet-ref' points at this subnet, sorted by ascending public_id;
            empty when no VLAN references the subnet
    """
    subnet_obj: dict[str, Any] = _load_subnet_object(objects_manager, types_manager, public_id)
    sort_col, sort_dir = _parse_sort_args(sort, order)
    network: IPv4Network | None = _parse_subnet_network(subnet_obj)

    if network is None:
        return _build_broken_state_payload(subnet_obj, page, page_size)

    assignable: int = assignable_address_count(network)
    assigned: dict[str, dict[str, Any]] = _load_assigned_rows_map(objects_manager, public_id, network)

    type_meta: dict[int, dict[str, Any]] = _resolve_type_meta(types_manager, [
        info[_AssignedField.TYPE_ID]
        for info in assigned.values()
        if isinstance(info.get(_AssignedField.TYPE_ID), int)
    ])

    return {
        IpamOverviewKey.SUBNET: {
            CmdbObjectKey.PUBLIC_ID: subnet_obj.get(CmdbObjectKey.PUBLIC_ID),
            IpamOverviewKey.CIDR: str(network),
            IpamOverviewKey.TOTAL_IPS: total_address_count(network),
            IpamOverviewKey.ASSIGNABLE_IPS: assignable,
            IpamOverviewKey.USED_IPS: len(assigned),
            IpamOverviewKey.FREE_IPS: max(0, assignable - len(assigned)),
        },
        IpamOverviewKey.IPS: _build_ips_block(
            network, assignable, page, page_size,
            _resolve_candidate_ips(network, search, sort_col, sort_dir, assigned, type_meta, objects_manager),
            assigned, type_meta, objects_manager,
        ),
        IpamOverviewKey.TYPE_DISTRIBUTION: _build_type_distribution(assigned, type_meta, assignable),
        IpamOverviewKey.IP_DISTRIBUTION: _build_ip_distribution(network, assigned),
        IpamOverviewKey.VLANS: load_vlans_by_subnets(
            objects_manager, types_manager, [public_id],
        ).get(public_id, []),
    }
