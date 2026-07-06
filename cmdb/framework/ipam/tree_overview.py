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
Builds the data payloads for the IPAM sidebar tree

The frontend renders a locations-style sidebar tree of all SUPERNETs and their SUBNETs. The
initial payload (``build_ipam_tree``) is one call: a flat list of every SUPERNET (each entry
carrying 'has_children' so the FE can render an expand caret without a probe request) plus a
flat list of every unassigned SUBNET - one whose 'dg-supernet-ref' is empty. Expanding a
supernet fetches its full CIDR-nested subnet subtree in one call
(``build_supernet_subnet_tree``); ``build_unassigned_subnets`` re-fetches the unassigned block
alone for targeted refreshes

Tree nodes are intentionally lightweight - public_id, name, cidr and the address family under
'type' - and skip the interface-IP counting, VLAN resolution and validity annotation the
overview rows carry. Nesting reuses the overview's CIDR-containment semantics (a node's parent
is the most-specific sibling that strictly contains it); the unassigned block stays flat
because standalone subnets are an unstructured bucket (no overlap rules apply to them). Every
list - the supernet block, the unassigned block and each 'children' array - is sorted IPv4
before IPv6, then by ascending network address with prefix length as tiebreaker; nodes with a
missing or unparsable CIDR trail their family group ordered by name
"""
from typing import Any

from cmdb.manager import ObjectsManager, TypesManager
from cmdb.models.object_model import CmdbObjectKey, extract_field_value
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.special_type_model.ipam_constants import (
    SupernetField,
    SubnetField,
    IpAddressFamily,
    IpamTreeKey,
)
from cmdb.framework.ipam.cidr import Network, parse_cidr, is_strict_subnet
from cmdb.framework.ipam.references import resolve_special_type_id, resolve_special_type_icon
from cmdb.framework.ipam.supernet_overview import (
    load_supernet_object,
    load_subnets_for_supernet,
    subnet_family,
    supernet_family,
)
# -------------------------------------------------------------------------------------------------------------------- #


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  PURE HELPERS                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
def _coerce_ref_id(value: Any) -> int | None:
    """
    Coerces a stored reference-field value into an int public_id when possible, else None

    Mirrors the coercion the IPAM enforcement layer applies to 'dg-supernet-ref': None, the
    empty string and 0 are 'no reference', and any value that does not convert cleanly to an
    int (e.g. a garbage string) is treated the same way

    Args:
        value (Any): The raw field value

    Returns:
        int | None: The integer public_id, or None when 'value' carries no usable reference
    """
    if value is None or value == '' or value == 0:
        return None

    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parent_supernet_id(subnet_obj: dict[str, Any]) -> int | None:
    """
    Returns the public_id of the supernet a SUBNET references, or None when unassigned

    Reads the subnet's 'dg-supernet-ref' field and coerces it via ``_coerce_ref_id``, so a
    subnet whose reference field is missing, cleared or unusable counts as unassigned

    Args:
        subnet_obj (dict[str, Any]): The SUBNET CmdbObject document

    Returns:
        int | None: The referenced supernet's public_id, or None when the subnet is unassigned
    """
    return _coerce_ref_id(extract_field_value(subnet_obj, SubnetField.PARENT_SUPERNET))


def _collect_referenced_supernet_ids(subnet_objs: list[dict[str, Any]]) -> set[int]:
    """
    Returns the set of supernet public_ids referenced by at least one of the given SUBNETs

    Drives the 'has_children' flag on the supernet entries of the initial tree payload: a
    supernet whose public_id is absent from the set has no assigned subnet. Dangling
    references (a ref pointing at a deleted supernet) are included - they simply never match
    a listed supernet

    Args:
        subnet_objs (list[dict[str, Any]]): SUBNET CmdbObject documents

    Returns:
        set[int]: public_ids of every supernet referenced by at least one subnet
    """
    referenced: set[int] = set()

    for subnet_obj in subnet_objs:
        supernet_id: int | None = _parent_supernet_id(subnet_obj)

        if supernet_id is not None:
            referenced.add(supernet_id)

    return referenced


def _shape_tree_node(
    obj: dict[str, Any],
    name_field: str,
    range_field: str,
    family: str,
    icon: str | None,
) -> dict[str, Any]:
    """
    Shapes one IPAM CmdbObject into a lightweight sidebar-tree node

    The CIDR is normalised to its canonical string form when it parses; an unparsable string
    is passed through verbatim so the FE can still display it, and a missing / non-string
    value becomes None. The name is passed through only when it is a string. The icon is the
    object's CmdbType icon, resolved once per SpecialType by the caller and shared across every
    node of the same family (None when the type has no icon / is undefined)

    Args:
        obj (dict[str, Any]): The SUBNET or SUPERNET CmdbObject document
        name_field (str): The name field to read (SubnetField.NAME / SupernetField.NAME)
        range_field (str): The network-range field to read (SubnetField.NETWORK_RANGE /
            SupernetField.NETWORK_RANGE)
        family (str): The object's resolved IpAddressFamily ('ipv4' / 'ipv6')
        icon (str | None): The object's CmdbType icon, or None when unset / undefined

    Returns:
        dict[str, Any]: One node with public_id, name, cidr, the address family under 'type'
            and the type 'icon'
    """
    raw_cidr: Any = extract_field_value(obj, range_field)
    network: Network | None = parse_cidr(raw_cidr) if isinstance(raw_cidr, str) else None
    raw_name: Any = extract_field_value(obj, name_field)

    return {
        CmdbObjectKey.PUBLIC_ID: obj.get(CmdbObjectKey.PUBLIC_ID),
        IpamTreeKey.NAME: raw_name if isinstance(raw_name, str) else None,
        IpamTreeKey.CIDR: str(network) if network is not None else (raw_cidr if isinstance(raw_cidr, str) else None),
        IpamTreeKey.TYPE: family,
        IpamTreeKey.ICON: icon,
    }


def subnet_tree_node(subnet_obj: dict[str, Any], icon: str | None = None) -> dict[str, Any]:
    """
    Shapes a SUBNET CmdbObject into a sidebar-tree node

    Thin binding of ``_shape_tree_node`` to the SUBNET name / range fields with the family
    resolved CIDR-first via ``subnet_family`` (selector fallback, IPv4 default)

    Args:
        subnet_obj (dict[str, Any]): The SUBNET CmdbObject document
        icon (str | None): The SUBNET CmdbType icon (resolved once by the caller), or None

    Returns:
        dict[str, Any]: One node with public_id, name, cidr, the address family under 'type'
            and the type 'icon'
    """
    return _shape_tree_node(
        subnet_obj,
        SubnetField.NAME,
        SubnetField.NETWORK_RANGE,
        subnet_family(subnet_obj),
        icon,
    )


def _supernet_tree_node(
    supernet_obj: dict[str, Any],
    referenced_supernet_ids: set[int],
    icon: str | None,
) -> dict[str, Any]:
    """
    Shapes a SUPERNET CmdbObject into a sidebar-tree entry carrying 'has_children'

    'has_children' is True when at least one SUBNET references the supernet via
    'dg-supernet-ref', so the FE can render an expand caret without a probe request. The
    subtree itself is fetched lazily via ``build_supernet_subnet_tree``

    Args:
        supernet_obj (dict[str, Any]): The SUPERNET CmdbObject document
        referenced_supernet_ids (set[int]): Output of ``_collect_referenced_supernet_ids``
        icon (str | None): The SUPERNET CmdbType icon (resolved once by the caller), or None

    Returns:
        dict[str, Any]: One entry with public_id, name, cidr, the address family under 'type',
            the type 'icon' and 'has_children'
    """
    node: dict[str, Any] = _shape_tree_node(
        supernet_obj,
        SupernetField.NAME,
        SupernetField.NETWORK_RANGE,
        supernet_family(supernet_obj),
        icon,
    )
    node[IpamTreeKey.HAS_CHILDREN] = node[CmdbObjectKey.PUBLIC_ID] in referenced_supernet_ids

    return node


def _tree_sort_key(node: dict[str, Any]) -> tuple[int, int, int, int, str]:
    """
    Returns the sort key implementing the sidebar tree's display order

    Order: IPv4 nodes before IPv6 nodes; within a family, nodes with a parsable 'cidr' sort
    by ascending network address with prefix length as tiebreaker (so 10.0.0.0/8 precedes
    10.0.0.0/16); nodes whose 'cidr' is missing or unparsable trail their family group,
    ordered case-insensitively by name. The family rank reads the node's 'type' so unparsable
    nodes still group under their selector-declared family

    Args:
        node (dict[str, Any]): A tree node shaped by ``_shape_tree_node``

    Returns:
        tuple[int, int, int, int, str]: (family rank, unparsable flag, network address,
            prefix length, lowercase name)
    """
    family_rank: int = 1 if node.get(IpamTreeKey.TYPE) == IpAddressFamily.IPV6 else 0
    cidr: Any = node.get(IpamTreeKey.CIDR)
    network: Network | None = parse_cidr(cidr) if isinstance(cidr, str) else None

    if network is None:
        name: Any = node.get(IpamTreeKey.NAME)
        return (family_rank, 1, 0, 0, name.lower() if isinstance(name, str) else '')

    return (family_rank, 0, int(network.network_address), network.prefixlen, '')


def sort_tree_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Returns a new list of tree nodes in the sidebar display order

    Applies ``_tree_sort_key``: IPv4 before IPv6, ascending network address with prefix
    length as tiebreaker within each family, unparsable-CIDR nodes trailing their family
    ordered by name. Used for every flat block (supernets, unassigned) and the root level
    of nested subtrees so the order rule is identical at every tree level

    Args:
        nodes (list[dict[str, Any]]): Tree nodes shaped by ``_shape_tree_node``

    Returns:
        list[dict[str, Any]]: The nodes in display order (input list is not mutated)
    """
    return sorted(nodes, key=_tree_sort_key)


