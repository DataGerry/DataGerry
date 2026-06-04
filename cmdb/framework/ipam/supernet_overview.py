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
Builds the data payloads for the SUPERNET overview view

The frontend renders a KPI strip (computed against every subnet under the supernet) and a
lazily-expandable, paginated table of top-level subnets. 'Top-level' is defined via CIDR
containment among siblings: a subnet is top-level when no other subnet under the same
supernet strictly contains it. Direct CIDR-children of any visible row are fetched on demand
via a separate orchestrator when the user expands that row

This module exposes pure helpers (CIDR math, row / summary shaping, parent-child indexing)
plus two DB orchestrators: ``build_supernet_overview`` for the paginated top-level view and
``build_supernet_subnet_children`` for the direct-children fetch
"""
from typing import Any

from flask import abort

from cmdb.manager import ObjectsManager, TypesManager
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.special_type_model.ipam_constants import (
    SupernetField,
    SubnetField,
    IpAddressFamily,
    InterfaceField,
    IpamSection,
    IpamPagination,
    IpamOverviewKey,
)
from cmdb.framework.ipam.cidr import (
    Network,
    parse_cidr,
    is_strict_subnet,
    network_family,
    total_address_count,
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


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  PURE HELPERS                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
def _ip_range(network: Network) -> dict[str, str]:
    """
    Returns the lowest and highest address of a network (IPv4 or IPv6) as strings

    'Lowest' is the network address and 'highest' is the broadcast address; neither is filtered
    out so the range reflects the literal bounds of the CIDR

    Args:
        network (Network): The parsed network

    Returns:
        dict[str, str]: {'first': <network address>, 'last': <broadcast address>}
    """
    return {
        IpamOverviewKey.FIRST: str(network.network_address),
        IpamOverviewKey.LAST: str(network.broadcast_address),
    }


def _percent(numerator: int, denominator: int) -> float:
    """
    Returns 'numerator / denominator * 100' rounded to 2 decimals, or 0.0 when denominator is 0

    Args:
        numerator (int): The numerator
        denominator (int): The denominator

    Returns:
        float: Percentage rounded to 2 decimals; 0.0 if denominator is 0
    """
    if denominator <= 0:
        return 0.0

    return round(numerator / denominator * 100, 2)


def _resolve_family(obj: dict[str, Any], type_field: str, range_field: str) -> str:
    """
    Resolves the address family of an IPAM CmdbObject as an IpAddressFamily value ('ipv4' / 'ipv6')

    CIDR-first: the family is derived from the actual ``range_field`` CIDR via ``network_family``
    whenever it parses, because the CIDR is what determines real address-family behaviour
    (containment, enumeration feasibility, counts). This keeps every view consistent with the
    subnet IP-Übersicht, which derives the family straight from the parsed network. Only when the
    CIDR is missing / unparsable does the explicit ``type_field`` selector decide, defaulting to
    IPv4 (legacy objects pre-date the selector and the former range regex only admitted IPv4)

    Args:
        obj (dict[str, Any]): The SUBNET or SUPERNET CmdbObject document
        type_field (str): The address-family selector field name (SubnetField.TYPE /
            SupernetField.TYPE)
        range_field (str): The network-range field name (SubnetField.NETWORK_RANGE /
            SupernetField.NETWORK_RANGE)

    Returns:
        str: IpAddressFamily.IPV6 or IpAddressFamily.IPV4
    """
    raw_cidr: Any = extract_field_value(obj, range_field)
    network: Network | None = parse_cidr(raw_cidr) if isinstance(raw_cidr, str) else None

    if network is not None:
        return network_family(network)

    raw_type: Any = extract_field_value(obj, type_field)

    return IpAddressFamily.IPV6 if raw_type == IpAddressFamily.IPV6 else IpAddressFamily.IPV4


def subnet_family(subnet_obj: dict[str, Any]) -> str:
    """
    Returns the address family of a SUBNET CmdbObject as an IpAddressFamily value ('ipv4' / 'ipv6')

    Thin wrapper over ``_resolve_family`` bound to the SUBNET selector / range fields; see that
    helper for the CIDR-first precedence and the selector / IPv4 fallback

    Args:
        subnet_obj (dict[str, Any]): The SUBNET CmdbObject document

    Returns:
        str: IpAddressFamily.IPV6 or IpAddressFamily.IPV4
    """
    return _resolve_family(subnet_obj, SubnetField.TYPE, SubnetField.NETWORK_RANGE)


def supernet_family(supernet_obj: dict[str, Any]) -> str:
    """
    Returns the address family of a SUPERNET CmdbObject as an IpAddressFamily value ('ipv4' / 'ipv6')

    Thin wrapper over ``_resolve_family`` bound to the SUPERNET selector / range fields. Drives
    whether the supernet KPI strip reports address-ratio percentages (IPv4) or omits them as null
    (IPv6), where used/total address ratios are meaningless against a 2**n address space

    Args:
        supernet_obj (dict[str, Any]): The SUPERNET CmdbObject document

    Returns:
        str: IpAddressFamily.IPV6 or IpAddressFamily.IPV4
    """
    return _resolve_family(supernet_obj, SupernetField.TYPE, SupernetField.NETWORK_RANGE)


def compute_subnet_row(subnet_obj: dict[str, Any], used_count: int) -> dict[str, Any]:
    """
    Shapes a single SUBNET CmdbObject + its interface-IP usage count into one overview row

    Returns a degenerate row (zeroed counts, null cidr) when the subnet's 'dg-network-range'
    field is missing or unparsable, so a broken record does not break the whole view. All
    counts and percentages are computed against the subnet's total address count (network and
    broadcast included), matching the denominator used by the subnet IP-Verteilung grid and
    the headline 'Gesamt IPs' KPI

    Args:
        subnet_obj (dict[str, Any]): The SUBNET CmdbObject document
        used_count (int): Number of dg-ipam-interface rows that reference this subnet

    Returns:
        dict[str, Any]: One row with public_id, subnet_type, cidr, ip_range, used_ips, free_ips,
                        usage_percent. 'subnet_type' is the row's address family ('ipv4' / 'ipv6';
                        see subnet_family). 'usage_percent' is None for IPv6 rows (an address
                        ratio against a 2**n space is meaningless) and a percentage for IPv4.
                        'ip_range' is the subnet's full network range ({first, last}), or None
                        when the CIDR is missing/unparsable
    """
    raw_cidr: Any = extract_field_value(subnet_obj, SubnetField.NETWORK_RANGE)
    network: Network | None = parse_cidr(raw_cidr) if isinstance(raw_cidr, str) else None
    subnet_type: str = subnet_family(subnet_obj)
    is_ipv6: bool = subnet_type == IpAddressFamily.IPV6

    if network is None:
        return {
            CmdbObjectKey.PUBLIC_ID: subnet_obj.get(CmdbObjectKey.PUBLIC_ID),
            IpamOverviewKey.SUBNET_TYPE: subnet_type,
            IpamOverviewKey.CIDR: raw_cidr if isinstance(raw_cidr, str) else None,
            IpamOverviewKey.IP_RANGE: None,
            IpamOverviewKey.USED_IPS: 0,
            IpamOverviewKey.FREE_IPS: 0,
            IpamOverviewKey.USAGE_PERCENT: None if is_ipv6 else 0.0,
        }

    total: int = total_address_count(network)
    free: int = max(0, total - used_count)

    return {
        CmdbObjectKey.PUBLIC_ID: subnet_obj.get(CmdbObjectKey.PUBLIC_ID),
        IpamOverviewKey.SUBNET_TYPE: subnet_type,
        IpamOverviewKey.CIDR: str(network),
        IpamOverviewKey.IP_RANGE: _ip_range(network),
        IpamOverviewKey.USED_IPS: used_count,
        IpamOverviewKey.FREE_IPS: free,
        IpamOverviewKey.USAGE_PERCENT: None if is_ipv6 else _percent(used_count, total),
    }


def compute_supernet_summary(
    supernet_network: Network | None,
    total_used: int,
    subnet_count: int,
    family: str = IpAddressFamily.IPV4,
) -> dict[str, Any]:
    """
    Shapes the KPI strip values for the supernet as a whole

    For IPv4 supernets all percentages are computed against the supernet's total address count
    (network and broadcast included), keeping the KPI aligned with the per-subnet rows produced
    by 'compute_subnet_row' and with the subnet IP-Verteilung grid; 'utilization_percent' is
    intentionally equal to 'used_percent'. For IPv6 supernets the three address-ratio percentages
    are returned as None - used/free against a 2**n address space is meaningless - while the raw
    counts (total_ips, used_ips, free_ips) are still reported as numbers. The resolved address
    family is echoed under 'subnet_type'. A degenerate summary with zeroed counts is returned
    when the supernet's CIDR is missing or unparsable

    Args:
        supernet_network (Network | None): Parsed CIDR of the supernet, None if missing
            or unparsable
        total_used (int): Sum of used IPs across all subnets that reference the supernet
        subnet_count (int): Number of subnets that reference the supernet
        family (str): The supernet's IpAddressFamily; IPv6 nulls the percentage fields

    Returns:
        dict[str, Any]: subnet_type, cidr, ip_range, total_ips, used_ips, free_ips, used_percent,
            free_percent, utilization_percent, subnet_count. The three *_percent fields are None
            for an IPv6 supernet
    """
    is_ipv6: bool = family == IpAddressFamily.IPV6

    if supernet_network is None:
        zero_percent: float | None = None if is_ipv6 else 0.0
        return {
            IpamOverviewKey.SUBNET_TYPE: family,
            IpamOverviewKey.CIDR: None,
            IpamOverviewKey.IP_RANGE: None,
            IpamOverviewKey.TOTAL_IPS: 0,
            IpamOverviewKey.USED_IPS: total_used,
            IpamOverviewKey.FREE_IPS: 0,
            IpamOverviewKey.USED_PERCENT: zero_percent,
            IpamOverviewKey.FREE_PERCENT: zero_percent,
            IpamOverviewKey.UTILIZATION_PERCENT: zero_percent,
            IpamOverviewKey.SUBNET_COUNT: subnet_count,
        }

    total: int = total_address_count(supernet_network)
    free: int = max(0, total - total_used)
    used_percent: float | None = None if is_ipv6 else _percent(total_used, total)
    free_percent: float | None = None if is_ipv6 else _percent(free, total)

    return {
        IpamOverviewKey.SUBNET_TYPE: family,
        IpamOverviewKey.CIDR: str(supernet_network),
        IpamOverviewKey.IP_RANGE: _ip_range(supernet_network),
        IpamOverviewKey.TOTAL_IPS: total,
        IpamOverviewKey.USED_IPS: total_used,
        IpamOverviewKey.FREE_IPS: free,
        IpamOverviewKey.USED_PERCENT: used_percent,
        IpamOverviewKey.FREE_PERCENT: free_percent,
        IpamOverviewKey.UTILIZATION_PERCENT: used_percent,
        IpamOverviewKey.SUBNET_COUNT: subnet_count,
    }


def _network_sort_key(network: Network) -> tuple[int, int]:
    """
    Returns a stable sort key for a network: (network address as int, prefix length)

    Ordering by network address gives ascending IP order; prefix length as the tiebreaker
    ensures a broader (shorter-prefix) network sorts before any more-specific network that
    starts at the same address, which is the order 'sort_and_link_subnets' relies on for
    its single-pass parent linking

    Args:
        network (Network): The parsed network

    Returns:
        tuple[int, int]: (int(network_address), prefixlen)
    """
    return (int(network.network_address), network.prefixlen)


def _subnet_family_rank(row: dict[str, Any]) -> int:
    """
    Returns the family-group rank of a row: 0 for IPv4, 1 for IPv6

    Drives the IPv4-before-IPv6 grouping in 'sort_and_link_subnets'. Only a row whose
    'subnet_type' is exactly IpAddressFamily.IPV6 ranks 1; everything else (IpAddressFamily.IPV4 or a
    row that predates / omits the key) ranks 0 so it stays in the IPv4 group

    Args:
        row (dict[str, Any]): An overview row carrying an optional 'subnet_type' key

    Returns:
        int: 1 when the row is IPv6, 0 otherwise
    """
    return 1 if row.get(IpamOverviewKey.SUBNET_TYPE) == IpAddressFamily.IPV6 else 0


def sort_and_link_subnets(subnet_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Groups subnet rows IPv4-before-IPv6, sorts each group by ascending IP and annotates each
    with the parent subnet's public_id

    Within a family group, rows with a parsable 'cidr' are sorted by ascending network address
    (prefix length ascending as a tiebreaker) and each is given a 'parent_id' equal to the
    public_id of the most-specific other subnet in the same list that strictly contains it, or
    None when no enclosing subnet is present (top-level under the supernet). Rows whose 'cidr'
    is missing or unparsable get parent_id None and trail the sorted rows in their original
    relative order so the frontend can still display them

    A final stable partition by 'subnet_type' places every IPv4-family row ahead of every
    IPv6-family row while preserving the ascending-CIDR order computed within each group. Both
    families parse (parse_cidr is family-agnostic), so IPv6 rows are sorted and parent-linked
    among themselves exactly like IPv4 rows; the partition only guarantees the IPv4-before-IPv6
    grouping. Cross-family parent links cannot occur because is_strict_subnet treats networks of
    different families as disjoint, so the single shared linking stack never links an IPv6 child
    to an IPv4 parent (or vice versa)

    The linking pass uses a stack of (network, public_id) pairs: because parents always
    precede their children in the sort order, the top of the stack after popping non-
    enclosing entries is always the closest enclosing subnet

    Args:
        subnet_rows (list[dict[str, Any]]): Rows produced by 'compute_subnet_row'

    Returns:
        list[dict[str, Any]]: A new list where every row has an added 'parent_id' key; IPv4-family
            rows (parsable in IP order, then unparsable) come first, IPv6-family rows trail
    """
    sortable: list[tuple[Network, dict[str, Any]]] = []
    unsortable: list[dict[str, Any]] = []

    for row in subnet_rows:
        cidr: Any = row.get(IpamOverviewKey.CIDR)
        network: Network | None = parse_cidr(cidr) if isinstance(cidr, str) else None

        if network is None:
            row[IpamOverviewKey.PARENT_ID] = None
            unsortable.append(row)
        else:
            sortable.append((network, row))

    sortable.sort(key=lambda item: _network_sort_key(item[0]))

    stack: list[tuple[Network, Any]] = []

    for network, row in sortable:
        while stack and not is_strict_subnet(stack[-1][0], network):
            stack.pop()

        row[IpamOverviewKey.PARENT_ID] = stack[-1][1] if stack else None
        stack.append((network, row.get(CmdbObjectKey.PUBLIC_ID)))

    ordered: list[dict[str, Any]] = [row for _, row in sortable] + unsortable
    ordered.sort(key=_subnet_family_rank)

    return ordered


