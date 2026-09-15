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
This module contains shared caching helpers used while building DocAPI template data.
"""
from cmdb.manager import ObjectsManager, TypesManager
# -------------------------------------------------------------------------------------------------------------------- #

def cache_objects_and_types(
    object_ids: list[int],
    object_cache: dict[int, dict],
    type_cache: dict[int, dict],
    objects_manager: ObjectsManager,
    types_manager: TypesManager,
) -> None:
    """
    Lazily loads any of `object_ids` (and the types they reference) that are not already cached

    Both caches are mutated in place: objects missing from `object_cache` are fetched in a single
    bulk query, then any type referenced by a cached object but missing from `type_cache` is fetched
    in a second bulk query. Keeping both caches in sync here prevents objects reached during relation
    traversal from being silently dropped later because their type was never loaded.

    Args:
        object_ids (list[int]): The public_ids of the objects that must be present in the cache
        object_cache (dict[int, dict]): Object cache keyed by public_id, mutated in place
        type_cache (dict[int, dict]): Type cache keyed by public_id, mutated in place
        objects_manager (ObjectsManager): Manager used to fetch missing objects
        types_manager (TypesManager): Manager used to fetch missing types
    """
    missing_ids = [oid for oid in object_ids if oid not in object_cache]
    if missing_ids:
        for obj in objects_manager.find(criteria={"public_id": {"$in": missing_ids}}):
            object_cache[obj["public_id"]] = obj

    missing_type_ids = {
        obj["type_id"]
        for obj in object_cache.values()
        if obj.get("type_id") and obj["type_id"] not in type_cache
    }
    if missing_type_ids:
        for obj_type in types_manager.find(criteria={"public_id": {"$in": list(missing_type_ids)}}):
            type_cache[obj_type["public_id"]] = obj_type
