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
from ipaddress import IPv4Network
from typing import Any

from flask import abort

from cmdb.manager import ObjectsManager, TypesManager
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.special_type_model.ipam_constants import (
    SupernetField,
    SubnetField,
    InterfaceField,
    IpamSection,
)
from cmdb.framework.ipam.cidr import parse_cidr, is_strict_subnet, total_address_count
from cmdb.framework.ipam.pagination import DEFAULT_PAGE_SIZE, clamp_page
from cmdb.framework.ipam.references import resolve_special_type_id
from cmdb.framework.ipam.subnet_validator import extract_field_value
# -------------------------------------------------------------------------------------------------------------------- #


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  PURE HELPERS                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
def _ip_range(network: IPv4Network) -> dict[str, str]:
    """
    Returns the lowest and highest address of an IPv4 network as strings

    'Lowest' is the network address and 'highest' is the broadcast address; neither is filtered
    out so the range reflects the literal bounds of the CIDR

    Args:
        network (IPv4Network): The parsed network

    Returns:
        dict[str, str]: {'first': <network address>, 'last': <broadcast address>}
    """
    return {
        'first': str(network.network_address),
        'last': str(network.broadcast_address),
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
        dict[str, Any]: One row with public_id, cidr, used_ips, free_ips, usage_percent
    """
    raw_cidr: Any = extract_field_value(subnet_obj, SubnetField.NETWORK_RANGE)
    network: IPv4Network | None = parse_cidr(raw_cidr) if isinstance(raw_cidr, str) else None

    if network is None:
        return {
            'public_id': subnet_obj.get('public_id'),
            'cidr': raw_cidr if isinstance(raw_cidr, str) else None,
            'used_ips': 0,
            'free_ips': 0,
            'usage_percent': 0.0,
        }

    total: int = total_address_count(network)
    free: int = max(0, total - used_count)

    return {
        'public_id': subnet_obj.get('public_id'),
        'cidr': str(network),
        'used_ips': used_count,
        'free_ips': free,
        'usage_percent': _percent(used_count, total),
    }


def compute_supernet_summary(
    supernet_network: IPv4Network | None,
    total_used: int,
    subnet_count: int,
) -> dict[str, Any]:
    """
    Shapes the KPI strip values for the supernet as a whole

    All percentages are computed against the supernet's total address count (network and
    broadcast included), keeping the supernet KPI aligned with the per-subnet rows produced by
    'compute_subnet_row' and with the subnet IP-Verteilung grid. 'utilization_percent' is
    intentionally equal to 'used_percent' under this scheme. A degenerate summary with zeroed
    counts is returned when the supernet's CIDR is missing or unparsable

    Args:
        supernet_network (IPv4Network | None): Parsed CIDR of the supernet, None if missing
            or unparsable
        total_used (int): Sum of used IPs across all subnets that reference the supernet
        subnet_count (int): Number of subnets that reference the supernet

    Returns:
        dict[str, Any]: cidr, ip_range, total_ips, used_ips, free_ips, used_percent,
            free_percent, utilization_percent, subnet_count
    """
    if supernet_network is None:
        return {
            'cidr': None,
            'ip_range': None,
            'total_ips': 0,
            'used_ips': total_used,
            'free_ips': 0,
            'used_percent': 0.0,
            'free_percent': 0.0,
            'utilization_percent': 0.0,
            'subnet_count': subnet_count,
        }

    total: int = total_address_count(supernet_network)
    free: int = max(0, total - total_used)
    used_percent: float = _percent(total_used, total)
    free_percent: float = _percent(free, total)

    return {
        'cidr': str(supernet_network),
        'ip_range': _ip_range(supernet_network),
        'total_ips': total,
        'used_ips': total_used,
        'free_ips': free,
        'used_percent': used_percent,
        'free_percent': free_percent,
        'utilization_percent': used_percent,
        'subnet_count': subnet_count,
    }


def _network_sort_key(network: IPv4Network) -> tuple[int, int]:
    """
    Returns a stable sort key for an IPv4Network: (network address as int, prefix length)

    Ordering by network address gives ascending IP order; prefix length as the tiebreaker
    ensures a broader (shorter-prefix) network sorts before any more-specific network that
    starts at the same address, which is the order 'sort_and_link_subnets' relies on for
    its single-pass parent linking

    Args:
        network (IPv4Network): The parsed network

    Returns:
        tuple[int, int]: (int(network_address), prefixlen)
    """
    return (int(network.network_address), network.prefixlen)


def sort_and_link_subnets(subnet_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Sorts subnet rows by ascending IP and annotates each with the parent subnet's public_id

    Rows with a parsable 'cidr' are sorted by ascending network address (prefix length
    ascending as a tiebreaker) and each is given a 'parent_id' equal to the public_id of
    the most-specific other subnet in the same list that strictly contains it, or None
    when no enclosing subnet is present (top-level under the supernet). Rows whose 'cidr'
    is missing or unparsable are appended after the sorted rows in their original relative
    order with parent_id set to None so the frontend can still display them

    The linking pass uses a stack of (network, public_id) pairs: because parents always
    precede their children in the sort order, the top of the stack after popping non-
    enclosing entries is always the closest enclosing subnet

    Args:
        subnet_rows (list[dict[str, Any]]): Rows produced by 'compute_subnet_row'

    Returns:
        list[dict[str, Any]]: A new list where every row has an added 'parent_id' key;
            rows with parsable CIDRs come first in IP order, unparsable rows trail
    """
    sortable: list[tuple[IPv4Network, dict[str, Any]]] = []
    unsortable: list[dict[str, Any]] = []

    for row in subnet_rows:
        cidr: Any = row.get('cidr')
        network: IPv4Network | None = parse_cidr(cidr) if isinstance(cidr, str) else None

        if network is None:
            row['parent_id'] = None
            unsortable.append(row)
        else:
            sortable.append((network, row))

    sortable.sort(key=lambda item: _network_sort_key(item[0]))

    stack: list[tuple[IPv4Network, Any]] = []

    for network, row in sortable:
        while stack and not is_strict_subnet(stack[-1][0], network):
            stack.pop()

        row['parent_id'] = stack[-1][1] if stack else None
        stack.append((network, row.get('public_id')))

    return [row for _, row in sortable] + unsortable


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
        parent_id: Any = row.get('parent_id')
        index.setdefault(parent_id, []).append(row)

    return index


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
        public_id: Any = row.get('public_id')
        row['has_children'] = bool(public_id is not None and children_index.get(public_id))