def _index_children_by_parent(rows: list[dict[str, Any]]) -> dict[Any, list[dict[str, Any]]]:
    """
    Buckets rows by their 'parent_id' so direct children of any subnet are O(1) to look up

    The output preserves the input order within each bucket, which - because the input comes
    from ``sort_and_link_subnets`` - means children are already in ascending CIDR order. The
    None bucket (top-level + unsortable rows) is included alongside the per-subnet buckets

    Args:
        rows (list[dict[str, Any]]): Rows produced by ``sort_and_link_subnets``; every row
            must carry a 'parent_id' key

    Returns:
        dict[Any, list[dict[str, Any]]]: {parent_id: [child_row, ...]}; lookups for a subnet
            id absent from the map yield an empty list at the call site
    """
    index: dict[Any, list[dict[str, Any]]] = {}

    for row in rows:
        parent_id: Any = row.get(IpamOverviewKey.PARENT_ID)
        index.setdefault(parent_id, []).append(row)

    return index


def _filter_rows_by_network_substring(
    rows: list[dict[str, Any]],
    query: str,
) -> list[dict[str, Any]]:
    """
    Returns the rows whose 'cidr' (the subnet's network property) contains ``query`` as a
    case-insensitive substring

    The query is matched literally against the row's already-shaped CIDR string, so user input
    like '10.0' surfaces both '10.0.0.0/24' and '192.10.0.0/16'. Rows whose 'cidr' is missing
    or not a string never match, so unparsable subnets drop out of search results without
    erroring. Input row order is preserved among matches, which - because callers pass rows
    produced by ``sort_and_link_subnets`` - keeps matches in ascending CIDR order

    Args:
        rows (list[dict[str, Any]]): Rows produced by ``sort_and_link_subnets`` (or any list
            whose entries carry a string 'cidr' field)
        query (str): Substring to match; the caller is expected to have already stripped
            whitespace and decided that a non-empty filter applies

    Returns:
        list[dict[str, Any]]: Matching rows in their original relative order
    """
    needle: str = query.lower()
    matches: list[dict[str, Any]] = []

    for row in rows:
        cidr: Any = row.get(IpamOverviewKey.CIDR)

        if isinstance(cidr, str) and needle in cidr.lower():
            matches.append(row)

    return matches


