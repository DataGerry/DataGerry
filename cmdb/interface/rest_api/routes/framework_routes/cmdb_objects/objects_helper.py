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
import copy
import json
from datetime import datetime, timezone
from logging import Logger, getLogger
from typing import Any

from bson import json_util
from flask import abort, current_app
from werkzeug.exceptions import HTTPException

from cmdb.database.database_utils import default, object_hook
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
    enforce_object_invariants,
    format_errors_for_abort,
)
from cmdb.security.acl.permission import AccessControlPermission
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


def is_special_type_changed(st_old: str | None, st_new: str | None) -> bool:
    """
    Reports whether an object's special_type would actually change between two values

    A real special_type is a non-empty string (SUPERNET / SUBNET / VLAN); every falsy value -
    ``""``, ``None`` or an omitted key - means "no special type". Those are normalised to ``None``
    before comparing, so a caller that omits ``special_type`` (``None``) is not falsely reported as
    changing a stored empty-string ``special_type`` (the update was otherwise rejected with a 400)

    Args:
        st_old (str | None): The object's current special_type
        st_new (str | None): The special_type supplied in the update payload

    Returns:
        bool: True only when the two values differ once falsy values are treated as equivalent
    """
    return (st_old or None) != (st_new or None)


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
        HTTPException: 400 when the object's location is a parent of other locations, or 500 on an
            unexpected error
    """
    try:
        locations_manager: LocationsManager = ManagerProvider.get_manager(ManagerType.LOCATIONS, request_user)

        object_location = locations_manager.get_location_for_object(public_id)

        if object_location:
            child_location = locations_manager.get_one_by({'parent': object_location['public_id']})

            if child_location and len(child_location) > 0:
                abort(400, "The Location of this Object has child Locations and is therefore not deletable!")

            # Delete the location because it is not a parent to another location
            locations_manager.delete_location(object_location['public_id'])
    except HTTPException as http_err:
        raise http_err
    except Exception as error:
        LOGGER.error(
            "[handle_delete_object_location] Locations Exception: %s. Type: %s", error, type(error), exc_info=True
        )
        abort(500, "An internal server error occured while handling Locations of this Object!")


def handle_delete_location_and_child_locations(request_user: CmdbUser, public_id: int) -> list[int]:
    """
    Deletes the CmdbLocation of an object together with every location beneath it

    A no-op when the object has no location. Child locations are resolved from the full location
    tree and removed before the object's own location. Returns the object_ids of the removed
    descendant locations - the child objects that SURVIVE this deletion - so the caller can clear
    their now-dangling location reference

    Args:
        request_user (CmdbUser): The CmdbUser making the request
        public_id (int): public_id of the CmdbObject whose location subtree should be removed

    Returns:
        list[int]: public_ids of the child CmdbObjects whose location node was deleted
    """
    locations_manager: LocationsManager = ManagerProvider.get_manager(ManagerType.LOCATIONS, request_user)

    # check if location for this object exists
    object_location: dict[str, Any] | None = locations_manager.get_location_for_object(public_id)

    if not object_location:
        return []

    # get all child locations for this location (resolved server-side via $graphLookup)
    all_child_locations: list[dict[str, Any]] = locations_manager.get_all_descendant_locations(
        object_location['public_id']
    )

    # object_ids of the descendant location nodes = the child objects that survive this delete
    child_object_ids: list[int] = [
        location['object_id'] for location in all_child_locations if 'object_id' in location
    ]

    # delete all child locations
    if all_child_locations:
        locations_manager.delete_locations(all_child_locations)

    # delete Location of current Object
    locations_manager.delete_location(object_location['public_id'])

    return child_object_ids


def handle_delete_from_object_groups(request_user: CmdbUser, public_ids: int | list[int]) -> None:
    """
    Removes one or more CmdbObjects from every static CmdbObjectGroup

    Args:
        request_user (CmdbUser): The CmdbUser making the request
        public_ids (int | list[int]): A single object public_id or a list of them to remove
    """
    object_groups_manager: ObjectGroupsManager = ManagerProvider.get_manager(ManagerType.OBJECT_GROUP, request_user)

    object_groups_manager.remove_ids_from_groups(public_ids, ObjectGroupMode.STATIC)


def build_type_object_counts(request_user: CmdbUser) -> list[dict[str, Any]]:
    """
    Builds the per-type object-count list for the Service Portal sync payload

    Counts every CmdbObject grouped by its type_id in a single aggregation, then resolves each
    type_id to its CmdbType label via one bulk lookup. CmdbTypes with no objects are omitted, and
    a counted type_id whose CmdbType no longer exists is skipped. The counts include all objects
    (no active filter), so their sum matches the reported config_item_count

    Args:
        request_user (CmdbUser): The CmdbUser making the request

    Returns:
        list[dict[str, Any]]: Entries shaped ``{"name": <type label>, "count": <int>}``
    """
    objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
    types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)

    counts_by_type: dict[int, int] = objects_manager.count_objects_grouped_by_type()

    if not counts_by_type:
        return []

    types_lookup: dict[int, CmdbType] = types_manager.get_types_lookup(list(counts_by_type.keys()))

    type_counts: list[dict[str, Any]] = []

    for type_id, count in counts_by_type.items():
        object_type: CmdbType | None = types_lookup.get(type_id)

        if object_type is None:
            continue

        type_counts.append({"name": object_type.label, "count": count})

    return type_counts


def handle_sync_config_item_count(request_user: CmdbUser, config_item_count: int) -> None:
    """
    Syncs the current ConfigItem count to the DataGerry service portal (cloud mode)

    Also reports the current per-type object counts (type label + count) alongside the total, so
    the portal receives a breakdown of the subscription's config items

    Args:
        request_user (CmdbUser): The CmdbUser making the request
        config_item_count (int): The current number of CmdbObjects to report
    """
    type_counts: list[dict[str, Any]] = build_type_object_counts(request_user)

    DgServicePortalManager().sync_config_items(request_user, config_item_count, type_counts)


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


def to_normalized_cmdb_object(object_data: dict[str, Any]) -> CmdbObject:
    """
    Builds a CmdbObject from a payload dict, normalizing BSON types via a JSON round-trip

    The round-trip (``json.dumps(..., default=default)`` then ``json.loads(..., object_hook)``)
    coerces Python/BSON values (e.g. datetimes) into the canonical shape the model expects,
    matching how the object is stored and compared

    Args:
        object_data (dict[str, Any]): The object payload to convert

    Returns:
        CmdbObject: The constructed CmdbObject instance
    """
    return CmdbObject(**json.loads(json.dumps(object_data, default=default), object_hook=object_hook))


def build_new_object_data(
        objects_manager: ObjectsManager,
        request_data: dict[str, Any],
    ) -> tuple[dict[str, Any], CmdbType]:
    """
    Normalises a raw insert payload into a ready-to-store CmdbObject document

    Applies the BSON object_hook, assigns a fresh public_id (or verifies a supplied one is unused),
    resolves and returns the target CmdbType, defaults the active flag, stamps creation_time and the
    initial version, and validates/backfills the field types

    Args:
        objects_manager (ObjectsManager): Manager used to resolve ids/types and check existence
        request_data (dict[str, Any]): The raw request body of the new CmdbObject

    Returns:
        tuple[dict[str, Any], CmdbType]: The prepared object document and its resolved CmdbType

    Raises:
        HTTPException: 400 when the supplied public_id already exists, 404 when the type is unknown,
            or the 400s raised by validate_and_fill_object_fields
    """
    new_object_data: dict[str, Any] = json.loads(json.dumps(request_data), object_hook=json_util.object_hook)

    if "public_id" not in new_object_data:
        new_object_data['public_id'] = objects_manager.get_new_object_public_id()
    else:
        existing_object: dict[str, Any] | None = objects_manager.get_object(new_object_data['public_id'])

        if existing_object:
            abort(400, f'Object with ID: {new_object_data["public_id"]} already exists!')

    object_type: CmdbType | None = objects_manager.get_object_type(new_object_data['type_id'])

    if not object_type:
        abort(404, f"Type with ID:{new_object_data['type_id']} of new Object not found!")

    if 'active' not in new_object_data:
        new_object_data['active'] = True

    new_object_data['creation_time'] = datetime.now(timezone.utc)
    new_object_data['version'] = '1.0.0'

    # Validate fields have a type property (and backfill it from the type schema when omitted)
    validate_and_fill_object_fields(objects_manager, new_object_data)

    return new_object_data, object_type


def compute_object_version(current_object: CmdbObject, updated_object: CmdbObject) -> tuple[str, dict[str, Any]]:
    """
    Derives the field-level diff and applies the resulting semantic version bump

    The bump is chosen from how many fields changed relative to the total field count: a single
    changed field is a PATCH, all fields a MAJOR, more than half a MINOR, and anything else a PATCH.
    ``updated_object`` is mutated in place with the new version

    Args:
        current_object (CmdbObject): The stored object before the update
        updated_object (CmdbObject): The candidate object after the update

    Returns:
        tuple[str, dict[str, Any]]: The new version string and the diff (as returned by ``/``)
    """
    changes: dict[str, Any] = current_object / updated_object

    changed_count: int = len(changes['new'])
    field_count: int = len(updated_object.fields)

    if changed_count == 1:
        version_type = updated_object.VERSIONING_PATCH
    elif changed_count == field_count:
        version_type = updated_object.VERSIONING_MAJOR
    elif changed_count > (field_count / 2):
        version_type = updated_object.VERSIONING_MINOR
    else:
        version_type = updated_object.VERSIONING_PATCH

    return updated_object.update_version(version_type), changes


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


# Cohesive single-object update orchestration (fetch -> guard -> validate -> persist -> side effects);
# the local count is inherent to the sequence, so the too-many-locals check is scoped off here
def apply_object_update(  # pylint: disable=too-many-locals
        obj_id: int,
        payload: dict[str, Any],
        active_state: bool | None,
        request_user: CmdbUser,
        objects_manager: ObjectsManager,
        types_manager: TypesManager,
        logs_manager: LogsManager,
    ) -> dict[str, Any]:
    """
    Applies a full-object update to a single CmdbObject and runs its side effects

    DataGerry has no partial-update semantics: the complete object is always sent, so the payload
    fields are authoritative. Refuses a special_type change, enforces the IPAM license + invariants,
    computes the version bump, persists the object, syncs new select options and emits the update
    webhook + edit log

    Args:
        obj_id (int): public_id of the CmdbObject to update
        payload (dict[str, Any]): The validated full-object payload (shared across bulk targets)
        active_state (bool | None): The active flag to apply, or None to keep the object's current
        request_user (CmdbUser): The CmdbUser making the request
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes (IPAM license/invariant checks)
        logs_manager (LogsManager): Manager used to persist the edit log

    Returns:
        dict[str, Any]: The persisted object document (one entry of the update response)

    Raises:
        HTTPException: 404 when the object is missing before/after the write, 400 on a special_type
            change or an IPAM invariant violation, 500 when the object's type cannot be resolved
    """
    new_data: dict[str, Any] = copy.deepcopy(payload)

    current_object_instance: CmdbObject | None = objects_manager.get_object(
        obj_id,
        request_user,
        AccessControlPermission.READ,
        as_dict=False,
    )

    if not current_object_instance:
        abort(404, f"Object with ID:{obj_id} not found!")

    if is_special_type_changed(current_object_instance.special_type, new_data.get('special_type')):
        abort(400, f"SpecialType of an Object is not changable. Occured for Object with ID: {obj_id}")

    current_type_instance: CmdbType | None = objects_manager.get_object_type(current_object_instance.get_type_id())

    if not current_type_instance:
        abort(500, "Type of Object not found in database!")

    new_data.update({
        'public_id': obj_id,
        'creation_time': current_object_instance.creation_time,
        'author_id': current_object_instance.author_id,
        'active': active_state if active_state in [True, False] else current_object_instance.active,
        'version': payload.get('version', current_object_instance.version),
        'last_edit_time': datetime.now(timezone.utc),
        'editor_id': request_user.public_id,
    })

    update_comment: str = new_data.pop('comment', "")

    # Validate fields have a type (and backfill it) - the full payload is the source of truth
    validate_and_fill_object_fields(objects_manager, new_data)

    previous_object: dict[str, Any] = CmdbObject.to_json(current_object_instance)

    # Editing an IPAM special-type object (or adding/changing an interface subnet) needs an IPAM license
    guard_object_write_license(types_manager, request_user, new_data, previous_object)

    ipam_errors: list[dict[str, Any]] = enforce_object_invariants(
        objects_manager,
        types_manager,
        new_data,
        previous_object=previous_object,
    )

    if ipam_errors:
        abort(400, format_errors_for_abort(ipam_errors))

    update_object_instance: CmdbObject = to_normalized_cmdb_object(new_data)

    new_version, changes = compute_object_version(current_object_instance, update_object_instance)
    new_data['version'] = new_version

    objects_manager.update_object(obj_id, new_data, request_user, AccessControlPermission.UPDATE)

    object_after: dict[str, Any] | None = objects_manager.get_object(obj_id, request_user, AccessControlPermission.READ)

    if not object_after:
        abort(404, f"Updated Object with ID:{obj_id} not found in database!")

    object_after: CmdbObject = CmdbObject.from_data(object_after)

    # sync select fields
    if object_after.has_fields_of_type(FieldType.SELECT):
        sync_select_field_options(request_user, object_after, current_type_instance)

    emit_object_update_events(
        request_user,
        logs_manager,
        current_object_instance,
        object_after,
        update_object_instance,
        changes,
        update_comment,
    )

    return new_data
