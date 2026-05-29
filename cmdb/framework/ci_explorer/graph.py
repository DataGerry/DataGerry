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
Top-level orchestrator for the CI Explorer node/edge payload

Single entry point used by the /ci_explorer/items route. Loads every object in scope
(root, relation-linked, location-grafted, IPAM-grafted) in a small, fixed number of
Mongo round trips, runs the batched ref-field / dg_location enrichment once over the
full union, then composes the response in a single pass. Independent of Flask - it
takes already-parsed primitive args plus the five managers
"""
from typing import Any

from cmdb.manager import (
    LocationsManager,
    ObjectRelationsManager,
    ObjectsManager,
    RelationsManager,
    TypesManager,
)
from cmdb.models.ci_explorer_model import NodeType

from cmdb.framework.ci_explorer.edges import (
    compose_ipam_edge,
    compose_location_edge,
    compose_relation_edge,
)
from cmdb.framework.ci_explorer.enrichment import (
    build_location_name_lookup,
    build_summary_lookup,
    collect_ref_and_location_ids,
    flatten_object_fields,
)
from cmdb.framework.ci_explorer.ipam import (
    IPAM_RELATION_COLOR,
    IpamNeighbour,
    collect_ipam_neighbours,
)
from cmdb.framework.ci_explorer.locations import (
    CHILD_LOCATION_REL_COLOR,
    PARENT_LOCATION_REL_COLOR,
    collect_location_children_objects,
    collect_location_parent_object,
)
from cmdb.framework.ci_explorer.nodes import compose_node
from cmdb.framework.ci_explorer.relations import (
    build_relation_criteria,
    collect_linked_object_ids,
    collect_relation_ids,
    load_object_relations,
    split_object_relation_direction,
)
# -------------------------------------------------------------------------------------------------------------------- #


def _index_by_public_id(docs: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    """
    Indexes a list of documents by their integer ``public_id``

    Documents whose ``public_id`` is missing or not an integer are silently skipped so a
    partial / malformed batch never crashes the caller. Used to turn the linked-object,
    type and enriched-object lists into O(1) lookup maps for the composition pass

    Args:
        docs (list[dict[str, Any]]): Documents pulled from one of the framework
            collections (objects, types, relations, locations)

    Returns:
        dict[int, dict[str, Any]]: {public_id: document}
    """
    return {
        doc['public_id']: doc
        for doc in docs
        if isinstance(doc.get('public_id'), int)
    }


# pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-locals
def build_ci_explorer_graph(
    target_id: int,
    target_type: NodeType,
    with_root: bool,
    with_locations: bool,
    with_ipam_relations: bool,
    item_limit: int,
    types_filter: frozenset[int],
    relations_filter: frozenset[int],
    objects_manager: ObjectsManager,
    types_manager: TypesManager,
    relations_manager: RelationsManager,
    object_relations_manager: ObjectRelationsManager,
    locations_manager: LocationsManager,
) -> dict[str, Any]:
    """
    Builds the full node/edge payload for the CI Explorer graph view

    Pipeline:
      1. Load the target CmdbObject when ``with_root`` or ``with_ipam_relations`` is True
         (skipped otherwise - the IPAM walker needs raw field values, the root branch
         needs the doc for the response, the location branch only needs ``target_id``)
      2. Build the object-relation criteria, fetch matching object_relations, fetch the
         referenced CmdbRelation documents, then bulk-fetch the linked CmdbObjects
      3. Resolve each object_relation into a DirectionalEdge (which side is the linked
         object on, what color/name/icon to display)
      4. When ``with_locations`` is True, walk one hop in each direction of the dg_location
         tree (skipping branches the target_type excludes) and collect the raw owning
         CmdbObjects. The remaining-budget for the second branch correctly reflects how
         many slots the first branch consumed (B1 fix vs. the original route)
      5. When ``with_ipam_relations`` is True, walk one hop in each direction of the IPAM
         SpecialType hierarchy (SUPERNET <-> SUBNET <-> VLAN/Interface) and collect the
         raw neighbour CmdbObjects. Direction filtering follows ``target_type`` so the
         visible cap stays consistent with the relation/location branches
      6. Bulk-fetch the CmdbType documents for every object in scope
      7. Run the batched enrichment once across the whole union: collect ref-field +
         dg_location ids, do one $in lookup each, then flatten every object's fields
      8. Compose nodes (one builder used everywhere - root, relation-linked, location-
         grafted, IPAM-grafted) and edges (relation / IPAM / location shapes) from the
         enriched objects + type docs. IPAM nodes/edges fold into the same
         parent_nodes / children_nodes / parent_edges / child_edges buckets as relation
         neighbours, with ``metadata.source='ipam'`` distinguishing them on the edge
      9. Assemble the response based on ``target_type`` (CHILD / PARENT / BOTH)

    Args:
        target_id (int): public_id of the focal CmdbObject
        target_type (NodeType): Direction(s) to include in the response
        with_root (bool): When True, the response includes a ``root_node`` block
        with_locations (bool): When True, the response includes dg_location-grafted
            neighbours with inverted parent/child semantics
        with_ipam_relations (bool): When True, the response includes IPAM-hierarchy
            neighbours (SUPERNET / SUBNET / VLAN / interface carriers) folded into the
            standard parent/child buckets
        item_limit (int): Upper bound on the number of neighbour nodes; 0 means unlimited
        types_filter (frozenset[int]): Allowed neighbour type_ids; empty disables filtering
        relations_filter (frozenset[int]): Allowed CmdbRelation public_ids; empty disables
            filtering
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        relations_manager (RelationsManager): db interface for CmdbRelations
        object_relations_manager (ObjectRelationsManager): db interface for CmdbObjectRelations
        locations_manager (LocationsManager): db interface for CmdbLocations

    Returns:
        dict[str, Any]: The full response envelope; keys present depend on ``target_type``,
            ``with_root``, ``with_locations`` and ``with_ipam_relations``. See the route
            docstring for the shape
    """
    item_limit_active: bool = item_limit > 0
    include_children: bool = target_type in (NodeType.BOTH, NodeType.CHILD)
    include_parents: bool = target_type in (NodeType.BOTH, NodeType.PARENT)

    # 1. Target object load (root display, IPAM walking, or both)
    root_object: dict[str, Any] | None = (
        objects_manager.get_object(target_id)
        if (with_root or with_ipam_relations)
        else None
    )

    # 2. Relation criteria + object_relations + relations + linked objects
    rel_criteria: dict[str, Any] = build_relation_criteria(target_id, types_filter, relations_filter)
    object_relations: list[dict[str, Any]] = load_object_relations(object_relations_manager, rel_criteria)

    relation_ids: set[int] = collect_relation_ids(object_relations)
    relations_by_id: dict[int, dict[str, Any]] = {}

    if relation_ids:
        relations_by_id = _index_by_public_id(list(
            relations_manager.find(criteria={'public_id': {'$in': list(relation_ids)}})
        ))

    linked_object_ids: set[int] = collect_linked_object_ids(object_relations, target_id)
    linked_objects: dict[int, dict[str, Any]] = {}

    if linked_object_ids:
        cursor: list[dict[str, Any]] = list(objects_manager.find(
            criteria={'public_id': {'$in': list(linked_object_ids)}},
            limit=item_limit if item_limit_active else 0,
        ))
        linked_objects = _index_by_public_id(cursor)

    # 3. DirectionalEdges, skipping any object_relation whose linked object did not survive
    #    the item_limit cap on the linked-objects cursor
    directional_edges: list[tuple[Any, dict[str, Any]]] = []
    distinct_relation_neighbour_ids: set[int] = set()

    for obj_rel in object_relations:
        relation_doc: dict[str, Any] | None = relations_by_id.get(obj_rel['relation_id'])

        if relation_doc is None:
            continue

        directional_edge = split_object_relation_direction(obj_rel, target_id, relation_doc)

        if directional_edge is None:
            continue

        if directional_edge.linked_id not in linked_objects:
            continue

        directional_edges.append((directional_edge, relation_doc))
        distinct_relation_neighbour_ids.add(directional_edge.linked_id)

    # 4. Location grafting (one hop each direction; B1 + B2 fixes encoded in helpers)
    target_location: dict[str, Any] | None = None
    location_parent_object: dict[str, Any] | None = None
    location_children_objects: list[dict[str, Any]] = []
    remaining: int = max(0, item_limit - len(distinct_relation_neighbour_ids)) if item_limit_active else 0

    if with_locations:
        target_location = locations_manager.get_location_for_object(target_id)

        if target_location is not None:
            if include_children:
                location_parent_object = collect_location_parent_object(
                    target_location, types_filter, remaining, item_limit_active,
                    locations_manager, objects_manager,
                )

                if location_parent_object is not None and item_limit_active:
                    remaining -= 1  # B1 fix: spend exactly the slots we used

            if include_parents:
                location_children_objects = collect_location_children_objects(
                    target_location, types_filter, remaining, item_limit_active,
                    locations_manager, objects_manager,
                )

                if item_limit_active:
                    remaining = max(0, remaining - len(location_children_objects))

    # 5. IPAM relation grafting (one hop in each direction of the SUPERNET/SUBNET/VLAN/Interface
    # hierarchy; folded into the same parent/child buckets with metadata.source='ipam')
    ipam_neighbours: list[IpamNeighbour] = []

    if with_ipam_relations and root_object is not None:
        ipam_neighbours = collect_ipam_neighbours(
            target_id=target_id,
            target_object=root_object,
            include_parents=include_parents,
            include_children=include_children,
            types_filter=types_filter,
            remaining=remaining,
            item_limit_active=item_limit_active,
            objects_manager=objects_manager,
            types_manager=types_manager,
        )

    # 6. Bulk-load every CmdbType referenced by any in-scope object (single $in)
    in_scope_objects: list[dict[str, Any]] = []

    if root_object is not None:
        in_scope_objects.append(root_object)

    in_scope_objects.extend(linked_objects.values())

    if location_parent_object is not None:
        in_scope_objects.append(location_parent_object)

    in_scope_objects.extend(location_children_objects)
    in_scope_objects.extend(neighbour.neighbour_object for neighbour in ipam_neighbours)

    type_ids: set[int] = {
        obj['type_id'] for obj in in_scope_objects if isinstance(obj.get('type_id'), int)
    }

    types_by_id: dict[int, dict[str, Any]] = {}

    if type_ids:
        types_by_id = _index_by_public_id(list(
            types_manager.find(criteria={'public_id': {'$in': list(type_ids)}})
        ))

    # 6. Batched enrichment over the whole union (B4 + B5 + B6 wins all here)
    ref_ids, location_field_ids = collect_ref_and_location_ids(in_scope_objects, types_by_id)
    summary_lookup: dict[int, str] = build_summary_lookup(objects_manager, ref_ids)
    location_name_lookup: dict[int, str] = build_location_name_lookup(locations_manager, location_field_ids)

    enriched_by_id: dict[int, dict[str, Any]] = {}

    for obj in in_scope_objects:
        public_id: Any = obj.get('public_id')

        if not isinstance(public_id, int):
            continue

        enriched_by_id[public_id] = flatten_object_fields(
            obj, types_by_id, summary_lookup, location_name_lookup,
        )

    # 7. Composition pass
    response: dict[str, Any] = {}

    if with_root and root_object is not None:
        root_type_doc: dict[str, Any] | None = types_by_id.get(root_object.get('type_id'))
        enriched_root: dict[str, Any] | None = enriched_by_id.get(target_id)

        if root_type_doc is not None and enriched_root is not None:
            response['root_node'] = compose_node(enriched_root, root_type_doc, None)

    child_nodes_by_id: dict[int, dict[str, Any]] = {}
    parent_nodes_by_id: dict[int, dict[str, Any]] = {}
    child_edges: list[dict[str, Any]] = []
    parent_edges: list[dict[str, Any]] = []

    for directional_edge, relation_doc in directional_edges:
        type_doc: dict[str, Any] | None = types_by_id.get(directional_edge.linked_type_id)
        enriched_obj: dict[str, Any] | None = enriched_by_id.get(directional_edge.linked_id)

        if type_doc is None or enriched_obj is None:
            continue

        node: dict[str, Any] = compose_node(enriched_obj, type_doc, directional_edge.relation_color)
        edge: dict[str, Any] = compose_relation_edge(directional_edge, relation_doc)

        if directional_edge.linked_is_child:
            child_nodes_by_id[directional_edge.linked_id] = node
            child_edges.append(edge)
        else:
            parent_nodes_by_id[directional_edge.linked_id] = node
            parent_edges.append(edge)

    # Location-parent flips into the children bucket
    if location_parent_object is not None:
        loc_parent_id: int = location_parent_object['public_id']
        loc_parent_type_doc: dict[str, Any] | None = types_by_id.get(location_parent_object.get('type_id'))
        enriched_loc_parent: dict[str, Any] | None = enriched_by_id.get(loc_parent_id)

        if loc_parent_type_doc is not None and enriched_loc_parent is not None:
            child_nodes_by_id[loc_parent_id] = compose_node(
                enriched_loc_parent, loc_parent_type_doc, CHILD_LOCATION_REL_COLOR,
            )
            child_edges.append(compose_location_edge(target_id, loc_parent_id))

    # Location-children flip into the parent bucket
    for child_object in location_children_objects:
        loc_child_id: int = child_object['public_id']
        loc_child_type_doc: dict[str, Any] | None = types_by_id.get(child_object.get('type_id'))
        enriched_loc_child: dict[str, Any] | None = enriched_by_id.get(loc_child_id)

        if loc_child_type_doc is None or enriched_loc_child is None:
            continue

        parent_nodes_by_id[loc_child_id] = compose_node(
            enriched_loc_child, loc_child_type_doc, PARENT_LOCATION_REL_COLOR,
        )
        parent_edges.append(compose_location_edge(loc_child_id, target_id))

    # IPAM neighbours fold into the standard parent/child buckets; edges carry
    # metadata.source='ipam' so the FE can distinguish them from CmdbRelation edges
    for ipam_neighbour in ipam_neighbours:
        ipam_neighbour_id: int = ipam_neighbour.neighbour_object['public_id']
        ipam_type_doc: dict[str, Any] | None = types_by_id.get(
            ipam_neighbour.neighbour_object.get('type_id'),
        )
        enriched_ipam_obj: dict[str, Any] | None = enriched_by_id.get(ipam_neighbour_id)

        if ipam_type_doc is None or enriched_ipam_obj is None:
            continue

        ipam_node: dict[str, Any] = compose_node(
            enriched_ipam_obj, ipam_type_doc, IPAM_RELATION_COLOR,
        )

        if ipam_neighbour.is_child_of_target:
            child_nodes_by_id[ipam_neighbour_id] = ipam_node
            child_edges.append(compose_ipam_edge(
                target_id, ipam_neighbour_id, ipam_neighbour.edge_category, is_child_of_target=True,
            ))
        else:
            parent_nodes_by_id[ipam_neighbour_id] = ipam_node
            parent_edges.append(compose_ipam_edge(
                ipam_neighbour_id, target_id, ipam_neighbour.edge_category, is_child_of_target=False,
            ))

    if include_children:
        response['children_nodes'] = list(child_nodes_by_id.values())
        response['child_edges'] = child_edges

    if include_parents:
        response['parent_nodes'] = list(parent_nodes_by_id.values())
        response['parent_edges'] = parent_edges

    return response
