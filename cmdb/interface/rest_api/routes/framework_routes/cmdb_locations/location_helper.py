# DataGerry - OpenSource Enterprise CMDB
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
Helper methods shared by the CmdbLocation REST routes
"""
from logging import Logger, getLogger
from typing import Any

from flask import abort

from cmdb.manager import ObjectsManager, LocationsManager

from cmdb.models.object_model import CmdbObject, CmdbObjectFieldKey
from cmdb.models.type_model.cmdb_type import CmdbType
from cmdb.models.type_model.field_type_enum import FieldType
from cmdb.models.user_model import CmdbUser
from cmdb.models.location_model.location_node import LocationNode
from cmdb.framework.rendering.render_list import RenderList
from cmdb.framework.rendering.render_result import RenderResult
from cmdb.models.location_model.location_constants import RootLocationDefault, LocationKey

from cmdb.interface.rest_api.routes.framework_routes.cmdb_locations.location_constants import (
    OBJECT_ID_NAME_TEMPLATE,
    LOCATION_TREE_HAS_CHILDREN_KEY,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# CmdbLocation keys the lazy tree nodes omit - the frontend tree does not use them. type_selectable
# is intentionally KEPT so a drag-and-drop can gray out nodes that are not selectable as a parent
_TRIMMED_LOCATION_NODE_KEYS: frozenset[str] = frozenset({
    LocationKey.TYPE_ID.value,
    LocationKey.TYPE_LABEL.value,
})


def parse_required_int(data: dict[str, Any], key: str) -> int:
    """
    Reads a required integer field from a request body, aborting 400 when missing or malformed

    Keeps a bad/missing client parameter a 400 (client error) instead of letting the KeyError /
    ValueError fall through to the route's generic handler and surface as a 500

    Args:
        data (dict[str, Any]): The parsed request body
        key (str): The required field name to read and coerce to int

    Raises:
        HTTPException: 400 when the key is absent or its value is not an integer

    Returns:
        int: The integer value of ``data[key]``
    """
    try:
        return int(data[key])
    except (KeyError, ValueError, TypeError):
        abort(400, f"Missing or malformed Location parameter: '{key}'!")


def resolve_location_name(
        raw_name: str | None,
        object_id: int,
        objects_manager: ObjectsManager,
        request_user: CmdbUser) -> str:
    """
    Resolves the display name for a CmdbLocation

    When the request provides an explicit name it is used as-is. Otherwise the name is derived
    from the linked CmdbObject's rendered summary line, falling back to ``ObjectID: <id>`` when
    that summary line is also empty

    Args:
        raw_name (str | None): The name supplied in the request payload (may be empty or None)
        object_id (int): public_id of the linked CmdbObject
        objects_manager (ObjectsManager): Manager used to load the linked CmdbObject
        request_user (CmdbUser): User requesting the operation (used for rendering)

    Raises:
        HTTPException: Aborts with 404 if the linked CmdbObject must be rendered but does not exist

    Returns:
        str: The resolved CmdbLocation name
    """
    if raw_name not in ['', None]:
        return raw_name

    current_object = objects_manager.get_object(object_id)

    if not current_object:
        abort(404, "The linked Object was not found in the database!")

    current_object = CmdbObject.from_data(current_object)

    rendered_list: list[RenderResult] = RenderList(
        [current_object],
        request_user,
        True,
    ).render_result_list(raw=True)

    resolved_name: str | None = rendered_list[0]['summary_line']

    if resolved_name not in ['', None]:
        return resolved_name

    return OBJECT_ID_NAME_TEMPLATE.format(object_id=object_id)


def _annotate_has_children(nodes: list[dict[str, Any]], parents_with_children: set[int]) -> None:
    """
    Recursively adds a ``has_children`` flag to every node of a serialized location forest

    The flag reflects whether the node has any direct child in the FULL tree (not merely in the
    pruned forest), so a search result can tell the frontend a shown node still has children to
    expand even when they were filtered out. Mutates the nodes in place

    Args:
        nodes (list[dict[str, Any]]): Serialized location nodes (each may carry a ``children`` list)
        parents_with_children (set[int]): public_ids known to have at least one direct child
    """
    for node in nodes:
        node[LOCATION_TREE_HAS_CHILDREN_KEY] = node[LocationKey.PUBLIC_ID.value] in parents_with_children

        child_nodes: list[dict[str, Any]] = node.get('children', [])

        if child_nodes:
            _annotate_has_children(child_nodes, parents_with_children)


def build_location_forest(
        locations: list[dict[str, Any]],
        parents_with_children: set[int] | None = None) -> list[dict[str, Any]]:
    """
    Assembles a flat list of CmdbLocation dicts into a nested location forest

    Locations whose ``parent`` is the root id become the roots of the forest; every other
    location is attached beneath its parent via ``LocationNode`` (which guards against parent
    cycles). Each root is then serialized to a nested, JSON-compatible dict. When
    ``parents_with_children`` is supplied (e.g. for the pruned search forest) every node also gets a
    ``has_children`` flag telling whether it has direct children in the FULL tree, even ones the
    prune left out

    Args:
        locations (list[dict[str, Any]]): Flat list of CmdbLocation dicts (e.g. from ``to_json``)
        parents_with_children (set[int] | None): public_ids that have at least one direct child in
            the full tree; when given, each node is annotated with ``has_children``

    Returns:
        list[dict[str, Any]]: The root locations serialized as nested trees
    """
    root_locations: list[LocationNode] = []
    descendant_locations: list[dict[str, Any]] = []

    for location in locations:
        if location['parent'] == RootLocationDefault.PUBLIC_ID:
            root_locations.append(LocationNode(location))
        else:
            descendant_locations.append(location)

    for root_location in root_locations:
        root_location.children = root_location.get_children(root_location.public_id, descendant_locations)

    forest: list[dict[str, Any]] = [LocationNode.to_json(root_location) for root_location in root_locations]

    if parents_with_children is not None:
        _annotate_has_children(forest, parents_with_children)

    return forest


def build_location_level(
        child_locations: list[dict[str, Any]],
        locations_manager: LocationsManager) -> list[dict[str, Any]]:
    """
    Serialises one level of the location tree, flagging which nodes have children of their own

    Powers the lazily-expanded sidebar tree: each returned node carries a ``has_children`` boolean so
    the frontend can render an expand control (and fetch the next level on demand) without loading the
    whole forest. The has-children hint for the entire level is resolved in a single grouped query
    rather than one lookup per node. Type metadata the tree does not use (type_id, type_label) is
    dropped from each node; type_selectable is kept so a drag-and-drop can gray out nodes that are
    not selectable as a parent

    Args:
        child_locations (list[dict[str, Any]]): The CmdbLocation dicts of a single tree level
        locations_manager (LocationsManager): db interface used for the grouped children lookup

    Returns:
        list[dict[str, Any]]: The level's nodes, each with an added ``has_children`` boolean
    """
    node_ids: list[int] = [location[LocationKey.PUBLIC_ID.value] for location in child_locations]
    parents_with_children: set[int] = locations_manager.get_parents_with_children(node_ids)

    nodes: list[dict[str, Any]] = []

    for location in child_locations:
        node: dict[str, Any] = {
            key: value for key, value in location.items() if key not in _TRIMMED_LOCATION_NODE_KEYS
        }
        node[LOCATION_TREE_HAS_CHILDREN_KEY] = location[LocationKey.PUBLIC_ID.value] in parents_with_children
        nodes.append(node)

    return nodes


# ------------------------------------------ OBJECT-DRIVEN LOCATION SYNC --------------------------------------------- #

def extract_object_location_parent(fields: list[dict[str, Any]]) -> tuple[bool, int | None]:
    """
    Reads the parent-location id from an object's location-typed field

    A CmdbType has at most one location field and its stored value is the public_id of the parent
    CmdbLocation. The first return flags whether the object even has a location field, so callers can
    skip the whole location sync for types without one; the second is the coerced parent id, where
    None means "no parent / remove" (a null or non-positive value)

    Args:
        fields (list[dict[str, Any]]): The object's fields (each a name+value+type triple)

    Returns:
        tuple[bool, int | None]: (has_location_field, parent_location_id_or_None)
    """
    location_field: dict[str, Any] | None = next(
        (field for field in fields if field.get(CmdbObjectFieldKey.TYPE) == FieldType.LOCATION),
        None,
    )

    if location_field is None:
        return False, None

    try:
        parent: int = int(location_field.get(CmdbObjectFieldKey.VALUE))
    except (TypeError, ValueError):
        return True, None

    return True, parent if parent > 0 else None


def validate_shared_move_parent(parent: int | None, locations_manager: LocationsManager) -> None:
    """
    Validates the target parent of a placement change - the half that does not depend on the object

    The synthetic root is always a valid, selectable parent; any other parent must exist and belong to
    a type that is selectable as a parent (``type_selectable``, denormalized onto the location node).
    Removing the placement (``parent`` None) is always allowed. Split out so a bulk move can check the
    parent it shares across the whole batch once instead of once per object

    Args:
        parent (int | None): The new parent CmdbLocation id, or None to remove the placement
        locations_manager (LocationsManager): db interface for CmdbLocations

    Raises:
        HTTPException: 400 when the parent does not exist or is not selectable as a parent
    """
    if parent is None or parent == RootLocationDefault.PUBLIC_ID:
        return

    parent_location: dict[str, Any] | None = locations_manager.get_location(parent)

    if not parent_location:
        abort(400, f"The selected parent Location (ID:{parent}) does not exist!")

    if not parent_location.get(LocationKey.TYPE_SELECTABLE.value, True):
        abort(400, f"The selected parent Location (ID:{parent}) is not selectable as a parent!")


def validate_object_location_change(
        object_id: int,
        parent: int | None,
        locations_manager: LocationsManager) -> None:
    """
    Validates a pending change to an object's location placement, aborting 400 when invalid

    Only a real change is validated (an unchanged parent is a no-op). Setting a parent requires that
    parent CmdbLocation to exist, to belong to a type that is selectable as a parent, and to not sit
    inside the object's own location subtree (which would create a cycle). Removing the parent is
    always allowed: the location node's direct children are promoted onto its own parent rather than
    being orphaned. The synthetic root is always a valid, selectable parent

    Args:
        object_id (int): public_id of the CmdbObject whose location is changing
        parent (int | None): The new parent CmdbLocation id, or None to remove the placement
        locations_manager (LocationsManager): db interface for CmdbLocations

    Raises:
        HTTPException: 400 when the parent does not exist, is not selectable as a parent, or the
            change would create a cycle
    """
    existing: dict[str, Any] | None = locations_manager.get_location_for_object(object_id)
    current_parent: int | None = existing['parent'] if existing else None

    if parent == current_parent:
        return

    if parent is None:
        # Removing the placement deletes the location node; its direct children are promoted onto
        # the node's own parent (see LocationsManager.delete_location), so this is always allowed
        return

    validate_shared_move_parent(parent, locations_manager)

    if existing:
        forbidden: set[int] = {existing['public_id']}
        forbidden |= {
            descendant['public_id']
            for descendant in locations_manager.get_all_descendant_locations(existing['public_id'])
        }

        if parent in forbidden:
            abort(400, f"The selected parent Location (ID:{parent}) would create a cycle in the location tree!")


def delete_location_with_reparenting(
        location: dict[str, Any],
        locations_manager: LocationsManager,
        objects_manager: ObjectsManager) -> bool:
    """
    Deletes a CmdbLocation node and re-parents its direct children onto the node's own parent

    Keeps the object<->location mirror consistent across both collections: the child location NODES
    are promoted onto the deleted node's parent by LocationsManager.delete_location, and the owning
    child OBJECTS' location field (which stores their parent-location id) is re-pointed at the same
    grandparent here. Without the object-side update those fields would dangle at the deleted node
    and the objects would fail validate_object_location_change on their next edit

    Args:
        location (dict[str, Any]): The CmdbLocation to delete (carries its public_id and parent)
        locations_manager (LocationsManager): db interface for CmdbLocations
        objects_manager (ObjectsManager): db interface for CmdbObjects

    Returns:
        bool: True if the location was deleted
    """
    public_id: int = location[LocationKey.PUBLIC_ID.value]
    grandparent_id: int = location[LocationKey.PARENT.value]

    # snapshot the owning objects of the direct children BEFORE the delete promotes their nodes
    child_object_ids: list[int] = [
        child.object_id for child in locations_manager.get_locations_by(parent=public_id)
    ]

    # promotes the child location NODES onto the grandparent, then removes this node
    ack: bool = locations_manager.delete_location(public_id)

    # keep the mirrored object fields in sync with the re-parented nodes
    objects_manager.set_location_field_for_objects(child_object_ids, grandparent_id)

    return ack


def normalize_parent_id(raw_parent: Any) -> int | None:
    """
    Coerces a request-supplied parent id to a positive int, or None for "no placement"

    Mirrors the object location field semantics (see extract_object_location_parent): a null,
    non-integer, or non-positive value (e.g. 0) means "remove the placement", any positive value is
    a parent CmdbLocation id

    Args:
        raw_parent (Any): The raw ``parent`` value from the request body

    Returns:
        int | None: The positive parent id, or None to remove the placement
    """
    try:
        parent: int = int(raw_parent)
    except (TypeError, ValueError):
        return None

    return parent if parent > 0 else None


def validate_object_location_move(
        object_id: int,
        parent: int | None,
        objects_manager: ObjectsManager,
        locations_manager: LocationsManager) -> CmdbType:
    """
    Read-only validation of a placement move; returns the object's type for the caller to reuse

    Confirms the object exists, its type resolves and declares a location field (only such objects
    can sit in the location tree), and the target placement is legal (parent exists, is
    selectable-as-parent, no cycle - via validate_object_location_change). Writes nothing, so a
    bulk move can validate every target up front and reject the whole batch before any change

    Args:
        object_id (int): public_id of the CmdbObject to move
        parent (int | None): The new parent CmdbLocation id, or None to remove the placement
        objects_manager (ObjectsManager): db interface for CmdbObjects
        locations_manager (LocationsManager): db interface for CmdbLocations

    Raises:
        HTTPException: 404 when the object is missing, 400 when it has no location field or the
            placement is invalid, 500 when the object's type cannot be resolved

    Returns:
        CmdbType: The moved object's resolved CmdbType (reused by move_object_location)
    """
    current_object: CmdbObject | None = objects_manager.get_object(object_id, as_dict=False)

    if not current_object:
        abort(404, f"Object with ID:{object_id} not found!")

    object_type: CmdbType | None = objects_manager.get_object_type(current_object.get_type_id())

    if not object_type:
        abort(500, f"Type of Object with ID:{object_id} not found in database!")

    if not current_object.has_fields_of_type(FieldType.LOCATION):
        abort(400, f"Object with ID:{object_id} has no location field and cannot be placed in the location tree!")

    validate_object_location_change(object_id, parent, locations_manager)

    return object_type


def validate_object_location_moves(
        object_ids: list[int],
        parent: int | None,
        objects_manager: ObjectsManager,
        locations_manager: LocationsManager) -> dict[int, CmdbType]:
    """
    Read-only validation of a BULK placement move; returns each object's type for the caller to reuse

    Runs the same checks as ``validate_object_location_move`` in the same order per object, but
    without re-reading what the whole batch shares:

    - the objects are fetched in ONE ``$in`` query instead of one read per object
    - each distinct type is resolved ONCE, however many objects of it are in the batch
    - the target parent is the same for the entire batch, so its existence and selectable-as-parent
      check runs once rather than per object (the per-object cycle check still runs individually,
      because it depends on where each object currently sits)

    One consequence of validating the shared parent up front: when BOTH the parent is invalid and a
    listed object is missing, the parent error is what the caller sees. Previously the first object's
    404 won. The batch is rejected either way

    Args:
        object_ids (list[int]): public_ids of the CmdbObjects to move
        parent (int | None): The new parent CmdbLocation id, or None to remove the placements
        objects_manager (ObjectsManager): db interface for CmdbObjects
        locations_manager (LocationsManager): db interface for CmdbLocations

    Raises:
        HTTPException: 404 when a listed object is missing, 400 when one has no location field or a
            placement is invalid, 500 when an object's type cannot be resolved

    Returns:
        dict[int, CmdbType]: The resolved CmdbType per object_id (reused by move_object_location)
    """
    validate_shared_move_parent(parent, locations_manager)

    objects_by_id: dict[int, CmdbObject] = {
        current_object.get_public_id(): current_object
        for current_object in objects_manager.get_objects_by(public_id={'$in': object_ids})
    }

    types_by_id: dict[int, CmdbType] = {}
    validated_types: dict[int, CmdbType] = {}

    for object_id in object_ids:
        current_object: CmdbObject | None = objects_by_id.get(object_id)

        if not current_object:
            abort(404, f"Object with ID:{object_id} not found!")

        type_id: int = current_object.get_type_id()

        if type_id not in types_by_id:
            object_type: CmdbType | None = objects_manager.get_object_type(type_id)

            if not object_type:
                abort(500, f"Type of Object with ID:{object_id} not found in database!")

            types_by_id[type_id] = object_type

        if not current_object.has_fields_of_type(FieldType.LOCATION):
            abort(400,
                  f"Object with ID:{object_id} has no location field and cannot be placed in the location tree!")

        validate_object_location_change(object_id, parent, locations_manager)

        validated_types[object_id] = types_by_id[type_id]

    return validated_types


def move_object_location(
        object_id: int,
        parent: int | None,
        request_user: CmdbUser,
        objects_manager: ObjectsManager,
        locations_manager: LocationsManager,
        object_type: CmdbType | None = None) -> None:
    """
    Moves one object's location placement to a new parent, mirroring both sides of the tree

    Validates the move (unless a pre-validated ``object_type`` is supplied by a bulk caller), then
    updates BOTH sides of the object<->location mirror: the object's location field value and its
    CmdbLocation node (created / re-parented / removed by sync_object_location, which promotes the
    node's children onto its own parent when the placement is removed). ``parent`` None removes the
    placement. This is a targeted placement change - it deliberately does NOT bump the object
    version or emit an edit log / webhook (matching the direct location-update route, not the full
    object-edit pipeline)

    Args:
        object_id (int): public_id of the CmdbObject to move
        parent (int | None): The new parent CmdbLocation id, or None to remove the placement
        request_user (CmdbUser): The user making the request (used to derive the node name)
        objects_manager (ObjectsManager): db interface for CmdbObjects
        locations_manager (LocationsManager): db interface for CmdbLocations
        object_type (CmdbType | None): Pre-validated type from validate_object_location_move; when
            None the move is validated here first

    Raises:
        HTTPException: 404 / 400 / 500 as raised by validate_object_location_move
    """
    if object_type is None:
        object_type = validate_object_location_move(object_id, parent, objects_manager, locations_manager)

    objects_manager.set_location_field_for_objects([object_id], parent)
    sync_object_location(object_id, parent, None, object_type, request_user, objects_manager, locations_manager)


def sync_object_location(
        object_id: int,
        parent: int | None,
        location_name: str | None,
        object_type: CmdbType,
        request_user: CmdbUser,
        objects_manager: ObjectsManager,
        locations_manager: LocationsManager) -> None:
    """
    Mirrors an object's location placement into the CmdbLocation tree (best-effort)

    Creates, updates or deletes the object's CmdbLocation so the separate location tree matches the
    object's location field: a parent with no existing location -> create; a changed parent (or an
    explicit name) on an existing location -> update; a removed parent -> delete. An unchanged parent
    with no name given is a no-op. Any failure is logged and swallowed so the already-persisted object
    is never lost - there are no cross-collection transactions here (best-effort). Call
    validate_object_location_change first to reject an invalid placement before the object is saved

    Args:
        object_id (int): public_id of the CmdbObject
        parent (int | None): The parent CmdbLocation id, or None to remove the placement
        location_name (str | None): Optional custom tree name; when None the name is derived
        object_type (CmdbType): The object's CmdbType (supplies label/icon/selectable for a new node)
        request_user (CmdbUser): The user making the request (used to render a derived name)
        objects_manager (ObjectsManager): db interface used to derive the name
        locations_manager (LocationsManager): db interface for CmdbLocations
    """
    try:
        existing: dict[str, Any] | None = locations_manager.get_location_for_object(object_id)
        current_parent: int | None = existing['parent'] if existing else None

        # Nothing changed and no explicit rename requested -> leave the location untouched
        if parent == current_parent and location_name is None:
            return

        if parent is None:
            if existing:
                delete_location_with_reparenting(existing, locations_manager, objects_manager)
            return

        resolved_name: str = resolve_location_name(location_name, object_id, objects_manager, request_user)

        if existing:
            locations_manager.update_location(object_id, {'parent': parent, 'name': resolved_name})
        else:
            locations_manager.insert_location({
                'object_id': object_id,
                'parent': parent,
                'type_id': object_type.public_id,
                'type_label': object_type.label,
                'type_icon': object_type.get_icon(),
                'type_selectable': object_type.selectable_as_parent,
                'name': resolved_name,
            })
    except Exception as err:
        LOGGER.error("[sync_object_location] Failed to sync Location for Object ID:%s: %s. Type: %s",
                     object_id, err, type(err))
