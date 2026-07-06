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
Builds the paginated subnet-options payload backing the dg-ipam-interface subnet picker

The frontend's interface section lets the user pick an address family (ipv4 / ipv6) before
choosing a subnet; the picker then loads only subnets of that family from here instead of the
unfiltered generic objects route. The family of each subnet is resolved CIDR-first with the
'dg-subnet-type' selector as fallback and IPv4 as legacy default (see ``subnet_family``), so
legacy subnets without the selector and subnets whose selector contradicts their CIDR land in
exactly the family every other IPAM view reports for them. Nothing is stored - this is a pure
read model

Rows reuse the lightweight sidebar-tree node shape (public_id, name, cidr, address family
under 'type') and the shared display order: ascending network address with prefix length as
tiebreaker (IPv4 before IPv6 in the unfiltered list), subnets with a missing or unparsable
CIDR trailing their family group ordered by name. The envelope mirrors the assignable-objects
picker: {page, page_size, total, search, type, rows}
"""
from typing import Any

from cmdb.manager import ObjectsManager, TypesManager
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.special_type_model.ipam_constants import IpamOverviewKey, IpamTreeKey
from cmdb.framework.ipam.pagination import clamp_page
from cmdb.framework.ipam.search import active_search
from cmdb.framework.ipam.references import resolve_special_type_icon
from cmdb.framework.ipam.tree_overview import (
    load_all_special_type_objects,
    sort_tree_nodes,
    subnet_tree_node,
)
# -------------------------------------------------------------------------------------------------------------------- #


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  PURE HELPERS                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
def filter_nodes_by_family(nodes: list[dict[str, Any]], family: str) -> list[dict[str, Any]]:
    """
    Returns the nodes whose resolved address family equals the requested one

    An empty / falsy ``family`` deactivates the filter and returns every node, so the route
    can pass the raw query-param value straight through. The comparison reads the node's
    'type' key, which carries the CIDR-first resolved family - the caller is expected to have
    validated the token against IpAddressFamily already

    Args:
        nodes (list[dict[str, Any]]): Subnet nodes shaped by ``subnet_tree_node``
        family (str): The requested IpAddressFamily token, or '' for no filtering

    Returns:
        list[dict[str, Any]]: Matching nodes in their original relative order (a new list)
    """
    if not family:
        return list(nodes)

    return [node for node in nodes if node.get(IpamTreeKey.TYPE) == family]


def filter_nodes_by_search(nodes: list[dict[str, Any]], search: str) -> list[dict[str, Any]]:
    """
    Returns the nodes whose name or CIDR contains the query as a case-insensitive substring

    The shared activation rule applies (see ``active_search``): an empty / whitespace query or
    one shorter than IpamSearch.MIN_QUERY_LENGTH after stripping deactivates the filter and
    returns every node. A node matches when either its 'name' or its 'cidr' is a string
    containing the needle, so both '10.0' and a name fragment surface options; nodes where
    both values are missing never match an active search

    Args:
        nodes (list[dict[str, Any]]): Subnet nodes shaped by ``subnet_tree_node``
        search (str): Raw search query; whitespace handling and the minimum-length rule are
            applied here, the MAX_QUERY_LENGTH truncation is the route's responsibility

    Returns:
        list[dict[str, Any]]: Matching nodes in their original relative order (a new list)
    """
    needle: str | None = active_search(search)

    if needle is None:
        return list(nodes)

    lowered: str = needle.lower()
    matches: list[dict[str, Any]] = []

    for node in nodes:
        name: Any = node.get(IpamTreeKey.NAME)
        cidr: Any = node.get(IpamTreeKey.CIDR)

        name_hit: bool = isinstance(name, str) and lowered in name.lower()
        cidr_hit: bool = isinstance(cidr, str) and lowered in cidr.lower()

        if name_hit or cidr_hit:
            matches.append(node)

    return matches


# -------------------------------------------------------------------------------------------------------------------- #
#                                                   ORCHESTRATOR                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
def build_subnet_options_page(
    objects_manager: ObjectsManager,
    types_manager: TypesManager,
    *,
    page: int,
    page_size: int,
    search: str,
    family: str = '',
) -> dict[str, Any]:
    """
    Builds the paginated subnet-options payload for the interface section's subnet picker

    Steps:
      1. Load every SUBNET CmdbObject via ``load_all_special_type_objects``. With no SUBNET
         CmdbType defined the load yields no objects and the response collapses to an empty
         page envelope instead of erroring
      2. Shape each subnet into a lightweight node (public_id, name, cidr, family under
         'type') and sort the full set into the shared display order via ``sort_tree_nodes``
      3. Apply the family filter (skipped when ``family`` is empty), then the
         case-insensitive name / CIDR substring filter (skipped when the normalized query is
         shorter than IpamSearch.MIN_QUERY_LENGTH)
      4. Compute the post-filter total, clamp the requested page / page_size into the valid
         range via ``clamp_page``, and slice the page out of the filtered node list

    All subnets are candidates regardless of supernet assignment - unassigned subnets must
    stay selectable in interface rows

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        page (int): Requested 1-based page number; clamped server-side
        page_size (int): Requested page size; clamped into [IpamPagination.MIN_PAGE_SIZE,
            IpamPagination.MAX_PAGE_SIZE]
        search (str): Raw search query; whitespace is stripped and queries shorter than
            IpamSearch.MIN_QUERY_LENGTH are ignored. The MAX_QUERY_LENGTH truncation is the
            route's responsibility
        family (str): Optional IpAddressFamily token ('ipv4' / 'ipv6') restricting the rows
            to one family; '' returns both families. Token validation is the route's
            responsibility

    Returns:
        dict[str, Any]: {'page', 'page_size', 'total', 'search', 'type', 'rows': [...]} where
            each row is {'public_id', 'name', 'cidr', 'type', 'icon'} and 'total' is the count
            after both filters, not the unfiltered count
    """
    subnet_objs: list[dict[str, Any]] = load_all_special_type_objects(
        objects_manager, types_manager, SpecialType.SUBNET,
    )
    subnet_icon: str | None = resolve_special_type_icon(types_manager, SpecialType.SUBNET)

    nodes: list[dict[str, Any]] = sort_tree_nodes([subnet_tree_node(s, subnet_icon) for s in subnet_objs])
    filtered: list[dict[str, Any]] = filter_nodes_by_search(filter_nodes_by_family(nodes, family), search)

    total: int = len(filtered)
    clamped_page, clamped_size = clamp_page(page, page_size, total)
    start_offset: int = (clamped_page - 1) * clamped_size

    return {
        IpamOverviewKey.PAGE: clamped_page,
        IpamOverviewKey.PAGE_SIZE: clamped_size,
        IpamOverviewKey.TOTAL: total,
        IpamOverviewKey.SEARCH: search,
        IpamOverviewKey.TYPE: family,
        IpamOverviewKey.ROWS: filtered[start_offset:start_offset + clamped_size],
    }
