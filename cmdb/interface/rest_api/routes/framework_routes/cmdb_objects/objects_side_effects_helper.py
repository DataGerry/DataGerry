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
What a CmdbObject write owes the rest of the database

Everything that happens AFTER an object has been stored or removed: the webhook notification, the
change log, the location and object-group cleanup, the relation cleanup and the update / state-change
events. The cloud config-item count is reported by ``cmdb.framework.config_item_sync``, which the object
importer shares.

**Every function here is best-effort by design.** Each catches and logs its own failures, because a
webhook that cannot be reached or a log that cannot be written must not roll back an object the user
successfully saved. The trade-off is real: a successful write can leave no audit entry, and the caller
is not told. **The change log is observable, though:** every entry goes through `log_object_change` /
`write_object_log`, and an entry that could not be written is logged under the fixed
``OBJECT_LOG_LOST`` marker with the action, the object id and the traceback, so an operator can alert
on it. Every entry stores the object **as rendered**, which is what the log view draws.

`handle_delete_invalid_object_relations` deletes exactly the relations it read and logs each one, reading
again until none are left, so a relation created while it runs is neither left on a deleted object nor
removed unlogged.

Kept apart from `objects_helper.py` so that module stays under pylint's 1,500-line cap. The group is
closed: nothing here calls back into the write pipelines, so the import runs one way
"""
import json
from logging import Logger, getLogger
from typing import Any

from flask import abort
from werkzeug.exceptions import HTTPException

from cmdb.database.json_codec import default

from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.manager import (
    ObjectsManager,
    LogsManager,
    LocationsManager,
    ObjectGroupsManager,
    ObjectRelationsManager,
    ObjectRelationLogsManager,
)
from cmdb.models.user_model.cmdb_user import CmdbUser
from cmdb.models.object_model.cmdb_object import CmdbObject
from cmdb.models.object_model import CmdbObjectKey
from cmdb.models.webhook_model.webhook_event_type_enum import WebhookEventType
from cmdb.models.object_group_model import ObjectGroupMode
from cmdb.models.log_model import LogInteraction
from cmdb.models.log_model.log_action_enum import LogAction
from cmdb.models.log_model.cmdb_object_log import CmdbObjectLog
from cmdb.models.log_model.object_log_constants import ObjectLogKey
from cmdb.framework.rendering.render_result import RenderResult
from cmdb.framework.rendering.render_constants import RenderTypeInfoKey
from cmdb.framework.rendering.cmdb_multi_render import CmdbMultiRender
from cmdb.framework.object_edit import ObjectWrite, ObjectWriteCallback
from cmdb.interface.rest_api.routes.framework_routes.cmdb_locations.location_helper import (
    delete_location_with_reparenting,
)
from cmdb.models.object_relation_model import ObjectRelationKey
from cmdb.utils import Builder
from cmdb.interface.rest_api.routes.webhook_routes.webhook_helper import send_webhook_event
from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_constants import (
    OBJECT_LOG_LOST_MARKER,
    RELATION_CASCADE_MAX_ROUNDS,
    ObjectLogComment,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# The only keys `format_object_relation_log_data` reads for a DELETE entry; everything else on a
# CmdbObjectRelation is irrelevant to the log, so the cascade reads back just these three
RELATION_DELETE_LOG_PROJECTION: dict[str, int] = {
    ObjectRelationKey.PUBLIC_ID.value: 1,
    ObjectRelationKey.RELATION_PARENT_ID.value: 1,
    ObjectRelationKey.RELATION_CHILD_ID.value: 1,
}

# -------------------------------------------------------------------------------------------------------------------- #

def handle_notify_webhooks(
        request_user: CmdbUser,
        target_object: CmdbObject,
        event_type: WebhookEventType
    ) -> None:
    """
    Emits a CREATE or DELETE webhook event for a CmdbObject

    Failures are caught and logged so a webhook problem never blocks the surrounding object
    operation

    Args:
        request_user (CmdbUser): The CmdbUser making the request
        target_object (CmdbObject): The CmdbObject the event is about
        event_type (WebhookEventType): The webhook event type to emit (CREATE or DELETE)
    """
    try:
        if event_type == WebhookEventType.CREATE:
            send_webhook_event(request_user, event_type, object_after=CmdbObject.to_json(target_object))

        if event_type == WebhookEventType.DELETE:
            send_webhook_event(request_user, event_type, object_before=CmdbObject.to_json(target_object))
    except Exception as err:
        LOGGER.error("[handle_notify_webhooks] Send Webhook Event Exception: %s, Type:%s", err, type(err))


def render_single_object(target_object: CmdbObject, request_user: CmdbUser) -> RenderResult | None:
    """
    Renders one CmdbObject, or returns None when it cannot be rendered

    ``CmdbMultiRender.result(single_object=True)`` is typed to return a list, a single result or
    None - it yields None when the object's type is gone. This narrows that union to the one shape
    callers can use, so a missing render is an explicit None instead of an AttributeError inside a
    caller's except arm

    Args:
        target_object (CmdbObject): The CmdbObject to render
        request_user (CmdbUser): The CmdbUser the render is performed for (drives ACL and references)

    Returns:
        RenderResult | None: The rendered object, or None when it could not be rendered
    """
    rendered: list[RenderResult] | RenderResult | None = CmdbMultiRender(
        [target_object],
        request_user,
    ).result(single_object=True)

    return rendered if isinstance(rendered, RenderResult) else None


def report_lost_object_log(action: LogAction, object_id: Any, reason: str, with_traceback: bool = False) -> None:
    """
    Logs that a change-log entry of a CmdbObject could not be written

    Always under ``OBJECT_LOG_LOST_MARKER``, so every lost entry can be found by one search whatever
    lost it

    Args:
        action (LogAction): The action the entry would have recorded
        object_id (Any): public_id of the object the entry was about
        reason (str): Why the entry is missing
        with_traceback (bool): Whether to attach the exception being handled. Defaults to False
    """
    LOGGER.error(
        "%s action=%s object_id=%s: %s",
        OBJECT_LOG_LOST_MARKER, action.name, object_id, reason,
        exc_info=with_traceback,
    )


def build_object_log_data(
        request_user: CmdbUser,
        object_id: int,
        version: str,
        comment: str,
        render_result: RenderResult,
        changes: Any = None,
    ) -> dict[str, Any]:
    """
    Builds the entry a CmdbObjectLog stores for one change of a CmdbObject

    Args:
        request_user (CmdbUser): The user credited with the change
        object_id (int): public_id of the changed object
        version (str): The object's version the entry records
        comment (str): The comment stored on the entry
        render_result (RenderResult): The object as rendered - the log view draws it with the renderer, and
            its type information names the type the entry is stamped with
        changes (Any): The field-level diff, or None when the action records none. Defaults to None

    Returns:
        dict[str, Any]: The keyword arguments `LogsManager.insert_log` stores
    """
    log_data: dict[str, Any] = {
        ObjectLogKey.OBJECT_ID.value: object_id,
        ObjectLogKey.VERSION.value: version,
        ObjectLogKey.USER_ID.value: request_user.get_public_id(),
        ObjectLogKey.USER_NAME.value: request_user.get_display_name(),
        ObjectLogKey.COMMENT.value: comment,
        ObjectLogKey.RENDER_STATE.value: json.dumps(render_result, default=default).encode('UTF-8'),
        # What the log reads are judged by: the type ACL stage matches on it, also once the object is gone
        ObjectLogKey.TYPE_ID.value: render_result.type_information.get(RenderTypeInfoKey.TYPE_ID.value),
    }

    if changes is not None:
        log_data[ObjectLogKey.CHANGES.value] = changes

    return log_data


def write_object_log(logs_manager: LogsManager, action: LogAction, log_data: dict[str, Any]) -> bool:
    """
    Writes one CmdbObjectLog entry, best-effort

    The object write this entry follows is already stored, so nothing here may fail it: any error is
    reported under ``OBJECT_LOG_LOST_MARKER`` with its traceback and answered with False

    Args:
        logs_manager (LogsManager): Manager used to persist the entry
        action (LogAction): The action the entry records
        log_data (dict[str, Any]): The entry (see `build_object_log_data`)

    Returns:
        bool: True when the entry was written
    """
    try:
        logs_manager.insert_log(action=action, log_type=CmdbObjectLog.__name__, **log_data)

        return True
    except Exception:  # pylint: disable=broad-exception-caught
        report_lost_object_log(
            action, log_data.get(ObjectLogKey.OBJECT_ID.value), 'the log entry could not be written',
            with_traceback=True,
        )

        return False


def log_object_change(
        request_user: CmdbUser,
        logs_manager: LogsManager,
        action: LogAction,
        target_object: CmdbObject,
        comment: str,
        version: str | None = None,
        changes: Any = None,
    ) -> bool:
    """
    Renders a CmdbObject and writes its change-log entry, best-effort

    The one path every single-object log entry takes: render, build, write. An object that cannot be
    rendered (its type is gone) and any error on the way are reported under ``OBJECT_LOG_LOST_MARKER``
    and answered with False - never raised, because the object write is already done

    Args:
        request_user (CmdbUser): The user credited with the change; the render is performed for them
        logs_manager (LogsManager): Manager used to persist the entry
        action (LogAction): The action the entry records
        target_object (CmdbObject): The object as it is after the change
        comment (str): The comment stored on the entry
        version (str | None): The version to record; the rendered object's own when None
        changes (Any): The field-level diff, or None. Defaults to None

    Returns:
        bool: True when the entry was written
    """
    object_id: int = target_object.get_public_id()

    try:
        render_result: RenderResult | None = render_single_object(target_object, request_user)

        if render_result is None:
            report_lost_object_log(action, object_id, 'the object could not be rendered')

            return False

        # pylint cannot narrow the union CmdbMultiRender.result declares, so it reads the value as a
        # list here; render_single_object above guarantees a RenderResult
        recorded_version: str = version or render_result.object_information['version']  # pylint: disable=no-member

        log_data: dict[str, Any] = build_object_log_data(
            request_user, object_id, recorded_version, comment, render_result, changes,
        )
    except Exception:  # pylint: disable=broad-exception-caught
        report_lost_object_log(action, object_id, 'the log entry could not be built', with_traceback=True)

        return False

    return write_object_log(logs_manager, action, log_data)


def handle_create_object_log(
        request_user: CmdbUser,
        target_object: CmdbObject,
        log_action: LogAction
    ) -> None:
    """
    Writes a CmdbObjectLog entry for a created or deleted CmdbObject

    Best-effort through `log_object_change`: a create or delete can succeed while leaving no audit entry,
    and the caller is not told - the loss is logged under ``OBJECT_LOG_LOST_MARKER``

    Args:
        request_user (CmdbUser): The CmdbUser making the request
        target_object (CmdbObject): The CmdbObject the log entry is about
        log_action (LogAction): The log action to record (CREATE or DELETE)
    """
    comment: str = ObjectLogComment.DELETED.value if log_action == LogAction.DELETE else ObjectLogComment.CREATED.value

    try:
        logs_manager: LogsManager = ManagerProvider.get_manager(ManagerType.LOGS, request_user)
    except Exception:  # pylint: disable=broad-exception-caught
        report_lost_object_log(
            log_action, target_object.get_public_id(), 'no logs manager could be resolved', with_traceback=True,
        )

        return

    log_object_change(request_user, logs_manager, log_action, target_object, comment)


def handle_delete_object_location(
        request_user: CmdbUser,
        public_id: int,
        locations_manager: LocationsManager | None = None,
        objects_manager: ObjectsManager | None = None) -> None:
    """
    Deletes the CmdbLocation of an object, promoting its direct children

    A no-op when the object has no location. When the location exists it is deleted and its direct
    child locations are re-parented onto its own parent (their grandparent) by
    LocationsManager.delete_location, so a location with children is deletable and the subtree
    stays connected

    Callers already holding the managers (e.g. a bulk-delete loop) can pass them in to avoid a
    ManagerProvider lookup per object; when omitted they are resolved on demand

    Args:
        request_user (CmdbUser): The CmdbUser making the request
        public_id (int): public_id of the CmdbObject whose location should be removed
        locations_manager (LocationsManager | None): Optional pre-resolved CmdbLocations manager
        objects_manager (ObjectsManager | None): Optional pre-resolved CmdbObjects manager

    Raises:
        HTTPException: 500 on an unexpected error
    """
    try:
        if locations_manager is None:
            locations_manager = ManagerProvider.get_manager(ManagerType.LOCATIONS, request_user)

        object_location: dict[str, Any] | None = locations_manager.get_location_for_object(public_id)

        if object_location:
            if objects_manager is None:
                objects_manager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
            delete_location_with_reparenting(object_location, locations_manager, objects_manager)
    except HTTPException as http_err:
        raise http_err
    except Exception as error:
        LOGGER.error(
            "[handle_delete_object_location] Locations Exception: %s. Type: %s", error, type(error), exc_info=True
        )
        abort(500, "An internal server error occured while handling Locations of this Object!")


def handle_delete_from_object_groups(request_user: CmdbUser, public_ids: int | list[int]) -> None:
    """
    Removes one or more CmdbObjects from every static CmdbObjectGroup

    Args:
        request_user (CmdbUser): The CmdbUser making the request
        public_ids (int | list[int]): A single object public_id or a list of them to remove
    """
    object_groups_manager: ObjectGroupsManager = ManagerProvider.get_manager(ManagerType.OBJECT_GROUP, request_user)

    object_groups_manager.remove_ids_from_groups(public_ids, ObjectGroupMode.STATIC)


def handle_delete_invalid_object_relations(request_user: CmdbUser, public_ids: list[int]) -> None:
    """
    Deletes the CmdbObjectRelations of removed objects and logs each deletion

    Every relation in which one of the objects appears as parent or child is removed, with one
    CmdbObjectRelationLog per removed relation. The single delete passes its one object; the bulk delete passes
    its whole selection, so a selection costs one read, one delete and one log batch rather than one of each per
    object. A no-op without objects or without relations.

    **Exactly what was read is deleted and logged.** Each round reads the matching relations, prepares their
    DELETE logs, deletes those ids - never the query - and writes the logs; then it reads again, so a relation
    created while the cascade ran is deleted and logged in the next round instead of being left on a deleted
    object or removed unlogged. After ``RELATION_CASCADE_MAX_ROUNDS`` rounds the rest is left with a warning.
    A relation the relation routes deleted between the read and the delete is logged by both.

    The log ids are reserved as one batch and paired with ``zip(..., strict=True)``: ``insert_many(
    skip_public=True)`` requires every document to carry a ``public_id``, so a short reservation fails loudly
    rather than inserting entries with the key missing

    Args:
        request_user (CmdbUser): The CmdbUser making the request
        public_ids (list[int]): public_ids of the deleted CmdbObjects whose relations should be removed
    """
    if not public_ids:
        return

    object_relations_manager: ObjectRelationsManager = ManagerProvider.get_manager(
        ManagerType.OBJECT_RELATIONS,
        request_user
    )
    object_relation_logs_manager: ObjectRelationLogsManager = ManagerProvider.get_manager(
        ManagerType.OBJECT_RELATION_LOGS,
        request_user
    )

    related_relations_query: dict[str, Any] = object_relations_manager.get_relations_of_objects_query(public_ids)

    for _round in range(RELATION_CASCADE_MAX_ROUNDS):
        # Only the three keys the DELETE log entry carries are read back - the full documents are never needed
        affected_relations: list[dict[str, Any]] = object_relations_manager.find(
            criteria=related_relations_query,
            projection=RELATION_DELETE_LOG_PROJECTION,
        )

        if not affected_relations:
            return

        # Prepared BEFORE the delete, so a relation whose entry cannot be built is known before it is gone
        logs_to_create: list[dict[str, Any]] = prepare_relation_delete_logs(
            request_user, object_relation_logs_manager, affected_relations,
        )

        object_relations_manager.delete_many(Builder.in_(
            ObjectRelationKey.PUBLIC_ID.value,
            [relation[ObjectRelationKey.PUBLIC_ID.value] for relation in affected_relations],
        ))

        write_relation_delete_logs(object_relation_logs_manager, logs_to_create)

    LOGGER.warning(
        "[handle_delete_invalid_object_relations] Relations of the deleted objects %s kept appearing; "
        "stopped after %d rounds", public_ids, RELATION_CASCADE_MAX_ROUNDS,
    )


def prepare_relation_delete_logs(
        request_user: CmdbUser,
        object_relation_logs_manager: ObjectRelationLogsManager,
        relations: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
    """
    Builds the DELETE log entry of each relation, skipping (and logging) one that cannot be built

    Args:
        request_user (CmdbUser): The CmdbUser making the request, recorded as the author
        object_relation_logs_manager (ObjectRelationLogsManager): Builds the entries
        relations (list[dict[str, Any]]): The relations about to be deleted (``RELATION_DELETE_LOG_PROJECTION``)

    Returns:
        list[dict[str, Any]]: One entry per relation that could be built, without a public_id yet
    """
    logs_to_create: list[dict[str, Any]] = []

    for relation in relations:
        try:
            logs_to_create.append(object_relation_logs_manager.format_object_relation_log_data(
                LogInteraction.DELETE, request_user, relation, None,
            ))
        except Exception as error:
            LOGGER.error("[handle_delete_invalid_object_relations] Failed to prepare log. Error: %s",
                         error, exc_info=True)

    return logs_to_create


def write_relation_delete_logs(
        object_relation_logs_manager: ObjectRelationLogsManager,
        logs_to_create: list[dict[str, Any]],
    ) -> None:
    """
    Stores prepared DELETE log entries with one id reservation and one insert

    Args:
        object_relation_logs_manager (ObjectRelationLogsManager): Reserves the ids and inserts the entries
        logs_to_create (list[dict[str, Any]]): The prepared entries; a no-op when empty

    Raises:
        ValueError: When the reservation returns fewer ids than entries (``zip(..., strict=True)``)
    """
    if not logs_to_create:
        return

    reserved_log_ids: list[int] = object_relation_logs_manager.reserve_public_ids(len(logs_to_create))

    # strict: insert_many(skip_public=True) requires EVERY document to carry a public_id, so a short
    # id batch must fail loudly here instead of inserting logs with the key missing
    for log_doc, new_id in zip(logs_to_create, reserved_log_ids, strict=True):
        log_doc[CmdbObjectKey.PUBLIC_ID.value] = new_id

    object_relation_logs_manager.insert_many(logs_to_create, skip_public=True)


def emit_object_update_events(
        request_user: CmdbUser,
        logs_manager: LogsManager,
        before_object: CmdbObject,
        after_object: CmdbObject,
        updated_object: CmdbObject,
        changes: dict[str, Any],
        update_comment: str,
    ) -> None:
    """
    Emits the UPDATE webhook and writes the edit log for an updated CmdbObject

    Both steps are best-effort and isolated: a webhook or logging failure is caught and logged so it
    never blocks the object update

    Args:
        request_user (CmdbUser): The CmdbUser making the request
        logs_manager (LogsManager): Manager used to persist the edit log
        before_object (CmdbObject): The object state before the update (webhook payload)
        after_object (CmdbObject): The re-read object state after the update (webhook payload)
        updated_object (CmdbObject): The candidate object carrying the bumped version / render_state
        changes (dict[str, Any]): The field-level diff recorded on the webhook and log
        update_comment (str): The user-supplied comment stored on the edit log
    """
    try:
        send_webhook_event(request_user,
                           WebhookEventType.UPDATE,
                           CmdbObject.to_json(before_object),
                           CmdbObject.to_json(after_object),
                           changes)
    except Exception as error:
        LOGGER.error("[emit_object_update_events] Send Webhook Event Exception: %s, Type:%s", error, type(error))

    # The entry stores the object AS RENDERED - the log view draws it with the object renderer, so the
    # stored document (which carries no type, section or summary information) would render empty
    log_object_change(
        request_user, logs_manager, LogAction.EDIT, after_object, update_comment,
        version=updated_object.get_version(), changes=changes,
    )


def build_object_write_emitter(request_user: CmdbUser, comment: str) -> ObjectWriteCallback:
    """
    Builds the callback a framework write hands each stored CmdbObject edit to

    A feature that writes objects outside the REST update pipeline (the IPAM unassign writes) cannot
    import this layer, so its orchestrator takes a callback instead. This one emits what the REST
    update emits for an edit: the UPDATE webhook and the EDIT change-log entry, both best-effort
    through ``emit_object_update_events``. The LogsManager is resolved on the first write the callback
    is handed and reused for the rest, so a request refused before anything is written resolves none

    Args:
        request_user (CmdbUser): The CmdbUser credited with the edits
        comment (str): The comment stored on every change-log entry

    Returns:
        ObjectWriteCallback: Emits the events of one ``ObjectWrite``
    """
    resolved: list[LogsManager] = []

    def emit(write: ObjectWrite) -> None:
        if not resolved:
            resolved.append(ManagerProvider.get_manager(ManagerType.LOGS, request_user))

        emit_object_update_events(
            request_user, resolved[0], write.before, write.after, write.after, write.changes, comment,
        )

    return emit


def emit_object_state_change_events(
        request_user: CmdbUser,
        logs_manager: LogsManager,
        before_object: CmdbObject,
        after_object: CmdbObject,
        render_result: RenderResult,
        state: bool,
    ) -> None:
    """
    Emits the UPDATE webhook and writes the ACTIVE_CHANGE log for an object activation toggle

    Both steps are best-effort and isolated: a webhook or logging failure is caught and logged so it
    never blocks the state change itself

    Args:
        request_user (CmdbUser): The CmdbUser making the request
        logs_manager (LogsManager): Manager used to persist the state-change log
        before_object (CmdbObject): The object carrying the pre-read version used on webhook + log
        after_object (CmdbObject): The re-read object state after the toggle (webhook 'after' payload)
        render_result (RenderResult): The rendered object captured for the log's render_state
        state (bool): The new active state
    """
    try:
        send_webhook_event(request_user,
                           WebhookEventType.UPDATE,
                           CmdbObject.to_json(before_object),
                           CmdbObject.to_json(after_object),
                           {'state': state})
    except Exception as error:
        LOGGER.error(
            "[emit_object_state_change_events] Send Webhook Event Exception: %s, Type:%s", error, type(error)
        )

    change: dict[str, bool] = {'old': not state, 'new': state}

    try:
        log_data: dict[str, Any] = build_object_log_data(
            request_user, before_object.get_public_id(), before_object.version,
            ObjectLogComment.ACTIVE_CHANGED.value, render_result, change,
        )
    except Exception:  # pylint: disable=broad-exception-caught
        report_lost_object_log(
            LogAction.ACTIVE_CHANGE, before_object.get_public_id(), 'the log entry could not be built',
            with_traceback=True,
        )

        return

    write_object_log(logs_manager, LogAction.ACTIVE_CHANGE, log_data)
