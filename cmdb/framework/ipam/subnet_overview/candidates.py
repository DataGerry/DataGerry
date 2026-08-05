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
Candidate-IP selection for the subnet IP-Übersicht table

Owns everything that decides WHICH IPs appear in the IP table and in what order: the lazy
page slice, full / search-filtered enumeration of assignable addresses, the status / type
filters, the sort policy (NULLS LAST in either direction) and the route-parameter parsers.
The IpamSubnetTableLimits.MAX_MATERIALIZED_CANDIDATES guard lives here: subnets too large
to materialize abort HTTP 400 when search / sort / filter would require enumerating them
"""
from ipaddress import IPv4Address, IPv4Network
from typing import Any

from flask import abort

from cmdb.manager import ObjectsManager
from cmdb.models.special_type_model.ipam_constants import (
    IpamOverviewKey,
    IpamRowStatus,
    IpamSortColumn,
    IpamSortDirection,
    IpamSubnetTableLimits,
)
from cmdb.framework.ipam.cidr import (
    Network,
    parse_ip,
    assignable_address_count,
    first_assignable_int,
)
from cmdb.framework.ipam.search import active_search
from cmdb.framework.ipam.subnet_overview.assigned_rows import (
    AssignedField,
    resolve_summary_lines_for_ips,
    sorted_assigned_ips,
    sorted_invalid_ips,
)
# -------------------------------------------------------------------------------------------------------------------- #


def page_slice_ips(network: IPv4Network, page: int, page_size: int) -> list[str]:
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


def list_all_assignable_ips(network: IPv4Network) -> list[str]:
    """
    Returns every assignable IP address of a subnet as a canonical string in ascending order

    Same address-skipping policy as ``page_slice_ips`` and
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
    ``page_slice_ips`` uses applies here: for /30 and shorter the network and broadcast
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
            ``load_assigned_rows_map``
        type_meta (dict[int, dict[str, Any]]): {type_id: {'label', 'ci_explorer_color'}} as
            produced by ``resolve_type_meta``
        summary_lines (dict[str, str]): {ip_str: summary_line} produced by
            ``resolve_summary_lines_for_ips``; empty when the sort column is not ASSIGNED_TO

    Returns:
        Any: Comparable key value, or None when the row has no value for the requested column
    """
    info: dict[str, Any] | None = assigned.get(ip_str)

    if sort_col == IpamSortColumn.IP:
        return int(parse_ip(ip_str))

    if sort_col == IpamSortColumn.STATUS:
        return IpamRowStatus.ASSIGNED if info is not None else IpamRowStatus.FREE

    if sort_col == IpamSortColumn.TYPE:
        if info is None:
            return None

        type_id: Any = info.get(AssignedField.TYPE_ID)
        meta: dict[str, Any] | None = type_meta.get(type_id) if isinstance(type_id, int) else None
        label: Any = meta.get(IpamOverviewKey.LABEL) if meta else None

        return label.lower() if isinstance(label, str) else None

    if sort_col == IpamSortColumn.ASSIGNED_TO:
        summary: Any = summary_lines.get(ip_str)

        return summary.lower() if isinstance(summary, str) and summary else None

    if sort_col == IpamSortColumn.MAC_ADDRESS:
        if info is None:
            return None

        mac: Any = info.get(AssignedField.MAC)

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
            ``load_assigned_rows_map``
        type_meta (dict[int, dict[str, Any]]): {type_id: {'label', 'ci_explorer_color'}} as
            produced by ``resolve_type_meta``
        objects_manager (ObjectsManager): db interface for CmdbObjects, used only to batch
            summary lines when sort_col == ASSIGNED_TO and at least one candidate is assigned

    Returns:
        list[str]: Candidate IPs ordered by key with NULL-keyed rows trailing the partition
    """
    reverse: bool = sort_dir == IpamSortDirection.DESC

    if sort_col == IpamSortColumn.IP:
        return sorted(candidate_ips, key=lambda ip: int(parse_ip(ip)), reverse=reverse)

    summary_lines: dict[str, str] = (
        resolve_summary_lines_for_ips(candidate_ips, assigned, objects_manager)
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


def _apply_candidate_filter(
    candidates: list[str],
    status_filter: IpamRowStatus | None,
    type_filter: list[int],
    assigned: dict[str, dict[str, Any]],
) -> list[str]:
    """
    Narrows a candidate IP list to rows matching the status and type filters (AND-combined)

    ``status_filter`` selects assigned-vs-free rows: ASSIGNED keeps IPs present in
    ``assigned``, FREE keeps IPs absent from ``assigned``. ``type_filter`` (a list of CmdbType
    public_ids) keeps only assigned rows whose stored type_id is in the set; the elements
    combine via OR within the type filter and the whole filter combines with status via AND,
    so status=FREE + any non-empty type_filter produces an empty list (free rows carry no
    owner type). Both filters are optional - status=None and an empty type_filter return the
    candidate list unchanged

    Args:
        candidates (list[str]): Canonical IP strings under consideration (already search-filtered
            if a search is active)
        status_filter (IpamRowStatus | None): Chosen status filter, or None to skip
        type_filter (list[int]): Chosen CmdbType public_id list; empty list to skip
        assigned (dict[str, dict[str, Any]]): {ip_str: row_info} as produced by
            ``load_assigned_rows_map``

    Returns:
        list[str]: Candidate IPs that match every active filter, in input order
    """
    if status_filter is None and not type_filter:
        return candidates

    type_filter_set: set[int] = set(type_filter)
    result: list[str] = []

    for ip in candidates:
        info: dict[str, Any] | None = assigned.get(ip)
        is_assigned: bool = info is not None

        if status_filter == IpamRowStatus.ASSIGNED and not is_assigned:
            continue

        if status_filter == IpamRowStatus.FREE and is_assigned:
            continue

        if type_filter_set:
            if not is_assigned or info.get(AssignedField.TYPE_ID) not in type_filter_set:
                continue

        result.append(ip)

    return result


def resolve_candidate_ips(
    network: Network,
    search: str,
    sort_col: IpamSortColumn | None,
    sort_dir: IpamSortDirection,
    status_filter: IpamRowStatus | None,
    type_filter: list[int],
    assigned: dict[str, dict[str, Any]],
    type_meta: dict[int, dict[str, Any]],
    objects_manager: ObjectsManager,
    is_ipv6: bool = False,
) -> list[str] | None:
    """
    Selects the candidate IP list for the IP-table page, or None to signal the lazy path

    Returning None means "no search, no row filter, no invalid rows AND the chosen sort is
    the natural ascending IP order (or no sort is requested)" - the orchestrator then
    paginates straight from ``page_slice_ips`` without materializing the full assignable
    range. Otherwise the helper materializes the candidate list: assignable IPs first (search-
    filtered if active, otherwise full), then the invalid IPs (also search-filtered),
    preserving the "assignable then invalid" two-tier order in the default case. The status /
    type filters are then applied across the combined list, and finally the sort if
    ``sort_col`` is not None

    When sort is explicitly requested, the chosen sort applies uniformly to the combined
    list - invalid rows are not kept in a separate trailing tier under explicit sort. Default
    order (no sort) keeps invalid rows trailing

    Size guard (IPv4 only): when the subnet's assignable count exceeds
    IpamSubnetTableLimits.MAX_MATERIALIZED_CANDIDATES, materializing the address range is
    refused. A user-requested search / sort / filter aborts HTTP 400; when only the presence
    of invalid rows would force materialization, the helper falls back to the lazy path
    instead (returns None) - those invalid rows then surface exclusively via the dedicated
    invalid-only view (whose row set is bounded by the assigned count) and the top-level
    ``invalid_count``, while plain browsing keeps working at any subnet size

    Args:
        network (IPv4Network): The parsed subnet network
        search (str): Raw search query as received by the caller
        sort_col (IpamSortColumn | None): Chosen sort column, or None when no sort is requested
        sort_dir (IpamSortDirection): Chosen sort direction (ASC when sort_col is None)
        status_filter (IpamRowStatus | None): Chosen status filter, or None to skip
        type_filter (list[int]): Chosen CmdbType public_id list; empty to skip
        assigned (dict[str, dict[str, Any]]): {ip_str: row_info} as produced by
            ``load_assigned_rows_map``
        type_meta (dict[int, dict[str, Any]]): {type_id: {'label', 'ci_explorer_color'}} as
            produced by ``resolve_type_meta``
        objects_manager (ObjectsManager): db interface for CmdbObjects (used by the
            assigned_to summary-line batch when that sort is active)
        is_ipv6 (bool): True for an IPv6 subnet. IPv6 never enumerates free space - the table
            lists only assigned addresses (in-CIDR first, out-of-CIDR trailing), search/sort/
            filter apply over that assigned set, and a status=free filter yields an empty page

    Returns:
        list[str] | None: Candidate IPs in final order, or None to signal the lazy path (IPv4
            only; IPv6 always returns a materialized assigned-only list)
    """
    needle: str | None = active_search(search)
    filter_active: bool = status_filter is not None or bool(type_filter)

    if is_ipv6:
        candidates: list[str] = sorted_assigned_ips(assigned, valid=True) + sorted_invalid_ips(assigned)

        if needle is not None:
            lowered: str = needle.lower()
            candidates = [ip for ip in candidates if lowered in ip.lower()]

        if filter_active:
            candidates = _apply_candidate_filter(candidates, status_filter, type_filter, assigned)

        if sort_col is None:
            return candidates

        return _sort_candidate_ips(candidates, sort_col, sort_dir, assigned, type_meta, objects_manager)

    natural_order: bool = sort_col is None or (
        sort_col == IpamSortColumn.IP and sort_dir == IpamSortDirection.ASC
    )
    invalid_ips: list[str] = sorted_invalid_ips(assigned)

    if needle is None and natural_order and not filter_active and not invalid_ips:
        return None

    if assignable_address_count(network) > IpamSubnetTableLimits.MAX_MATERIALIZED_CANDIDATES:
        if needle is not None or not natural_order or filter_active:
            abort(
                400,
                f"Subnet {network} is too large for search, sort or filtering: its "
                f"{assignable_address_count(network)} assignable addresses exceed the "
                f"{IpamSubnetTableLimits.MAX_MATERIALIZED_CANDIDATES}-address limit!",
            )

        # Only invalid rows forced materialization: stay lazy; the rows surface via the
        # invalid-only view and the top-level invalid_count instead of the main table
        return None

    assignable_candidates: list[str] = (
        list_assignable_ips_matching_substring(network, needle)
        if needle is not None
        else list_all_assignable_ips(network)
    )

    if needle is not None and invalid_ips:
        lowered_needle: str = needle.lower()
        invalid_ips = [ip for ip in invalid_ips if lowered_needle in ip.lower()]

    candidates: list[str] = assignable_candidates + invalid_ips

    if filter_active:
        candidates = _apply_candidate_filter(candidates, status_filter, type_filter, assigned)

    if sort_col is None:
        return candidates

    return _sort_candidate_ips(candidates, sort_col, sort_dir, assigned, type_meta, objects_manager)


def parse_filter_args(
    raw_status: str,
    raw_type: str,
) -> tuple[IpamRowStatus | None, list[int]]:
    """
    Validates and normalizes the route's 'status' and 'type' query parameter strings

    Empty / whitespace ``raw_status`` returns None for the status component so the orchestrator
    skips the status filter; otherwise the value must be a valid IpamRowStatus member (HTTP 400
    on unknown). ``raw_type`` accepts a comma-separated list of CmdbType public_ids: each
    element is whitespace-stripped, empty elements are skipped, duplicates are collapsed while
    preserving the first occurrence's position. A non-integer element aborts HTTP 400. An
    empty list (raw value empty / whitespace / only commas) means no type filter. The two
    components are independent - either, both, or neither may be active

    Args:
        raw_status (str): Raw value of the ?status= query param
        raw_type (str): Raw value of the ?type= query param (comma-separated)

    Returns:
        tuple[IpamRowStatus | None, list[int]]: (status filter, type filter list). The status
            component is None when its raw value is empty / whitespace. The type component is
            an empty list when no usable public_id is present; otherwise the deduplicated
            integer public_ids in input order
    """
    status_value: str = (raw_status or '').strip()
    status_filter: IpamRowStatus | None = None

    if status_value:
        if not IpamRowStatus.is_valid(status_value):
            abort(400, f"Unknown status filter: '{status_value}'!")

        status_filter = IpamRowStatus(status_value)

    type_filter: list[int] = []
    seen: set[int] = set()

    for entry in (raw_type or '').split(','):
        token: str = entry.strip()

        if not token:
            continue

        try:
            parsed: int = int(token)
        except ValueError:
            abort(400, f"Type filter must be a comma-separated list of integer public_ids, got: '{token}'!")

        if parsed in seen:
            continue

        seen.add(parsed)
        type_filter.append(parsed)

    return status_filter, type_filter


def parse_sort_args(
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
