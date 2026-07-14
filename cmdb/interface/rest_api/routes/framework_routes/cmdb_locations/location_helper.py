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
from cmdb.database.predefined_data.predefined_data_constants import RootLocationDefault, LocationKey

from cmdb.interface.rest_api.routes.framework_routes.cmdb_locations.location_constants import (
    OBJECT_ID_NAME_TEMPLATE,
    LOCATION_TREE_HAS_CHILDREN_KEY,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# CmdbLocation keys the lazy tree nodes omit - the frontend tree does not use them
_TRIMMED_LOCATION_NODE_KEYS: frozenset[str] = frozenset({
    LocationKey.TYPE_ID.value,
    LocationKey.TYPE_LABEL.value,
    LocationKey.TYPE_SELECTABLE.value,
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


def build_location_forest(locations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Assembles a flat list of CmdbLocation dicts into a nested location forest

    Locations whose ``parent`` is the root id become the roots of the forest; every other
    location is attached beneath its parent via ``LocationNode`` (which guards against parent
    cycles). Each root is then serialized to a nested, JSON-compatible dict

    Args:
        locations (list[dict[str, Any]]): Flat list of CmdbLocation dicts (e.g. from ``to_json``)

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

    return [LocationNode.to_json(root_location) for root_location in root_locations]


def build_location_level(
        child_locations: list[dict[str, Any]],
        locations_manager: LocationsManager) -> list[dict[str, Any]]:
    """
    Serialises one level of the location tree, flagging which nodes have children of their own

    Powers the lazily-expanded sidebar tree: each returned node carries a ``has_children`` boolean so
    the frontend can render an expand control (and fetch the next level on demand) without loading the
    whole forest. The has-children hint for the entire level is resolved in a single grouped query
    rather than one lookup per node. Type metadata the tree does not use (type_id, type_label,
    type_selectable) is dropped from each node

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


def validate_object_location_change(
        object_id: int,
        parent: int | None,
        locations_manager: LocationsManager) -> None:
    """
    Validates a pending change to an object's location placement, aborting 400 when invalid

    Only a real change is validated (an unchanged parent is a no-op). Setting a parent requires that
    parent CmdbLocation to exist and to not sit inside the object's own location subtree (which would
    create a cycle). Removing the parent is refused while the object's location still has children, as
    that would orphan the subtree

    Args:
        object_id (int): public_id of the CmdbObject whose location is changing
        parent (int | None): The new parent CmdbLocation id, or None to remove the placement
        locations_manager (LocationsManager): db interface for CmdbLocations

    Raises:
        HTTPException: 400 when the parent does not exist, the change would create a cycle, or
            removing the placement would orphan child locations
    """
    existing: dict[str, Any] | None = locations_manager.get_location_for_object(object_id)
    current_parent: int | None = existing['parent'] if existing else None

    if parent == current_parent:
        return

    if parent is None:
        if existing and locations_manager.location_has_children(existing['public_id']):
            abort(400, f"The Location of Object with ID:{object_id} has child Locations and cannot be removed!")
        return

    if parent != RootLocationDefault.PUBLIC_ID and not locations_manager.get_location(parent):
        abort(400, f"The selected parent Location (ID:{parent}) does not exist!")

    if existing:
        forbidden: set[int] = {existing['public_id']}
        forbidden |= {
            descendant['public_id']
            for descendant in locations_manager.get_all_descendant_locations(existing['public_id'])
        }

        if parent in forbidden:
            abort(400, f"The selected parent Location (ID:{parent}) would create a cycle in the location tree!")


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
                locations_manager.delete_location(existing['public_id'])
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
