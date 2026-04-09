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
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.manager import (
    WebhooksManager,
    LogsManager,
    DgServicePortalManager,
    ObjectRelationsManager,
    ObjectRelationLogsManager,
    ObjectGroupsManager,
    LocationsManager,
    ObjectsManager,
    TypesManager,
)

from cmdb.models.type_model.cmdb_type import CmdbType
from cmdb.models.user_model.cmdb_user import CmdbUser
from cmdb.models.object_model.cmdb_object import CmdbObject
from cmdb.models.webhook_model.webhook_event_type_enum import WebhookEventType
from cmdb.models.object_group_model import ObjectGroupMode
from cmdb.models.log_model import LogInteraction
from cmdb.models.log_model.log_action_enum import LogAction
from cmdb.models.log_model.cmdb_object_log import CmdbObjectLog
from cmdb.framework.rendering.cmdb_render import CmdbRender
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #

def delete_one_cascade(
        request_user: CmdbUser,
        deleted_object: CmdbObject,
        object_type: CmdbType,
        objects_manager: ObjectsManager,
        log_action: LogAction
    ) -> None:
    """TODO: document"""
    # Remove the object from all static object groups
    handle_delete_from_object_groups(request_user, deleted_object.get_public_id())

    # Remove invalid CmdbObjectRelations since the object no longer exists
    handle_delete_invalid_object_relations(request_user, deleted_object.get_public_id())

    # Send deletion event to all active webhooks
    handle_notify_webhooks(request_user, deleted_object, WebhookEventType.DELETE)

    # Create ObjectLog of the deletion
    handle_creat_object_log(request_user, deleted_object, object_type, log_action)

    # Sync config item count in CLOUD_MODE
    if current_app.cloud_mode:
        objects_count: int = objects_manager.count_documents()
        handle_sync_config_item_count(request_user, objects_count)


def sync_select_field_options(
        request_user: CmdbUser,
        target_object: CmdbObject,
        object_type: CmdbType
    ) -> None:
    """TODO: document"""
    types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)

    type_select_fields: dict[str, dict[str, Any]] = object_type.get_fields_with_type("select")

    new_options = {}

    def process_field(field: dict[str, Any]) -> None:
        """TODO: document"""
        if field.get("type") != "select":
            return

        value = field.get("value")

        if value in (None, "", [], {}):
            return

        field_name = field.get("name")

        if field_name not in type_select_fields:
            return

        options = type_select_fields[field_name].get("options", [])

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
        fname = field["name"]

        if fname not in new_options:
            continue

        field.setdefault("options", [])

        for value in new_options[fname]:
            field["options"].append({
                "name": value,
                "label": value
            })

            updated = True

    if updated:
        types_manager.update_type(object_type.public_id, object_type)


def handle_notify_webhooks(
        request_user: CmdbUser,
        target_object: CmdbObject,
        event_type: WebhookEventType
    ) -> None:
    """TODO: document"""
    try:
        webhooks_manager: WebhooksManager = ManagerProvider.get_manager(ManagerType.WEBHOOKS, request_user)

        if event_type == WebhookEventType.CREATE:
            webhooks_manager.send_webhook_event(event_type, object_after=CmdbObject.to_json(target_object))

        if event_type == WebhookEventType.DELETE:
            webhooks_manager.send_webhook_event(event_type, object_before=CmdbObject.to_json(target_object))
    except Exception as err:
        LOGGER.error("[handle_webhooks] Send Webhook Event Exception: %s, Type:%s", err, type(err))


def handle_creat_object_log(
        request_user: CmdbUser,
        target_object: CmdbObject,
        target_type: CmdbType,
        log_action: LogAction
    ) -> None:
    """TODO: document"""
    try:
        rendered_object: RenderResult = CmdbRender(
            target_object,
            target_type,
            request_user
        ).result()

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
        LOGGER.error("[handle_logs] Failed to create ObjectLog. Error: %s", err)


def handle_delete_object_location(request_user: CmdbUser, public_id: int) -> None:
    """TODO: document"""
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
            "[delete_cmdb_object] Locations Exception: %s. Type: %s", error, type(error), exc_info=True
        )
        abort(500, "An internal server error occured while handling Locations of this Object!")


def handle_delete_location_and_child_locations(request_user: CmdbUser, public_id: int) -> None:
    """TODO: document"""
    locations_manager: LocationsManager = ManagerProvider.get_manager(ManagerType.LOCATIONS, request_user)

    # check if location for this object exists
    object_location: dict[str, Any] | None = locations_manager.get_location_for_object(public_id)

    if not object_location:
        return

    # get all child locations for this location
    all_locations: list[dict[str, Any]] = locations_manager.get_all_locations_excluding_root()

    all_child_locations: list[dict[str, Any]] = locations_manager.get_all_children(
        object_location['public_id'],
        all_locations
    )

    # delete all child locations
    if all_child_locations:
        locations_manager.delete_locations(all_child_locations)

    # delete Location of current Object
    locations_manager.delete_location(object_location['public_id'])


def handle_delete_from_object_groups(request_user: CmdbUser, public_ids: int | list[int]) -> None:
    """TODO: document"""
    object_groups_manager: ObjectGroupsManager = ManagerProvider.get_manager(ManagerType.OBJECT_GROUP, request_user)

    object_groups_manager.remove_ids_from_groups(public_ids, ObjectGroupMode.STATIC)


def handle_sync_config_item_count(request_user: CmdbUser, config_item_count: int) -> None:
    """TODO: document"""
    DgServicePortalManager().sync_config_items(request_user, config_item_count)


def handle_delete_invalid_object_relations(request_user: CmdbUser, public_id: int) -> None:
    """TODO: document"""
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
            LOGGER.error("[handle_invalid_object_relations] Failed to prepare log. Error: %s", error, exc_info=True)

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
    Validates that all object fields exist in the type schema
    and fills missing 'type' properties.

    This includes:
    - object.fields[]
    - multi_data_sections[].values[].data[]
    """

    type_id: int | None = object_data.get("type_id")
    if not type_id:
        abort(400, "Missing type_id in object data!")

    type_schema: dict[str, Any] | None = objects_manager.get_object_type(type_id, as_dict=True)
    type_field_map = {f["name"]: f["type"] for f in type_schema["fields"]}

    def validate_field_list(fields: list[dict[str, Any]]) -> None:
        for field in fields:
            field_name: str | None = field.get("name")

            if not field_name:
                abort(400, "One of the fields is missing a 'name' property!")

            if field_name not in type_field_map:
                abort(400, f"Field '{field_name}' is not defined in type {type_id}!")

            if "type" not in field or not field["type"]:
                field["type"] = type_field_map[field_name]

    # Validate normal object fields
    validate_field_list(object_data.get("fields", []))

    # Validate multi-data sections
    for section in object_data.get("multi_data_sections", []):
        for value in section.get("values", []):
            validate_field_list(value.get("data", []))
