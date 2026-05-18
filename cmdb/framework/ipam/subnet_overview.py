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
)
from cmdb.framework.ipam.cidr import (
    parse_cidr,
    parse_ipv4,
    ip_in_network,
    total_address_count,
    assignable_address_count,
    first_assignable_int,
)
from cmdb.framework.ipam.pagination import DEFAULT_PAGE_SIZE, clamp_page
from cmdb.framework.ipam.references import resolve_special_type_id
from cmdb.framework.ipam.subnet_validator import extract_field_value
# -------------------------------------------------------------------------------------------------------------------- #


FREE_BUCKET_LABEL: str = 'Free'
UNKNOWN_BUCKET_LABEL: str = 'Unknown'


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
        list[str]: IP strings for the requested page; empty when the subnet has no assignable
            addresses or the page is past the end
    """
    first: int | None = first_assignable_int(network)

    if first is None:
        return []

    total: int = assignable_address_count(network)
    start_offset: int = (page - 1) * page_size

    if start_offset >= total:
        return []

    end_offset: int = min(start_offset + page_size, total)

    return [str(IPv4Address(first + i)) for i in range(start_offset, end_offset)]


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
        'ip': ip_str,
        'status': 'assigned',
        'type_info': type_info,
        'assigned_to': assigned_to,
        'mac_address': mac_address,
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
        'ip': ip_str,
        'status': 'free',
        'type_info': None,
        'assigned_to': None,
        'mac_address': None,
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

    for entry in row.get('data', []) or []:
        name: Any = entry.get('name')

        if name == InterfaceField.SUBNET:
            subnet_ref = entry.get('value')
        elif name == InterfaceField.IP:
            ip_value = entry.get('value')
        elif name == InterfaceField.MAC:
            mac_value = entry.get('value')

    return subnet_ref, ip_value, mac_value


def _empty_ip_distribution() -> dict[str, Any]:
    """
    Returns the zero-shaped 'ip_distribution' payload used when the subnet's CIDR is missing
    or unparsable

    The shape mirrors a populated distribution so the frontend can render a placeholder
    without branching on a null sentinel

    Returns:
        dict[str, Any]: ranges_count / sectors_per_range / sector_size all 0 and an empty
            'ranges' list
    """
    return {
        'ranges_count': 0,
        'sectors_per_range': 0,
        'sector_size': 0,
        'ranges': [],
    }


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
    sector_index: int,
    first_ip_int: int,
    sector_size: int,
    used_count: int,
) -> dict[str, Any]:
    """
    Shapes one sector entry of the 'ip_distribution' grid

    The percentage is the per-cell saturation ('used_count / sector_size * 100'), rounded to
    two decimals; this matches the frontend's heatmap colouring convention

    Args:
        sector_index (int): 0-based index of the sector within its range
        first_ip_int (int): Integer of the first address the sector covers
        sector_size (int): Number of addresses the sector covers
        used_count (int): Number of assigned IPs inside the sector

    Returns:
        dict[str, Any]: Sector entry with index, ip_start, ip_end, size, used_count, percentage
    """
    return {
        'index': sector_index,
        'ip_start': str(IPv4Address(first_ip_int)),
        'ip_end': str(IPv4Address(first_ip_int + sector_size - 1)),
        'size': sector_size,
        'used_count': used_count,
        'percentage': round((used_count / sector_size) * 100, 2),
    }


def _build_ip_distribution(
    network: IPv4Network | None,
    assigned: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """
    Builds the 'IP-Verteilung' grid payload for one subnet

    Splits the full address space (network + broadcast included) into at most
    IpamDistributionLimits.MAX_RANGES rows of at most MAX_SECTORS_PER_RANGE cells each, where
    each cell aggregates the count of assigned IPs in its address window. Cells are sized by
    'total // (ranges * sectors)' so every cell covers an equal slice of the subnet. For
    subnets smaller than the cap the layout shrinks so no cell drops below 1 IP. The returned
    structure is suitable for direct rendering by the frontend, which colours each cell by its
    'percentage' field

    Args:
        network (IPv4Network | None): The parsed subnet network, or None when the subnet's
            CIDR is missing or unparsable
        assigned (dict[str, dict[str, Any]]): {ip_str: row_info} as produced by
            _load_assigned_rows_map; only used to bucket-count, the row metadata is ignored
            here

    Returns:
        dict[str, Any]: ranges_count, sectors_per_range, sector_size, and a 'ranges' list with
            one entry per range carrying index, ip_start, ip_end, and a nested 'sectors' list;
            the zero-shaped payload from _empty_ip_distribution when network is None
    """
    if network is None:
        return _empty_ip_distribution()

    total: int = total_address_count(network)
    ranges_count, sectors_per_range, sector_size = _compute_grid_dimensions(total)
    total_cells: int = ranges_count * sectors_per_range
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
                sector_index,
                sector_first_int,
                sector_size,
                counts[global_cell],
            ))

        ranges.append({
            'index': range_index,
            'ip_start': str(IPv4Address(range_first_int)),
            'ip_end': str(IPv4Address(range_first_int + range_span - 1)),
            'sectors': sectors,
        })

    return {
        'ranges_count': ranges_count,
        'sectors_per_range': sectors_per_range,
        'sector_size': sector_size,
        'ranges': ranges,
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
        type_id: Any = info.get('type_id')

        if isinstance(type_id, int) and type_id in type_meta:
            by_type[type_id] = by_type.get(type_id, 0) + 1
        else:
            unknown_count += 1

    free_count: int = max(0, total - len(assigned))

    distribution: list[dict[str, Any]] = [
        {
            'public_id': type_id,
            'label': type_meta[type_id]['label'],
            'ci_explorer_color': type_meta[type_id].get('ci_explorer_color'),
            'count': count,
            'percentage': round((count / total) * 100, 2),
        }
        for type_id, count in by_type.items()
    ]

    if unknown_count > 0:
        distribution.append({
            'public_id': None,
            'label': UNKNOWN_BUCKET_LABEL,
            'ci_explorer_color': None,
            'count': unknown_count,
            'percentage': round((unknown_count / total) * 100, 2),
        })

    distribution.append({
        'public_id': None,
        'label': FREE_BUCKET_LABEL,
        'ci_explorer_color': None,
        'count': free_count,
        'percentage': round((free_count / total) * 100, 2),
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
        {'public_id': public_id},
        as_dict=True,
    )

    if not candidates:
        abort(404, f"Subnet with public_id {public_id} was not found!")

    candidate: dict[str, Any] = candidates[0]

    if candidate.get('type_id') != subnet_type_id:
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
        'multi_data_sections': {
            '$elemMatch': {
                'section_id': IpamSection.INTERFACE,
                'values': {
                    '$elemMatch': {
                        'data': {
                            '$elemMatch': {
                                'name': InterfaceField.SUBNET,
                                'value': subnet_object_id,
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
        candidate_id: Any = candidate.get('public_id')
        candidate_type_id: Any = candidate.get('type_id')

        for section in candidate.get('multi_data_sections', []) or []:
            if section.get('section_id') != IpamSection.INTERFACE:
                continue

            for row in section.get('values', []) or []:
                row_subnet, row_ip, row_mac = _extract_row_fields(row)

                if row_subnet != subnet_object_id or not isinstance(row_ip, str):
                    continue

                parsed_ip: IPv4Address | None = parse_ipv4(row_ip)

                if parsed_ip is None or not ip_in_network(parsed_ip, network):
                    continue

                out[str(parsed_ip)] = {
                    'object_id': candidate_id,
                    'type_id': candidate_type_id,
                    'mac': row_mac if isinstance(row_mac, str) and row_mac else None,
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
        tid: {'label': t.label, 'ci_explorer_color': t.ci_explorer_color}
        for tid, t in lookup.items()
    }


# -------------------------------------------------------------------------------------------------------------------- #
#                                                   ORCHESTRATOR                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
def build_subnet_overview(
    objects_manager: ObjectsManager,
    types_manager: TypesManager,
    public_id: int,
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> dict[str, Any]:
    """
    Builds the full IP-Übersicht payload for the SUBNET CmdbObject identified by public_id

    Aborts HTTP 404 when the subnet does not exist and HTTP 400 when the public_id refers to a
    non-subnet CmdbObject or no SUBNET CmdbType is defined. When the subnet's
    'dg-network-range' is missing or unparsable, returns the KPI block with zeroed counters and
    an empty page (broken state is observable but does not 500)

    The KPI block uses two related denominators: 'total_ips' is the full address count
    (network + broadcast included, matching the IP-Verteilung grid) and 'assignable_ips' is
    the subset the interface validator would accept (network and broadcast excluded for /≤30,
    full count for /31, /32). 'free_ips' is computed against 'assignable_ips' so it matches
    what the user sees in the paginated IP table

    Summary lines are resolved only for the assigned rows on the requested page, never for the
    whole subnet, so the cost is bounded by page_size

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        public_id (int): public_id of the subnet to summarise
        page (int): 1-based page number (clamped into the valid range)
        page_size (int): Page size (clamped to [1, MAX_PAGE_SIZE])

    Returns:
        dict[str, Any]: {'subnet': {public_id, cidr, ip_range, total_ips, assignable_ips,
            used_ips, free_ips},
            'ips': {page, page_size, total, rows: [...]},
            'type_distribution': [{public_id, label, ci_explorer_color, count, percentage},
            ...],
            'ip_distribution': {ranges_count, sectors_per_range, sector_size, ranges: [...]}}
            where 'type_distribution' covers the whole subnet (not just the current page) and
            includes 'Unknown' (when present) and 'Free' buckets after the type buckets, and
            'ip_distribution' is the IP-Verteilung heatmap grid covering the full address
            space (network + broadcast included). 'ips.total' equals 'assignable_ips' so the
            table paginates exactly the rows the validator would accept
    """
    subnet_obj: dict[str, Any] = _load_subnet_object(objects_manager, types_manager, public_id)

    raw_cidr: Any = extract_field_value(subnet_obj, SubnetField.NETWORK_RANGE)
    network: IPv4Network | None = parse_cidr(raw_cidr) if isinstance(raw_cidr, str) else None

    if network is None:
        safe_page, safe_size = clamp_page(page, page_size, 0)
        return {
            'subnet': {
                'public_id': subnet_obj.get('public_id'),
                'cidr': raw_cidr if isinstance(raw_cidr, str) else None,
                'ip_range': None,
                'total_ips': 0,
                'assignable_ips': 0,
                'used_ips': 0,
                'free_ips': 0,
            },
            'ips': {
                'page': safe_page,
                'page_size': safe_size,
                'total': 0,
                'rows': [],
            },
            'type_distribution': [],
            'ip_distribution': _empty_ip_distribution(),
        }

    total: int = total_address_count(network)
    assignable: int = assignable_address_count(network)
    assigned: dict[str, dict[str, Any]] = _load_assigned_rows_map(objects_manager, public_id, network)
    used_ips: int = len(assigned)
    free_ips: int = max(0, assignable - used_ips)

    assigned_type_ids: list[int] = [
        info['type_id']
        for info in assigned.values()
        if isinstance(info.get('type_id'), int)
    ]
    type_meta: dict[int, dict[str, Any]] = _resolve_type_meta(types_manager, assigned_type_ids)

    type_distribution: list[dict[str, Any]] = _build_type_distribution(assigned, type_meta, assignable)
    ip_distribution: dict[str, Any] = _build_ip_distribution(network, assigned)

    safe_page, safe_size = clamp_page(page, page_size, assignable)
    page_ips: list[str] = _page_slice_ips(network, safe_page, safe_size)

    rows: list[dict[str, Any]] = []

    for ip in page_ips:
        info: dict[str, Any] | None = assigned.get(ip)

        if info is None:
            rows.append(_compose_free_row(ip))
            continue

        summary_line: str = objects_manager.get_summary_line(info['object_id'], with_type=True)

        type_id: Any = info['type_id']
        type_entry: dict[str, Any] | None = type_meta.get(type_id) if type_id is not None else None
        type_info: dict[str, Any] | None = (
            {
                'public_id': type_id,
                'label': type_entry.get('label') if type_entry else None,
                'ci_explorer_color': type_entry.get('ci_explorer_color') if type_entry else None,
            }
            if type_id is not None
            else None
        )

        rows.append(_compose_assigned_row(
            ip,
            type_info,
            {'public_id': info['object_id'], 'summary_line': summary_line},
            info['mac'],
        ))

    return {
        'subnet': {
            'public_id': subnet_obj.get('public_id'),
            'cidr': str(network),
            'ip_range': {
                'first': str(network.network_address),
                'last': str(network.broadcast_address),
            },
            'total_ips': total,
            'assignable_ips': assignable,
            'used_ips': used_ips,
            'free_ips': free_ips,
        },
        'ips': {
            'page': safe_page,
            'page_size': safe_size,
            'total': assignable,
            'rows': rows,
        },
        'type_distribution': type_distribution,
        'ip_distribution': ip_distribution,
    }
