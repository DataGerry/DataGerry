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

Single entry point used by the ``/ci_explorer/items`` route. Loads every object in scope (root,
relation-linked, location-grafted, IPAM-grafted) in a small, fixed number of Mongo round trips, runs
the batched ref-field / dg_location enrichment once over the full union, then composes the response in
a single pass. Independent of Flask - it takes a ``CiExplorerGraphRequest`` plus a
``CiExplorerManagers`` bundle, and reports what it cannot build by raising rather than by aborting.

Three rules govern what comes out:

**The focal object must exist.** It is loaded first, whatever the flags say, and a missing one is a
``CiExplorerTargetNotFoundError`` the route turns into a 404. Returning an empty graph instead - which
would make a typo'd id indistinguishable from an isolated CI, and does
so with a 200.

**Nothing else is fatal, but nothing is silent either.** A neighbour whose CmdbType or enrichment is
missing is skipped, because half a graph is more useful than none - each skip is logged with the ids
involved, so a degraded graph can be recognised as one instead of being read as the truth. The focal
object's own type is the exception: without it there is no node to draw the neighbours around, so that
is a ``CiExplorerGraphBuildError``.

**Nothing the requesting user may not read is in the payload - nor counts against the cap.** The object ACL
lives on the CmdbType, so the types the user may not read are resolved once, before any source reads
(``access.load_denied_type_ids``): a denied focal object raises the same ``CiExplorerTargetNotFoundError`` as a
missing one before anything else is loaded, and every source keeps denied neighbours out of its own Mongo read
(``type_scope.NeighbourTypeScope``), so they spend none of the ``item_limit`` budget. A denied neighbour is
omitted silently - no placeholder, and no capped graph emptier than an uncapped one - because either would
confirm the existence of exactly what the ACL hides. The per-object pass over the loaded types still runs last,
as a safety net that costs no query. Passing no user disables the filter, the convention every manager here
follows.

**The neighbour cap is deterministic.** The linked-object read is sorted by public_id before the limit
is applied, so the same request returns the same subgraph twice; an unsorted ``limit`` returns natural
order, which MongoDB does not guarantee and which changes as documents are rewritten. Truncation is
logged, since the payload has no field that could report it.

