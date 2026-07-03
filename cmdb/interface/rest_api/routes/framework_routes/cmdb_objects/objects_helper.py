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
Helper methods for CmdbObject routes
"""
import json
from logging import Logger, getLogger
from typing import Any

from flask import abort, current_app
from werkzeug.exceptions import HTTPException

from cmdb.database.database_utils import default
from cmdb.framework.rendering.render_result import RenderResult
from cmdb.framework.rendering.render_list import RenderList
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.manager import (
    LogsManager,
    DgServicePortalManager,
    ObjectRelationsManager,
    ObjectRelationLogsManager,
    ObjectGroupsManager,
    LocationsManager,
    ObjectsManager,
    TypesManager,
)
from cmdb.interface.rest_api.routes.webhook_routes.webhook_helper import send_webhook_event

from cmdb.models.type_model.cmdb_type import CmdbType
from cmdb.models.type_model.field_type_enum import FieldType
from cmdb.models.type_model.field_key_enum import FieldKey
from cmdb.models.user_model.cmdb_user import CmdbUser
from cmdb.models.object_model.cmdb_object import CmdbObject
from cmdb.models.webhook_model.webhook_event_type_enum import WebhookEventType
from cmdb.models.object_group_model import ObjectGroupMode
from cmdb.models.log_model import LogInteraction
from cmdb.models.log_model.log_action_enum import LogAction
from cmdb.models.log_model.cmdb_object_log import CmdbObjectLog
from cmdb.framework.rendering.cmdb_multi_render import CmdbMultiRender
from cmdb.framework.ipam.enforcement import (
    object_write_requires_ipam_license,
    object_delete_requires_ipam_license,
)
from cmdb.interface.rest_api.routes.cmdb_license.license_guard import abort_if_feature_locked
from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_constants import ObjectViewMode
from cmdb.security.license.license_constants import LicenseFeature
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #

def guard_object_write_license(
    types_manager: TypesManager,
    request_user: CmdbUser,
    candidate_object: dict[str, Any],
    previous_object: dict[str, Any] | None = None,
) -> None:
    """
    Blocks creating/editing an IPAM-gated object when the IPAM feature is not licensed

    A no-op unless the write touches IPAM-licensed surface (a special-type object, or an interface
    row that adds/changes a subnet link). For a gated write it aborts with HTTP 403 on-premise when
    IPAM is unlicensed; it is a no-op in cloud/local mode and when IPAM is licensed

    Args:
        types_manager (TypesManager): db interface for CmdbTypes
        request_user (CmdbUser): The user performing the object write
        candidate_object (dict[str, Any]): The about-to-be-saved CmdbObject document
        previous_object (dict[str, Any] | None): The pre-edit document on update; None on insert
    """
    if object_write_requires_ipam_license(types_manager, candidate_object, previous_object):
        abort_if_feature_locked(LicenseFeature.IPAM, request_user)


def guard_object_delete_license(
    types_manager: TypesManager,
    request_user: CmdbUser,
    target_object: dict[str, Any],
) -> None:
    """
    Blocks deleting an IPAM special-type object when the IPAM feature is not licensed

    A no-op unless the target is an IPAM special-type object. For such a target it aborts with HTTP
    403 on-premise when IPAM is unlicensed; it is a no-op in cloud/local mode and when IPAM is
    licensed

    Args:
        types_manager (TypesManager): db interface for CmdbTypes
        request_user (CmdbUser): The user performing the deletion
        target_object (dict[str, Any]): The CmdbObject document being deleted
    """
    if object_delete_requires_ipam_license(types_manager, target_object):
        abort_if_feature_locked(LicenseFeature.IPAM, request_user)


def render_or_native(
        view: str,
        results: list[CmdbObject],
        request_user: CmdbUser,
    ) -> list[dict[str, Any]]:
    """
    Serialises a list of CmdbObjects according to the requested ``view`` mode

    Shared by the object list and the object reference routes so both apply the same
    native / render dispatch and the same 400 on an unknown view

    Args:
        view (str): The requested view mode (see ObjectViewMode); 'native' returns the stored
            documents, 'render' returns their rendered representation
        results (list[CmdbObject]): The CmdbObjects to serialise
        request_user (CmdbUser): The CmdbUser making the request (used by the renderer)

    Returns:
        list[dict[str, Any]]: One serialised entry per CmdbObject

    Raises:
        HTTPException: Aborts with 400 when ``view`` is not a known ObjectViewMode value
    """
    if view == ObjectViewMode.NATIVE:
        return [object_.__dict__ for object_ in results]

    if view == ObjectViewMode.RENDER:
        return RenderList(results, request_user, True).render_result_list(raw=True)

    abort(400, "Invalid or unprovided 'view' parameter!")


def delete_one_cascade(
        request_user: CmdbUser,
        deleted_object: CmdbObject,
        objects_manager: ObjectsManager,
        log_action: LogAction
    ) -> None:
    """
    Runs the follow-up cleanup after a single CmdbObject was deleted

    Removes the object from static object groups, deletes its now-invalid CmdbObjectRelations,
    emits a delete webhook event, writes a deletion log and (in cloud mode) syncs the ConfigItem
    count. Each step is best-effort and isolated, so a failure in one does not block the others

    Args:
        request_user (CmdbUser): The CmdbUser that performed the deletion
        deleted_object (CmdbObject): The CmdbObject that was deleted
        objects_manager (ObjectsManager): Manager used to recount objects in cloud mode
        log_action (LogAction): The log action to record for the deletion
    """
    # Remove the object from all static object groups
    handle_delete_from_object_groups(request_user, deleted_object.get_public_id())

    # Remove invalid CmdbObjectRelations since the object no longer exists
    handle_delete_invalid_object_relations(request_user, deleted_object.get_public_id())

    # Send deletion event to all active webhooks
    handle_notify_webhooks(request_user, deleted_object, WebhookEventType.DELETE)

    # Create ObjectLog of the deletion
    handle_create_object_log(request_user, deleted_object, log_action)

    # Sync config item count in CLOUD_MODE
    if current_app.cloud_mode:
        objects_count: int = objects_manager.count_documents()
        handle_sync_config_item_count(request_user, objects_count)


def sync_select_field_options(
        request_user: CmdbUser,
        target_object: CmdbObject,
        object_type: CmdbType
    ) -> None:
    """
    Adds any new free-text select values entered on an object back into its CmdbType

    Walks the object's select fields (both the regular fields and the multi-data-section rows),
    collects values not yet present in the type's select options and appends them to the type so
    the option becomes selectable for every object of that type. The type is only persisted when
    at least one new option was added

    Args:
        request_user (CmdbUser): The CmdbUser making the request
        target_object (CmdbObject): The CmdbObject whose select values are inspected
        object_type (CmdbType): The CmdbType to extend with newly seen select options
    """
    types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)

    type_select_fields: dict[str, dict[str, Any]] = object_type.get_fields_with_type(FieldType.SELECT)

    new_options = {}

    def process_field(field: dict[str, Any]) -> None:
        """Records a not-yet-known value of a single select field for later insertion"""
        if field.get(FieldKey.TYPE) != FieldType.SELECT:
            return

        value = field.get(FieldKey.VALUE)

        if value in (None, "", [], {}):
            return

        field_name = field.get(FieldKey.NAME)

        if field_name not in type_select_fields:
            return

        options = type_select_fields[field_name].get(FieldKey.OPTIONS, [])

        existing_names = {opt["name"] for opt in options}

        if value not in existing_names:
            new_options.setdefault(field_name, set()).add(value)

    # check main fields
    for field in target_object.fields:
        process_field(field)

    # check multi data sections
    for section in target_object.multi_data_sections or []:
        for row in section.get("values", []):
            for field in row.get("data", []):
                process_field(field)

    if not new_options:
        return

    # apply updates to type
    updated = False

    for field in object_type.fields:
        fname = field[FieldKey.NAME]

        if fname not in new_options:
            continue

        field.setdefault(FieldKey.OPTIONS, [])

        for value in new_options[fname]:
            field[FieldKey.OPTIONS].append({
                "name": value,
                "label": value
            })

            updated = True

    if updated:
        types_manager.update_type(object_type.public_id, object_type)


def is_special_type_changed(st_old: str, st_new: str) -> bool:
    """
    Reports whether an object's special_type would change between two values

    Args:
        st_old (str): The object's current special_type
        st_new (str): The special_type supplied in the update payload

    Returns:
        bool: True when the two special_type values differ
    """
    return st_old != st_new


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


def handle_create_object_log(
        request_user: CmdbUser,
        target_object: CmdbObject,
        log_action: LogAction
    ) -> None:
    """
    Writes a CmdbObjectLog entry for a created or deleted CmdbObject

    Renders the object to capture its render_state in the log. Failures are caught and logged so
    a logging problem never blocks the surrounding object operation

    Args:
        request_user (CmdbUser): The CmdbUser making the request
        target_object (CmdbObject): The CmdbObject the log entry is about
        log_action (LogAction): The log action to record (CREATE or DELETE)
    """
    try:
        rendered_object: RenderResult = CmdbMultiRender(
            [target_object],
            request_user
        ).result(single_object=True)

        logs_manager: LogsManager = ManagerProvider.get_manager(ManagerType.LOGS, request_user)

        log_comment: str = "Object created"

        if log_action == LogAction.DELETE:
            log_comment = "Object was deleted"

        log_data: dict[str, Any] = {
            'object_id': rendered_object.object_information['object_id'],
            'version': rendered_object.object_information['version'],
            'user_id': request_user.get_public_id(),
            'user_name': request_user.get_display_name(),
            'comment': log_comment,
            'render_state': json.dumps(rendered_object, default=default).encode('UTF-8')
        }

        logs_manager.insert_log(action=log_action, log_type=CmdbObjectLog.__name__, **log_data)
    except Exception as err:
        LOGGER.error("[handle_create_object_log] Failed to create ObjectLog. Error: %s", err)


def handle_delete_object_location(request_user: CmdbUser, public_id: int) -> None:
    """
    Deletes the CmdbLocation of an object, refusing when that location has children

    Looks up the object's location; if it exists and is not the parent of other locations it is
    deleted, otherwise the request aborts with 405

    Args:
        request_user (CmdbUser): The CmdbUser making the request
        public_id (int): public_id of the CmdbObject whose location should be removed

    Raises:
        HTTPException: 405 when the object's location is a parent of other locations, or 500 on an
            unexpected error
    """
    try:
        locations_manager: LocationsManager = ManagerProvider.get_manager(ManagerType.LOCATIONS, request_user)

        object_location = locations_manager.get_location_for_object(public_id)

        if object_location:
            child_location = locations_manager.get_one_by({'parent': object_location['public_id']})

            if child_location and len(child_location) > 0:
                abort(405, "The Location of this Object has child Locations and is therefore not deletable!")

            # Delete the location because it is not a parent to another location
            locations_manager.delete_location(object_location['public_id'])
    except HTTPException as http_err:
        raise http_err
    except Exception as error:
        LOGGER.error(
            "[handle_delete_object_location] Locations Exception: %s. Type: %s", error, type(error), exc_info=True
        )
        abort(500, "An internal server error occured while handling Locations of this Object!")


def handle_delete_location_and_child_locations(request_user: CmdbUser, public_id: int) -> None:
    """
    Deletes the CmdbLocation of an object together with every location beneath it

    A no-op when the object has no location. Child locations are resolved from the full location
    tree and removed before the object's own location

    Args:
        request_user (CmdbUser): The CmdbUser making the request
        public_id (int): public_id of the CmdbObject whose location subtree should be removed
    """
    locations_manager: LocationsManager = ManagerProvider.get_manager(ManagerType.LOCATIONS, request_user)

    # check if location for this object exists
    object_location: dict[str, Any] | None = locations_manager.get_location_for_object(public_id)

    if not object_location:
        return

    # get all child locations for this location (resolved server-side via $graphLookup)
    all_child_locations: list[dict[str, Any]] = locations_manager.get_all_descendant_locations(
        object_location['public_id']
    )

    # delete all child locations
    if all_child_locations:
        locations_manager.delete_locations(all_child_locations)

    # delete Location of current Object
    locations_manager.delete_location(object_location['public_id'])


def handle_delete_from_object_groups(request_user: CmdbUser, public_ids: int | list[int]) -> None:
    """
    Removes one or more CmdbObjects from every static CmdbObjectGroup

    Args:
        request_user (CmdbUser): The CmdbUser making the request
        public_ids (int | list[int]): A single object public_id or a list of them to remove
    """
    object_groups_manager: ObjectGroupsManager = ManagerProvider.get_manager(ManagerType.OBJECT_GROUP, request_user)

    object_groups_manager.remove_ids_from_groups(public_ids, ObjectGroupMode.STATIC)


def handle_sync_config_item_count(request_user: CmdbUser, config_item_count: int) -> None:
    """
    Syncs the current ConfigItem count to the DataGerry service portal (cloud mode)

    Args:
        request_user (CmdbUser): The CmdbUser making the request
        config_item_count (int): The current number of CmdbObjects to report
    """
    DgServicePortalManager().sync_config_items(request_user, config_item_count)


def handle_delete_invalid_object_relations(request_user: CmdbUser, public_id: int) -> None:
    """
    Deletes the CmdbObjectRelations of a removed object and logs each deletion

    Removes every relation in which the object appears as parent or child in a single bulk delete,
    then writes one CmdbObjectRelationLog per removed relation. A no-op when the object has no
    relations; per-relation log-prep failures are caught and logged

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

    # Get all affected ObjectRelations
    affected_relations: list[dict[str, Any]] = object_relations_manager.get_related_relations(public_id)

    if not affected_relations:
        return

    # Delete all affected relations
    object_relations_manager.delete_many_raw(object_relations_manager.get_related_relations_query(public_id))

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

    for log_doc, new_id in zip(logs_to_create, reserved_log_ids):
        log_doc["public_id"] = new_id

    # Create all Logs
    object_relation_logs_manager.insert_many(logs_to_create, skip_public=True)


