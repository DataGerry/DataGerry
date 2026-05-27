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
dg_location grafting for the CI Explorer

When ``with_locations`` is on, the CI Explorer extends the graph with one hop of the
dg_location hierarchy *with inverted semantics*: the location-parent of the focal object
shows up in the children bucket and the location-children show up in the parent bucket.

The helpers in this module are deliberately load-only: each returns the raw CmdbObject
documents the orchestrator should later enrich + compose. That keeps the orchestrator's
batched enrichment pass single-step (one ref-id $in, one location-id $in across the full
union of objects in scope), avoiding the per-branch enrichment the route used to do

Two bug fixes against the original route (audited in Phase 2):
  - B1: item_limit consumed by the parent collector is bounded to at most 1 slot, so
    the children collector still has the remaining budget available. The original
    `remaining -= remaining` zeroed it out
  - B2: types_filter is applied at the Mongo query level on the children collector so
    item_limit caps the *post-filter* visible count, matching the relation side
"""
from typing import Any

from cmdb.manager import LocationsManager, ObjectsManager
# -------------------------------------------------------------------------------------------------------------------- #

CHILD_LOCATION_REL_COLOR: str = '#C084FC'
PARENT_LOCATION_REL_COLOR: str = '#A855F7'

ROOT_LOCATION_SENTINEL_PARENT: int = 1


def collect_location_parent_object(
    target_location: dict[str, Any],
    types_filter: frozenset[int],
    remaining: int,
    item_limit_active: bool,
    locations_manager: LocationsManager,
    objects_manager: ObjectsManager,
) -> dict[str, Any] | None:
    """
    Returns the CmdbObject owning the location *one hop up* from the target, or None

    Skips the load entirely when:
      - ``target_location.parent`` is the root sentinel (== 1)
      - ``item_limit_active`` is True and ``remaining <= 0``
      - the parent location row cannot be loaded
      - the parent location's owning object cannot be loaded
      - ``types_filter`` is active and the parent object's type_id is not in the filter

    No node composition happens here - the caller enriches the returned object alongside
    every other in-scope object before composing the final node + edge

    Args:
        target_location (dict[str, Any]): The CmdbLocation document of the target
        types_filter (frozenset[int]): Allowed type_ids; empty set disables the filter
        remaining (int): Slot budget still available; only honored when
            ``item_limit_active`` is True
        item_limit_active (bool): Whether the route is operating under an item_limit cap
        locations_manager (LocationsManager): db interface for CmdbLocations
        objects_manager (ObjectsManager): db interface for CmdbObjects

    Returns:
        dict[str, Any] | None: The raw parent CmdbObject document, or None when nothing
            should be grafted into the children bucket from the location-parent branch
    """
    if target_location.get('parent') == ROOT_LOCATION_SENTINEL_PARENT:
        return None

    if item_limit_active and remaining <= 0:
        return None

    parent_location: dict[str, Any] | None = locations_manager.get_location(target_location['parent'])

    if not parent_location:
        return None

    parent_object: dict[str, Any] | None = objects_manager.get_object(parent_location['object_id'])

    if not parent_object:
        return None

    if types_filter and parent_object['type_id'] not in types_filter:
        return None

    return parent_object


def collect_location_children_objects(
    target_location: dict[str, Any],
    types_filter: frozenset[int],
    remaining: int,
    item_limit_active: bool,
    locations_manager: LocationsManager,
    objects_manager: ObjectsManager,
) -> list[dict[str, Any]]:
    """
    Returns the list of CmdbObjects owning locations one hop *down* from the target

    ``types_filter`` is applied at the Mongo query level (B2 fix) so the visible cap
    behaves the same as on the relation side: the final slice to ``remaining`` happens
    after the type filter, so ``item_limit`` always bounds the visible node count rather
    than the pre-filter count. Returns an empty list when the target has no location-
    children or when ``item_limit_active`` is True and ``remaining <= 0``

    Args:
        target_location (dict[str, Any]): The CmdbLocation document of the target
        types_filter (frozenset[int]): Allowed type_ids; empty set disables the filter
        remaining (int): Slot budget still available; only honored when
            ``item_limit_active`` is True
        item_limit_active (bool): Whether the route is operating under an item_limit cap
        locations_manager (LocationsManager): db interface for CmdbLocations
        objects_manager (ObjectsManager): db interface for CmdbObjects

    Returns:
        list[dict[str, Any]]: Raw CmdbObject documents to graft into the parent bucket
    """
    if item_limit_active and remaining <= 0:
        return []

    child_locations: list[Any] = locations_manager.get_locations_by(parent=target_location['public_id'])

    if not child_locations:
        return []

    object_ids: list[int] = [loc.object_id for loc in child_locations]
    criteria: dict[str, Any] = {'public_id': {'$in': object_ids}}

    if types_filter:
        criteria['type_id'] = {'$in': list(types_filter)}

    child_objects: list[dict[str, Any]] = list(objects_manager.find(criteria=criteria))

    if item_limit_active and len(child_objects) > remaining:
        child_objects = child_objects[:remaining]

    return child_objects
