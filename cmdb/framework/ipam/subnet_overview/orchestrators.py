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
Top-level payload orchestrators for the subnet IP-Übersicht

``build_subnet_overview`` assembles the full view payload (KPI block, paginated IP table,
distributions, VLANs, invalid count); ``build_invalid_ips_overview`` is the
invalid-rows-only variant backing the conflict view after a CIDR change
"""
from typing import Any

from cmdb.manager import ObjectsManager, TypesManager
from cmdb.models.special_type_model.ipam_constants import (
    SubnetField,
    IpAddressFamily,
    IpamOverviewKey,
    IpamPagination,
)
from cmdb.models.object_model import CmdbObjectKey, extract_field_value
from cmdb.framework.ipam.cidr import (
    Network,
    network_family,
    total_address_count,
    assignable_address_count,
)
from cmdb.framework.ipam.pagination import clamp_page
from cmdb.framework.ipam.references import load_vlans_by_subnets
from cmdb.framework.ipam.search import active_search
from cmdb.framework.ipam.subnet_overview.assigned_rows import (
    AssignedField,
    load_assigned_rows_map,
    load_subnet_object,
    parse_subnet_network,
    resolve_type_meta,
    sorted_invalid_ips,
)
from cmdb.framework.ipam.subnet_overview.candidates import (
    parse_filter_args,
    parse_sort_args,
    resolve_candidate_ips,
)
from cmdb.framework.ipam.subnet_overview.distribution import (
    build_ip_distribution,
    build_type_distribution,
)
from cmdb.framework.ipam.subnet_overview.rows import build_ips_block
# -------------------------------------------------------------------------------------------------------------------- #


def _build_broken_state_payload(
    subnet_obj: dict[str, Any],
    page: int,
    page_size: int,
) -> dict[str, Any]:
    """
    Builds the degenerate payload returned when the subnet's CIDR is missing or unparsable

    Mirrors the happy-path envelope so the FE can render the response unconditionally: every
    counter is zeroed (including the top-level ``invalid_count``), the 'ips' block ships an
    empty page (page / page_size clamped via ``clamp_page(..., 0)``), both distributions are
    empty, and the 'vlans' list is empty. The 'cidr' field echoes the raw value when it is a
    string (so the user can see the broken input they need to fix) and is None otherwise

    Args:
        subnet_obj (dict[str, Any]): The SUBNET CmdbObject document
        page (int): 1-based page number requested by the caller
        page_size (int): Page size requested by the caller

    Returns:
        dict[str, Any]: Degenerate payload matching the happy-path key set
    """
    raw_cidr: Any = extract_field_value(subnet_obj, SubnetField.NETWORK_RANGE)
    raw_type: Any = extract_field_value(subnet_obj, SubnetField.TYPE)
    family: str = IpAddressFamily.IPV6 if raw_type == IpAddressFamily.IPV6 else IpAddressFamily.IPV4
    safe_page, safe_size = clamp_page(page, page_size, 0)

    return {
        IpamOverviewKey.SUBNET: {
            CmdbObjectKey.PUBLIC_ID: subnet_obj.get(CmdbObjectKey.PUBLIC_ID),
            IpamOverviewKey.SUBNET_TYPE: family,
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
        IpamOverviewKey.INVALID_COUNT: 0,
    }


def _subnet_summary_block(
    subnet_obj: dict[str, Any],
    network: Network,
    assignable: int,
    used_count: int,
    valid_used: int,
) -> dict[str, Any]:
    """
    Shapes the shared 'subnet' KPI block for both subnet IP-Übersicht orchestrators

    'subnet_type' is the address family (ipv4 / ipv6) derived from the parsed network; 'free_ips'
    is computed against the assignable count so it matches the paginated IP table. The full
    overview and the invalid-only overview emit the identical block

    Args:
        subnet_obj (dict[str, Any]): The SUBNET CmdbObject document
        network (Network): The parsed subnet network
        assignable (int): Assignable address count of the subnet
        used_count (int): Number of assigned dg-ipam-interface rows (valid + invalid)
        valid_used (int): Number of assigned rows whose IP is inside the subnet

    Returns:
        dict[str, Any]: {public_id, subnet_type, cidr, total_ips, assignable_ips, used_ips, free_ips}
    """
    return {
        CmdbObjectKey.PUBLIC_ID: subnet_obj.get(CmdbObjectKey.PUBLIC_ID),
        IpamOverviewKey.SUBNET_TYPE: network_family(network),
        IpamOverviewKey.CIDR: str(network),
        IpamOverviewKey.TOTAL_IPS: total_address_count(network),
        IpamOverviewKey.ASSIGNABLE_IPS: assignable,
        IpamOverviewKey.USED_IPS: used_count,
        IpamOverviewKey.FREE_IPS: max(0, assignable - valid_used),
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
    status: str = '',
    type_filter: str = '',
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

    Summary lines for the page are resolved one-per-IP through ``compose_ip_row``. When
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
    under search, sort, and filter - they always cover the whole subnet

    When ``status`` or ``type_filter`` is active the candidate IPs are narrowed to rows that
    match every active filter (AND-combined). ``status`` accepts IpamRowStatus values
    ('assigned' / 'free'); ``type_filter`` is a comma-separated list of CmdbType public_ids
    where each element is parsed to int (whitespace stripped, empty entries skipped,
    duplicates collapsed). A row passes the type filter when its owning type is in the set
    (logical OR within the type filter). ``status=free`` with any non-empty ``type_filter``
    yields an empty page because free rows carry no owner type. Unknown ``status`` or a
    non-integer element in ``type_filter`` aborts 400

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
        status (str): Optional row-status filter; one of IpamRowStatus values
            ('assigned' / 'free'). Empty / whitespace skips the status filter. Aborts 400
            on unknown values
        type_filter (str): Optional comma-separated list of CmdbType public_ids (e.g.
            "50,51,52"). Each element parses to int; whitespace is stripped, empty elements
            are skipped, duplicates are collapsed. A row passes when its owning type is in
            the set (OR within the type filter); intrinsically excludes free rows when any
            element is present. Empty / whitespace skips the type filter. Aborts 400 on a
            non-integer element. Combines with ``status`` via AND

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
            included). Each sector inside ip_distribution carries ip_start, ip_end,
            used_count, percentage, type_stats; 'type_stats' is the per-type breakdown of the
            sector's assigned IPs, shaped as a list of {public_id, label, ci_explorer_color,
            count, percentage} entries with percentage computed against the sector's
            used_count, and an Unknown bucket (public_id=None, ci_explorer_color=None)
            appended last whenever the sector holds rows whose owning type cannot be
            resolved. The grid is emitted only at its full 4 x 16 size (/26 and shorter
            prefixes); for /27 and narrower, or when the CIDR is unparsable, ip_distribution
            is an empty dict. 'ips.total' equals 'assignable_ips' under no search and no
            sort (lazy path), or the candidate-list length otherwise. 'vlans' lists every
            VLAN whose 'dg-subnet-ref' points at this subnet, sorted by ascending public_id;
            empty when no VLAN references the subnet
    """
    subnet_obj: dict[str, Any] = load_subnet_object(objects_manager, types_manager, public_id)
    sort_col, sort_dir = parse_sort_args(sort, order)
    status_filter, type_filter_ids = parse_filter_args(status, type_filter)
    network: Network | None = parse_subnet_network(subnet_obj)

    if network is None:
        return _build_broken_state_payload(subnet_obj, page, page_size)

    is_ipv6: bool = network_family(network) == IpAddressFamily.IPV6
    assignable: int = assignable_address_count(network)
    assigned: dict[str, dict[str, Any]] = load_assigned_rows_map(objects_manager, public_id, network)
    valid_used: int = sum(1 for info in assigned.values() if info[AssignedField.IS_VALID])
    invalid_count: int = len(assigned) - valid_used

    type_meta: dict[int, dict[str, Any]] = resolve_type_meta(types_manager, [
        info[AssignedField.TYPE_ID]
        for info in assigned.values()
        if isinstance(info.get(AssignedField.TYPE_ID), int)
    ])

    return {
        IpamOverviewKey.SUBNET: _subnet_summary_block(subnet_obj, network, assignable, len(assigned), valid_used),
        IpamOverviewKey.IPS: build_ips_block(
            network, assignable, page, page_size,
            resolve_candidate_ips(
                network, search, sort_col, sort_dir,
                status_filter, type_filter_ids,
                assigned, type_meta, objects_manager, is_ipv6,
            ),
            assigned, type_meta, objects_manager,
        ),
        IpamOverviewKey.TYPE_DISTRIBUTION: build_type_distribution(assigned, type_meta, assignable, is_ipv6),
        IpamOverviewKey.IP_DISTRIBUTION: build_ip_distribution(network, assigned, type_meta),
        IpamOverviewKey.VLANS: load_vlans_by_subnets(
            objects_manager, types_manager, [public_id],
        ).get(public_id, []),
        IpamOverviewKey.INVALID_COUNT: invalid_count,
    }


