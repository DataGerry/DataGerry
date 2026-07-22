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
IPAM relation grafting for the CI Explorer

The IPAM SpecialTypes (SUPERNET, SUBNET, VLAN) and the dg-ipam-interface MDS section
template form their own parent/child hierarchy that does NOT live in framework.objectRelations
- the edges are encoded as ref-typed fields and MDS row references instead. This module
walks one hop in each direction of that hierarchy for a given target object and produces
``IpamNeighbour`` records the orchestrator turns into normal-looking parent/child nodes
+ edges (folded into the same response buckets as relation neighbours, distinguished only
by ``metadata.source='ipam'`` on the edge)

Hierarchy walked (parent -> child semantics, per the SpecialType schemas):

    SUPERNET
        |
        | (SUBNET.dg-supernet-ref)
        v
    SUBNET
        |+-- (VLAN.dg-subnet-ref)              -> VLAN
        |
        +-- (dg-ipam-interface row.            -> any CmdbObject whose dg-ipam-interface
              dg-interface-subnet)                MDS section references this SUBNET
"""
from dataclasses import dataclass
from typing import Any

from cmdb.manager import ObjectsManager, TypesManager
from cmdb.utils import BaseStrEnum

from cmdb.models.object_model import CmdbObjectKey, CmdbObjectMdsKey, CmdbObjectMdsRowKey
from cmdb.models.object_model.cmdb_object_helpers import extract_field_value
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.special_type_model.ipam_constants import (
    InterfaceField,
    IpamSection,
    SubnetField,
    VlanField,
)

from cmdb.framework.ipam.references import (
    find_interfaces_referencing_subnet,
    find_subnets_referencing_supernet,
    find_vlans_referencing_subnet,
    resolve_special_type_id,
)
# -------------------------------------------------------------------------------------------------------------------- #


class IpamEdgeCategory(BaseStrEnum):
    """
    Internal identifier for the three IPAM edge categories

    Each member names the pair of endpoint roles the edge connects. Values are stable
    internal slugs only - they do NOT appear on the wire. The wire ``metadata.relation_name``
    is looked up direction-aware via IPAM_EDGE_NAMES_PARENT / IPAM_EDGE_NAMES_CHILD so the
    string describes whichever end the neighbour sits on (e.g. a SUBNET-SUPERNET edge reads
    'Supernet' from the SUBNET side and 'Subnet' from the SUPERNET side)
    """
    SUBNET_SUPERNET = 'subnet_supernet'
    SUBNET_VLAN = 'subnet_vlan'
    SUBNET_INTERFACE = 'subnet_interface'


IPAM_RELATION_LABEL: str = 'assigned'

# Direction-aware wire ``relation_name`` lookups. The 'parent' table is used when the
# neighbour is the parent of the target (the edge goes neighbour → target in the IPAM
# hierarchy); the 'child' table is used when the neighbour is below the target. The string
# names what role the neighbour plays, so the FE label reads naturally from the target's
# perspective regardless of direction
IPAM_EDGE_NAMES_PARENT: dict[str, str] = {
    IpamEdgeCategory.SUBNET_SUPERNET: 'Supernet',
    IpamEdgeCategory.SUBNET_VLAN: 'Subnet',
    IpamEdgeCategory.SUBNET_INTERFACE: 'Subnet-IP',
}

IPAM_EDGE_NAMES_CHILD: dict[str, str] = {
    IpamEdgeCategory.SUBNET_SUPERNET: 'Subnet',
    IpamEdgeCategory.SUBNET_VLAN: 'VLAN',
    IpamEdgeCategory.SUBNET_INTERFACE: 'Interface',
}

# Direction-aware icon lookups, paired with the name tables above: each icon visually
# hints at the neighbour's role so the edge in the graph reads correctly from either side
IPAM_EDGE_ICONS_PARENT: dict[str, str] = {
    IpamEdgeCategory.SUBNET_SUPERNET: 'fa-network-wired',
    IpamEdgeCategory.SUBNET_VLAN: 'fa-sitemap',
    IpamEdgeCategory.SUBNET_INTERFACE: 'fa-sitemap',
}

IPAM_EDGE_ICONS_CHILD: dict[str, str] = {
    IpamEdgeCategory.SUBNET_SUPERNET: 'fa-sitemap',
    IpamEdgeCategory.SUBNET_VLAN: 'fa-tag',
    IpamEdgeCategory.SUBNET_INTERFACE: 'fa-ethernet',
}

IPAM_RELATION_COLOR: str = '#4A90E2'
IPAM_METADATA_SOURCE: str = 'ipam'


@dataclass(frozen=True)
class IpamNeighbour:
    """
    One IPAM-grafted neighbour with the directional metadata the orchestrator needs to
    drop it into the right parent/child bucket and build its edge

    Attributes:
        neighbour_object: The fully-loaded CmdbObject document for the neighbour
        is_child_of_target: True when the neighbour sits below the target in the IPAM
            hierarchy (e.g. SUBNET when target is SUPERNET); False when above (e.g.
            SUPERNET when target is SUBNET). Controls which response bucket the
            orchestrator drops the node + edge into
        edge_category: The IpamEdgeCategory describing the endpoint-pair category; the
            edge composer reads it to emit the wire ``relation_name`` and look up the icon
    """
    neighbour_object: dict[str, Any]
    is_child_of_target: bool
    edge_category: IpamEdgeCategory


def _collect_subnet_refs_from_interface_rows(target_object: dict[str, Any]) -> list[int]:
    """
    Walks the target's dg-ipam-interface MDS rows and returns the distinct SUBNET ids referenced

    Skips rows whose subnet ref is missing, not an int, or equal to the target itself (a
    self-reference can never be a meaningful neighbour). The returned list preserves
    encounter order and deduplicates ids that appear on multiple rows

    Args:
        target_object (dict[str, Any]): The focal CmdbObject's full document; may carry
            zero or more dg-ipam-interface MDS sections

    Returns:
        list[int]: SUBNET public_ids referenced by any interface row; empty when the object
            carries no dg-ipam-interface section
    """
    seen: set[int] = set()
    ordered: list[int] = []
    target_id: Any = target_object.get(CmdbObjectKey.PUBLIC_ID)

    for section in target_object.get(CmdbObjectKey.MULTI_DATA_SECTIONS, []) or []:
        if section.get(CmdbObjectMdsKey.SECTION_ID) != IpamSection.INTERFACE:
            continue

        for row in section.get(CmdbObjectMdsKey.VALUES, []) or []:
            for entry in row.get(CmdbObjectMdsRowKey.DATA, []) or []:
                if entry.get('name') != InterfaceField.SUBNET:
                    continue

                value: Any = entry.get('value')

                if not isinstance(value, int) or value == target_id or value in seen:
                    continue

                seen.add(value)
                ordered.append(value)

    return ordered


def _plan_ipam_neighbours(
    target_id: int,
    target_object: dict[str, Any],
    types_manager: TypesManager,
    objects_manager: ObjectsManager,
) -> list[tuple[int, IpamEdgeCategory, bool]]:
    """
    Builds the list of (neighbour_public_id, edge_category, is_child_of_target) candidates

    Inspects the target's type against the SUPERNET / SUBNET / VLAN SpecialTypes and walks
    every applicable IPAM edge: SUPERNET -> SUBNETs, SUBNET -> SUPERNET / VLANs / interface
    carriers, VLAN -> SUBNET, plus the dg-ipam-interface MDS rows on any object regardless
    of type. Skips self-references and ref-fields whose value isn't an int. Duplicates by
    public_id are *preserved* at this stage; the bulk-load step downstream dedupes them
    into the response buckets

    Args:
        target_id (int): public_id of the focal CmdbObject
        target_object (dict[str, Any]): Full document of the focal CmdbObject
        types_manager (TypesManager): db interface for CmdbTypes
        objects_manager (ObjectsManager): db interface for CmdbObjects

    Returns:
        list[tuple[int, IpamEdgeCategory, bool]]: Candidate neighbours; each tuple is
            (neighbour_public_id, edge's IpamEdgeCategory, True iff neighbour is a child
            of target). Empty when the target has no IPAM neighbours
    """
    supernet_type_id: int | None = resolve_special_type_id(types_manager, SpecialType.SUPERNET)
    subnet_type_id: int | None = resolve_special_type_id(types_manager, SpecialType.SUBNET)
    vlan_type_id: int | None = resolve_special_type_id(types_manager, SpecialType.VLAN)

    target_type_id: Any = target_object.get(CmdbObjectKey.TYPE_ID)
    plan: list[tuple[int, IpamEdgeCategory, bool]] = []

    # Target is SUPERNET → SUBNETs are its children (SUBNET-SUPERNET edges)
    if supernet_type_id is not None and target_type_id == supernet_type_id:
        for subnet in find_subnets_referencing_supernet(objects_manager, types_manager, target_id):
            plan.append((subnet[CmdbObjectKey.PUBLIC_ID], IpamEdgeCategory.SUBNET_SUPERNET, True))

    # Target is SUBNET → parent SUPERNET, child VLANs, child interface-carrying objects
    if subnet_type_id is not None and target_type_id == subnet_type_id:
        supernet_ref: Any = extract_field_value(target_object, SubnetField.PARENT_SUPERNET)

        if isinstance(supernet_ref, int) and supernet_ref != target_id:
            plan.append((supernet_ref, IpamEdgeCategory.SUBNET_SUPERNET, False))

        for vlan in find_vlans_referencing_subnet(objects_manager, types_manager, target_id):
            plan.append((vlan[CmdbObjectKey.PUBLIC_ID], IpamEdgeCategory.SUBNET_VLAN, True))

        for interface_carrier in find_interfaces_referencing_subnet(objects_manager, target_id):
            plan.append((interface_carrier[CmdbObjectKey.PUBLIC_ID], IpamEdgeCategory.SUBNET_INTERFACE, True))

    # Target is VLAN → parent SUBNET (SUBNET-VLAN edge)
    if vlan_type_id is not None and target_type_id == vlan_type_id:
        subnet_ref_from_vlan: Any = extract_field_value(target_object, VlanField.SUBNET_REF)

        if isinstance(subnet_ref_from_vlan, int) and subnet_ref_from_vlan != target_id:
            plan.append((subnet_ref_from_vlan, IpamEdgeCategory.SUBNET_VLAN, False))

    # Any object can carry dg-ipam-interface rows → walk them for SUBNET parent edges
    # (SUBNET-INTERFACE edges)
    for interface_subnet_id in _collect_subnet_refs_from_interface_rows(target_object):
        plan.append((interface_subnet_id, IpamEdgeCategory.SUBNET_INTERFACE, False))

    return plan


def collect_ipam_neighbours(
    target_id: int,
    target_object: dict[str, Any],
    include_parents: bool,
    include_children: bool,
    types_filter: frozenset[int],
    remaining: int,
    item_limit_active: bool,
    objects_manager: ObjectsManager,
    types_manager: TypesManager,
) -> list[IpamNeighbour]:
    """
    Returns the IPAM neighbours of the target in the requested direction(s)

    Pipeline:
      1. Build the candidate plan from the target's type + dg-ipam-interface MDS rows
         (see _plan_ipam_neighbours)
      2. Drop plan entries whose direction the caller did not request (so the bulk fetch
         only touches objects that will appear in the response)
      3. Bulk-load the candidate objects with a single ``find({'public_id': {'$in': ...}})``,
         AND-combined with the ``type_id`` ``$in`` constraint when ``types_filter`` is active
         so the filter is applied at the Mongo level (matches the relation and location
         children semantics)
      4. Filter the plan to only the candidates that survived the bulk load
      5. Apply ``item_limit`` to the post-filter list so the visible count is consistent
         with how the relation and location branches honor the cap

    Args:
        target_id (int): public_id of the focal CmdbObject
        target_object (dict[str, Any]): Full target document, as loaded by the orchestrator
            *before* enrichment (so ref-field values are still raw ints, not summary lines)
        include_parents (bool): When True, neighbours where the target sits below (e.g.
            SUPERNET parent of a SUBNET target) are returned
        include_children (bool): When True, neighbours where the target sits above (e.g.
            SUBNETs of a SUPERNET target) are returned
        types_filter (frozenset[int]): Allowed neighbour type_ids; empty set disables filtering
        remaining (int): Slot budget still available; only honored when ``item_limit_active``
        item_limit_active (bool): Whether the route is operating under an item_limit cap
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes

    Returns:
        list[IpamNeighbour]: One entry per surviving neighbour, in encounter order. Empty
            when the target has no IPAM neighbours, both directions are disabled, or the
            cap is zero
    """
    if item_limit_active and remaining <= 0:
        return []

    if not include_parents and not include_children:
        return []

    plan: list[tuple[int, IpamEdgeCategory, bool]] = _plan_ipam_neighbours(
        target_id, target_object, types_manager, objects_manager,
    )

    plan = [
        entry for entry in plan
        if (entry[2] and include_children) or (not entry[2] and include_parents)
    ]

    if not plan:
        return []

    public_ids: list[int] = [public_id for public_id, _, _ in plan]
    criteria: dict[str, Any] = {CmdbObjectKey.PUBLIC_ID: {'$in': public_ids}}

    if types_filter:
        criteria[CmdbObjectKey.TYPE_ID] = {'$in': list(types_filter)}

    full_objects: list[dict[str, Any]] = list(objects_manager.find(criteria=criteria))

    full_by_id: dict[int, dict[str, Any]] = {
        obj[CmdbObjectKey.PUBLIC_ID]: obj
        for obj in full_objects
        if isinstance(obj.get(CmdbObjectKey.PUBLIC_ID), int)
    }

    surviving: list[tuple[int, IpamEdgeCategory, bool]] = [
        (public_id, edge_category, is_child)
        for public_id, edge_category, is_child in plan
        if public_id in full_by_id
    ]

    if item_limit_active and len(surviving) > remaining:
        surviving = surviving[:remaining]

    return [
        IpamNeighbour(
            neighbour_object=full_by_id[public_id],
            is_child_of_target=is_child,
            edge_category=edge_category,
        )
        for public_id, edge_category, is_child in surviving
    ]