def _annotate_has_children(
    rows: list[dict[str, Any]],
    children_index: dict[Any, list[dict[str, Any]]],
) -> None:
    """
    Sets a 'has_children' boolean on every row based on whether any other row lists it as its
    parent

    Rows are mutated in place. A row is considered to have children when its 'public_id'
    appears as a key in the children index with at least one entry. Rows without a 'public_id'
    or with an unparsable CIDR can never act as a parent so they always get False

    Args:
        rows (list[dict[str, Any]]): Rows produced by ``sort_and_link_subnets``
        children_index (dict[Any, list[dict[str, Any]]]): Output of
            ``_index_children_by_parent`` against the same row set
    """
    for row in rows:
        public_id: Any = row.get(CmdbObjectKey.PUBLIC_ID)
        row[IpamOverviewKey.HAS_CHILDREN] = bool(public_id is not None and children_index.get(public_id))


def _annotate_is_valid(
    rows: list[dict[str, Any]],
    supernet_network: Network | None,
) -> None:
    """
    Sets an 'is_valid' boolean on every row based on whether the row's CIDR sits strictly
    inside the supernet's network

    Rows are mutated in place. 'Valid' uses strict containment: the subnet's network must be
    contained in the supernet network AND not be equal to it, so a subnet whose CIDR exactly
    matches the supernet is reported as invalid. Rows with a missing or unparsable 'cidr'
    field are always invalid (the field is the only authoritative signal of the subnet's
    range). When the supernet network is None (its own CIDR is missing or unparsable) every
    row is invalid - the FE then shows the orphan-all state until the supernet CIDR is fixed

    Args:
        rows (list[dict[str, Any]]): Rows produced by ``sort_and_link_subnets``
        supernet_network (Network | None): Parsed CIDR of the supernet, or None when the
            supernet's CIDR is missing or unparsable
    """
    for row in rows:
        if supernet_network is None:
            row[IpamOverviewKey.IS_VALID] = False
            continue

        cidr: Any = row.get(IpamOverviewKey.CIDR)
        network: Network | None = parse_cidr(cidr) if isinstance(cidr, str) else None

        if network is None:
            row[IpamOverviewKey.IS_VALID] = False
            continue

        row[IpamOverviewKey.IS_VALID] = is_strict_subnet(supernet_network, network)