Pipeline:
  1. Load the focal CmdbObject (always - see above), resolve the types the user may not read, and refuse a
     denied focal object before any source reads
  2. Build the object-relation criteria (the type scope on the other side's stamped type), fetch matching
     object_relations, fetch the referenced
     CmdbRelation documents, then bulk-fetch the linked CmdbObjects under the sorted cap
  3. Resolve each object_relation into a DirectionalEdge (which side the linked object is on, what
     colour / name / icon to display)
  4. When ``with_locations``, walk one hop in each direction of the dg_location tree, skipping branches
     the target_type excludes, and collect the raw owning CmdbObjects. The remaining budget for the
     second branch reflects the slots the first one spent
  5. When ``with_ipam_relations``, walk one hop in each direction of the IPAM SpecialType hierarchy
     (SUPERNET <-> SUBNET <-> VLAN/Interface) and collect the raw neighbour CmdbObjects
  5a. When ``with_port_connections``, walk the physical chain out of every cabled port of the focal
     object and collect the CIs its cables reach, patch panels included (see ``connections.py``)
  6. Bulk-fetch the CmdbType documents for every object in scope (single $in)
  6a. Re-check those types against the user's ACL and drop any object of a denied one from all four sources -
     the safety net behind the per-source exclusion of step 2-5a
  7. Run the batched enrichment once across the whole union: collect ref-field + dg_location ids, one
     $in lookup each, then flatten every object's fields
  8. Compose nodes (one builder for root, relation-linked, location-grafted and IPAM-grafted alike) and
     edges (relation / IPAM / location shapes). IPAM and location neighbours fold into the same
     parent/child buckets as relation neighbours, with ``metadata.source`` distinguishing them
  9. Assemble the response according to ``target_type`` (CHILD / PARENT / BOTH)

**Port connections are undirected**, so they have no parent side to fold into: every physical edge
lands in the children bucket carrying ``metadata.undirected: true``, and a request for parents only
gets none of them. A cable between two CIs is a fact about both, not a hierarchy.

**The location directions are inverted on purpose**: an object's location *parent* appears in the
children bucket and its location *children* in the parent bucket, because the graph reads
"contains" downwards while the location tree reads "is contained by" upwards. Two tests pin it
"""
from dataclasses import dataclass, field
from logging import Logger, getLogger
from typing import Any

from cmdb.framework.ci_explorer.access import (
    collect_denied_type_ids,
    filter_accessible_objects,
    is_denied,
    load_denied_type_ids,
)
from cmdb.framework.ci_explorer.type_scope import NeighbourTypeScope
from cmdb.framework.ci_explorer.context import CiExplorerGraphRequest, CiExplorerManagers
from cmdb.framework.ci_explorer.connections import (
    ConnectionNeighbour,
    ConnectionSourceManagers,
    collect_connection_neighbours,
)
from cmdb.framework.ci_explorer.edges import (
    compose_ipam_edge,
    compose_location_edge,
    compose_port_connection_edge,
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
from cmdb.framework.ci_explorer.connections import PORT_CONNECTION_RELATION_COLOR
from cmdb.framework.ci_explorer.nodes import compose_node
from cmdb.models.user_model import CmdbUser
from cmdb.framework.ci_explorer.relations import (
    build_relation_criteria,
    collect_linked_object_ids,
    collect_relation_ids,
    load_object_relations,
    split_object_relation_direction,
)

from cmdb.errors.ci_explorer import CiExplorerGraphBuildError, CiExplorerTargetNotFoundError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# Document keys read here. The graph reads documents of four collections, so these are spelled once
PUBLIC_ID_KEY: str = 'public_id'
TYPE_ID_KEY: str = 'type_id'
RELATION_ID_KEY: str = 'relation_id'

# Response keys of the payload the route returns
ROOT_NODE_KEY: str = 'root_node'
CHILDREN_NODES_KEY: str = 'children_nodes'
CHILD_EDGES_KEY: str = 'child_edges'
PARENT_NODES_KEY: str = 'parent_nodes'
PARENT_EDGES_KEY: str = 'parent_edges'


@dataclass
class GraphBuckets:
    """
    The four buckets a composed neighbour lands in

    Nodes are kept by public_id so the same object grafted twice - as a relation neighbour and as a
    location or IPAM neighbour - appears once, while its edges are kept in full
    """
    child_nodes_by_id: dict[int, dict[str, Any]] = field(default_factory=dict)
    parent_nodes_by_id: dict[int, dict[str, Any]] = field(default_factory=dict)
    child_edges: list[dict[str, Any]] = field(default_factory=list)
    parent_edges: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class RelationNeighbourhood:
    """
    Everything the object-relation branch produced

    Attributes:
        directional_edges: (DirectionalEdge, relation document) pairs that survived the cap
        linked_objects: The linked CmdbObjects by public_id
        distinct_neighbour_ids: The neighbours that count against the item_limit budget
    """
    directional_edges: list[tuple[Any, dict[str, Any]]] = field(default_factory=list)
    linked_objects: dict[int, dict[str, Any]] = field(default_factory=dict)
    distinct_neighbour_ids: set[int] = field(default_factory=set)


@dataclass
class LocationNeighbourhood:
    """
    Everything the dg_location branch produced, plus the budget it left behind

    Attributes:
        parent_object: The owning CmdbObject of the location one hop up, if any
        children_objects: The owning CmdbObjects of the locations one hop down
        remaining: Slots still available for the IPAM branch
    """
    parent_object: dict[str, Any] | None = None
    children_objects: list[dict[str, Any]] = field(default_factory=list)
    remaining: int = 0


@dataclass
class ConnectionNeighbourhood:
    """
    Everything the port-connectivity branch produced

    Attributes:
        neighbours: The CIs the focal object is cabled to, each with the cable that says so
        objects: Those CmdbObjects by public_id, already type-filtered
    """
    neighbours: list[ConnectionNeighbour] = field(default_factory=list)
    objects: dict[int, dict[str, Any]] = field(default_factory=dict)


def index_by_public_id(docs: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    """
    Indexes a list of documents by their integer ``public_id``

    Documents whose ``public_id`` is missing or not an integer are skipped and counted in one warning,
    so a partial or malformed batch never crashes the caller but never passes unnoticed either

    Args:
        docs (list[dict[str, Any]]): Documents pulled from one of the framework collections

    Returns:
        dict[int, dict[str, Any]]: {public_id: document}
    """
    indexed: dict[int, dict[str, Any]] = {
        doc[PUBLIC_ID_KEY]: doc for doc in docs if isinstance(doc.get(PUBLIC_ID_KEY), int)
    }

    if len(indexed) != len(docs):
        LOGGER.warning(
            "[ci_explorer] Skipped %s document(s) without a usable public_id", len(docs) - len(indexed),
        )

    return indexed


def load_relation_neighbourhood(
        request: CiExplorerGraphRequest,
        managers: CiExplorerManagers,
        type_scope: NeighbourTypeScope) -> RelationNeighbourhood:
    """
    Loads the object-relation branch: the relations, the linked objects and the directional edges

    The linked-object read is sorted by public_id before the cap is applied, so a truncated graph is
    the same truncated graph on every request. An object_relation whose linked object did not survive
    that cap is dropped together with its edge, and the drop is logged - the payload has no field that
    could report a partial graph

    Args:
        request (CiExplorerGraphRequest): What the caller asked for
        managers (CiExplorerManagers): The managers to read through
        type_scope (NeighbourTypeScope): The types a neighbour may be of - applied to the relations' stamped
            types and to the linked-object read, both before the cap

    Returns:
        RelationNeighbourhood: The edges, the linked objects and the neighbours that count against
            the item_limit
    """
    criteria: dict[str, Any] = build_relation_criteria(
        request.target_id, type_scope, request.relations_filter,
    )
    object_relations: list[dict[str, Any]] = load_object_relations(managers.object_relations, criteria)

    relation_ids: set[int] = collect_relation_ids(object_relations)
    relations_by_id: dict[int, dict[str, Any]] = {}

    if relation_ids:
        relations_by_id = index_by_public_id(list(
            managers.relations.find(criteria={PUBLIC_ID_KEY: {'$in': list(relation_ids)}})
        ))

    linked_object_ids: set[int] = collect_linked_object_ids(object_relations, request.target_id)
    linked_objects: dict[int, dict[str, Any]] = {}

    if linked_object_ids:
        linked_objects = index_by_public_id(list(managers.objects.find(
            criteria={PUBLIC_ID_KEY: {'$in': sorted(linked_object_ids)}, **type_scope.object_criteria()},
            sort=[(PUBLIC_ID_KEY, 1)],
            limit=request.item_limit if request.item_limit_active else 0,
        )))

        if len(linked_objects) < len(linked_object_ids):
            LOGGER.warning(
                "[ci_explorer] Graph of object %s truncated: %s of %s relation neighbours shown",
                request.target_id, len(linked_objects), len(linked_object_ids),
            )

    neighbourhood = RelationNeighbourhood(linked_objects=linked_objects)

    for object_relation in object_relations:
        relation_doc: dict[str, Any] | None = relations_by_id.get(object_relation[RELATION_ID_KEY])

        if relation_doc is None:
            LOGGER.warning(
                "[ci_explorer] ObjectRelation %s references missing Relation %s - edge omitted",
                object_relation.get(PUBLIC_ID_KEY), object_relation.get(RELATION_ID_KEY),
            )
            continue

        directional_edge = split_object_relation_direction(object_relation, request.target_id, relation_doc)

        if directional_edge is None:
            LOGGER.warning(
                "[ci_explorer] ObjectRelation %s names neither side as object %s - edge omitted",
                object_relation.get(PUBLIC_ID_KEY), request.target_id,
            )
            continue

        if directional_edge.linked_id not in linked_objects:
            # Its neighbour lost the item_limit cap; the truncation itself is logged above
            continue

        neighbourhood.directional_edges.append((directional_edge, relation_doc))
        neighbourhood.distinct_neighbour_ids.add(directional_edge.linked_id)

    return neighbourhood


def load_location_neighbourhood(
        request: CiExplorerGraphRequest,
        managers: CiExplorerManagers,
        remaining: int,
        type_scope: NeighbourTypeScope) -> LocationNeighbourhood:
    """
    Loads the dg_location branch: one hop up, one hop down, within the remaining budget

    The directions are inverted on purpose - the location *parent* is collected for the children
    bucket and the location *children* for the parent bucket - which is why the include flags read the
    way round they do here

    Args:
        request (CiExplorerGraphRequest): What the caller asked for
        managers (CiExplorerManagers): The managers to read through
        remaining (int): Slots left after the relation branch
        type_scope (NeighbourTypeScope): The types a neighbour may be of

    Returns:
        LocationNeighbourhood: The grafted objects and the budget left for the IPAM branch
    """
    neighbourhood = LocationNeighbourhood(remaining=remaining)

    if not request.with_locations:
        return neighbourhood

    target_location: dict[str, Any] | None = managers.locations.get_location_for_object(request.target_id)

    if target_location is None:
        return neighbourhood

    if request.include_children:
        neighbourhood.parent_object = collect_location_parent_object(
            target_location, type_scope, neighbourhood.remaining, request.item_limit_active,
            managers.locations, managers.objects,
        )

        if neighbourhood.parent_object is not None and request.item_limit_active:
            neighbourhood.remaining -= 1  # Spend exactly the slots used

    if request.include_parents:
        neighbourhood.children_objects = collect_location_children_objects(
            target_location, type_scope, neighbourhood.remaining, request.item_limit_active,
            managers.locations, managers.objects,
        )

        if request.item_limit_active:
            neighbourhood.remaining = max(0, neighbourhood.remaining - len(neighbourhood.children_objects))

    return neighbourhood


def enrich_in_scope_objects(
        in_scope_objects: list[dict[str, Any]],
        types_by_id: dict[int, dict[str, Any]],
        managers: CiExplorerManagers) -> dict[int, dict[str, Any]]:
    """
    Runs the batched enrichment once over every object in scope

    One $in lookup for the referenced objects' summaries and one for the dg_location names, then a
    flatten per object - which is what keeps the whole graph at a fixed number of round trips

    Args:
        in_scope_objects (list[dict[str, Any]]): Root, relation, location and IPAM objects together
        types_by_id (dict[int, dict[str, Any]]): The CmdbTypes of those objects
        managers (CiExplorerManagers): The managers to read through

    Returns:
        dict[int, dict[str, Any]]: {public_id: enriched object}
    """
    ref_ids, location_field_ids = collect_ref_and_location_ids(in_scope_objects, types_by_id)
    summary_lookup: dict[int, str] = build_summary_lookup(managers.objects, ref_ids)
    location_name_lookup: dict[int, str] = build_location_name_lookup(managers.locations, location_field_ids)

    enriched_by_id: dict[int, dict[str, Any]] = {}

    for obj in in_scope_objects:
        public_id: Any = obj.get(PUBLIC_ID_KEY)

        if not isinstance(public_id, int):
            LOGGER.warning("[ci_explorer] Object without a usable public_id omitted from the graph")
            continue

        enriched_by_id[public_id] = flatten_object_fields(
            obj, types_by_id, summary_lookup, location_name_lookup,
        )

    return enriched_by_id


def resolve_composable(
        document: dict[str, Any],
        types_by_id: dict[int, dict[str, Any]],
        enriched_by_id: dict[int, dict[str, Any]],
        role: str) -> tuple[int, dict[str, Any], dict[str, Any]] | None:
    """
    Resolves the three things a node needs, or reports why it cannot be composed

    The public_id is read with ``.get`` on purpose: the enrichment pass already tolerates a document
    without one, and the compose passes must not dereference it with ``[]`` - a single malformed
    neighbour took the whole request down with a 500 one step after being deliberately skipped.

    Args:
        document (dict[str, Any]): The neighbour's raw CmdbObject document
        types_by_id (dict[int, dict[str, Any]]): The CmdbTypes of the in-scope objects
        enriched_by_id (dict[int, dict[str, Any]]): The enriched objects by public_id
        role (str): What this neighbour is, used in the warning ('Relation neighbour', ...)

    Returns:
        tuple[int, dict[str, Any], dict[str, Any]] | None: (public_id, type document, enriched
            object), or None when the neighbour has to be skipped
    """
    public_id: Any = document.get(PUBLIC_ID_KEY)

    if not isinstance(public_id, int):
        LOGGER.warning("[ci_explorer] %s omitted: no usable public_id", role)
        return None

    type_doc: dict[str, Any] | None = types_by_id.get(document.get(TYPE_ID_KEY))
    enriched: dict[str, Any] | None = enriched_by_id.get(public_id)

    if type_doc is None or enriched is None:
        LOGGER.warning(
            "[ci_explorer] %s %s omitted: no %s",
            role, public_id, 'CmdbType' if type_doc is None else 'enriched object',
        )
        return None

    return public_id, type_doc, enriched


def load_connection_neighbourhood(
        request: CiExplorerGraphRequest,
        managers: CiExplorerManagers,
        remaining: int,
        type_scope: NeighbourTypeScope) -> ConnectionNeighbourhood:
    """
    Loads the port-connectivity branch: the CIs the focal object is physically cabled to

    A no-op unless the caller asked for it AND the direction it belongs to was requested. Port
    connections are undirected and ride in the children bucket, so a parents-only request skips the
    source entirely rather than returning edges the response has nowhere to put.

    The three managers it needs are optional on the bundle, because the route resolves them only for
    this flag - a bundle missing them is treated as the flag being off rather than as an error, so an
    internal caller cannot get a 500 out of not knowing about a licensed source

    Args:
        request (CiExplorerGraphRequest): What the caller asked for
        managers (CiExplorerManagers): The managers to read through
        remaining (int): Slots left after the relation, location and IPAM branches
        type_scope (NeighbourTypeScope): The types a neighbour may be of

    Returns:
        ConnectionNeighbourhood: The neighbours with their collapsed physical paths, and the
            far-side CmdbObjects by public_id
    """
    if not request.with_port_connections or not request.include_children:
        return ConnectionNeighbourhood()

    if managers.ports is None or managers.port_connections is None or managers.extendable_options is None:
        LOGGER.warning(
            "[ci_explorer] with_port_connections was requested without the managers it reads through",
        )
        return ConnectionNeighbourhood()

    neighbours, neighbour_objects = collect_connection_neighbours(
        target_id=request.target_id,
        type_scope=type_scope,
        remaining=remaining,
        item_limit_active=request.item_limit_active,
        managers=ConnectionSourceManagers(
            ports=managers.ports,
            connections=managers.port_connections,
            objects=managers.objects,
            extendable_options=managers.extendable_options,
        ),
    )

    return ConnectionNeighbourhood(neighbours=neighbours, objects=neighbour_objects)


def compose_connection_buckets(
        request: CiExplorerGraphRequest,
        neighbourhood: ConnectionNeighbourhood,
        types_by_id: dict[int, dict[str, Any]],
        enriched_by_id: dict[int, dict[str, Any]],
        buckets: GraphBuckets) -> None:
    """
    Composes the physically connected CIs into the children bucket, in place

    Their edges carry ``metadata.source='port_connection'`` and ``metadata.undirected=true``, so the
    frontend renders them without an arrowhead while every existing client keeps reading the same two
    buckets. One connection is one edge: two objects cabled twice appear as one node and two edges

    Args:
        request (CiExplorerGraphRequest): What the caller asked for
        neighbourhood (ConnectionNeighbourhood): What the physical walk resolved
        types_by_id (dict[int, dict[str, Any]]): The CmdbTypes of the in-scope objects
        enriched_by_id (dict[int, dict[str, Any]]): The enriched objects by public_id
        buckets (GraphBuckets): The buckets to fill
    """
    for neighbour in neighbourhood.neighbours:
        neighbour_object: dict[str, Any] | None = neighbourhood.objects.get(neighbour.neighbour_object_id)

        if neighbour_object is None:
            continue

        composable = resolve_composable(
            neighbour_object, types_by_id, enriched_by_id, 'Port-connection neighbour',
        )

        if composable is None:
            continue

        neighbour_id, type_doc, enriched_obj = composable
        buckets.child_nodes_by_id[neighbour_id] = compose_node(
            enriched_obj, type_doc, PORT_CONNECTION_RELATION_COLOR,
        )
        buckets.child_edges.append(compose_port_connection_edge(
            request.target_id, neighbour_id, neighbour.path,
        ))


def drop_denied_neighbours(
        relation_neighbourhood: RelationNeighbourhood,
        location_neighbourhood: LocationNeighbourhood,
        ipam_neighbours: list[IpamNeighbour],
        denied_type_ids: set[int]) -> list[IpamNeighbour]:
    """
    Removes every neighbour of an ACL-denied CmdbType from all three sources - the safety net

    The sources already kept denied neighbours out of their reads (``type_scope.NeighbourTypeScope``), so on an
    ordinary request this removes nothing. It re-checks the types actually loaded, before the enrichment, so an
    ACL changed between the two reads still never puts a denied neighbour in the payload. The relation edges are
    dropped alongside their objects: an edge whose far end is not in the payload would draw a line to nothing.

    The two neighbourhoods are dataclasses owned by this module and are filtered **in place**, while
    the IPAM neighbours arrive as a plain list and are returned filtered - hence the asymmetry in the
    signature.

    Args:
        relation_neighbourhood (RelationNeighbourhood): The object-relation branch, filtered in place
        location_neighbourhood (LocationNeighbourhood): The dg_location branch, filtered in place
        ipam_neighbours (list[IpamNeighbour]): The IPAM branch
        denied_type_ids (set[int]): public_ids of the CmdbTypes the user may not read

    Returns:
        list[IpamNeighbour]: The IPAM neighbours that survived the filter
    """
    relation_neighbourhood.directional_edges = [
        (directional_edge, relation_doc)
        for directional_edge, relation_doc in relation_neighbourhood.directional_edges
        if not is_denied(relation_neighbourhood.linked_objects[directional_edge.linked_id], denied_type_ids)
    ]
    relation_neighbourhood.linked_objects = {
        linked_id: linked_object
        for linked_id, linked_object in relation_neighbourhood.linked_objects.items()
        if not is_denied(linked_object, denied_type_ids)
    }

    if location_neighbourhood.parent_object is not None and is_denied(
            location_neighbourhood.parent_object, denied_type_ids):
        location_neighbourhood.parent_object = None

    location_neighbourhood.children_objects = [
        child_object for child_object in location_neighbourhood.children_objects
        if not is_denied(child_object, denied_type_ids)
    ]

    return [
        ipam_neighbour for ipam_neighbour in ipam_neighbours
        if not is_denied(ipam_neighbour.neighbour_object, denied_type_ids)
    ]


def compose_relation_buckets(
        neighbourhood: RelationNeighbourhood,
        types_by_id: dict[int, dict[str, Any]],
        enriched_by_id: dict[int, dict[str, Any]],
        buckets: GraphBuckets) -> None:
    """
    Composes the relation neighbours into the parent / child buckets, in place

    Args:
        neighbourhood (RelationNeighbourhood): The directional edges to compose
        types_by_id (dict[int, dict[str, Any]]): The CmdbTypes of the in-scope objects
        enriched_by_id (dict[int, dict[str, Any]]): The enriched objects by public_id
        buckets (GraphBuckets): The buckets to fill
    """
    for directional_edge, relation_doc in neighbourhood.directional_edges:
        composable = resolve_composable(
            neighbourhood.linked_objects[directional_edge.linked_id],
            types_by_id,
            enriched_by_id,
            'Relation neighbour',
        )

        if composable is None:
            continue

        _linked_id, type_doc, enriched_obj = composable
        node: dict[str, Any] = compose_node(enriched_obj, type_doc, directional_edge.relation_color)
        edge: dict[str, Any] = compose_relation_edge(directional_edge, relation_doc)

        if directional_edge.linked_is_child:
            buckets.child_nodes_by_id[directional_edge.linked_id] = node
            buckets.child_edges.append(edge)
        else:
            buckets.parent_nodes_by_id[directional_edge.linked_id] = node
            buckets.parent_edges.append(edge)


def compose_location_buckets(
        request: CiExplorerGraphRequest,
        neighbourhood: LocationNeighbourhood,
        types_by_id: dict[int, dict[str, Any]],
        enriched_by_id: dict[int, dict[str, Any]],
        buckets: GraphBuckets) -> None:
    """
    Composes the dg_location neighbours into the buckets, in place, with the directions inverted

    The location parent lands in the CHILDREN bucket and the location children in the PARENT bucket:
    the graph reads "contains" downwards while the location tree reads "is contained by" upwards

    Args:
        request (CiExplorerGraphRequest): What the caller asked for
        neighbourhood (LocationNeighbourhood): The grafted location objects
        types_by_id (dict[int, dict[str, Any]]): The CmdbTypes of the in-scope objects
        enriched_by_id (dict[int, dict[str, Any]]): The enriched objects by public_id
        buckets (GraphBuckets): The buckets to fill
    """
    if neighbourhood.parent_object is not None:
        composable = resolve_composable(
            neighbourhood.parent_object, types_by_id, enriched_by_id, 'Location parent',
        )

        if composable is not None:
            parent_id, parent_type_doc, enriched_parent = composable
            buckets.child_nodes_by_id[parent_id] = compose_node(
                enriched_parent, parent_type_doc, CHILD_LOCATION_REL_COLOR,
            )
            buckets.child_edges.append(compose_location_edge(request.target_id, parent_id))

    for child_object in neighbourhood.children_objects:
        composable = resolve_composable(child_object, types_by_id, enriched_by_id, 'Location child')

        if composable is None:
            continue

        child_id, child_type_doc, enriched_child = composable
        buckets.parent_nodes_by_id[child_id] = compose_node(
            enriched_child, child_type_doc, PARENT_LOCATION_REL_COLOR,
        )
        buckets.parent_edges.append(compose_location_edge(child_id, request.target_id))


def compose_ipam_buckets(
        request: CiExplorerGraphRequest,
        ipam_neighbours: list[IpamNeighbour],
        types_by_id: dict[int, dict[str, Any]],
        enriched_by_id: dict[int, dict[str, Any]],
        buckets: GraphBuckets) -> None:
    """
    Composes the IPAM neighbours into the standard parent / child buckets, in place

    Their edges carry ``metadata.source='ipam'`` so the frontend can tell them from CmdbRelation edges

    Args:
        request (CiExplorerGraphRequest): What the caller asked for
        ipam_neighbours (list[IpamNeighbour]): The neighbours the IPAM walk found
        types_by_id (dict[int, dict[str, Any]]): The CmdbTypes of the in-scope objects
        enriched_by_id (dict[int, dict[str, Any]]): The enriched objects by public_id
        buckets (GraphBuckets): The buckets to fill
    """
    for ipam_neighbour in ipam_neighbours:
        composable = resolve_composable(
            ipam_neighbour.neighbour_object, types_by_id, enriched_by_id, 'IPAM neighbour',
        )

        if composable is None:
            continue

        neighbour_id, type_doc, enriched_obj = composable
        node: dict[str, Any] = compose_node(enriched_obj, type_doc, IPAM_RELATION_COLOR)

        if ipam_neighbour.is_child_of_target:
            buckets.child_nodes_by_id[neighbour_id] = node
            buckets.child_edges.append(compose_ipam_edge(
                request.target_id, neighbour_id, ipam_neighbour.edge_category, is_child_of_target=True,
            ))
        else:
            buckets.parent_nodes_by_id[neighbour_id] = node
            buckets.parent_edges.append(compose_ipam_edge(
                neighbour_id, request.target_id, ipam_neighbour.edge_category, is_child_of_target=False,
            ))


def load_types_in_scope(
        in_scope_objects: list[dict[str, Any]],
        managers: CiExplorerManagers) -> dict[int, dict[str, Any]]:
    """
    Bulk-fetches the CmdbType of every object in scope in a single ``$in``

    One read for root, relation, location, IPAM and port-connection objects together - which is what
    keeps the graph at a fixed number of round trips however many neighbours it draws

    Args:
        in_scope_objects (list[dict[str, Any]]): Every CmdbObject the response may contain
        managers (CiExplorerManagers): The managers to read through

    Returns:
        dict[int, dict[str, Any]]: {public_id: CmdbType document}
    """
    type_ids: set[int] = {
        obj[TYPE_ID_KEY] for obj in in_scope_objects if isinstance(obj.get(TYPE_ID_KEY), int)
    }

    if not type_ids:
        return {}

    return index_by_public_id(list(
        managers.types.find(criteria={PUBLIC_ID_KEY: {'$in': sorted(type_ids)}})
    ))


def compose_root_node(
        request: CiExplorerGraphRequest,
        root_object: dict[str, Any],
        types_by_id: dict[int, dict[str, Any]],
        enriched_by_id: dict[int, dict[str, Any]]) -> dict[str, Any]:
    """
    Composes the ``root_node`` block for the focal object

    The one place where a missing piece is fatal rather than skipped: every other node can be left
    out and still leave a useful graph, but a graph asked for ``with_root`` and answered without one
    is not the graph that was requested

    Args:
        request (CiExplorerGraphRequest): What the caller asked for
        root_object (dict[str, Any]): The focal CmdbObject document
        types_by_id (dict[int, dict[str, Any]]): The CmdbTypes of the in-scope objects
        enriched_by_id (dict[int, dict[str, Any]]): The enriched objects by public_id

    Raises:
        CiExplorerGraphBuildError: If the focal object's CmdbType or enriched form is missing

    Returns:
        dict[str, Any]: The composed root node
    """
    root_type_doc: dict[str, Any] | None = types_by_id.get(root_object.get(TYPE_ID_KEY))
    enriched_root: dict[str, Any] | None = enriched_by_id.get(request.target_id)

    if root_type_doc is None or enriched_root is None:
        raise CiExplorerGraphBuildError(
            f"The CmdbType of object ID:{request.target_id} is missing, so the graph has no root node!"
        )

    return compose_node(enriched_root, root_type_doc, None)


def remaining_budget(request: CiExplorerGraphRequest, available: int, spent: int) -> int:
    """
    The neighbour slots a source leaves to the next one

    Args:
        request (CiExplorerGraphRequest): What the caller asked for
        available (int): The slots the source started with
        spent (int): The readable neighbours it took

    Returns:
        int: What is left, never below 0; 0 when no cap applies (the sources then ignore it)
    """
    return max(0, available - spent) if request.item_limit_active else 0


def assert_target_readable(
        request: CiExplorerGraphRequest,
        root_object: dict[str, Any],
        denied_type_ids: set[int] | frozenset[int]) -> None:
    """
    Refuses a focal object of a type the user may not read - with the error a missing object raises

    Args:
        request (CiExplorerGraphRequest): What the caller asked for
        root_object (dict[str, Any]): The focal CmdbObject
        denied_type_ids (set[int] | frozenset[int]): The types the user may not read

    Raises:
        CiExplorerTargetNotFoundError: If the focal object is of a denied type - deliberately the same error a
            missing object raises, since a 403 would confirm it exists
    """
    if is_denied(root_object, denied_type_ids):
        raise CiExplorerTargetNotFoundError(
            f"The ACL denies read access to the CmdbObject with ID:{request.target_id}!"
        )


def resolve_type_scope(
        request: CiExplorerGraphRequest,
        managers: CiExplorerManagers,
        root_object: dict[str, Any],
        user: CmdbUser | None) -> NeighbourTypeScope:
    """
    Resolves the types the user may not read, refuses a hidden focal object, and answers the sources' type scope

    Runs before any source reads: a hidden target then costs one type query rather than every source's reads,
    and the scope keeps denied neighbours out of every source's read, so they spend none of the item_limit budget

    Args:
        request (CiExplorerGraphRequest): What the caller asked for
        managers (CiExplorerManagers): The managers to read through
        root_object (dict[str, Any]): The focal CmdbObject
        user (CmdbUser | None): The CmdbUser the graph is built for; None disables access control

    Raises:
        CiExplorerTargetNotFoundError: If the focal object is of a type the user may not read

    Returns:
        NeighbourTypeScope: The caller's types filter, and the types they may not read
    """
    denied_type_ids: frozenset[int] = load_denied_type_ids(managers.types, user)
    assert_target_readable(request, root_object, denied_type_ids)

    return NeighbourTypeScope(allowed=request.types_filter, denied=denied_type_ids)


def build_ci_explorer_graph(
        request: CiExplorerGraphRequest,
        managers: CiExplorerManagers,
        user: CmdbUser | None = None) -> dict[str, Any]:
    """
    Builds the full node/edge payload for the CI Explorer graph view

    See the module docstring for the pipeline and the four rules that govern the output

    Args:
        request (CiExplorerGraphRequest): What the caller asked for
        managers (CiExplorerManagers): The managers to read through
        user (CmdbUser | None): The CmdbUser the graph is built for, whose group's ACL decides which
            objects may appear. None disables access control, matching ``acl/helpers.verify_access``

    Raises:
        CiExplorerTargetNotFoundError: If no CmdbObject carries the requested target_id, or if the
            user's ACL denies the focal object - the two are deliberately indistinguishable
        CiExplorerGraphBuildError: If the focal object's CmdbType is missing, leaving no root node

    Returns:
        dict[str, Any]: The response envelope; which keys are present depends on ``target_type`` and
            ``with_root``
    """
    root_object: dict[str, Any] | None = managers.objects.get_object(request.target_id)

    if root_object is None:
        raise CiExplorerTargetNotFoundError(
            f"No CmdbObject with ID:{request.target_id} to build a CI Explorer graph for!"
        )

    type_scope: NeighbourTypeScope = resolve_type_scope(request, managers, root_object, user)

    relation_neighbourhood: RelationNeighbourhood = load_relation_neighbourhood(request, managers, type_scope)

    location_neighbourhood: LocationNeighbourhood = load_location_neighbourhood(
        request, managers,
        remaining_budget(request, request.item_limit, len(relation_neighbourhood.distinct_neighbour_ids)),
        type_scope,
    )

    ipam_neighbours: list[IpamNeighbour] = []

    if request.with_ipam_relations:
        ipam_neighbours = collect_ipam_neighbours(
            target_id=request.target_id,
            target_object=root_object,
            include_parents=request.include_parents,
            include_children=request.include_children,
            type_scope=type_scope,
            remaining=location_neighbourhood.remaining,
            item_limit_active=request.item_limit_active,
            objects_manager=managers.objects,
            types_manager=managers.types,
        )

    connection_neighbourhood: ConnectionNeighbourhood = load_connection_neighbourhood(
        request, managers, remaining_budget(request, location_neighbourhood.remaining, len(ipam_neighbours)),
        type_scope,
    )

    in_scope_objects: list[dict[str, Any]] = [root_object]
    in_scope_objects.extend(relation_neighbourhood.linked_objects.values())

    if location_neighbourhood.parent_object is not None:
        in_scope_objects.append(location_neighbourhood.parent_object)

    in_scope_objects.extend(location_neighbourhood.children_objects)
    in_scope_objects.extend(neighbour.neighbour_object for neighbour in ipam_neighbours)
    in_scope_objects.extend(connection_neighbourhood.objects.values())

    types_by_id: dict[int, dict[str, Any]] = load_types_in_scope(in_scope_objects, managers)

    # The safety net behind the per-source exclusion: the same rule over the types actually loaded, no query
    loaded_denied_type_ids: set[int] = collect_denied_type_ids(types_by_id, user)

    if loaded_denied_type_ids:
        assert_target_readable(request, root_object, loaded_denied_type_ids)
        ipam_neighbours = drop_denied_neighbours(
            relation_neighbourhood, location_neighbourhood, ipam_neighbours, loaded_denied_type_ids,
        )
        connection_neighbourhood.objects = {
            neighbour_id: neighbour_object
            for neighbour_id, neighbour_object in connection_neighbourhood.objects.items()
            if not is_denied(neighbour_object, loaded_denied_type_ids)
        }
        in_scope_objects = filter_accessible_objects(in_scope_objects, loaded_denied_type_ids)

    enriched_by_id: dict[int, dict[str, Any]] = enrich_in_scope_objects(
        in_scope_objects, types_by_id, managers,
    )

    response: dict[str, Any] = {}

    if request.with_root:
        response[ROOT_NODE_KEY] = compose_root_node(request, root_object, types_by_id, enriched_by_id)

    buckets = GraphBuckets()

    compose_relation_buckets(relation_neighbourhood, types_by_id, enriched_by_id, buckets)
    compose_location_buckets(request, location_neighbourhood, types_by_id, enriched_by_id, buckets)
    compose_ipam_buckets(request, ipam_neighbours, types_by_id, enriched_by_id, buckets)
    compose_connection_buckets(request, connection_neighbourhood, types_by_id, enriched_by_id, buckets)

    if request.include_children:
        response[CHILDREN_NODES_KEY] = list(buckets.child_nodes_by_id.values())
        response[CHILD_EDGES_KEY] = buckets.child_edges

    if request.include_parents:
        response[PARENT_NODES_KEY] = list(buckets.parent_nodes_by_id.values())
        response[PARENT_EDGES_KEY] = buckets.parent_edges

    return response
