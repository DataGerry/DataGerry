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
Helper functions for the CmdbRelation routes

Pure, side-effect-light helpers extracted from the route handlers so the orchestration in
``relations_routes`` stays readable and the comparison logic stays unit-testable.
"""
from typing import Any

from cmdb.manager import ObjectRelationsManager
# -------------------------------------------------------------------------------------------------------------------- #


def get_deleted_type_ids(old_ids: list[int], new_ids: list[int]) -> list[int]:
    """
    Identifies the IDs that have been removed when comparing two lists

    Args:
        old_ids (list[int]): The previous list of IDs
        new_ids (list[int]): The updated list of IDs

    Returns:
        list[int]: The IDs present in 'old_ids' but no longer in 'new_ids'
    """
    return list(set(old_ids) - set(new_ids))


def handle_deleted_type_ids(old_relation: dict[str, Any],
                            new_relation: dict[str, Any],
                            object_relations_manager: ObjectRelationsManager) -> None:
    """
    Deletes the ObjectRelations invalidated by removed parent/child CmdbTypes

    Compares the allowed parent and child CmdbTypes of the old vs. new relation; for every type
    that is no longer allowed, the corresponding CmdbObjectRelations are deleted.

    Args:
        old_relation (dict[str, Any]): The relation before the change
        new_relation (dict[str, Any]): The relation after the change
        object_relations_manager (ObjectRelationsManager): Manager for CmdbObjectRelations
    """
    deleted_parent_ids: list[int] = get_deleted_type_ids(old_relation["parent_type_ids"],
                                                         new_relation["parent_type_ids"])

    if deleted_parent_ids:
        object_relations_manager.delete_invalidated_object_relations(old_relation["public_id"],
                                                                     deleted_parent_ids,
                                                                     True)

    deleted_child_ids: list[int] = get_deleted_type_ids(old_relation["child_type_ids"],
                                                        new_relation["child_type_ids"])

    if deleted_child_ids:
        object_relations_manager.delete_invalidated_object_relations(old_relation["public_id"],
                                                                     deleted_child_ids,
                                                                     False)
