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
Single-sector drill-down for the subnet IP-Verteilung grid

Backs the 'click a heatmap sector' interaction: resolves the clicked sector's bounds against
the same grid dimensions the overview emitted and paginates only that sector's IPs
"""
from typing import Any

from flask import abort

from cmdb.manager import ObjectsManager, TypesManager
from cmdb.models.special_type_model.ipam_constants import (
    IpAddressFamily,
    IpamDistributionLimits,
    IpamOverviewKey,
    IpamPagination,
)
from cmdb.framework.ipam.cidr import (
    Network,
    Address,
    parse_ip,
    network_family,
    total_address_count,
    first_assignable_int,
    assignable_address_count,
)
from cmdb.framework.ipam.pagination import clamp_page
from cmdb.framework.ipam.subnet_overview.assigned_rows import (
    AssignedField,
    load_assigned_rows_map,
    load_subnet_object,
    parse_subnet_network,
    resolve_summary_lines_for_ips,
    resolve_type_meta,
    sorted_assigned_ips,
)
from cmdb.framework.ipam.subnet_overview.distribution import compute_grid_dimensions, format_ip
from cmdb.framework.ipam.subnet_overview.rows import compose_ip_row
# -------------------------------------------------------------------------------------------------------------------- #


def _require_sector_grid(public_id: int, network: Network) -> int:
    """
    Returns the grid sector size for a subnet, aborting HTTP 400 when no full grid is exposed

    Mirrors ``build_ip_distribution``'s emit rule: the IP-Verteilung grid (and therefore any
    clickable sector) only exists when the subnet fills the full MAX_RANGES x MAX_SECTORS grid
    (/26 and shorter). Narrower subnets have no sectors, so the drill-down has nothing to resolve

    Args:
        public_id (int): public_id of the subnet (for the error message)
        network (Network): The parsed subnet network

    Returns:
        int: The number of addresses each grid sector covers
    """
    ranges_count, sectors_per_range, sector_size = compute_grid_dimensions(total_address_count(network))
    max_grid_cells: int = IpamDistributionLimits.MAX_RANGES * IpamDistributionLimits.MAX_SECTORS_PER_RANGE

    if ranges_count * sectors_per_range < max_grid_cells:
        abort(400, f"Subnet with ID {public_id} is too small to expose an IP-distribution grid!")

    return sector_size


def _resolve_sector_bounds(network: Network, sector_start: Any, sector_size: int) -> tuple[int, int]:
    """
    Validates a sector-start address and returns the [lo, hi] integer bounds of that sector

    The start must parse in the subnet's address family, sit inside the subnet, and align to a
    sector boundary (offset divisible by ``sector_size``) so the window matches exactly one cell
    of the IP-Verteilung grid. Any violation aborts HTTP 400

    Args:
        network (Network): The parsed subnet network
        sector_start (Any): The candidate sector start address (canonical IP string)
        sector_size (int): Number of addresses each grid cell covers

    Returns:
        tuple[int, int]: (sector_lo, sector_hi) inclusive integer bounds of the sector
    """
    start_addr: Address | None = parse_ip(sector_start) if isinstance(sector_start, str) else None

    if start_addr is None or start_addr.version != network.version:
        abort(400, f"'{sector_start}' is not a valid {network_family(network)} sector start address!")

    offset: int = int(start_addr) - int(network.network_address)

    if offset < 0 or offset >= total_address_count(network) or offset % sector_size != 0:
        abort(400, f"'{sector_start}' is not an aligned sector boundary of this subnet!")

    return int(network.network_address) + offset, int(network.network_address) + offset + sector_size - 1


def _sector_assigned_only_page(
    assigned: dict[str, dict[str, Any]],
    sector_lo: int,
    sector_hi: int,
    page: int,
    page_size: int,
) -> tuple[list[str], int, int, int]:
    """
    Paginates the assigned IPs that fall inside a sector window (the IPv6 path - no free enumeration)

    Args:
        assigned (dict[str, dict[str, Any]]): {ip_str: row_info} as produced by load_assigned_rows_map
        sector_lo (int): Inclusive integer lower bound of the sector
        sector_hi (int): Inclusive integer upper bound of the sector
        page (int): Requested 1-based page number; clamped server-side
        page_size (int): Requested page size; clamped server-side

    Returns:
        tuple[list[str], int, int, int]: (page_ips, total_count, safe_page, safe_size)
    """
    candidates: list[str] = [
        ip for ip in sorted_assigned_ips(assigned, valid=True)
        if sector_lo <= int(parse_ip(ip)) <= sector_hi
    ]
    safe_page, safe_size = clamp_page(page, page_size, len(candidates))
    start: int = (safe_page - 1) * safe_size

    return candidates[start:start + safe_size], len(candidates), safe_page, safe_size


def _sector_assignable_page(
    network: Network,
    sector_lo: int,
    sector_hi: int,
    page: int,
    page_size: int,
) -> tuple[list[str], int, int, int]:
    """
    Paginates the assignable addresses (free + assigned) inside a sector window (the IPv4 path)

    The sector window is intersected with the subnet's contiguous assignable range so the
    network / broadcast addresses are excluded at the first / last sector exactly as the full IP
    table excludes them. The page is sliced by integer offset (O(page_size)), so even a sector of
    a large subnet paginates without materializing the whole window

    Args:
        network (Network): The parsed subnet network (IPv4)
        sector_lo (int): Inclusive integer lower bound of the sector
        sector_hi (int): Inclusive integer upper bound of the sector
        page (int): Requested 1-based page number; clamped server-side
        page_size (int): Requested page size; clamped server-side

    Returns:
        tuple[list[str], int, int, int]: (page_ips, total_count, safe_page, safe_size)
    """
    assignable_lo: int = first_assignable_int(network)
    assignable_hi: int = assignable_lo + assignable_address_count(network) - 1

    lo: int = max(sector_lo, assignable_lo)
    hi: int = min(sector_hi, assignable_hi)
    total_count: int = max(0, hi - lo + 1)

    safe_page, safe_size = clamp_page(page, page_size, total_count)
    start: int = (safe_page - 1) * safe_size
    end: int = min(start + safe_size, total_count)
    page_ips: list[str] = [format_ip(lo + offset, False) for offset in range(start, end)]

    return page_ips, total_count, safe_page, safe_size


def build_subnet_sector_ips(
    objects_manager: ObjectsManager,
    types_manager: TypesManager,
    public_id: int,
    sector_start: Any,
    page: int = 1,
    page_size: int = IpamPagination.DEFAULT_PAGE_SIZE,
) -> dict[str, Any]:
    """
    Builds the paginated IP list for a single IP-Verteilung sector of a subnet

    Backs the 'click a heatmap sector' drill-down: instead of the whole subnet, only the IPs of
    the clicked sector are returned. The sector window is derived from the same grid dimensions
    the overview's ip_distribution used, so it matches the clicked cell exactly. For IPv4 the page
    lists the sector's assignable addresses (free + assigned, network / broadcast excluded); for
    IPv6 it lists only the assigned addresses inside the sector (never enumerating the space). Rows
    reuse the IP-table row shape (assigned / free) so the frontend can render the same row template

    Aborts HTTP 404 when the subnet does not exist, HTTP 400 when the public_id is not a SUBNET /
    no SUBNET CmdbType is defined, when the subnet has no grid (CIDR missing / unparsable, or the
    subnet is too small to expose the full grid), or when ``sector_start`` is not an aligned sector
    boundary of the subnet

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        public_id (int): public_id of the SUBNET CmdbObject
        sector_start (Any): The clicked sector's start address (its ip_start from ip_distribution)
        page (int): 1-based page number for the sector's IP list (clamped server-side)
        page_size (int): Page size (clamped to [IpamPagination.MIN_PAGE_SIZE, MAX_PAGE_SIZE])

    Returns:
        dict[str, Any]: {'sector': {ip_start, ip_end}, 'ips': {page, page_size, total, rows}}
    """
    subnet_obj: dict[str, Any] = load_subnet_object(objects_manager, types_manager, public_id)
    network: Network | None = parse_subnet_network(subnet_obj)

    if network is None:
        abort(400, f"Subnet with ID {public_id} has no IP-distribution grid (network range missing or unparsable)!")

    sector_size: int = _require_sector_grid(public_id, network)
    sector_lo, sector_hi = _resolve_sector_bounds(network, sector_start, sector_size)

    assigned: dict[str, dict[str, Any]] = load_assigned_rows_map(objects_manager, public_id, network)
    type_meta: dict[int, dict[str, Any]] = resolve_type_meta(types_manager, [
        info[AssignedField.TYPE_ID]
        for info in assigned.values()
        if isinstance(info.get(AssignedField.TYPE_ID), int)
    ])

    is_ipv6: bool = network_family(network) == IpAddressFamily.IPV6
    page_ips, total_count, safe_page, safe_size = (
        _sector_assigned_only_page(assigned, sector_lo, sector_hi, page, page_size)
        if is_ipv6
        else _sector_assignable_page(network, sector_lo, sector_hi, page, page_size)
    )

    summary_lines: dict[str, str] = resolve_summary_lines_for_ips(page_ips, assigned, objects_manager)

    return {
        IpamOverviewKey.SECTOR: {
            IpamOverviewKey.IP_START: format_ip(sector_lo, is_ipv6),
            IpamOverviewKey.IP_END: format_ip(sector_hi, is_ipv6),
        },
        IpamOverviewKey.IPS: {
            IpamOverviewKey.PAGE: safe_page,
            IpamOverviewKey.PAGE_SIZE: safe_size,
            IpamOverviewKey.TOTAL: total_count,
            IpamOverviewKey.ROWS: [
                compose_ip_row(ip, assigned, type_meta, summary_lines) for ip in page_ips
            ],
        },
    }