# -------------------------------------------------------------------------------------------------------------------- #
#                                                   DATA LOADING                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
def _load_supernet_object(
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
        {'public_id': public_id},
        as_dict=True,
    )

    if not candidates:
        abort(404, f"Supernet with public_id {public_id} was not found!")

    candidate: dict[str, Any] = candidates[0]

    if candidate.get('type_id') != supernet_type_id:
        abort(400, f"Object with public_id {public_id} is not a SUPERNET!")

    return candidate


def _load_subnets_for_supernet(
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
        'type_id': subnet_type_id,
        'fields': {
            '$elemMatch': {
                'name': SubnetField.PARENT_SUPERNET,
                'value': supernet_public_id,
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
        'multi_data_sections': {
            '$elemMatch': {
                'section_id': IpamSection.INTERFACE,
                'values': {
                    '$elemMatch': {
                        'data': {
                            '$elemMatch': {
                                'name': InterfaceField.SUBNET,
                                'value': {'$in': subnet_ids},
                            },
                        },
                    },
                },
            },
        },
    }

    candidates: list[dict[str, Any]] = objects_manager.find_objects(criteria, as_dict=True)

    for candidate in candidates:
        for section in candidate.get('multi_data_sections', []) or []:
            if section.get('section_id') != IpamSection.INTERFACE:
                continue

            for row in section.get('values', []) or []:
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
    for entry in row.get('data', []) or []:
        if entry.get('name') == InterfaceField.SUBNET:
            return entry.get('value')

    return None


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
    count interface IPs per subnet, shape one row per subnet, then run ``sort_and_link_subnets``
    so each row carries a ``parent_id`` pointing at its most-specific CIDR-enclosing sibling
    (or None when top-level)

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        supernet_public_id (int): public_id of the supernet to load subnets for

    Returns:
        list[dict[str, Any]]: Subnet rows sorted by ascending CIDR with ``parent_id`` set;
            rows with unparsable CIDRs trail the sorted block
    """
    subnet_objs: list[dict[str, Any]] = _load_subnets_for_supernet(
        objects_manager, types_manager, supernet_public_id,
    )
    subnet_ids: list[int] = [s['public_id'] for s in subnet_objs if 'public_id' in s]

    used_per_subnet: dict[int, int] = _count_used_ips_per_subnet(objects_manager, subnet_ids)

    subnet_rows: list[dict[str, Any]] = [
        compute_subnet_row(s, used_per_subnet.get(s.get('public_id'), 0))
        for s in subnet_objs
    ]

    return sort_and_link_subnets(subnet_rows)


def build_supernet_overview(
    objects_manager: ObjectsManager,
    types_manager: TypesManager,
    public_id: int,
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> dict[str, Any]:
    """
    Builds the paginated top-level supernet overview payload

    The KPI strip in 'supernet' covers every subnet under the supernet (regardless of nesting
    depth), so the totals stay stable as the user paginates or expands rows. The 'subnets'
    block lists only top-level subnets - those whose CIDR is not strictly contained by any
    sibling - paginated with the same page / page_size semantics used by the subnet overview.
    Each returned row carries 'has_children: bool' so the frontend can render an expand caret
    without a probe request; the direct children themselves are fetched via
    ``build_supernet_subnet_children``

    Aborts with HTTP 404 when the supernet does not exist, HTTP 400 when the public_id refers
    to a non-supernet CmdbObject or no SUPERNET CmdbType is defined

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        public_id (int): public_id of the supernet to summarise
        page (int): 1-based page number for the top-level subnet list (clamped into the valid
            range)
        page_size (int): Page size for the top-level subnet list (clamped to [1, MAX_PAGE_SIZE])

    Returns:
        dict[str, Any]: {'supernet': {public_id, ...summary over all subnets...},
            'subnets': {page, page_size, total, rows: [...top-level rows with has_children]}}
    """
    supernet_obj: dict[str, Any] = _load_supernet_object(objects_manager, types_manager, public_id)

    raw_supernet_cidr: Any = extract_field_value(supernet_obj, SupernetField.NETWORK_RANGE)
    supernet_network: IPv4Network | None = (
        parse_cidr(raw_supernet_cidr) if isinstance(raw_supernet_cidr, str) else None
    )

    ordered_subnets: list[dict[str, Any]] = _build_linked_subnet_rows(
        objects_manager, types_manager, public_id,
    )

    children_index: dict[Any, list[dict[str, Any]]] = _index_children_by_parent(ordered_subnets)
    _annotate_has_children(ordered_subnets, children_index)

    total_used: int = sum(row['used_ips'] for row in ordered_subnets)

    summary: dict[str, Any] = compute_supernet_summary(
        supernet_network,
        total_used,
        len(ordered_subnets),
    )

    top_level: list[dict[str, Any]] = [row for row in ordered_subnets if row.get('parent_id') is None]
    total_top_level: int = len(top_level)

    safe_page, safe_size = clamp_page(page, page_size, total_top_level)
    start: int = (safe_page - 1) * safe_size
    end: int = start + safe_size
    page_rows: list[dict[str, Any]] = top_level[start:end]

    return {
        'supernet': {
            'public_id': supernet_obj.get('public_id'),
            **summary,
        },
        'subnets': {
            'page': safe_page,
            'page_size': safe_size,
            'total': total_top_level,
            'rows': page_rows,
        },
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
    CIDR order (inherited from ``sort_and_link_subnets``). Each child row also carries
    ``has_children`` so the frontend can render nested expand carets without follow-up probes

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
    _load_supernet_object(objects_manager, types_manager, supernet_public_id)

    ordered_subnets: list[dict[str, Any]] = _build_linked_subnet_rows(
        objects_manager, types_manager, supernet_public_id,
    )

    parent_present: bool = any(row.get('public_id') == subnet_public_id for row in ordered_subnets)

    if not parent_present:
        abort(
            400,
            f"Subnet with public_id {subnet_public_id} is not a SUBNET under supernet"
            f" {supernet_public_id}!",
        )

    children_index: dict[Any, list[dict[str, Any]]] = _index_children_by_parent(ordered_subnets)
    _annotate_has_children(ordered_subnets, children_index)

    children: list[dict[str, Any]] = children_index.get(subnet_public_id, [])

    return {
        'parent': {'public_id': subnet_public_id},
        'rows': children,
    }
