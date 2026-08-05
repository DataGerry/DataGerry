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
Distribution payloads ('IP-Verteilung' grid and type pie) for the subnet IP-Übersicht

Owns the heatmap grid (ranges x sectors with per-cell type breakdowns) and the whole-subnet
type distribution that feeds the frontend pie chart
"""
from ipaddress import IPv4Address, IPv6Address
from typing import Any

from cmdb.models.object_model import CmdbObjectKey
from cmdb.models.special_type_model.ipam_constants import (
    IpAddressFamily,
    IpamBucketLabel,
    IpamDistributionLimits,
    IpamOverviewKey,
)
from cmdb.framework.ipam.cidr import (
    Network,
    Address,
    parse_ip,
    network_family,
    total_address_count,
)
from cmdb.framework.ipam.subnet_overview.assigned_rows import AssignedField
# -------------------------------------------------------------------------------------------------------------------- #


def format_ip(value: int, is_ipv6: bool) -> str:
    """
    Renders an integer address as a canonical IP string in the requested address family

    Used by the IP-Verteilung grid to label sector / range boundaries: an IPv6 subnet's
    boundary integers exceed the IPv4 range, so the family must be chosen explicitly rather
    than always constructing an IPv4Address

    Args:
        value (int): The integer value of the address
        is_ipv6 (bool): True to render as IPv6, False as IPv4

    Returns:
        str: The canonical address string
    """
    return str((IPv6Address if is_ipv6 else IPv4Address)(value))


def compute_grid_dimensions(total: int) -> tuple[int, int, int]:
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


def _bucket_used_by_type(
    assigned: dict[str, dict[str, Any]],
    network: Network,
    sector_size: int,
    total_cells: int,
) -> list[dict[int | None, int]]:
    """
    Tallies assigned IPs per grid cell, broken down by the owning CmdbType id

    Walks the assigned map once, computes each IP's offset from the subnet's network address,
    and integer-divides by 'sector_size' to land in the owning cell. IPs outside the subnet or
    unparsable are skipped defensively (the caller already filters in load_assigned_rows_map
    but this stays robust against future drift). Within each cell the count is bucketed by the
    row's type_id: int type_ids are kept as-is, anything else (missing, non-int) collapses into
    a single ``None`` key so the consumer can route it through the Unknown bucket without a
    second pass. Resolving the ``None`` key against the live type_meta is the caller's job -
    this helper only records what the row claims. Complexity is O(used), not O(total_cells), so
    /1 stays cheap

    Args:
        assigned (dict[str, dict[str, Any]]): {ip_str: row_info} as produced by
            load_assigned_rows_map
        network (IPv4Network): The parsed subnet network
        sector_size (int): Number of addresses each cell covers
        total_cells (int): Number of cells in the grid (ranges_count * sectors_per_range)

    Returns:
        list[dict[int | None, int]]: Per-cell {type_id_or_None: count} breakdowns, indexed by
            global cell position; length == total_cells. Each breakdown is empty when the cell
            has no assigned IPs. Summing a breakdown's values yields the cell's used count
    """
    breakdowns: list[dict[int | None, int]] = [{} for _ in range(total_cells)]

    if total_cells == 0 or sector_size <= 0:
        return breakdowns

    base_int: int = int(network.network_address)
    span: int = total_cells * sector_size

    for ip_str, info in assigned.items():
        parsed: Address | None = parse_ip(ip_str)

        if parsed is None:
            continue

        offset: int = int(parsed) - base_int

        if offset < 0 or offset >= span:
            continue

        raw_type_id: Any = info.get(AssignedField.TYPE_ID)
        key: int | None = raw_type_id if isinstance(raw_type_id, int) else None

        cell: dict[int | None, int] = breakdowns[offset // sector_size]
        cell[key] = cell.get(key, 0) + 1

    return breakdowns


def _compose_sector_type_stats(
    breakdown: dict[int | None, int],
    type_meta: dict[int, dict[str, Any]],
    is_ipv6: bool = False,
) -> list[dict[str, Any]]:
    """
    Shapes the 'type_stats' list for one sector of the 'ip_distribution' grid

    Translates a raw per-cell {type_id_or_None: count} breakdown into the wire-format bucket
    list emitted next to each sector. Type ids that are int AND present in type_meta become
    real buckets (carrying public_id, label, ci_explorer_color); anything else (None, or an
    int that no longer resolves because the CmdbType was deleted) collapses into a single
    Unknown bucket with public_id=None and ci_explorer_color=None so the chart never grows a
    slice per stale type_id. Mirrors the Unknown-collapsing rule of build_type_distribution
    so the per-sector and whole-subnet payloads stay consistent

    Percentages are computed against the sector's used count (the sum of all values in the
    breakdown) and rounded to two decimals. Buckets are sorted by count descending, then by
    public_id ascending as a tiebreak; the Unknown bucket is always emitted last so its
    position is stable regardless of size

    Precondition: every count value in ``breakdown`` is positive. ``_bucket_used_by_type``
    upholds this by only inserting via ``cell[key] = cell.get(key, 0) + 1`` so the helper
    short-circuits on ``used_count <= 0`` rather than guarding each division

    Args:
        breakdown (dict[int | None, int]): Per-cell {type_id_or_None: count} as produced by
            _bucket_used_by_type for one cell
        type_meta (dict[int, dict[str, Any]]): {type_id: {'label', 'ci_explorer_color'}} as
            produced by resolve_type_meta; type_ids absent from this mapping fall through to
            the Unknown bucket

    Returns:
        list[dict[str, Any]]: One entry per known type bucket with keys public_id, label,
            ci_explorer_color, count, percentage, followed by the Unknown bucket (only when
            non-empty). Empty list when the cell has no assigned IPs
    """
    used_count: int = sum(breakdown.values())

    if used_count <= 0:
        return []

    known_counts: dict[int, int] = {}
    unknown_count: int = 0

    for raw_key, count in breakdown.items():
        if isinstance(raw_key, int) and raw_key in type_meta:
            known_counts[raw_key] = known_counts.get(raw_key, 0) + count
        else:
            unknown_count += count

    known_buckets: list[dict[str, Any]] = [
        {
            CmdbObjectKey.PUBLIC_ID: type_id,
            IpamOverviewKey.LABEL: type_meta[type_id][IpamOverviewKey.LABEL],
            IpamOverviewKey.CI_EXPLORER_COLOR: type_meta[type_id].get(IpamOverviewKey.CI_EXPLORER_COLOR),
            IpamOverviewKey.COUNT: count,
            IpamOverviewKey.PERCENTAGE: None if is_ipv6 else round((count / used_count) * 100, 2),
        }
        for type_id, count in known_counts.items()
    ]

    known_buckets.sort(key=lambda bucket: (-bucket[IpamOverviewKey.COUNT], bucket[CmdbObjectKey.PUBLIC_ID]))

    if unknown_count > 0:
        known_buckets.append({
            CmdbObjectKey.PUBLIC_ID: None,
            IpamOverviewKey.LABEL: IpamBucketLabel.UNKNOWN,
            IpamOverviewKey.CI_EXPLORER_COLOR: None,
            IpamOverviewKey.COUNT: unknown_count,
            IpamOverviewKey.PERCENTAGE: None if is_ipv6 else round((unknown_count / used_count) * 100, 2),
        })

    return known_buckets


def _compose_sector(
    first_ip_int: int,
    sector_size: int,
    breakdown: dict[int | None, int],
    type_meta: dict[int, dict[str, Any]],
    is_ipv6: bool = False,
) -> dict[str, Any]:
    """
    Shapes one sector entry of the 'ip_distribution' grid

    The sector's used_count is derived from the breakdown (sum of all per-type counts) so the
    same source of truth feeds both the heatmap saturation and the per-type pie. ``percentage``
    is the per-cell saturation ('used_count / sector_size * 100'), rounded to two decimals;
    this matches the frontend's heatmap colouring convention. ``type_stats`` is the per-type
    pie data delegated to _compose_sector_type_stats; it is always present (empty list when
    the sector has no assigned IPs) so the FE never has to null-check. Position-implied fields
    (sector index, sector size) are omitted: the consumer reads the index from the sector's
    position in its parent range's 'sectors' array, and derives the size from
    ip_end - ip_start + 1

    Args:
        first_ip_int (int): Integer of the first address the sector covers
        sector_size (int): Number of addresses the sector covers (used only for the percentage
            denominator and to compute ip_end)
        breakdown (dict[int | None, int]): Per-cell {type_id_or_None: count} as produced by
            _bucket_used_by_type for this cell
        type_meta (dict[int, dict[str, Any]]): {type_id: {'label', 'ci_explorer_color'}} as
            produced by resolve_type_meta

    Returns:
        dict[str, Any]: Sector entry with ip_start, ip_end, used_count, percentage, type_stats
    """
    used_count: int = sum(breakdown.values())

    return {
        IpamOverviewKey.IP_START: format_ip(first_ip_int, is_ipv6),
        IpamOverviewKey.IP_END: format_ip(first_ip_int + sector_size - 1, is_ipv6),
        IpamOverviewKey.USED_COUNT: used_count,
        IpamOverviewKey.PERCENTAGE: None if is_ipv6 else round((used_count / sector_size) * 100, 2),
        IpamOverviewKey.TYPE_STATS: _compose_sector_type_stats(breakdown, type_meta, is_ipv6),
    }


def build_ip_distribution(
    network: Network | None,
    assigned: dict[str, dict[str, Any]],
    type_meta: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    """
    Builds the 'IP-Verteilung' grid payload for one subnet, or an empty dict when no grid is rendered

    The grid is only emitted at its full size (MAX_RANGES x MAX_SECTORS_PER_RANGE = 64 cells),
    which corresponds to /26 and shorter prefixes. For /27 and narrower subnets the resulting
    grid would have fewer cells; in that case (and when the CIDR is missing or unparsable) the
    function returns an empty dict so the frontend can omit the visualisation entirely. When
    rendered, every cell covers an equal slice of the subnet (network + broadcast included)
    and carries the count of assigned IPs, a per-cell saturation percentage that drives the
    heatmap colouring, and a per-type breakdown of the assigned IPs inside the cell

    The returned structure is intentionally minimal: position-implied fields (range index,
    sector index, sector size, top-level grid dimensions) are omitted because the grid
    dimensions are fixed and the indexes follow array order. Range-level ip_start / ip_end are
    kept because the frontend renders them as row labels next to each range

    Args:
        network (IPv4Network | None): The parsed subnet network, or None when the subnet's
            CIDR is missing or unparsable
        assigned (dict[str, dict[str, Any]]): {ip_str: row_info} as produced by
            load_assigned_rows_map; both the bucket counts and the per-cell type_stats are
            derived from it
        type_meta (dict[int, dict[str, Any]]): {type_id: {'label', 'ci_explorer_color'}} as
            produced by resolve_type_meta; used to label per-cell type buckets and to decide
            which type_ids fall through to Unknown

    Returns:
        dict[str, Any]: {'sector_size': N, 'ranges': [...]} when the subnet qualifies for the
            full grid, where 'sector_size' is the number of addresses each cell covers (same
            for every cell since the grid is uniform) and each range carries ip_start, ip_end,
            and a nested 'sectors' list of cells with ip_start, ip_end, used_count, percentage,
            type_stats. Empty dict ({}) otherwise
    """
    if network is None:
        return {}

    is_ipv6: bool = network_family(network) == IpAddressFamily.IPV6
    total: int = total_address_count(network)
    ranges_count, sectors_per_range, sector_size = compute_grid_dimensions(total)
    total_cells: int = ranges_count * sectors_per_range
    max_grid_cells: int = (
        IpamDistributionLimits.MAX_RANGES * IpamDistributionLimits.MAX_SECTORS_PER_RANGE
    )

    if total_cells < max_grid_cells:
        return {}

    breakdowns: list[dict[int | None, int]] = _bucket_used_by_type(
        assigned, network, sector_size, total_cells,
    )

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
                breakdowns[global_cell],
                type_meta,
                is_ipv6,
            ))

        ranges.append({
            IpamOverviewKey.IP_START: format_ip(range_first_int, is_ipv6),
            IpamOverviewKey.IP_END: format_ip(range_first_int + range_span - 1, is_ipv6),
            IpamOverviewKey.SECTORS: sectors,
        })

    return {
        IpamOverviewKey.SECTOR_SIZE: sector_size,
        IpamOverviewKey.RANGES: ranges,
    }


def build_type_distribution(
    assigned: dict[str, dict[str, Any]],
    type_meta: dict[int, dict[str, Any]],
    total: int,
    is_ipv6: bool = False,
) -> list[dict[str, Any]]:
    """
    Builds the whole-subnet IP-usage distribution that feeds the frontend pie chart

    Aggregates the assigned-IP map by owning CmdbType, appends a synthetic 'Free' bucket for
    unused capacity, and collapses every orphaned assignment (type_id missing on the interface
    row or no longer resolvable because the CmdbType was deleted) into a single 'Unknown'
    bucket so the chart never grows a slice per stale type_id. Only rows whose
    ``is_valid`` flag is True contribute - invalid (out-of-CIDR) rows are excluded so the
    percentages stay bounded; the FE surfaces those via the top-level ``invalid_count`` instead.

    The percentage denominator differs by family. For IPv4 it is the subnet's assignable address
    count (capacity), so the percentages express utilisation and a synthetic 'Free' bucket is
    appended for the unused capacity. For IPv6 it is the total assigned (valid) address count, so
    the percentages express the composition of the in-use addresses and sum to 100% across the
    buckets - a used/2**n ratio and a free count are meaningless against a 2**n space, so the
    'Free' bucket is omitted. Both families emit the same per-type bucket fields (public_id,
    label, ci_explorer_color, count, percentage). An empty list is returned when the subnet has
    zero assignable addresses or the CIDR is unparsable, so the frontend can render a placeholder

    Args:
        assigned (dict[str, dict[str, Any]]): {ip_str: {'object_id', 'type_id', 'mac',
            'is_valid'}} as produced by load_assigned_rows_map; one entry per dg-ipam-interface
            row referencing this subnet (valid + invalid)
        type_meta (dict[int, dict[str, Any]]): {type_id: {'label', 'ci_explorer_color'}} for
            every CmdbType referenced by the assigned map; type_ids absent from this mapping
            fall through to the Unknown bucket
        total (int): Assignable address count of the subnet (denominator for percentages)
        is_ipv6 (bool): True for an IPv6 subnet; nulls the percentages and omits the Free bucket

    Returns:
        list[dict[str, Any]]: One entry per type bucket with keys public_id, label,
            ci_explorer_color, count, percentage, followed by the Unknown bucket (only when
            non-empty) and - for IPv4 only - the Free bucket; the Unknown / Free buckets carry
            ci_explorer_color=None. 'percentage' is utilisation (vs capacity) for IPv4 and
            share-of-assigned for IPv6. Empty list when total is 0
    """
    if total <= 0:
        return []

    by_type: dict[int, int] = {}
    unknown_count: int = 0
    valid_count: int = 0

    for info in assigned.values():
        if not info.get(AssignedField.IS_VALID):
            continue

        valid_count += 1
        type_id: Any = info.get(AssignedField.TYPE_ID)

        if isinstance(type_id, int) and type_id in type_meta:
            by_type[type_id] = by_type.get(type_id, 0) + 1
        else:
            unknown_count += 1

    # IPv4 percentages express utilisation against capacity; IPv6 percentages express each type's
    # share of the assigned addresses (capacity is not a meaningful denominator for a 2**n space).
    # The denominator is only used to divide bucket counts, which exist only when valid_count > 0
    denominator: int = valid_count if is_ipv6 else total

    distribution: list[dict[str, Any]] = [
        {
            CmdbObjectKey.PUBLIC_ID: type_id,
            IpamOverviewKey.LABEL: type_meta[type_id][IpamOverviewKey.LABEL],
            IpamOverviewKey.CI_EXPLORER_COLOR: type_meta[type_id].get(IpamOverviewKey.CI_EXPLORER_COLOR),
            IpamOverviewKey.COUNT: count,
            IpamOverviewKey.PERCENTAGE: round((count / denominator) * 100, 2),
        }
        for type_id, count in by_type.items()
    ]

    if unknown_count > 0:
        distribution.append({
            CmdbObjectKey.PUBLIC_ID: None,
            IpamOverviewKey.LABEL: IpamBucketLabel.UNKNOWN,
            IpamOverviewKey.CI_EXPLORER_COLOR: None,
            IpamOverviewKey.COUNT: unknown_count,
            IpamOverviewKey.PERCENTAGE: round((unknown_count / denominator) * 100, 2),
        })

    if not is_ipv6:
        distribution.append({
            CmdbObjectKey.PUBLIC_ID: None,
            IpamOverviewKey.LABEL: IpamBucketLabel.FREE,
            IpamOverviewKey.CI_EXPLORER_COLOR: None,
            IpamOverviewKey.COUNT: max(0, total - valid_count),
            IpamOverviewKey.PERCENTAGE: round((max(0, total - valid_count) / total) * 100, 2),
        })

    return distribution