def build_invalid_ips_overview(
    objects_manager: ObjectsManager,
    types_manager: TypesManager,
    public_id: int,
    page: int = 1,
    page_size: int = IpamPagination.DEFAULT_PAGE_SIZE,
    search: str = '',
) -> dict[str, Any]:
    """
    Builds the invalid-IPs-only IP-Übersicht payload for the SUBNET identified by public_id

    Same envelope as ``build_subnet_overview`` ('subnet' summary block, 'ips' page block,
    'type_distribution', 'ip_distribution', 'vlans', top-level 'invalid_count'), but
    'ips.rows' is a flat list of every dg-ipam-interface row referencing this subnet whose IP
    falls outside the subnet's current CIDR. Each row carries the same shape as the main
    overview rows so the FE can reuse its row template; ``is_valid`` on these rows is always
    False. 'ips.total' equals the invalid count (after the optional search filter)

    The 'subnet' KPI block, 'type_distribution', 'ip_distribution' and 'vlans' stay invariant
    under this view - they always cover the whole subnet so the FE can render the same KPI
    strip and charts whether the user is looking at the full table or the invalid-only view.
    The top-level ``invalid_count`` is the total invalid count for the subnet and is unchanged
    by the ``search`` filter (which only narrows ``ips.rows`` / ``ips.total``)

    Aborts mirror ``build_subnet_overview``: 404 when the subnet does not exist, 400 when the
    public_id refers to a non-subnet object or no SUBNET CmdbType is defined. When the
    subnet's 'dg-network-range' is missing or unparsable, returns the degenerate broken-state
    payload (zeroed counters, empty rows, ``invalid_count`` = 0)

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        public_id (int): public_id of the subnet to summarise
        page (int): 1-based page number (clamped into the valid range)
        page_size (int): Page size (clamped to [IpamPagination.MIN_PAGE_SIZE,
            IpamPagination.MAX_PAGE_SIZE])
        search (str): Optional case-insensitive substring filter against each invalid row's
            canonical IP string; empty / whitespace and queries shorter than
            IpamSearch.MIN_QUERY_LENGTH after stripping are ignored

    Returns:
        dict[str, Any]: Same envelope as ``build_subnet_overview`` with 'ips.rows' filtered
            to invalid rows only (each carrying is_valid=False); 'ips.total' is the count
            after the search filter; 'invalid_count' is the whole-subnet invalid count
    """
    subnet_obj: dict[str, Any] = load_subnet_object(objects_manager, types_manager, public_id)
    network: Network | None = parse_subnet_network(subnet_obj)

    if network is None:
        return _build_broken_state_payload(subnet_obj, page, page_size)

    assignable: int = assignable_address_count(network)
    assigned: dict[str, dict[str, Any]] = load_assigned_rows_map(objects_manager, public_id, network)
    valid_used: int = sum(1 for info in assigned.values() if info[AssignedField.IS_VALID])
    invalid_count: int = len(assigned) - valid_used

    type_meta: dict[int, dict[str, Any]] = resolve_type_meta(types_manager, [
        info[AssignedField.TYPE_ID]
        for info in assigned.values()
        if isinstance(info.get(AssignedField.TYPE_ID), int)
    ])

    invalid_candidates: list[str] = sorted_invalid_ips(assigned)
    needle: str | None = active_search(search)

    if needle is not None:
        invalid_candidates = [ip for ip in invalid_candidates if needle.lower() in ip.lower()]

    return {
        IpamOverviewKey.SUBNET: _subnet_summary_block(subnet_obj, network, assignable, len(assigned), valid_used),
        IpamOverviewKey.IPS: build_ips_block(
            network, assignable, page, page_size,
            invalid_candidates,
            assigned, type_meta, objects_manager,
        ),
        IpamOverviewKey.TYPE_DISTRIBUTION: build_type_distribution(
            assigned, type_meta, assignable, network_family(network) == IpAddressFamily.IPV6,
        ),
        IpamOverviewKey.IP_DISTRIBUTION: build_ip_distribution(network, assigned, type_meta),
        IpamOverviewKey.VLANS: load_vlans_by_subnets(
            objects_manager, types_manager, [public_id],
        ).get(public_id, []),
        IpamOverviewKey.INVALID_COUNT: invalid_count,
    }