def nest_subnet_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Nests flat subnet nodes into a CIDR-containment tree and returns the root nodes

    Every node is mutated in place to carry a 'children' list (empty for leaves). A node's
    parent is the most-specific other node whose network strictly contains it - the same
    semantics the supernet overview's ``sort_and_link_subnets`` applies - found with a single
    stack pass over the nodes sorted by ascending network address and prefix length. Nodes of
    different families can never link (strict containment treats them as disjoint) and nodes
    with an equal CIDR become siblings. Nodes whose 'cidr' is missing or unparsable cannot
    participate in containment and are returned as roots

    Children inherit ascending CIDR order from the linking pass; the returned root list is
    sorted via ``sort_tree_nodes`` so the family grouping and unparsable-trailing rules hold
    at the top level too

    Args:
        nodes (list[dict[str, Any]]): Flat tree nodes shaped by ``_shape_tree_node``

    Returns:
        list[dict[str, Any]]: The root nodes in display order, each with nested 'children'
    """
    sortable: list[tuple[Network, dict[str, Any]]] = []
    roots: list[dict[str, Any]] = []

    for node in nodes:
        node[IpamTreeKey.CHILDREN] = []
        cidr: Any = node.get(IpamTreeKey.CIDR)
        network: Network | None = parse_cidr(cidr) if isinstance(cidr, str) else None

        if network is None:
            roots.append(node)
        else:
            sortable.append((network, node))

    sortable.sort(key=lambda item: (int(item[0].network_address), item[0].prefixlen))

    stack: list[tuple[Network, dict[str, Any]]] = []

    for network, node in sortable:
        while stack and not is_strict_subnet(stack[-1][0], network):
            stack.pop()

        if stack:
            stack[-1][1][IpamTreeKey.CHILDREN].append(node)
        else:
            roots.append(node)

        stack.append((network, node))

    return sort_tree_nodes(roots)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                   DATA LOADING                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
def load_all_special_type_objects(
    objects_manager: ObjectsManager,
    types_manager: TypesManager,
    special_type: SpecialType,
) -> list[dict[str, Any]]:
    """
    Returns every CmdbObject of the CmdbType marked with the given SpecialType

    Returns an empty list when no CmdbType carries the SpecialType yet, so the tree renders
    empty instead of erroring on a fresh installation

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        special_type (SpecialType): The SpecialType whose objects are loaded (SUPERNET / SUBNET)

    Returns:
        list[dict[str, Any]]: All CmdbObject documents of the resolved type
    """
    type_id: int | None = resolve_special_type_id(types_manager, special_type)

    if type_id is None:
        return []

    return objects_manager.find_objects({CmdbObjectKey.TYPE_ID: type_id}, as_dict=True)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                   ORCHESTRATOR                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
def build_ipam_tree(
    objects_manager: ObjectsManager,
    types_manager: TypesManager,
) -> dict[str, Any]:
    """
    Builds the initial sidebar-tree payload: every supernet plus every unassigned subnet

    One call covers the sidebar's first render. 'supernets' is the flat list of every
    SUPERNET entry (public_id, name, cidr, type, has_children); the per-supernet subtrees
    are fetched lazily via ``build_supernet_subnet_tree`` when the user expands an entry.
    'unassigned' is the flat list of every SUBNET without a usable 'dg-supernet-ref'
    (public_id, name, cidr, type) - standalone subnets carry no nesting (see module
    docstring). Both blocks are sorted IPv4 before IPv6, then ascending by CIDR, with
    unparsable-CIDR nodes trailing their family ordered by name

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes

    Returns:
        dict[str, Any]: {'supernets': [supernet entries], 'unassigned': [subnet nodes]}
    """
    supernet_objs: list[dict[str, Any]] = load_all_special_type_objects(
        objects_manager, types_manager, SpecialType.SUPERNET,
    )
    subnet_objs: list[dict[str, Any]] = load_all_special_type_objects(
        objects_manager, types_manager, SpecialType.SUBNET,
    )

    referenced: set[int] = _collect_referenced_supernet_ids(subnet_objs)

    # The icon is the SpecialType's CmdbType icon - one per family, shared across every node
    supernet_icon: str | None = resolve_special_type_icon(types_manager, SpecialType.SUPERNET)
    subnet_icon: str | None = resolve_special_type_icon(types_manager, SpecialType.SUBNET)

    return {
        IpamTreeKey.SUPERNETS: sort_tree_nodes(
            [_supernet_tree_node(s, referenced, supernet_icon) for s in supernet_objs],
        ),
        IpamTreeKey.UNASSIGNED: sort_tree_nodes(
            [subnet_tree_node(s, subnet_icon) for s in subnet_objs if _parent_supernet_id(s) is None],
        ),
    }


def build_supernet_subnet_tree(
    objects_manager: ObjectsManager,
    types_manager: TypesManager,
    supernet_public_id: int,
) -> dict[str, Any]:
    """
    Builds the full CIDR-nested subnet subtree of one supernet

    Returns every SUBNET referencing the supernet (any nesting depth) as a nested node tree:
    a node's parent is the most-specific sibling whose network strictly contains it, exactly
    like the supernet overview view. The whole subtree comes back in one call - the hierarchy
    is computed from CIDR containment over all subnets of the supernet anyway, so per-node
    lazy loading would repeat the same work per expansion. A supernet without subnets returns
    an empty 'children' list

    Aborts with HTTP 404 when the supernet does not exist, HTTP 400 when the public_id refers
    to a non-supernet CmdbObject or no SUPERNET CmdbType is defined

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        supernet_public_id (int): public_id of the SUPERNET whose subtree is built

    Returns:
        dict[str, Any]: {'children': [root nodes, each with nested 'children']}
    """
    load_supernet_object(objects_manager, types_manager, supernet_public_id)

    subnet_objs: list[dict[str, Any]] = load_subnets_for_supernet(
        objects_manager, types_manager, supernet_public_id,
    )
    subnet_icon: str | None = resolve_special_type_icon(types_manager, SpecialType.SUBNET)

    return {
        IpamTreeKey.CHILDREN: nest_subnet_nodes([subnet_tree_node(s, subnet_icon) for s in subnet_objs]),
    }


def build_unassigned_subnets(
    objects_manager: ObjectsManager,
    types_manager: TypesManager,
) -> dict[str, Any]:
    """
    Builds the unassigned-subnets block alone, for targeted sidebar refreshes

    Returns the same flat 'unassigned' list as ``build_ipam_tree`` - every SUBNET without a
    usable 'dg-supernet-ref', sorted IPv4 before IPv6 then ascending by CIDR - without
    reloading the supernet block. No nesting pass runs: standalone subnets are an
    unstructured bucket

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes

    Returns:
        dict[str, Any]: {'unassigned': [subnet nodes]}
    """
    subnet_objs: list[dict[str, Any]] = load_all_special_type_objects(
        objects_manager, types_manager, SpecialType.SUBNET,
    )
    subnet_icon: str | None = resolve_special_type_icon(types_manager, SpecialType.SUBNET)

    return {
        IpamTreeKey.UNASSIGNED: sort_tree_nodes(
            [subnet_tree_node(s, subnet_icon) for s in subnet_objs if _parent_supernet_id(s) is None],
        ),
    }