def validate_and_fill_object_fields(objects_manager: ObjectsManager, object_data: dict[str, Any]) -> None:
    """
    Validates an object's fields against its CmdbType and fills missing 'type' properties

    Ensures every field carried by the object (in 'fields' and in every multi-data-section row)
    is declared by the object's type, and backfills the field's 'type' from the type schema when
    the payload omitted it

    Args:
        objects_manager (ObjectsManager): Manager used to resolve the CmdbType schema
        object_data (dict[str, Any]): The object payload to validate and complete in place

    Raises:
        HTTPException: 400 when type_id is missing, the type cannot be found, a field has no name,
            or a field is not declared by the type
    """
    type_id: int | None = object_data.get("type_id")
    if not type_id:
        abort(400, "Missing type_id in object data!")

    type_schema: dict[str, Any] | None = objects_manager.get_object_type(type_id, as_dict=True)

    if not type_schema:
        abort(400, f"Type with ID {type_id} of the Object was not found!")

    type_field_map = {f[FieldKey.NAME]: f[FieldKey.TYPE] for f in type_schema["fields"]}

    def validate_field_list(fields: list[dict[str, Any]]) -> None:
        """Validates every field in a list against the type and backfills missing 'type' keys"""
        for field in fields:
            field_name: str | None = field.get(FieldKey.NAME)

            if not field_name:
                abort(400, "One of the fields is missing a 'name' property!")

            if field_name not in type_field_map:
                abort(400, f"Field '{field_name}' is not defined in type {type_id}!")

            if FieldKey.TYPE not in field or not field[FieldKey.TYPE]:
                field[FieldKey.TYPE] = type_field_map[field_name]

    # Validate normal object fields
    validate_field_list(object_data.get("fields", []))

    # Validate multi-data sections
    for section in object_data.get("multi_data_sections", []):
        for value in section.get("values", []):
            validate_field_list(value.get("data", []))
