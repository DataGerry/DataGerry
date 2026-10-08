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

A CmdbObjectRelation write trusts nothing about its endpoints: ``resolve_object_relation_endpoints`` reads both
objects (existence, the caller's READ ACL, the relation's allowed type per side) and answers the type ids the
route stores, and ``guard_object_relation_field_values`` holds the values to the relation's declared fields.

A CmdbRelation update is split into ``apply_relation_update`` (everything that must happen for the
relation itself) and ``cascade_relation_update`` (everything that must then happen to its dependent
CmdbObjectRelations), so the route can report a failed cascade differently from a failed update: the
first leaves nothing written, the second leaves the relation already updated.

A CmdbObjectRelation is read under one rule: **it is as readable as the less readable of its two objects**,
judged by the type ids stamped on it. ``resolve_unreadable_type_ids_or_abort`` answers the types the caller may not
read, the manager narrows the lists and the relation tabs with them, and ``is_object_relation_readable`` judges a
single relation. The relation tabs of an object are moreover as readable as the object itself
(``read_tab_object_or_abort``).

A bulk delete is judged by ``read_bulk_delete_selection`` (an object body, a non-empty list of ids, at most
``MAX_BULK_DELETE_OBJECT_RELATIONS`` of them) and run by ``delete_object_relations``, one atomic read-and-delete per
id, so the documents it collects - and the history the route writes from them - are exactly the ones THIS request
removed.

