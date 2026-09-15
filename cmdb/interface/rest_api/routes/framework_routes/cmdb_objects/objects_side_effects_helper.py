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
change log, the location and object-group cleanup, the relation cleanup, the cloud config-item count
and the update / state-change events.

**Every function here is best-effort by design.** Each catches and logs its own failures, because a
webhook that cannot be reached or a log that cannot be written must not roll back an object the user
successfully saved. The trade-off is real and recorded: a successful write can leave no audit entry
with nothing surfaced to the caller - discussion-backlog #160. `handle_delete_invalid_object_relations`
carries a second one, #162: it reads the affected relations and deletes by the same QUERY rather than
by the ids it read, so a relation created between the two is deleted but never logged.

Split out of `objects_helper.py` on 2026-09-11, with the PATCH cluster, when that module passed
pylint's 1,500-line cap. The group is closed: nothing here calls back into the write pipelines, so the
import runs one way
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
    TypesManager,
    LogsManager,
    LocationsManager,
    ObjectGroupsManager,
    ObjectRelationsManager,
    ObjectRelationLogsManager,
    DgServicePortalManager,
)
from cmdb.models.user_model.cmdb_user import CmdbUser
from cmdb.models.object_model.cmdb_object import CmdbObject
from cmdb.models.object_model import CmdbObjectKey
from cmdb.models.type_model.cmdb_type import CmdbType
from cmdb.models.webhook_model.webhook_event_type_enum import WebhookEventType
from cmdb.models.object_group_model import ObjectGroupMode
from cmdb.models.log_model import LogInteraction
from cmdb.models.log_model.log_action_enum import LogAction
from cmdb.models.log_model.cmdb_object_log import CmdbObjectLog
from cmdb.framework.rendering.render_result import RenderResult
from cmdb.framework.rendering.cmdb_multi_render import CmdbMultiRender
from cmdb.interface.rest_api.routes.framework_routes.cmdb_locations.location_helper import (
    delete_location_with_reparenting,
)
from cmdb.models.object_relation_model import ObjectRelationKey
from cmdb.interface.rest_api.routes.webhook_routes.webhook_helper import send_webhook_event
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


def handle_create_object_log(
        request_user: CmdbUser,
        target_object: CmdbObject,
        log_action: LogAction
    ) -> None:
    """
    Writes a CmdbObjectLog entry for a created or deleted CmdbObject

    Renders the object to capture its render_state in the log. **Best-effort:** every failure - a
    render that yields nothing because the object's type is gone, or anything raised while writing
    the entry - is caught and logged so a logging problem never blocks the surrounding object
    operation. The consequence is that a create or delete can succeed while leaving no audit entry,
    and the caller is not told (discussion-backlog #160)

    Args:
        request_user (CmdbUser): The CmdbUser making the request
        target_object (CmdbObject): The CmdbObject the log entry is about
        log_action (LogAction): The log action to record (CREATE or DELETE)
    """
    try:
        rendered_object: RenderResult | None = render_single_object(target_object, request_user)

        # Without this guard the AttributeError on the render below is swallowed by the except arm
        # and the log entry silently disappears while the object operation still reports success
        if rendered_object is None:
            LOGGER.error(
                "[handle_create_object_log] Object with ID:%s could not be rendered; no ObjectLog written",
                target_object.get_public_id(),
            )

            return

        logs_manager: LogsManager = ManagerProvider.get_manager(ManagerType.LOGS, request_user)

        log_comment: str = "Object created"

        if log_action == LogAction.DELETE:
            log_comment = "Object was deleted"

        # pylint cannot narrow the union CmdbMultiRender.result declares, so it reads the value as a
        # list here; render_single_object above guarantees a RenderResult
        log_data: dict[str, Any] = {
            # pylint: disable=no-member
            'object_id': rendered_object.object_information['object_id'],
            'version': rendered_object.object_information['version'],
            # pylint: enable=no-member
            'user_id': request_user.get_public_id(),
            'user_name': request_user.get_display_name(),
            'comment': log_comment,
            'render_state': json.dumps(rendered_object, default=default).encode('UTF-8')
        }

        logs_manager.insert_log(action=log_action, log_type=CmdbObjectLog.__name__, **log_data)
    except Exception as err:
        LOGGER.error("[handle_create_object_log] Failed to create ObjectLog. Error: %s", err)


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


def build_type_object_counts(request_user: CmdbUser) -> tuple[list[dict[str, Any]], int]:
    """
    Builds the per-type object-count list for the Service Portal sync payload

    Counts every CmdbObject grouped by its type_id in a single aggregation, then resolves each
    type_id to its CmdbType label via one bulk lookup. CmdbTypes with no objects are omitted, and
    a counted type_id whose CmdbType no longer exists is skipped - so the returned breakdown may
    sum to less than the total. The total is taken from the same aggregation and counts every
    document (no active filter), so it always equals an unfiltered ``count_documents()``

    Args:
        request_user (CmdbUser): The CmdbUser making the request

    Returns:
        tuple[list[dict[str, Any]], int]: Entries shaped ``{"name": <type label>, "count": <int>}``
            and the exact total number of CmdbObjects
    """
    objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
    types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)

    counts_by_type, total_count = objects_manager.count_objects_grouped_by_type_with_total()

    if not counts_by_type:
        return [], total_count

    types_lookup: dict[int, CmdbType] = types_manager.get_types_lookup(list(counts_by_type.keys()))

    type_counts: list[dict[str, Any]] = []

    for type_id, count in counts_by_type.items():
        object_type: CmdbType | None = types_lookup.get(type_id)

        if object_type is None:
            continue

        type_counts.append({"name": object_type.label, "count": count})

    return type_counts, total_count


