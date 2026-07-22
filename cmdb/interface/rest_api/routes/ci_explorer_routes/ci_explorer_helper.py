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
Helper methods shared by the CI Explorer REST routes
"""
from typing import Any, Callable

from flask import abort

from cmdb.interface.rest_api.routes.ci_explorer_routes.ci_explorer_constants import CiExplorerField
# -------------------------------------------------------------------------------------------------------------------- #


def apply_ci_explorer_field(
    fetch: Callable[[int], dict[str, Any] | None],
    persist: Callable[[int, dict[str, Any]], Any],
    public_id: int,
    field: CiExplorerField,
    request_body: dict[str, Any] | None,
    entity_label: str,
) -> Any:
    """
    Sets a single CI Explorer field (tooltip / label) on an entity and persists it

    Shared by the ``/tooltip`` and ``/type_label`` routes: fetch the target entity, read the field
    value from the request body, write it onto the entity and persist via the entity's own manager.
    Persisting goes through the entity manager's canonical update (which keeps its type-active / ACL
    guards), so this helper sets the field and delegates rather than issuing a targeted write

    Args:
        fetch (Callable[[int], dict | None]): Loads the target entity by public_id (e.g.
            ``objects_manager.get_object``); returns None when it does not exist
        persist (Callable[[int, dict], Any]): Persists the mutated entity (e.g.
            ``objects_manager.update_object``)
        public_id (int): public_id of the entity to update
        field (CiExplorerField): The CI Explorer field to set
        request_body (dict | None): The parsed request body (may be None)
        entity_label (str): Human-readable entity name used in the 404 message (e.g. "Object")

    Raises:
        HTTPException: 404 when the entity does not exist; 400 when the field is missing from the body

    Returns:
        Any: The value that was set on the entity
    """
    entity: dict[str, Any] | None = fetch(public_id)

    if not entity:
        abort(404, f"The {entity_label} with ID:{public_id} was not found!")

    value = (request_body or {}).get(field.value)

    if value is None:
        abort(400, f"Missing '{field.value}' in the request body!")

    entity[field.value] = value
    persist(public_id, entity)

    return value