def _count_invalid_rows(rows: list[dict[str, Any]]) -> int:
    """
    Returns how many rows carry 'is_valid' = False

    Rows without an 'is_valid' key are counted as invalid: a caller that did not run
    ``_annotate_is_valid`` against the same supernet network should not get a misleadingly
    low count. The function does not mutate the input

    Args:
        rows (list[dict[str, Any]]): Rows that have been through ``_annotate_is_valid``

    Returns:
        int: Number of rows whose 'is_valid' is False (or absent)
    """
    return sum(1 for row in rows if not row.get(IpamOverviewKey.IS_VALID, False))


def _select_invalid_rows(ordered_subnets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Returns every row whose 'is_valid' annotation is False, preserving input order

    Used by the invalid-only orchestrator to surface the flat list of orphaned subnets after
    ``_annotate_is_valid`` has run. A row missing the 'is_valid' key is treated as invalid
    so that a caller that forgot to run the annotator does not get a misleadingly empty list

    Args:
        ordered_subnets (list[dict[str, Any]]): Rows that have been through ``_annotate_is_valid``

    Returns:
        list[dict[str, Any]]: The subset of ``ordered_subnets`` carrying is_valid=False,
            in their original relative order (ascending CIDR, with unsortable rows trailing)
    """
    return [row for row in ordered_subnets if not row.get(IpamOverviewKey.IS_VALID, False)]


def _select_listed_rows(
    ordered_subnets: list[dict[str, Any]],
    search: str,
) -> list[dict[str, Any]]:
    """
    Picks the rows to expose in the supernet overview's 'subnets' block

    Encapsulates the search-vs-tree branch. When the search query is active (see
    ``active_search``) the rows are filtered to every subnet whose 'network' property contains
    the query as a case-insensitive substring (regardless of nesting depth). Otherwise the
    function falls back to the top-level tree view, returning only rows whose 'parent_id' is
    None - the same set the overview surfaces when no search is active

    Args:
        ordered_subnets (list[dict[str, Any]]): All rows produced by ``sort_and_link_subnets``
            for the supernet under inspection
        search (str): Raw search query as received by the caller; may be empty, whitespace or
            shorter than the minimum query length

    Returns:
        list[dict[str, Any]]: Rows to list in the overview, preserving the input row order
    """
    needle: str | None = active_search(search)

    if needle is not None:
        return _filter_rows_by_network_substring(ordered_subnets, needle)

    return [row for row in ordered_subnets if row.get(IpamOverviewKey.PARENT_ID) is None]


def _select_invalid_listed_rows(
    ordered_subnets: list[dict[str, Any]],
    search: str,
) -> list[dict[str, Any]]:
    """
    Picks the rows to expose in the invalid-subnets-only overview's 'subnets' block

    Parallel to ``_select_listed_rows`` but scoped to the invalid subset: always restricts to
    rows whose 'is_valid' annotation is False, then applies the shared search activation rule
    via ``active_search``. With an active search the result is further filtered to entries
    whose 'network' (cidr) property contains the query as a case-insensitive substring;
    otherwise every invalid row is returned. The tree shape is intentionally dropped: this
    view is a flat list at every depth

    Args:
        ordered_subnets (list[dict[str, Any]]): Rows that have been through ``_annotate_is_valid``
        search (str): Raw search query as received by the caller; may be empty, whitespace or
            shorter than the minimum query length

    Returns:
        list[dict[str, Any]]: Invalid rows to list, preserving the input row order
    """
    invalid: list[dict[str, Any]] = _select_invalid_rows(ordered_subnets)
    needle: str | None = active_search(search)

    if needle is not None:
        return _filter_rows_by_network_substring(invalid, needle)

    return invalid


def _paginate_rows(
    rows: list[dict[str, Any]],
    page: int,
    page_size: int,
) -> tuple[int, int, list[dict[str, Any]]]:
    """
    Slices a flat row list into one page using the standard IPAM page / page_size policy

    Delegates clamping to ``clamp_page`` so the same bounds (1-based pages, page_size in
    [IpamPagination.MIN_PAGE_SIZE, IpamPagination.MAX_PAGE_SIZE]) apply across every overview
    route. The slice indices are derived from the clamped values, so a caller asking for a
    page past the end receives the last valid page rather than an empty one

    Args:
        rows (list[dict[str, Any]]): Flat list of rows to paginate
        page (int): Requested 1-based page number; clamped server-side
        page_size (int): Requested page size; clamped server-side

    Returns:
        tuple[int, int, list[dict[str, Any]]]: (safe_page, safe_size, page_rows) where
            page_rows is the rows that fall on the resolved page
    """
    safe_page, safe_size = clamp_page(page, page_size, len(rows))
    start: int = (safe_page - 1) * safe_size
    end: int = start + safe_size

    return safe_page, safe_size, rows[start:end]


# -------------------------------------------------------------------------------------------------------------------- #
#                                                   DATA LOADING                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
def load_supernet_object(
    objects_manager: ObjectsManager,
    types_manager: TypesManager,
    public_id: int,
) -> dict[str, Any]:
    """
    Loads the SUPERNET CmdbObject by public_id, aborting with a structured HTTP error when
    the SUPERNET CmdbType is undefined, the object does not exist, or the object exists but
    is of a different CmdbType

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        public_id (int): public_id of the candidate supernet object

    Returns:
        dict[str, Any]: The supernet CmdbObject document
    """
    supernet_type_id: int | None = resolve_special_type_id(types_manager, SpecialType.SUPERNET)

    if supernet_type_id is None:
        abort(400, "No SUPERNET CmdbType is defined; cannot build supernet overview!")

    candidates: list[dict[str, Any]] = objects_manager.find_objects(
        {CmdbObjectKey.PUBLIC_ID: public_id},
        as_dict=True,
    )

    if not candidates:
        abort(404, f"Supernet with public_id {public_id} was not found!")

    candidate: dict[str, Any] = candidates[0]

    if candidate.get(CmdbObjectKey.TYPE_ID) != supernet_type_id:
        abort(400, f"Object with public_id {public_id} is not a SUPERNET!")

    return candidate


def _parse_supernet_cidr(supernet_obj: dict[str, Any]) -> Network | None:
    """
    Returns the parsed Network of a SUPERNET CmdbObject, or None when unparsable / missing

    Reads the supernet's 'dg-network-range' field via ``extract_field_value`` and runs
    ``parse_cidr`` over it when the value is a string. Returns None when the field is missing,
    not a string, or fails to parse, so a degenerate supernet does not crash the overview build

    Args:
        supernet_obj (dict[str, Any]): The supernet CmdbObject document

    Returns:
        Network | None: Parsed network, or None when the CIDR is missing or unparsable
    """
    raw_cidr: Any = extract_field_value(supernet_obj, SupernetField.NETWORK_RANGE)

    if not isinstance(raw_cidr, str):
        return None

    return parse_cidr(raw_cidr)


def load_subnets_for_supernet(
    objects_manager: ObjectsManager,
    types_manager: TypesManager,
    supernet_public_id: int,
) -> list[dict[str, Any]]:
    """
    Returns every SUBNET CmdbObject whose 'dg-supernet-ref' points at the given supernet

    Returns an empty list when no SUBNET CmdbType is defined yet

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        supernet_public_id (int): public_id of the supernet object

    Returns:
        list[dict[str, Any]]: SUBNET CmdbObject documents linked to the supernet
    """
    subnet_type_id: int | None = resolve_special_type_id(types_manager, SpecialType.SUBNET)

    if subnet_type_id is None:
        return []

    criteria: dict[str, Any] = {
        CmdbObjectKey.TYPE_ID: subnet_type_id,
        CmdbObjectKey.FIELDS: {
            '$elemMatch': {
                CmdbObjectFieldKey.NAME: SubnetField.PARENT_SUPERNET,
                CmdbObjectFieldKey.VALUE: supernet_public_id,
            },
        },
    }

    return objects_manager.find_objects(criteria, as_dict=True)


def _count_used_ips_per_subnet(
    objects_manager: ObjectsManager,
    subnet_ids: list[int],
) -> dict[int, int]:
    """
    Counts dg-ipam-interface rows by referenced subnet across every CmdbObject in the system

    A single Mongo query selects candidate CmdbObjects whose interface section references
    any of the given subnet ids. Bucketing happens in Python to keep the pipeline portable
    (Cosmos Mongo API friendly: no aggregation stages required)

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        subnet_ids (list[int]): The subnet public_ids to count usage for

    Returns:
        dict[int, int]: {subnet_id: row_count} with one entry per id in subnet_ids
            (zero when no rows reference it)
    """
    counts: dict[int, int] = {sid: 0 for sid in subnet_ids}

    if not subnet_ids:
        return counts

    criteria: dict[str, Any] = {
        CmdbObjectKey.MULTI_DATA_SECTIONS: {
            '$elemMatch': {
                CmdbObjectMdsKey.SECTION_ID: IpamSection.INTERFACE,
                CmdbObjectMdsKey.VALUES: {
                    '$elemMatch': {
                        CmdbObjectMdsRowKey.DATA: {
                            '$elemMatch': {
                                CmdbObjectFieldKey.NAME: InterfaceField.SUBNET,
                                CmdbObjectFieldKey.VALUE: {'$in': subnet_ids},
                            },
                        },
                    },
                },
            },
        },
    }

    candidates: list[dict[str, Any]] = objects_manager.find_objects(criteria, as_dict=True)

    for candidate in candidates:
        for section in candidate.get(CmdbObjectKey.MULTI_DATA_SECTIONS, []) or []:
            if section.get(CmdbObjectMdsKey.SECTION_ID) != IpamSection.INTERFACE:
                continue

            for row in section.get(CmdbObjectMdsKey.VALUES, []) or []:
                row_subnet_id: Any = _row_subnet_ref(row)

                if row_subnet_id in counts:
                    counts[row_subnet_id] += 1

    return counts


def _row_subnet_ref(row: dict[str, Any]) -> Any:
    """
    Returns the dg-interface-subnet value of a single dg-ipam-interface MDS row, or None

    Args:
        row (dict[str, Any]): One entry from an MDS section's 'values' list

    Returns:
        Any: The referenced subnet's public_id, or None if the row has no such field
    """
    for entry in row.get(CmdbObjectMdsRowKey.DATA, []) or []:
        if entry.get(CmdbObjectFieldKey.NAME) == InterfaceField.SUBNET:
            return entry.get(CmdbObjectFieldKey.VALUE)

    return None


def _attach_vlans_to_rows(
    rows: list[dict[str, Any]],
    vlans_by_subnet: dict[int, list[dict[str, Any]]],
) -> None:
    """
    Sets a 'vlans' list on every row from the supplied per-subnet VLAN buckets

    Rows are mutated in place. A row whose public_id has no bucket receives an empty list so
    the FE can iterate the field unconditionally without nullability checks. Each row gets a
    shallow copy of its bucket list so downstream mutations of 'vlans' on one row cannot bleed
    into the original buckets or into sibling rows

    Args:
        rows (list[dict[str, Any]]): Overview rows; each row must carry a 'public_id' key
        vlans_by_subnet (dict[int, list[dict[str, Any]]]): Output of ``_load_vlans_by_subnet``
            (or any equivalent map of subnet_id → VLAN dicts)
    """
    for row in rows:
        row[IpamOverviewKey.VLANS] = list(vlans_by_subnet.get(row[CmdbObjectKey.PUBLIC_ID], []))


# -------------------------------------------------------------------------------------------------------------------- #
#                                                   ORCHESTRATOR                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
def _build_linked_subnet_rows(
    objects_manager: ObjectsManager,
    types_manager: TypesManager,
    supernet_public_id: int,
) -> list[dict[str, Any]]:
    """
    Loads every SUBNET under the supernet, shapes overview rows and links parents by CIDR

    Encapsulates the DB-and-link step that both orchestrators share: load the subnet objects,
    count interface IPs per subnet, batch-load VLANs referencing those subnets, shape one row
    per subnet, run ``sort_and_link_subnets`` so each row carries a ``parent_id`` pointing at
    its most-specific CIDR-enclosing sibling (or None when top-level), and attach the per-row
    VLAN list (empty when no VLAN references the subnet)

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        supernet_public_id (int): public_id of the supernet to load subnets for

    Returns:
        list[dict[str, Any]]: Subnet rows sorted by ascending CIDR with ``parent_id`` set and
            ``vlans`` populated; rows with unparsable CIDRs trail the sorted block
    """
    subnet_objs: list[dict[str, Any]] = load_subnets_for_supernet(
        objects_manager, types_manager, supernet_public_id,
    )
    subnet_ids: list[int] = [s[CmdbObjectKey.PUBLIC_ID] for s in subnet_objs if CmdbObjectKey.PUBLIC_ID in s]

    used_per_subnet: dict[int, int] = _count_used_ips_per_subnet(objects_manager, subnet_ids)
    vlans_by_subnet: dict[int, list[dict[str, Any]]] = load_vlans_by_subnets(
        objects_manager, types_manager, subnet_ids,
    )

    subnet_rows: list[dict[str, Any]] = [
        compute_subnet_row(s, used_per_subnet.get(s.get(CmdbObjectKey.PUBLIC_ID), 0))
        for s in subnet_objs
    ]

    ordered: list[dict[str, Any]] = sort_and_link_subnets(subnet_rows)
    _attach_vlans_to_rows(ordered, vlans_by_subnet)

    return ordered


def load_assigned_subnet_rows(
    objects_manager: ObjectsManager,
    types_manager: TypesManager,
    supernet_public_id: int,
) -> list[dict[str, Any]]:
    """
    Returns every assigned subnet of a supernet as overview rows, without pagination

    Validates that the supernet exists and is a SUPERNET (aborting otherwise, exactly like the
    overview routes), then returns all subnet rows referencing it - every nesting depth - sorted
    by ascending CIDR with parent_id and vlans populated. Intended for callers that need the full
    set rather than a page (e.g. the subnets export)

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        supernet_public_id (int): public_id of the SUPERNET whose assigned subnets are returned

    Returns:
        list[dict[str, Any]]: All assigned subnet rows (see compute_subnet_row / _build_linked_subnet_rows)
    """
    load_supernet_object(objects_manager, types_manager, supernet_public_id)

    return _build_linked_subnet_rows(objects_manager, types_manager, supernet_public_id)


def resolve_supernet_family(
    objects_manager: ObjectsManager,
    types_manager: TypesManager,
    supernet_public_id: int,
) -> str:
    """
    Returns the address family ('ipv4' / 'ipv6') of a SUPERNET, loading and validating it first

    Loads the supernet exactly like the overview routes (aborting 400/404 on a bad id) and
    resolves its family via ``supernet_family`` (CIDR-first, selector fallback). Intended for
    callers that need the family without the subnet rows - e.g. the subnets export, which uses
    it to decide whether the IPv4-only 'Usage (%)' column belongs in the sheet

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        supernet_public_id (int): public_id of the SUPERNET whose family is resolved

    Returns:
        str: IpAddressFamily.IPV6 or IpAddressFamily.IPV4
    """
    supernet_obj: dict[str, Any] = load_supernet_object(objects_manager, types_manager, supernet_public_id)

    return supernet_family(supernet_obj)


def _summarize_supernet(
    ordered_subnets: list[dict[str, Any]],
    supernet_network: Network | None,
    family: str,
) -> dict[str, Any]:
    """
    Builds the supernet KPI strip from already-shaped subnet rows, the supernet network and family

    Sums the per-row 'used_ips' across every subnet under the supernet (regardless of nesting
    depth) and passes the total, the subnet count, the parsed supernet network and the address
    family through ``compute_supernet_summary`` (the family decides whether the percentage fields
    are reported or nulled). Keeping this sum-and-summarize step in one function lets the overview
    orchestrator stay free of intermediate locals

    Args:
        ordered_subnets (list[dict[str, Any]]): Rows produced by ``sort_and_link_subnets``
            (and already annotated with 'has_children'); every row must carry 'used_ips'
        supernet_network (Network | None): Parsed CIDR of the supernet, None if missing
            or unparsable
        family (str): The supernet's IpAddressFamily ('ipv4' / 'ipv6')

    Returns:
        dict[str, Any]: KPI strip dict as produced by ``compute_supernet_summary``
    """
    total_used: int = sum(row[IpamOverviewKey.USED_IPS] for row in ordered_subnets)

    return compute_supernet_summary(supernet_network, total_used, len(ordered_subnets), family)


def _prepare_supernet_view(
    objects_manager: ObjectsManager,
    types_manager: TypesManager,
    public_id: int,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any], int]:
    """
    Loads the supernet and builds the fully-annotated subnet row list shared by the
    paginated-view orchestrators

    Encapsulates the pipeline that ``build_supernet_overview`` and
    ``build_invalid_subnet_overview`` both need before they diverge into their own row-
    selection logic: load the supernet (aborts 400/404 on failure), parse its CIDR, build
    the linked subnet rows, annotate 'has_children' and 'is_valid', compute the KPI summary,
    and count the invalid rows. Returning the supernet doc, the annotated row list, the
    summary and the invalid count lets each consumer assemble its response envelope with one
    line of work and keeps the O(n) invalid-count scan in exactly one place

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        public_id (int): public_id of the supernet to prepare

    Returns:
        tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any], int]:
            (supernet CmdbObject document, annotated rows in CIDR order, KPI summary dict,
            total number of invalid rows across the full row set)
    """
    supernet_obj: dict[str, Any] = load_supernet_object(objects_manager, types_manager, public_id)
    supernet_network: Network | None = _parse_supernet_cidr(supernet_obj)
    family: str = supernet_family(supernet_obj)

    ordered_subnets: list[dict[str, Any]] = _build_linked_subnet_rows(
        objects_manager, types_manager, public_id,
    )
    _annotate_has_children(ordered_subnets, _index_children_by_parent(ordered_subnets))
    _annotate_is_valid(ordered_subnets, supernet_network)

    summary: dict[str, Any] = _summarize_supernet(ordered_subnets, supernet_network, family)
    invalid_count: int = _count_invalid_rows(ordered_subnets)

    return supernet_obj, ordered_subnets, summary, invalid_count


def build_supernet_overview(
    objects_manager: ObjectsManager,
    types_manager: TypesManager,
    public_id: int,
    page: int = 1,
    page_size: int = IpamPagination.DEFAULT_PAGE_SIZE,
    search: str = '',
) -> dict[str, Any]:
    """
    Builds the paginated supernet overview payload

    The KPI strip in 'supernet' covers every subnet under the supernet (regardless of nesting
    depth), so the totals stay stable as the user paginates, expands rows or filters by search.
    The 'subnets' block lists rows paginated with the same page / page_size semantics used by
    the subnet overview. Each returned row carries 'has_children: bool' so the frontend can
    render an expand caret without a probe request; the direct children themselves are fetched
    via ``build_supernet_subnet_children``. Each row also carries 'is_valid: bool' - true when
    the subnet's CIDR sits strictly inside the supernet's CIDR, false when the subnet's range
    no longer fits (e.g. the supernet's CIDR was edited and orphaned the subnet) or when the
    subnet / supernet CIDR is missing or unparsable

    The top-level 'invalid_count' is the total number of invalid subnets under the supernet
    regardless of pagination, search or nesting depth; the FE uses it to render a banner that
    deep-links to the dedicated invalid-only view (``build_invalid_subnet_overview``)

    When ``search`` is empty / whitespace, the 'subnets' block lists only top-level subnets -
    those whose CIDR is not strictly contained by any sibling. When ``search`` is non-empty,
    the tree shape is dropped and the block instead returns a flat list of every subnet under
    the supernet (any nesting depth) whose 'network' property contains ``search`` as a
    case-insensitive substring, still paginated. Each row keeps its 'parent_id' / 'has_children'
    so the frontend can link back to the tree when the user clears the search

    Aborts with HTTP 404 when the supernet does not exist, HTTP 400 when the public_id refers
    to a non-supernet CmdbObject or no SUPERNET CmdbType is defined

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        public_id (int): public_id of the supernet to summarise
        page (int): 1-based page number for the subnet list (clamped into the valid range)
        page_size (int): Page size for the subnet list (clamped to
            [IpamPagination.MIN_PAGE_SIZE, IpamPagination.MAX_PAGE_SIZE])
        search (str): Optional case-insensitive substring filter against each subnet's
            'network' property; empty / whitespace and queries shorter than
            IpamSearch.MIN_QUERY_LENGTH after stripping are ignored and restore the top-level
            tree view

    Returns:
        dict[str, Any]: {'supernet': {public_id, ...summary over all subnets...},
            'subnets': {page, page_size, total, rows: [...subnet rows with has_children, is_valid]},
            'invalid_count': total invalid subnets under the supernet}
    """
    supernet_obj, ordered_subnets, summary, invalid_count = _prepare_supernet_view(
        objects_manager, types_manager, public_id,
    )

    listed_rows: list[dict[str, Any]] = _select_listed_rows(ordered_subnets, search)
    safe_page, safe_size, page_rows = _paginate_rows(listed_rows, page, page_size)

    return {
        IpamOverviewKey.SUPERNET: {
            CmdbObjectKey.PUBLIC_ID: supernet_obj.get(CmdbObjectKey.PUBLIC_ID),
            **summary,
        },
        IpamOverviewKey.SUBNETS: {
            IpamOverviewKey.PAGE: safe_page,
            IpamOverviewKey.PAGE_SIZE: safe_size,
            IpamOverviewKey.TOTAL: len(listed_rows),
            IpamOverviewKey.ROWS: page_rows,
        },
        IpamOverviewKey.INVALID_COUNT: invalid_count,
    }


def build_supernet_subnet_children(
    objects_manager: ObjectsManager,
    types_manager: TypesManager,
    supernet_public_id: int,
    subnet_public_id: int,
) -> dict[str, Any]:
    """
    Builds the direct-children payload for one subnet under the given supernet

    Returns every subnet whose closest CIDR-enclosing sibling under the same supernet is
    ``subnet_public_id`` - i.e. one level of nesting only. Children are returned in ascending
    CIDR order (inherited from ``sort_and_link_subnets``). Each child row carries
    ``has_children`` so the frontend can render nested expand carets without follow-up probes
    and ``is_valid`` so the FE can flag children that fall outside the supernet's current CIDR
    (e.g. after a range edit that orphaned them)

    Aborts with HTTP 404 when the supernet does not exist, HTTP 400 when the supernet id
    refers to a non-supernet CmdbObject, when no SUPERNET / SUBNET CmdbType is defined, or
    when ``subnet_public_id`` is not a SUBNET whose ``dg-supernet-ref`` matches the supernet

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        supernet_public_id (int): public_id of the SUPERNET whose subnet tree is being queried
        subnet_public_id (int): public_id of the parent SUBNET whose direct children should
            be returned

    Returns:
        dict[str, Any]: {'parent': {'public_id': subnet_public_id}, 'rows': [child_row, ...]}
    """
    supernet_obj: dict[str, Any] = load_supernet_object(
        objects_manager, types_manager, supernet_public_id,
    )

    ordered_subnets: list[dict[str, Any]] = _build_linked_subnet_rows(
        objects_manager, types_manager, supernet_public_id,
    )

    parent_present: bool = any(
        row.get(CmdbObjectKey.PUBLIC_ID) == subnet_public_id for row in ordered_subnets
    )

    if not parent_present:
        abort(
            400,
            f"Subnet with public_id {subnet_public_id} is not a SUBNET under supernet"
            f" {supernet_public_id}!",
        )

    children_index: dict[Any, list[dict[str, Any]]] = _index_children_by_parent(ordered_subnets)
    _annotate_has_children(ordered_subnets, children_index)
    _annotate_is_valid(ordered_subnets, _parse_supernet_cidr(supernet_obj))

    children: list[dict[str, Any]] = children_index.get(subnet_public_id, [])

    return {
        IpamOverviewKey.PARENT: {CmdbObjectKey.PUBLIC_ID: subnet_public_id},
        IpamOverviewKey.ROWS: children,
    }


def build_invalid_subnet_overview(
    objects_manager: ObjectsManager,
    types_manager: TypesManager,
    public_id: int,
    page: int = 1,
    page_size: int = IpamPagination.DEFAULT_PAGE_SIZE,
    search: str = '',
) -> dict[str, Any]:
    """
    Builds the paginated invalid-subnets-only overview payload

    Same envelope as ``build_supernet_overview`` (``supernet`` summary block, ``subnets`` page
    block, top-level ``invalid_count``), with one intentional difference in the ``subnets``
    block: the tree shape is dropped. The block is a flat list of every subnet under the
    supernet whose 'is_valid' annotation is False, regardless of nesting depth. Each row still
    carries 'parent_id' / 'has_children' / 'is_valid' / 'vlans' so the FE can render the same
    row template it uses for the main overview

    Search semantics mirror ``build_supernet_overview``: when ``search`` is empty / whitespace
    or shorter than IpamSearch.MIN_QUERY_LENGTH after stripping, every invalid row is returned;
    otherwise the invalid set is filtered to entries whose 'network' property contains
    ``search`` as a case-insensitive substring. ``subnets.total`` reflects the search-filtered
    count, while the top-level ``invalid_count`` and the 'supernet' KPI strip are computed over
    every subnet under the supernet (not just the page or the search match), so those metrics
    stay stable as the user paginates or filters

    Rows are ordered ascending by CIDR (inherited from ``sort_and_link_subnets``); rows with
    unparsable CIDR are also invalid and trail the sorted block

    Aborts with HTTP 404 when the supernet does not exist, HTTP 400 when the public_id refers
    to a non-supernet CmdbObject or no SUPERNET CmdbType is defined

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        public_id (int): public_id of the supernet whose invalid subnets are listed
        page (int): 1-based page number for the subnet list (clamped into the valid range)
        page_size (int): Page size for the subnet list (clamped to
            [IpamPagination.MIN_PAGE_SIZE, IpamPagination.MAX_PAGE_SIZE])
        search (str): Optional case-insensitive substring filter against each invalid subnet's
            'network' property; empty / whitespace and queries shorter than
            IpamSearch.MIN_QUERY_LENGTH after stripping are ignored and restore the unfiltered
            invalid list

    Returns:
        dict[str, Any]: {'supernet': {public_id, ...summary over all subnets...},
            'subnets': {page, page_size, total, rows: [...invalid rows in CIDR order]},
            'invalid_count': total invalid subnets under the supernet}
    """
    supernet_obj, ordered_subnets, summary, invalid_count = _prepare_supernet_view(
        objects_manager, types_manager, public_id,
    )

    listed_rows: list[dict[str, Any]] = _select_invalid_listed_rows(ordered_subnets, search)
    safe_page, safe_size, page_rows = _paginate_rows(listed_rows, page, page_size)

    return {
        IpamOverviewKey.SUPERNET: {
            CmdbObjectKey.PUBLIC_ID: supernet_obj.get(CmdbObjectKey.PUBLIC_ID),
            **summary,
        },
        IpamOverviewKey.SUBNETS: {
            IpamOverviewKey.PAGE: safe_page,
            IpamOverviewKey.PAGE_SIZE: safe_size,
            IpamOverviewKey.TOTAL: len(listed_rows),
            IpamOverviewKey.ROWS: page_rows,
        },
        IpamOverviewKey.INVALID_COUNT: invalid_count,
    }