def handle_sync_config_item_count(request_user: CmdbUser, config_item_count: int | None = None) -> None:
    """
    Syncs the current ConfigItem count to the DataGerry service portal (cloud mode)

    Also reports the current per-type object counts (type label + count) alongside the total, so
    the portal receives a breakdown of the subscription's config items

    Args:
        request_user (CmdbUser): The CmdbUser making the request
        config_item_count (int | None): The number of CmdbObjects to report. Omit it to take the
            total from the same aggregation that builds the breakdown - the caller then pays for
            one aggregation instead of an aggregation plus a full-collection count, and both
            numbers come from the same read
    """
    type_counts, total_count = build_type_object_counts(request_user)

    DgServicePortalManager().sync_config_items(
        request_user,
        total_count if config_item_count is None else config_item_count,
        type_counts,
    )


def handle_delete_invalid_object_relations(request_user: CmdbUser, public_id: int) -> None:
    """
    Deletes the CmdbObjectRelations of a removed object and logs each deletion

    Removes every relation in which the object appears as parent or child in a single bulk delete,
    then writes one CmdbObjectRelationLog per removed relation. A no-op when the object has no
    relations; per-relation log-prep failures are caught and logged

    Two properties worth knowing:

    * The relations are **read and then deleted by the same query**, not by the ids that were read.
      A relation created between the two operations is therefore deleted but never logged - recorded
      as discussion-backlog #162
    * The log ids are reserved as one batch and paired with ``zip(..., strict=True)``:
      ``insert_many(skip_public=True)`` requires every document to carry a ``public_id``, so a short
      reservation must fail loudly rather than insert entries with the key missing

    Args:
        request_user (CmdbUser): The CmdbUser making the request
        public_id (int): public_id of the deleted CmdbObject whose relations should be removed
    """
    object_relations_manager: ObjectRelationsManager = ManagerProvider.get_manager(
        ManagerType.OBJECT_RELATIONS,
        request_user
    )
    object_relation_logs_manager: ObjectRelationLogsManager = ManagerProvider.get_manager(
        ManagerType.OBJECT_RELATION_LOGS,
        request_user
    )

    related_relations_query: dict[str, Any] = object_relations_manager.get_related_relations_query(public_id)

    # Only the three keys the DELETE log entry carries are read back - the full relation documents
    # are never needed here
    affected_relations: list[dict[str, Any]] = object_relations_manager.find(
        criteria=related_relations_query,
        projection=RELATION_DELETE_LOG_PROJECTION,
    )

    if not affected_relations:
        return

    # Delete all affected relations
    object_relations_manager.delete_many_raw(related_relations_query)

    # Prepare Log data
    logs_to_create: list[dict[str, Any]] = []

    for relation in affected_relations:
        try:
            log_entry = object_relation_logs_manager.format_object_relation_log_data(
                LogInteraction.DELETE,
                request_user,
                relation,
                None,
            )

            logs_to_create.append(log_entry)
        except Exception as error:
            LOGGER.error("[handle_delete_invalid_object_relations] Failed to prepare log. Error: %s",
                         error, exc_info=True)

    if not logs_to_create:
        return

    # Add public_ids to the log data
    reserved_log_ids: list[int] = object_relation_logs_manager.reserve_public_ids(len(logs_to_create))

    # strict: insert_many(skip_public=True) requires EVERY document to carry a public_id, so a short
    # id batch must fail loudly here instead of inserting logs with the key missing
    for log_doc, new_id in zip(logs_to_create, reserved_log_ids, strict=True):
        log_doc[CmdbObjectKey.PUBLIC_ID.value] = new_id

    # Create all Logs
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

    try:
        log_data: dict[str, Any] = {
            'object_id': after_object.get_public_id(),
            'version': updated_object.get_version(),
            'user_id': request_user.get_public_id(),
            'user_name': request_user.get_display_name(),
            'comment': update_comment,
            'changes': changes,
            'render_state': json.dumps(updated_object, default=default).encode('UTF-8'),
        }
        logs_manager.insert_log(action=LogAction.EDIT, log_type=CmdbObjectLog.__name__, **log_data)
    except Exception as error:
        LOGGER.error("[emit_object_update_events] Failed to create Log. Error: %s", error)


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

    try:
        change: dict[str, bool] = {'old': not state, 'new': state}
        log_data: dict[str, Any] = {
            'object_id': before_object.get_public_id(),
            'version': before_object.version,
            'user_id': request_user.get_public_id(),
            'user_name': request_user.get_display_name(),
            'render_state': json.dumps(render_result, default=default).encode('UTF-8'),
            'comment': 'Active status has changed',
            'changes': change,
        }
        logs_manager.insert_log(action=LogAction.ACTIVE_CHANGE, log_type=CmdbObjectLog.__name__, **log_data)
    except Exception as error:
        LOGGER.error("[emit_object_state_change_events] Failed to create Log. Error: %s", error)
