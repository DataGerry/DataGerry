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
Helper functions for the CmdbRelation and CmdbObjectRelation routes

Helpers extracted from the route handlers so the orchestration in ``relations_routes`` /
``object_relation_routes`` stays readable and the comparison / validation logic stays
unit-testable. The validation helpers abort with the documented HTTP status on invalid input.
"""
from typing import Any

from flask import abort

from cmdb.manager import ObjectRelationsManager, RelationsManager, ObjectsManager
from cmdb.manager.query_builder import BuilderParameters

from cmdb.models.user_model import CmdbUser
from cmdb.framework.rendering.cmdb_multi_render import CmdbMultiRender
from cmdb.security.acl.permission import AccessControlPermission
# -------------------------------------------------------------------------------------------------------------------- #

# Keys of a counterpart summary returned for a relation-tab row
COUNTERPART_OBJECT_ID_KEY: str = 'object_id'
COUNTERPART_TYPE_LABEL_KEY: str = 'type_label'
COUNTERPART_ICON_KEY: str = 'icon'
COUNTERPART_SUMMARY_LINE_KEY: str = 'summary_line'


def resolve_counterpart_summaries(
    counterpart_ids: list[int],
    request_user: CmdbUser,
    objects_manager: ObjectsManager,
) -> dict[int, dict[str, Any]]:
    """
    Renders the given counterpart objects (ACL-scoped) into minimal relation-tab row summaries

    Only objects the requesting user may read are returned; ids that are missing, inactive or
    ACL-hidden are absent from the result, so the caller renders their row with a null counterpart

    Args:
        counterpart_ids (list[int]): public_ids of the counterpart objects to resolve
        request_user (CmdbUser): The user requesting the data (for ACL-scoped rendering)
        objects_manager (ObjectsManager): Manager used to fetch the counterpart objects

    Returns:
        dict[int, dict[str, Any]]: object_id -> {object_id, type_label, icon, summary_line}
    """
    unique_ids = list({cid for cid in counterpart_ids if cid is not None})

    if not unique_ids:
        return {}

    builder_params = BuilderParameters(criteria={'public_id': {'$in': unique_ids}})
    objects = objects_manager.iterate(builder_params, request_user, AccessControlPermission.READ).results

    summaries: dict[int, dict[str, Any]] = {}

    for render_result in CmdbMultiRender(objects, request_user).result():
        object_id = render_result.object_information.get('object_id')
        summaries[object_id] = {
            COUNTERPART_OBJECT_ID_KEY: object_id,
            COUNTERPART_TYPE_LABEL_KEY: render_result.type_information.get('type_label'),
            COUNTERPART_ICON_KEY: render_result.type_information.get('icon'),
            COUNTERPART_SUMMARY_LINE_KEY: render_result.summary_line,
        }

    return summaries


def get_existing_relation_or_abort(relations_manager: RelationsManager, relation_id: int | None) -> dict[str, Any]:
    """
    Returns the CmdbRelation for the given id or aborts with 400 if it no longer exists

    Shared by the CmdbObjectRelation create/update routes, which both require the referenced
    CmdbRelation to still exist before persisting.

    Args:
        relations_manager (RelationsManager): Manager used to look up the CmdbRelation
        relation_id (int | None): public_id of the referenced CmdbRelation

    Returns:
        dict[str, Any]: The existing CmdbRelation
    """
    target_relation: dict[str, Any] | None = relations_manager.get_relation(relation_id)

    if not target_relation:
        abort(400, f"The Relation with ID:{relation_id} does not exist anymore!")

    return target_relation


def validate_object_relation_endpoints(parent_id: int | None, child_id: int | None) -> None:
    """
    Validates that a CmdbObjectRelation references a distinct parent and child CmdbObject

    Aborts with 400 if either endpoint is missing or if both endpoints are the same CmdbObject.

    Args:
        parent_id (int | None): public_id of the parent CmdbObject
        child_id (int | None): public_id of the child CmdbObject
    """
    if not parent_id or not child_id:
        abort(400, "Both 'relation_parent_id' and 'relation_child_id' must be provided!")

    if parent_id == child_id:
        abort(400, "Parent and child cannot be the same Object in an ObjectRelation!")


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