The log helpers are deliberately best-effort: a CmdbObjectRelation write must not fail because its
history entry could not be stored, so they swallow (and log) the logs manager's errors. Every one of
them is called AFTER the write it describes, so a failed write never leaves a log claiming a change
that did not happen.
"""
from http import HTTPStatus
from logging import Logger, getLogger
from typing import Any

from flask import abort

from cmdb.manager import (
    ObjectRelationsManager,
    ObjectRelationLogsManager,
    RelationsManager,
    ObjectsManager,
    TypesManager,
)
from cmdb.manager.query_builder import BuilderParameters

from cmdb.models.user_model import CmdbUser
from cmdb.models.log_model import LogInteraction
from cmdb.models.object_relation_model import ObjectRelationKey
from cmdb.models.object_relation_model.object_relation_constants import ObjectRelationFieldValueKey, ObjectRelationRole
from cmdb.models.object_model.cmdb_object_key_enum import CmdbObjectKey
from cmdb.models.type_model.field_key_enum import FieldKey
from cmdb.models.relation_model import CmdbRelation, RelationKey, RelationDiffKey
from cmdb.framework.rendering.cmdb_multi_render import CmdbMultiRender
from cmdb.security.acl.builder import resolve_denied_type_ids
from cmdb.security.acl.permission import AccessControlPermission
from cmdb.interface.rest_api.routes.routes_helper import normalize_public_id_list, pin_public_id
from cmdb.interface.rest_api.routes.relation_routes.relation_constants import (
    MAX_BULK_DELETE_OBJECT_RELATIONS,
    BulkDeleteKey,
    OBJECT_RELATION_BULK_BODY_NOT_AN_OBJECT_MESSAGE,
    OBJECT_RELATION_BULK_NO_IDS_MESSAGE,
    OBJECT_RELATION_BULK_TOO_MANY_MESSAGE,
    OBJECT_RELATION_ENDPOINT_UNKNOWN_MESSAGE,
    OBJECT_RELATION_FIELD_DUPLICATE_MESSAGE,
    OBJECT_RELATION_FIELD_UNKNOWN_MESSAGE,
    OBJECT_RELATION_TYPE_NOT_ALLOWED_MESSAGE,
    OBJECT_RELATION_ACL_LOOKUP_FAILED_MESSAGE,
    OBJECT_RELATION_TABS_ACCESS_DENIED_MESSAGE,
    OBJECT_RELATION_TABS_OBJECT_NOT_FOUND_MESSAGE,
    OBJECT_RELATION_TABS_OBJECT_LOOKUP_FAILED_MESSAGE,
)
from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_access_helper import read_object_or_abort
from cmdb.interface.rest_api.routes.relation_routes.relation_structure_helper import duplicated_names

from cmdb.errors.manager import BaseManagerGetError, BaseManagerInitError
from cmdb.errors.manager.objects_manager import ObjectsManagerGetError
from cmdb.errors.manager.object_relation_logs_manager import (
    ObjectRelationLogsManagerBuildError,
    ObjectRelationLogsManagerInsertError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# Only what the endpoint check needs of an object: that it exists, and its type
ENDPOINT_PROJECTION: dict[str, int] = {CmdbObjectKey.PUBLIC_ID.value: 1, CmdbObjectKey.TYPE_ID.value: 1, '_id': 0}

# Keys of a counterpart summary returned for a relation-tab row
COUNTERPART_OBJECT_ID_KEY: str = 'object_id'
COUNTERPART_TYPE_LABEL_KEY: str = 'type_label'
COUNTERPART_ICON_KEY: str = 'icon'
COUNTERPART_SUMMARY_LINE_KEY: str = 'summary_line'


def resolve_unreadable_type_ids_or_abort(request_user: CmdbUser) -> list[int]:
    """
    Reads the CmdbTypes the caller may not read, the input of every object-relation read rule

    Args:
        request_user (CmdbUser): The caller

    Raises:
        HTTPException: 400 when the types could not be read

    Returns:
        list[int]: public_ids of the CmdbTypes the caller may not read; empty when nothing is denied
    """
    try:
        return resolve_denied_type_ids(request_user, AccessControlPermission.READ)
    except (BaseManagerGetError, BaseManagerInitError) as err:
        LOGGER.error("[resolve_unreadable_type_ids_or_abort] %s", err, exc_info=True)
        abort(400, OBJECT_RELATION_ACL_LOOKUP_FAILED_MESSAGE)


def is_object_relation_readable(object_relation: dict[str, Any], denied_type_ids: list[int]) -> bool:
    """
    Judges one CmdbObjectRelation by the types stamped for its two objects

    The single-document twin of ``build_readable_endpoints_condition``: a side with no type stamped is not refused

    Args:
        object_relation (dict[str, Any]): The stored CmdbObjectRelation
        denied_type_ids (list[int]): public_ids of the CmdbTypes the caller may not read

    Returns:
        bool: True when the caller may read the objects at both ends
    """
    denied: set[int] = set(denied_type_ids)

    return (object_relation.get(ObjectRelationKey.RELATION_PARENT_TYPE_ID.value) not in denied
            and object_relation.get(ObjectRelationKey.RELATION_CHILD_TYPE_ID.value) not in denied)


def read_tab_object_or_abort(object_id: int, request_user: CmdbUser, objects_manager: ObjectsManager) -> None:
    """
    Refuses the relation tabs of an object the caller may not read, or that does not exist

    Answers like ``GET /objects/<id>``. A missing object is refused too: deleting an object deletes its
    relations, so it has no tabs to answer

    Args:
        object_id (int): public_id of the object whose relation tabs are requested
        request_user (CmdbUser): The caller
        objects_manager (ObjectsManager): Manager used to read the object through the caller's ACL

    Raises:
        HTTPException: 403 when the caller may not read the object, 404 when it does not exist, 400 when reading
            it failed
    """
    try:
        read_object_or_abort(
            object_id,
            request_user,
            objects_manager,
            OBJECT_RELATION_TABS_ACCESS_DENIED_MESSAGE.format(object_id=object_id),
            OBJECT_RELATION_TABS_OBJECT_NOT_FOUND_MESSAGE.format(object_id=object_id),
        )
    except ObjectsManagerGetError as err:
        LOGGER.error("[read_tab_object_or_abort] %s", err, exc_info=True)
        abort(400, OBJECT_RELATION_TABS_OBJECT_LOOKUP_FAILED_MESSAGE.format(object_id=object_id))


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


def read_bulk_delete_selection(body: Any) -> list[int]:
    """
    Reads the selection of an ObjectRelation bulk delete from its request body

    The ids are normalised (numbers or digit strings) and de-duplicated in the order given, so an id named
    twice is deleted - and logged - once

    Args:
        body (Any): The parsed JSON body, expected to be an object carrying 'target_ids'

    Raises:
        HTTPException: 400 when the body is no object, the selection is missing, empty, not a list of
            positive ids, or names more than MAX_BULK_DELETE_OBJECT_RELATIONS distinct ids

    Returns:
        list[int]: The distinct public_ids to delete, in the order they were given
    """
    if not isinstance(body, dict):
        abort(400, OBJECT_RELATION_BULK_BODY_NOT_AN_OBJECT_MESSAGE.format(key=BulkDeleteKey.TARGET_IDS.value))

    target_ids: Any = body.get(BulkDeleteKey.TARGET_IDS.value)

    if not target_ids:
        abort(400, OBJECT_RELATION_BULK_NO_IDS_MESSAGE)

    selection: list[int] = list(dict.fromkeys(normalize_public_id_list(target_ids)))

    if len(selection) > MAX_BULK_DELETE_OBJECT_RELATIONS:
        abort(400, OBJECT_RELATION_BULK_TOO_MANY_MESSAGE.format(
            limit=MAX_BULK_DELETE_OBJECT_RELATIONS, count=len(selection),
        ))

    return selection


def delete_object_relations(
    object_relations_manager: ObjectRelationsManager,
    public_ids: list[int],
    deleted: list[dict[str, Any]],
) -> None:
    """
    Deletes the CmdbObjectRelations one atomic read-and-delete at a time, collecting what was deleted

    Each document is appended to `deleted` the moment it is gone, so a failure part-way leaves `deleted` holding
    exactly what was removed before it - the caller still logs those. An id another writer deleted first (or
    that never existed) is simply not collected

    Args:
        object_relations_manager (ObjectRelationsManager): Manager deleting the CmdbObjectRelations
        public_ids (list[int]): The public_ids to delete
        deleted (list[dict[str, Any]]): Receives every deleted document, in deletion order

    Raises:
        BaseManagerDeleteError: When a delete fails; the documents deleted before it are already in `deleted`
    """
    for public_id in public_ids:
        document: dict[str, Any] | None = object_relations_manager.find_one_and_delete(
            {ObjectRelationKey.PUBLIC_ID.value: public_id}
        )

        if document is not None:
            deleted.append(document)


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


def resolve_object_relation_endpoints(
        relation: dict[str, Any],
        parent_id: int | None,
        child_id: int | None,
        objects_manager: ObjectsManager,
        request_user: CmdbUser) -> tuple[int, int]:
    """
    Reads both endpoints of a CmdbObjectRelation write and answers their types, refusing what the relation forbids

    The endpoints are the ONLY source of the stored ``relation_parent_type_id`` / ``relation_child_type_id`` -
    the definition-update cascade deletes instances by those ids, so a client-supplied one could make it delete a
    valid instance or keep an invalid one. Refused with 400, in this order:

    * a missing endpoint, or the same object on both sides (``validate_object_relation_endpoints``)
    * an endpoint that does not exist, or whose type the caller may not READ - one answer for both, so it says
      nothing about objects the caller cannot see
    * an endpoint whose type the relation does not allow on that side: the parent's in ``parent_type_ids``, the
      child's in ``child_type_ids`` - the same per-side lists the cascade judges by

    One projected read of both objects, plus the caller's denied types (one projected read of the types,
    none at all when no type has an active ACL)

    Args:
        relation (dict[str, Any]): The referenced CmdbRelation, as stored
        parent_id (int | None): public_id of the parent CmdbObject, as sent
        child_id (int | None): public_id of the child CmdbObject, as sent
        objects_manager (ObjectsManager): Manager of the CmdbObjects
        request_user (CmdbUser): The user issuing the request

    Raises:
        werkzeug.exceptions.BadRequest: Aborts with 400 on any of the refusals above
        BaseManagerGetError: When reading the objects or the types fails

    Returns:
        tuple[int, int]: The parent's and the child's type public_id, to be stored
    """
    validate_object_relation_endpoints(parent_id, child_id)

    type_by_object: dict[int, int] = {
        document[CmdbObjectKey.PUBLIC_ID.value]: document[CmdbObjectKey.TYPE_ID.value]
        for document in objects_manager.find(
            criteria={CmdbObjectKey.PUBLIC_ID.value: {'$in': [parent_id, child_id]}},
            projection=ENDPOINT_PROJECTION,
        )
    }
    denied_type_ids: set[int] = set(resolve_denied_type_ids(request_user, AccessControlPermission.READ))

    sides: tuple[tuple[ObjectRelationRole, int, RelationKey], ...] = (
        (ObjectRelationRole.PARENT, parent_id, RelationKey.PARENT_TYPE_IDS),
        (ObjectRelationRole.CHILD, child_id, RelationKey.CHILD_TYPE_IDS),
    )

    for role, object_id, allowed_key in sides:
        type_id: int | None = type_by_object.get(object_id)

        if type_id is None or type_id in denied_type_ids:
            abort(HTTPStatus.BAD_REQUEST, OBJECT_RELATION_ENDPOINT_UNKNOWN_MESSAGE.format(
                role=role.value, public_id=object_id,
            ))

        if type_id not in (relation.get(allowed_key.value) or []):
            abort(HTTPStatus.BAD_REQUEST, OBJECT_RELATION_TYPE_NOT_ALLOWED_MESSAGE.format(
                relation_id=relation.get(RelationKey.PUBLIC_ID.value), type_id=type_id, role=role.value,
            ))

    return type_by_object[parent_id], type_by_object[child_id]


def object_relation_field_values_blocker(relation: dict[str, Any], field_values: list[Any] | None) -> str | None:
    """
    Reports why a CmdbObjectRelation's field values do not fit its CmdbRelation, if they do not

    Every value has to name a field the relation DECLARES (its flat ``fields`` list), and each name may appear
    once. A value under any other name would be shown in the relation tab and never reached by the relation's
    field cascade, which only knows the declared names. The entry SHAPE (a dict with a non-blank ``name``) is
    the schema's job

    Args:
        relation (dict[str, Any]): The referenced CmdbRelation, as stored
        field_values (list[Any] | None): The ``field_values`` of the write; nothing to judge when absent

    Returns:
        str | None: The reason the values are refused, or None when they fit
    """
    names: list[str] = [
        entry.get(ObjectRelationFieldValueKey.NAME.value)
        for entry in (field_values or []) if isinstance(entry, dict)
    ]
    declared: set[str] = {
        field.get(FieldKey.NAME.value)
        for field in (relation.get(RelationKey.FIELDS.value) or []) if isinstance(field, dict)
    }

    undeclared: list[str] = [name for name in names if name not in declared]

    if undeclared:
        return OBJECT_RELATION_FIELD_UNKNOWN_MESSAGE.format(
            relation_id=relation.get(RelationKey.PUBLIC_ID.value), names=', '.join(map(str, undeclared)),
        )

    repeated: list[str] = duplicated_names(names)

    if repeated:
        return OBJECT_RELATION_FIELD_DUPLICATE_MESSAGE.format(names=', '.join(repeated))

    return None


def guard_object_relation_field_values(relation: dict[str, Any], field_values: list[Any] | None) -> None:
    """
    Refuses a CmdbObjectRelation write whose field values do not fit its CmdbRelation

    Args:
        relation (dict[str, Any]): The referenced CmdbRelation, as stored
        field_values (list[Any] | None): The ``field_values`` of the write

    Raises:
        werkzeug.exceptions.BadRequest: Aborts with 400 naming the undeclared or repeated names
    """
    blocker: str | None = object_relation_field_values_blocker(relation, field_values)

    if blocker:
        abort(HTTPStatus.BAD_REQUEST, blocker)


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


def handle_deleted_type_ids(relation_id: int,
                            old_relation: dict[str, Any],
                            new_relation: dict[str, Any],
                            object_relations_manager: ObjectRelationsManager) -> None:
    """
    Deletes the ObjectRelations invalidated by removed parent/child CmdbTypes

    Compares the allowed parent and child CmdbTypes of the old vs. new relation; for every type
    that is no longer allowed, the corresponding CmdbObjectRelations are deleted.

    A stored relation that carries no type list at all (the lists are required on write, but older
    stored data may lack them) is read as an empty list, so the comparison reports nothing removed instead of
    failing the whole update with a KeyError.

    Args:
        relation_id (int): public_id of the CmdbRelation whose instances are reconciled
        old_relation (dict[str, Any]): The relation before the change
        new_relation (dict[str, Any]): The relation after the change
        object_relations_manager (ObjectRelationsManager): Manager for CmdbObjectRelations
    """
    deleted_parent_ids: list[int] = get_deleted_type_ids(
        old_relation.get(RelationKey.PARENT_TYPE_IDS.value) or [],
        new_relation.get(RelationKey.PARENT_TYPE_IDS.value) or [],
    )

    if deleted_parent_ids:
        object_relations_manager.delete_invalidated_object_relations(relation_id, deleted_parent_ids, True)

    deleted_child_ids: list[int] = get_deleted_type_ids(
        old_relation.get(RelationKey.CHILD_TYPE_IDS.value) or [],
        new_relation.get(RelationKey.CHILD_TYPE_IDS.value) or [],
    )

    if deleted_child_ids:
        object_relations_manager.delete_invalidated_object_relations(relation_id, deleted_child_ids, False)


def get_added_and_removed_fields(old_relation: dict[str, Any],
                                 new_relation: dict[str, Any]) -> dict[str, list[str]]:
    """
    Compares the 'sections' of two CmdbRelations to find which fields were added or removed

    Collects every field identifier referenced by the sections of each relation and returns the set
    difference in both directions. Pure data work: it reads two dicts and needs no database, which is
    why it lives here and not on the RelationsManager

    Args:
        old_relation (dict[str, Any]): The CmdbRelation before the change (carries 'sections')
        new_relation (dict[str, Any]): The CmdbRelation after the change (carries 'sections')

    Returns:
        dict[str, list[str]]: A dict with keys 'added' and 'removed', each a list of the field
            identifiers that were added to / removed from the relation's sections
    """
    old_fields: set[str] = set()
    new_fields: set[str] = set()

    # Collect every field identifier referenced across the relation's sections
    for section in old_relation.get(RelationKey.SECTIONS.value) or []:
        old_fields.update(section.get(RelationKey.FIELDS.value) or [])

    for section in new_relation.get(RelationKey.SECTIONS.value) or []:
        new_fields.update(section.get(RelationKey.FIELDS.value) or [])

    return {
        RelationDiffKey.ADDED.value: list(new_fields - old_fields),
        RelationDiffKey.REMOVED.value: list(old_fields - new_fields),
    }


def validate_relation_type_ids(types_manager: TypesManager, relation_data: dict[str, Any]) -> None:
    """
    Validates that a CmdbRelation only allows CmdbTypes that exist

    Both id lists are checked in a single existence query. A relation pointing at a CmdbType that
    was never created (or that a caller invented) would offer a parent / child side no object can
    ever fill, so the write is refused with 400 instead of storing the dangling ids.

    Args:
        types_manager (TypesManager): Manager used to check which of the referenced types exist
        relation_data (dict[str, Any]): The CmdbRelation payload to validate

    Raises:
        TypesManagerGetError: If the existence lookup fails
    """
    referenced_ids: list[int] = [
        *(relation_data.get(RelationKey.PARENT_TYPE_IDS.value) or []),
        *(relation_data.get(RelationKey.CHILD_TYPE_IDS.value) or []),
    ]

    if not referenced_ids:
        return

    existing_ids: set[int] = types_manager.get_existing_type_ids(referenced_ids)
    unknown_ids: list[int] = sorted({type_id for type_id in referenced_ids if type_id not in existing_ids})

    if unknown_ids:
        abort(400, f"The Relation references Types which do not exist: {unknown_ids}!")


def apply_relation_update(public_id: int,
                          data: dict[str, Any],
                          old_relation: dict[str, Any],
                          relations_manager: RelationsManager) -> tuple[CmdbRelation, dict[str, list[str]]]:
    """
    Persists the updated CmdbRelation and reports the section/field diff of that update

    The identity is pinned to the route's public_id so a forged body public_id cannot rewrite the
    document, and the diff is computed from the in-memory old/new data BEFORE anything is written, so
    the caller still has it if the write fails. Only the relation itself is touched here - its
    dependent CmdbObjectRelations are reconciled afterwards by ``cascade_relation_update``

    Args:
        public_id (int): public_id of the CmdbRelation being updated (the URL's, not the body's)
        data (dict[str, Any]): The new CmdbRelation data (mutated: its public_id is pinned)
        old_relation (dict[str, Any]): The stored CmdbRelation as it was before this update
        relations_manager (RelationsManager): Manager performing the write

    Raises:
        CmdbRelationInitFromDataError: If the payload cannot be turned into a CmdbRelation
        RelationsManagerUpdateError: If the update itself fails

    Returns:
        tuple[CmdbRelation, dict[str, list[str]]]: The stored CmdbRelation and the
            ``{'added': [...], 'removed': [...]}`` diff of its section fields
    """
    pin_public_id(data, public_id)

    # Compute the diff from the in-memory old/new data before any persistence
    changed_fields: dict[str, list[str]] = get_added_and_removed_fields(old_relation, data)
    relation: CmdbRelation = CmdbRelation.from_data(data)

    relations_manager.update_relation(public_id, relation)

    return relation, changed_fields


def cascade_relation_update(relation_id: int,
                            old_relation: dict[str, Any],
                            new_relation: dict[str, Any],
                            changed_fields: dict[str, list[str]],
                            object_relations_manager: ObjectRelationsManager) -> None:
    """
    Reconciles the CmdbObjectRelations that depend on an already-updated CmdbRelation

    Two things follow from a changed definition: instances whose parent / child CmdbType is no longer
    allowed are deleted, and the remaining instances gain / lose the field values the relation's
    sections gained / lost. Both are server-side operations.

    This runs AFTER the relation itself was persisted, so a failure here leaves the relation updated
    and its instances behind - the caller has to report that partial application rather than claim
    the update failed

    Args:
        relation_id (int): public_id of the updated CmdbRelation
        old_relation (dict[str, Any]): The CmdbRelation before the update
        new_relation (dict[str, Any]): The CmdbRelation data that was stored
        changed_fields (dict[str, list[str]]): The ``added`` / ``removed`` section-field diff
        object_relations_manager (ObjectRelationsManager): Manager for the dependent instances

    Raises:
        BaseManagerDeleteError: If deleting the invalidated CmdbObjectRelations fails
        BaseManagerUpdateError: If applying the field diff to the CmdbObjectRelations fails
    """
    handle_deleted_type_ids(relation_id, old_relation, new_relation, object_relations_manager)
    object_relations_manager.update_changed_fields(relation_id, changed_fields)
