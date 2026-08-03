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

The log helpers are deliberately best-effort: a CmdbObjectRelation write must not fail because its
history entry could not be stored, so they swallow (and log) the logs manager's errors. Every one of
them is called AFTER the write it describes, so a failed write never leaves a log claiming a change
that did not happen.
"""
from logging import Logger, getLogger
from typing import Any

from flask import abort

from cmdb.manager import ObjectRelationsManager, ObjectRelationLogsManager, RelationsManager, ObjectsManager
from cmdb.manager.query_builder import BuilderParameters

from cmdb.models.user_model import CmdbUser
from cmdb.models.log_model import LogInteraction
from cmdb.models.object_relation_model import ObjectRelationKey
from cmdb.framework.rendering.cmdb_multi_render import CmdbMultiRender
from cmdb.security.acl.permission import AccessControlPermission

from cmdb.errors.manager.object_relation_logs_manager import (
    ObjectRelationLogsManagerBuildError,
    ObjectRelationLogsManagerInsertError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

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


def log_object_relation_change(
    object_relation_logs_manager: ObjectRelationLogsManager,
    request_user: CmdbUser,
    action: LogInteraction,
    old_object_relation: dict[str, Any] | None,
    new_object_relation: dict[str, Any] | None,
) -> None:
    """
    Writes one CmdbObjectRelationLog, swallowing a logging failure

    The history of a CmdbObjectRelation must never decide whether its write succeeds, so a build /
    insert failure is logged and dropped instead of propagating to the route

    Args:
        object_relation_logs_manager (ObjectRelationLogsManager): Manager writing the log
        request_user (CmdbUser): The user whose change is recorded
        action (LogInteraction): The interaction to record (CREATE / EDIT / DELETE)
        old_object_relation (dict[str, Any] | None): State before the change (None for a CREATE)
        new_object_relation (dict[str, Any] | None): State after the change (None for a DELETE)
    """
    try:
        object_relation_logs_manager.build_object_relation_log(
            action,
            request_user,
            old_object_relation,
            new_object_relation,
        )
    except (ObjectRelationLogsManagerBuildError, ObjectRelationLogsManagerInsertError) as error:
        LOGGER.error("[log_object_relation_change] Failed to create an ObjectRelationLog: %s", error, exc_info=True)


def log_object_relation_update(
    object_relation_logs_manager: ObjectRelationLogsManager,
    request_user: CmdbUser,
    old_object_relation: dict[str, Any],
    new_object_relation: dict[str, Any],
) -> None:
    """
    Writes the history of an applied CmdbObjectRelation update

    An update that only changed field values is one EDIT entry. An update that moved the relation to
    another parent / child object is recorded as the DELETE of the old relation plus the CREATE of the
    new one, because the two endpoints define which relation this is - keeping it as a single EDIT
    would hide the move from both objects' histories

    Args:
        object_relation_logs_manager (ObjectRelationLogsManager): Manager writing the logs
        request_user (CmdbUser): The user who performed the update
        old_object_relation (dict[str, Any]): The CmdbObjectRelation before the update
        new_object_relation (dict[str, Any]): The CmdbObjectRelation as it was stored
    """
    endpoints_changed = object_relation_logs_manager.check_related_object_changed(
        old_object_relation,
        new_object_relation,
    )

    if not endpoints_changed:
        log_object_relation_change(
            object_relation_logs_manager, request_user, LogInteraction.EDIT,
            old_object_relation, new_object_relation,
        )

        return

    log_object_relation_change(
        object_relation_logs_manager, request_user, LogInteraction.DELETE, old_object_relation, None,
    )
    log_object_relation_change(
        object_relation_logs_manager, request_user, LogInteraction.CREATE, None, new_object_relation,
    )


def log_object_relation_deletions(
    object_relation_logs_manager: ObjectRelationLogsManager,
    request_user: CmdbUser,
    deleted_object_relations: list[dict[str, Any]],
) -> None:
    """
    Writes one DELETE CmdbObjectRelationLog per deleted CmdbObjectRelation, in a single batch insert

    The public_ids are reserved in one call and stamped onto the documents, so a bulk delete of N
    relations costs one counter read and one insert instead of 2N round trips. A logging failure is
    swallowed for the same reason as in `log_object_relation_change`

    Args:
        object_relation_logs_manager (ObjectRelationLogsManager): Manager writing the logs
        request_user (CmdbUser): The user who performed the deletion
        deleted_object_relations (list[dict[str, Any]]): The CmdbObjectRelations that were deleted
    """
    if not deleted_object_relations:
        return

    try:
        logs_to_create: list[dict[str, Any]] = [
            object_relation_logs_manager.format_object_relation_log_data(
                LogInteraction.DELETE,
                request_user,
                object_relation,
                None,
            )
            for object_relation in deleted_object_relations
        ]

        reserved_log_ids: list[int] = object_relation_logs_manager.reserve_public_ids(len(logs_to_create))

        for log_doc, new_id in zip(logs_to_create, reserved_log_ids):
            log_doc[ObjectRelationKey.PUBLIC_ID.value] = new_id

        object_relation_logs_manager.insert_many(logs_to_create, skip_public=True)
    except Exception as error:
        LOGGER.error("[log_object_relation_deletions] Failed to create the deletion Logs: %s", error, exc_info=True)


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
