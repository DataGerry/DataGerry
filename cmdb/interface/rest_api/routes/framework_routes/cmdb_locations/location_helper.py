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
from typing import Any

from flask import abort

from cmdb.manager import ObjectsManager

from cmdb.models.object_model import CmdbObject
from cmdb.models.user_model import CmdbUser
from cmdb.models.location_model.location_node import LocationNode
from cmdb.framework.rendering.render_list import RenderList
from cmdb.framework.rendering.render_result import RenderResult
from cmdb.database.predefined_data.predefined_data_constants import RootLocationDefault

from cmdb.interface.rest_api.routes.framework_routes.cmdb_locations.location_constants import OBJECT_ID_NAME_TEMPLATE
# -------------------------------------------------------------------------------------------------------------------- #


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
