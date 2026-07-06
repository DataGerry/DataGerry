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
Object-relation graph helpers for the CI Explorer

Pure functions that build the Mongo criteria, index loaded documents, and split each
object_relation into a directional edge view relative to the target object. The Mongo
fetch itself stays in the framework (rather than the route) so the orchestrator owns
both query construction and execution in one place
"""
from dataclasses import dataclass
from typing import Any, Iterable

from cmdb.manager import ObjectRelationsManager
# -------------------------------------------------------------------------------------------------------------------- #


@dataclass(frozen=True)
class DirectionalEdge:
    """
    Direction-aware view of one object_relation relative to the focal target object

    The CI Explorer renders one bucket of nodes/edges per direction (target's parents and
    target's children). This dataclass captures the information needed to drop one
    object_relation into the right bucket without re-reading the underlying document:
    ``linked_is_child`` tells the caller which bucket to use, the other fields carry the
    edge endpoints and the side-specific labels/colors pulled from the parent CmdbRelation

    Attributes:
        linked_is_child: True when the linked object is the *child* of the target (the
            target is the parent in the object_relation); False when the linked object is
            the parent (target is the child)
        linked_id: public_id of the other end of the object_relation
        linked_type_id: type_id of the other end (used to look up type metadata for the node)
        edge_from: public_id of the edge source (always points child -> parent in the
            relation graph, so child_id when the target is parent, target_id when child)
        edge_to: public_id of the edge target
        relation_color: per-direction color from the CmdbRelation
            (relation_color_parent when linked_is_child, _child otherwise)
        edge_relation_name: per-direction display name from the CmdbRelation
        edge_relation_icon: per-direction icon from the CmdbRelation
    """
    linked_is_child: bool
    linked_id: int
    linked_type_id: int
    edge_from: int
    edge_to: int
    relation_color: str | None
    edge_relation_name: str | None
    edge_relation_icon: str | None


def build_relation_criteria(
    target_id: int,
    types_filter: frozenset[int],
    relations_filter: frozenset[int],
) -> dict[str, Any]:
    """
    Builds the Mongo $or criteria for object_relations touching ``target_id``

    The criteria is direction-aware: when ``types_filter`` is set, the *other* side's
    type_id is the one constrained, because the user wants to see neighbours of those
    types - not relations where the target happens to be of those types. ``relations_filter``
    is AND-combined as a top-level ``relation_id`` constraint

    Args:
        target_id (int): public_id of the focal CmdbObject
        types_filter (frozenset[int]): Allowed neighbour CmdbType public_ids; empty set
            disables type filtering
        relations_filter (frozenset[int]): Allowed CmdbRelation public_ids; empty set
            disables relation filtering

    Returns:
        dict[str, Any]: A Mongo criteria document with an ``$or`` over (target as parent,
            target as child) and optional ``relation_id`` ``$in`` clause
    """
    if types_filter:
        or_clauses: list[dict[str, Any]] = [
            {
                'relation_parent_id': target_id,
                'relation_child_type_id': {'$in': list(types_filter)},
            },
            {
                'relation_child_id': target_id,
                'relation_parent_type_id': {'$in': list(types_filter)},
            },
        ]
    else:
        or_clauses = [
            {'relation_parent_id': target_id},
            {'relation_child_id': target_id},
        ]

    criteria: dict[str, Any] = {'$or': or_clauses}

    if relations_filter:
        criteria['relation_id'] = {'$in': list(relations_filter)}

    return criteria


def load_object_relations(
    object_relations_manager: ObjectRelationsManager,
    criteria: dict[str, Any],
) -> list[dict[str, Any]]:
    """
    Materialises the object_relation cursor produced by ``criteria`` into a list

    Thin wrapper around the manager's ``find`` method. Lives here so that the orchestrator
    has a single source for object-relation loading (easier to swap out for batched /
    paginated loading later if needed)

    Args:
        object_relations_manager (ObjectRelationsManager): db interface for CmdbObjectRelations
        criteria (dict[str, Any]): Mongo criteria built by ``build_relation_criteria``

    Returns:
        list[dict[str, Any]]: Matched object_relation documents
    """
    return list(object_relations_manager.find(criteria=criteria))


def collect_relation_ids(object_relations: Iterable[dict[str, Any]]) -> set[int]:
    """
    Returns the distinct ``relation_id`` values referenced by a batch of object_relations

    Args:
        object_relations (Iterable[dict[str, Any]]): object_relation documents

    Returns:
        set[int]: Distinct CmdbRelation public_ids referenced
    """
    return {rel['relation_id'] for rel in object_relations}


def collect_linked_object_ids(
    object_relations: Iterable[dict[str, Any]],
    target_id: int,
) -> set[int]:
    """
    Returns the distinct public_ids of the linked (non-target) objects in the batch

    For each object_relation, the linked object is the side that is NOT ``target_id``.
    When ``target_id`` somehow appears on neither side, both ends are skipped (the
    criteria builder should never produce that case)

    Args:
        object_relations (Iterable[dict[str, Any]]): object_relation documents
        target_id (int): public_id of the focal object

    Returns:
        set[int]: Distinct public_ids of the linked objects
    """
    linked: set[int] = set()

    for rel in object_relations:
        if rel['relation_parent_id'] != target_id:
            linked.add(rel['relation_parent_id'])

        if rel['relation_child_id'] != target_id:
            linked.add(rel['relation_child_id'])

    return linked


def split_object_relation_direction(
    object_relation: dict[str, Any],
    target_id: int,
    relation_doc: dict[str, Any],
) -> DirectionalEdge | None:
    """
    Builds the directional view of a single object_relation relative to ``target_id``

    When the target is the relation's parent the linked object is the child (returned with
    ``linked_is_child=True``); when the target is the child, the linked object is the
    parent. If the target appears on neither side the helper returns None and the caller
    skips the row - this is a defensive guard against a malformed criteria, the public
    ``build_relation_criteria`` never produces it

    Edge endpoints follow the convention used by the route today: edges always carry
    parent->child semantics in the relation graph. When target is parent, edge goes
    ``target_id -> linked_id``; when target is child, it goes ``linked_id -> target_id``

    Args:
        object_relation (dict[str, Any]): A single object_relation document
        target_id (int): public_id of the focal object
        relation_doc (dict[str, Any]): The CmdbRelation document referenced by
            ``object_relation['relation_id']``; carries the per-direction colors / labels

    Returns:
        DirectionalEdge | None: The directional view, or None when the target does not
            appear on either side
    """
    if object_relation['relation_parent_id'] == target_id:
        return DirectionalEdge(
            linked_is_child=True,
            linked_id=object_relation['relation_child_id'],
            linked_type_id=object_relation['relation_child_type_id'],
            edge_from=target_id,
            edge_to=object_relation['relation_child_id'],
            relation_color=relation_doc.get('relation_color_parent'),
            edge_relation_name=relation_doc.get('relation_name_parent'),
            edge_relation_icon=relation_doc.get('relation_icon_parent'),
        )

    if object_relation['relation_child_id'] == target_id:
        return DirectionalEdge(
            linked_is_child=False,
            linked_id=object_relation['relation_parent_id'],
            linked_type_id=object_relation['relation_parent_type_id'],
            edge_from=object_relation['relation_parent_id'],
            edge_to=target_id,
            relation_color=relation_doc.get('relation_color_child'),
            edge_relation_name=relation_doc.get('relation_name_child'),
            edge_relation_icon=relation_doc.get('relation_icon_child'),
        )

    return None
