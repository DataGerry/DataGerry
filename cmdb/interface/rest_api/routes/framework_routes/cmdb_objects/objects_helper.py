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
from cerberus import Validator  # type: ignore
from pymongo import UpdateOne
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
    ReportsManager,
    SectionTemplatesManager,
    TypesManager,
)
from cmdb.interface.rest_api.routes.webhook_routes.webhook_helper import send_webhook_event

from cmdb.models.type_model.cmdb_type import CmdbType
from cmdb.models.type_model.field_type_enum import FieldType
from cmdb.models.type_model.field_key_enum import FieldKey
from cmdb.models.user_model.cmdb_user import CmdbUser
from cmdb.models.object_model.cmdb_object import CmdbObject
from cmdb.models.object_model import (
    CmdbObjectKey,
    CmdbObjectFieldKey,
    CmdbObjectMdsKey,
    CmdbObjectMdsRowKey,
)
from cmdb.models.webhook_model.webhook_event_type_enum import WebhookEventType
from cmdb.models.object_group_model import ObjectGroupMode
from cmdb.models.log_model import LogInteraction
from cmdb.models.log_model.log_action_enum import LogAction
from cmdb.models.log_model.cmdb_object_log import CmdbObjectLog
from cmdb.framework.rendering.cmdb_multi_render import CmdbMultiRender
from cmdb.framework.section_templates import (
    PREDEFINED_SELECT_OPTION_REJECTED,
    resolve_predefined_select_fields,
)
from cmdb.framework.ipam.enforcement import (
    object_write_requires_ipam_license,
    object_delete_requires_ipam_license,
    enforce_delete_guards,
    format_errors_for_abort,
)
from cmdb.framework.object_invariants import enforce_object_write_invariants
from cmdb.interface.rest_api.routes.rack_routes.rack_object_hooks import (
    guard_member_location_change,
    handle_object_deleted as handle_rack_object_deleted,
    handle_rack_object_updated,
)
from cmdb.security.acl.permission import AccessControlPermission
from cmdb.interface.rest_api.routes.cmdb_license.license_guard import abort_if_feature_locked
from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_constants import (
    ObjectViewMode,
    ObjectPatchKey,
)
from cmdb.interface.rest_api.routes.framework_routes.cmdb_locations.location_helper import (
    extract_object_location_parent, validate_object_location_change, sync_object_location,
    delete_location_with_reparenting,
)
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

    # Remove the Rack state the object leaves behind: a deleted Rack takes its whole layout and its
    # members' place in the tree with it, a deleted member loses just its own membership
    handle_rack_object_deleted(
        request_user, CmdbObject.to_json(deleted_object), objects_manager,
        ManagerProvider.get_manager(ManagerType.TYPES, request_user),
    )

    # Send deletion event to all active webhooks
    handle_notify_webhooks(request_user, deleted_object, WebhookEventType.DELETE)

    # Create ObjectLog of the deletion
    handle_create_object_log(request_user, deleted_object, log_action)

    # Sync config item count in CLOUD_MODE
    if current_app.cloud_mode:
        objects_count: int = objects_manager.count_documents()
        handle_sync_config_item_count(request_user, objects_count)


def collect_unknown_select_values(
        object_fields: list[dict[str, Any]] | None,
        multi_data_sections: list[dict[str, Any]] | None,
        type_select_fields: dict[str, dict[str, Any]],
    ) -> dict[str, set[Any]]:
    """
    Collects the select values an object carries that its type does not list as an option yet

    Walks the object's regular fields and its multi-data-section rows, keeping only entries that are
    select fields of the type; an empty value and a value the type already offers are both ignored

    Args:
        object_fields (list[dict[str, Any]] | None): The object's flat ``fields`` list
        multi_data_sections (list[dict[str, Any]] | None): The object's ``multi_data_sections`` list
        type_select_fields (dict[str, dict[str, Any]]): {field name: field definition} of the type's
            select fields (see ``CmdbType.get_fields_with_type``)

    Returns:
        dict[str, set[Any]]: {select field name: values the type does not know}, empty when there are none
    """
    unknown_values: dict[str, set[Any]] = {}

    def process_field(field: dict[str, Any]) -> None:
        """Records a not-yet-known value of a single select field"""
        if field.get(FieldKey.TYPE) != FieldType.SELECT:
            return

        value = field.get(FieldKey.VALUE)

        if value in (None, "", [], {}):
            return

        field_name = field.get(FieldKey.NAME)

        if field_name not in type_select_fields:
            return

        options = type_select_fields[field_name].get(FieldKey.OPTIONS, [])
        existing_names = {option[FieldKey.NAME] for option in options}

        if value not in existing_names:
            unknown_values.setdefault(field_name, set()).add(value)

    for field in object_fields or []:
        process_field(field)

    for section in multi_data_sections or []:
        for row in section.get(CmdbObjectMdsKey.VALUES.value, []):
            for field in row.get(CmdbObjectMdsRowKey.DATA.value, []):
                process_field(field)

    return unknown_values


def guard_predefined_select_options(
        request_user: CmdbUser,
        object_fields: list[dict[str, Any]] | None,
        multi_data_sections: list[dict[str, Any]] | None,
        object_type: CmdbType,
    ) -> None:
    """
    Refuses an object write whose select value would extend a predefined section template's field

    An unknown select value normally becomes a new option on the type (see
    ``sync_select_field_options``), but a select field owned by a predefined CmdbSectionTemplate is
    immutable - the template cannot be edited through the API and any local edit of the type's copy is
    reverted the next time the template propagates. Such a value is therefore rejected before the
    object is written. A no-op for a type that uses no predefined template

    The section templates are only read when the object actually carries a value the type does not
    offer yet, so the ordinary write - every value picked from an existing option - pays no query

    Args:
        request_user (CmdbUser): The CmdbUser making the request
        object_fields (list[dict[str, Any]] | None): The about-to-be-saved object's ``fields`` list
        multi_data_sections (list[dict[str, Any]] | None): The object's ``multi_data_sections`` list
        object_type (CmdbType): The CmdbType the object belongs to

    Raises:
        HTTPException: 400 when a value would have to be added to a predefined template's select field
    """
    unknown_values: dict[str, set[Any]] = collect_unknown_select_values(
        object_fields,
        multi_data_sections,
        object_type.get_fields_with_type(FieldType.SELECT),
    )

    if not unknown_values:
        return

    section_templates_manager: SectionTemplatesManager = ManagerProvider.get_manager(
        ManagerType.SECTION_TEMPLATES,
        request_user,
    )

    protected_select_fields: dict[str, str] = resolve_predefined_select_fields(
        object_type,
        section_templates_manager,
    )

    if not protected_select_fields:
        return

    rejections: list[str] = [
        f"Field '{field_name}': "
        f"{PREDEFINED_SELECT_OPTION_REJECTED.format(value=value, template=protected_select_fields[field_name])}"
        for field_name, values in unknown_values.items()
        if field_name in protected_select_fields
        for value in sorted(values, key=str)
    ]

    if rejections:
        abort(400, " ".join(rejections))


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

    A select field owned by a predefined CmdbSectionTemplate is never extended - its definition is
    immutable. Such a value is rejected before the write by ``guard_predefined_select_options``; the
    filter here keeps the type safe even for a caller that skipped that guard

    Args:
        request_user (CmdbUser): The CmdbUser making the request
        target_object (CmdbObject): The CmdbObject whose select values are inspected
        object_type (CmdbType): The CmdbType to extend with newly seen select options
    """
    types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)

    new_options: dict[str, set[Any]] = collect_unknown_select_values(
        target_object.fields,
        target_object.multi_data_sections,
        object_type.get_fields_with_type(FieldType.SELECT),
    )

    if not new_options:
        return

    section_templates_manager: SectionTemplatesManager = ManagerProvider.get_manager(
        ManagerType.SECTION_TEMPLATES,
        request_user,
    )
    protected_select_fields: dict[str, str] = resolve_predefined_select_fields(
        object_type,
        section_templates_manager,
    )

    # apply updates to type
    updated = False

    for field in object_type.fields:
        fname = field[FieldKey.NAME]

        if fname not in new_options or fname in protected_select_fields:
            continue

        field.setdefault(FieldKey.OPTIONS.value, [])

        for value in new_options[fname]:
            field[FieldKey.OPTIONS].append({
                FieldKey.NAME.value: value,
                FieldKey.LABEL.value: value,
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
    # Transient location name: never stored (the POST route reads it from the raw body for the sync)
    new_object_data.pop('location_name', None)

    # Validate fields have a type property (and backfill it from the type schema when omitted)
    validate_and_fill_object_fields(objects_manager, new_object_data)

    return new_object_data, object_type


def guard_config_item_limit(request_user: CmdbUser, objects_manager: ObjectsManager) -> None:
    """
    Refuses a new CmdbObject when the user's subscription has no ConfigItem budget left

    A no-op outside cloud mode, where no such limit exists

    Args:
        request_user (CmdbUser): The CmdbUser the limit is checked for
        objects_manager (ObjectsManager): Manager used to count the stored CmdbObjects

    Raises:
        HTTPException: 400 when the ConfigItem limit is reached
    """
    if not current_app.cloud_mode:
        return

    if request_user.is_config_item_limit_reached(objects_manager.count_documents()):
        abort(400, "The maximum amout of ConfigItems is reached!")


def resolve_object_type(
        objects_manager: ObjectsManager,
        type_id: int,
        type_cache: dict[int, CmdbType] | None = None,
    ) -> CmdbType:
    """
    Resolves a CmdbObject's CmdbType, reusing an already resolved one when a cache is passed

    Every type read costs a query plus building the model, and a bulk update usually targets objects of
    the SAME type - so a caller that iterates hands in a cache and pays for each distinct type once
    instead of once per object. The cache is filled as types are resolved

    Args:
        objects_manager (ObjectsManager): Manager used to read the CmdbType
        type_id (int): public_id of the CmdbType to resolve
        type_cache (dict[int, CmdbType] | None): Types already resolved by this caller, extended in
                                                 place. Defaults to None (always read)

    Raises:
        HTTPException: 500 when the type does not exist

    Returns:
        CmdbType: The resolved CmdbType
    """
    if type_cache is not None and type_id in type_cache:
        return type_cache[type_id]

    object_type: CmdbType | None = objects_manager.get_object_type(type_id)

    if not object_type:
        abort(500, "Type of Object not found in database!")

    if type_cache is not None:
        type_cache[type_id] = object_type

    return object_type


def apply_object_insert(
        payload: dict[str, Any],
        request_user: CmdbUser,
        objects_manager: ObjectsManager,
        types_manager: TypesManager,
    ) -> int:
    """
    Inserts one CmdbObject and runs its side effects, the counterpart of `apply_object_update`

    The order matters and is the point of this function: everything that can refuse the request runs
    BEFORE the write (ConfigItem budget, payload normalisation, IPAM license, IPAM invariants, location
    placement), and everything that describes an object that now exists runs after it (the CmdbLocation
    mirror, the select-option sync, the CREATE webhook, the cloud item count and the create log)

    Args:
        payload (dict[str, Any]): The raw request body of the new CmdbObject
        request_user (CmdbUser): The CmdbUser making the request
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes (IPAM license checks)

    Raises:
        HTTPException: 400 when the ConfigItem limit is reached, the payload is unusable or an IPAM
            invariant is violated, 403 when the IPAM license is missing, 404 when the type is unknown,
            500 when the created object cannot be read back

    Returns:
        int: public_id of the created CmdbObject
    """
    guard_config_item_limit(request_user, objects_manager)

    # The custom CmdbLocation tree name (if any) travels in the object body; the parent itself is the
    # object's location field value. location_name is transient - build_new_object_data strips it
    location_name: str | None = (payload or {}).get(ObjectPatchKey.LOCATION_NAME.value)

    # Normalise the payload: assign/verify public_id, resolve the type, stamp defaults + version
    new_object_data, object_type = build_new_object_data(objects_manager, payload)

    # Creating an IPAM special-type object (or linking a subnet on an interface) needs an IPAM license
    guard_object_write_license(types_manager, request_user, new_object_data)

    # Every feature's write invariants (IPAM, Rack) - also canonicalises values on the candidate
    invariant_error: str | None = enforce_object_write_invariants(
        objects_manager,
        types_manager,
        new_object_data,
        previous_object=None,
    )

    if invariant_error:
        abort(400, invariant_error)

    # An unknown select value may not extend a predefined section template's field - reject before the write
    guard_predefined_select_options(
        request_user,
        new_object_data.get(CmdbObjectKey.FIELDS.value),
        new_object_data.get(CmdbObjectKey.MULTI_DATA_SECTIONS.value),
        object_type,
    )

    # Validate the location placement (parent exists) before the object is written
    has_location_field, location_parent = extract_object_location_parent(
        new_object_data.get(CmdbObjectKey.FIELDS.value, [])
    )
    locations_manager: LocationsManager | None = None

    if has_location_field:
        locations_manager = ManagerProvider.get_manager(ManagerType.LOCATIONS, request_user)
        validate_object_location_change(
            new_object_data[CmdbObjectKey.PUBLIC_ID.value], location_parent, locations_manager,
        )

    new_object_id: int = objects_manager.insert_object(
        new_object_data,
        request_user,
        AccessControlPermission.CREATE,
    )

    # Mirror the placement into the CmdbLocation tree (best-effort, after the object is saved)
    if has_location_field:
        sync_object_location(
            new_object_id,
            location_parent,
            location_name,
            object_type,
            request_user,
            objects_manager,
            locations_manager,
        )

    created_object: dict[str, Any] | None = objects_manager.get_object(new_object_id)

    if not created_object:
        # The object IS stored at this point, so this is a read failure, not a missing object
        abort(500, "The created Object could not be read back from the database!")

    created_instance: CmdbObject = CmdbObject.from_data(created_object)

    if created_instance.has_fields_of_type(FieldType.SELECT):
        sync_select_field_options(request_user, created_instance, object_type)

    handle_notify_webhooks(request_user, created_instance, WebhookEventType.CREATE)

    if current_app.cloud_mode:
        # Recount AFTER the insert so the synced total includes the just-created object (the
        # pre-insert count in guard_config_item_limit only answers the limit question)
        handle_sync_config_item_count(request_user, objects_manager.count_documents())

    handle_create_object_log(request_user, created_instance, LogAction.CREATE)

    return new_object_id


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
        type_cache: dict[int, CmdbType] | None = None,
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
        type_cache (dict[int, CmdbType] | None): Types already resolved by the caller, extended in
                                                 place. A bulk update usually targets objects of the
                                                 same type, so passing one turns N type reads into one
                                                 per distinct type. Defaults to None (always read)

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

    current_type_instance: CmdbType = resolve_object_type(
        objects_manager, current_object_instance.get_type_id(), type_cache,
    )

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
    location_name: str | None = new_data.pop('location_name', None)  # transient, never stored

    # Validate fields have a type (and backfill it) - the full payload is the source of truth
    validate_and_fill_object_fields(objects_manager, new_data)

    # Location placement is validated BEFORE the write; the CmdbLocation mirror runs best-effort after
    has_location_field, location_parent = extract_object_location_parent(new_data.get('fields', []))
    locations_manager: LocationsManager | None = None

    if has_location_field:
        locations_manager = ManagerProvider.get_manager(ManagerType.LOCATIONS, request_user)
        validate_object_location_change(obj_id, location_parent, locations_manager)
        # A Rack owns where its members sit, so a member may not be pointed somewhere else from the object
        # form - the way to move the device is to take it out of the Rack first
        guard_member_location_change(request_user, obj_id, location_parent, locations_manager)

    previous_object: dict[str, Any] = CmdbObject.to_json(current_object_instance)

    # Editing an IPAM special-type object (or adding/changing an interface subnet) needs an IPAM license
    guard_object_write_license(types_manager, request_user, new_data, previous_object)

    # Every feature's write invariants (IPAM, Rack) - also canonicalises values on the candidate
    invariant_error: str | None = enforce_object_write_invariants(
        objects_manager,
        types_manager,
        new_data,
        previous_object=previous_object,
    )

    if invariant_error:
        abort(400, invariant_error)

    # An unknown select value may not extend a predefined section template's field - reject before the write
    guard_predefined_select_options(
        request_user,
        new_data.get(CmdbObjectKey.FIELDS.value),
        new_data.get(CmdbObjectKey.MULTI_DATA_SECTIONS.value),
        current_type_instance,
    )

    update_object_instance: CmdbObject = to_normalized_cmdb_object(new_data)

    new_version, changes = compute_object_version(current_object_instance, update_object_instance)
    new_data['version'] = new_version

    objects_manager.update_object(obj_id, new_data, request_user, AccessControlPermission.UPDATE)

    if has_location_field:
        sync_object_location(obj_id, location_parent, location_name, current_type_instance,
                             request_user, objects_manager, locations_manager)

    # Rack consequences of the write, after the object's own location has been mirrored above: a lowered
    # height unplaces the mounts that no longer fit, and the members follow the rack in the location tree.
    # Post-write on purpose - both measure against what is now stored, so a failed write changes nothing
    handle_rack_object_updated(
        request_user, obj_id, new_data, previous_object, objects_manager, types_manager, locations_manager,
    )

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


# ----------------------------------------------- OBJECT PARTIAL UPDATE ---------------------------------------------- #

def get_object_patch_schema() -> dict[str, Any]:
    """
    Builds the Cerberus schema for a partial-update (PATCH) object payload

    Only the patchable parts are described: a subset of regular ``fields`` and three symmetric MDS
    row lists - ``created_mds_rows`` (no multi_data_id; the backend assigns it), ``edited_mds_rows``
    and ``deleted_mds_rows`` - plus an optional ``comment`` for the edit log. Each field entry is a
    ``{name, value, type?}`` triple. The disallowed (immutable / server-managed) keys are rejected
    separately so they can be named in the error

    Returns:
        dict[str, Any]: The Cerberus validation schema for a PATCH body
    """
    field_item: dict[str, Any] = {
        'type': 'dict',
        'schema': {
            'name': {'type': 'string', 'required': True, 'empty': False},
            'value': {'required': True, 'nullable': True},
            'type': {'type': 'string', 'required': False},
        },
    }

    return {
        'fields': {
            'type': 'list',
            'required': False,
            'schema': field_item,
        },
        'created_mds_rows': {
            'type': 'list',
            'required': False,
            'schema': {
                'type': 'dict',
                'schema': {
                    'section_id': {'type': 'string', 'required': True, 'empty': False},
                    'data': {'type': 'list', 'required': True, 'schema': field_item},
                },
            },
        },
        'edited_mds_rows': {
            'type': 'list',
            'required': False,
            'schema': {
                'type': 'dict',
                'schema': {
                    'section_id': {'type': 'string', 'required': True, 'empty': False},
                    'multi_data_id': {'type': 'integer', 'required': True},
                    'data': {'type': 'list', 'required': True, 'schema': field_item},
                },
            },
        },
        'deleted_mds_rows': {
            'type': 'list',
            'required': False,
            'schema': {
                'type': 'dict',
                'schema': {
                    'section_id': {'type': 'string', 'required': True, 'empty': False},
                    'multi_data_id': {'type': 'integer', 'required': True},
                },
            },
        },
        'comment': {'type': 'string', 'required': False, 'nullable': True, 'empty': True},
        'location_name': {'type': 'string', 'required': False, 'nullable': True, 'empty': True},
    }


def validate_object_patch_payload(raw_data: Any) -> dict[str, Any]:
    """
    Validates the raw body of a partial-update (PATCH) object request

    Rejects a non-object body, any key that is not patchable (immutable identifier or
    server-managed field) by naming it, an empty patch that would change nothing, and any body
    whose shape does not match the PATCH schema

    Args:
        raw_data (Any): The raw parsed JSON request body

    Raises:
        HTTPException: 400 when the body is not a JSON object, carries a disallowed key, is empty,
            or fails schema validation

    Returns:
        dict[str, Any]: The validated (and normalized) patch payload
    """
    if not isinstance(raw_data, dict):
        abort(400, "Patch payload must be a JSON object!")

    allowed_keys: set[str] = {member.value for member in ObjectPatchKey}
    disallowed_keys: list[str] = sorted(set(raw_data) - allowed_keys)

    if disallowed_keys:
        abort(400, f"These keys cannot be patched: {disallowed_keys}")

    # LOCATION_NAME counts as a change (a rename of the object's location node); COMMENT alone does not
    changing_keys: list[str] = [
        ObjectPatchKey.FIELDS.value,
        ObjectPatchKey.CREATED_MDS_ROWS.value,
        ObjectPatchKey.EDITED_MDS_ROWS.value,
        ObjectPatchKey.DELETED_MDS_ROWS.value,
        ObjectPatchKey.LOCATION_NAME.value,
    ]

    if not any(raw_data.get(key) for key in changing_keys):
        abort(400, "Patch payload must change at least one field, multi_data_section row or the location name!")

    validator: Validator = Validator(get_object_patch_schema())

    if not validator.validate(raw_data):
        abort(400, f"Invalid patch payload: {validator.errors}")

    return validator.document


def merge_patch_fields(
        stored_fields: list[dict[str, Any]],
        patch_fields: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
    """
    Merges a subset of field values into a stored field list by field name

    A patched field name that already exists has only its ``value`` overwritten (its stored
    ``type`` is kept); an unknown name is appended as a new entry. Stored fields not mentioned by
    the patch are left untouched. The returned list is a shallow copy — the input is not mutated

    Args:
        stored_fields (list[dict[str, Any]]): The object's current field entries ({name, value, type})
        patch_fields (list[dict[str, Any]]): The subset of field entries to apply ({name, value})

    Returns:
        list[dict[str, Any]]: The merged field list
    """
    merged_fields: list[dict[str, Any]] = [dict(field) for field in stored_fields]
    fields_by_name: dict[Any, dict[str, Any]] = {
        field.get(CmdbObjectFieldKey.NAME): field for field in merged_fields
    }

    for patch_field in patch_fields:
        field_name: str = patch_field[CmdbObjectFieldKey.NAME]

        if field_name in fields_by_name:
            fields_by_name[field_name][CmdbObjectFieldKey.VALUE.value] = patch_field.get(CmdbObjectFieldKey.VALUE)
        else:
            new_field: dict[str, Any] = {
                CmdbObjectFieldKey.NAME.value: field_name,
                CmdbObjectFieldKey.VALUE.value: patch_field.get(CmdbObjectFieldKey.VALUE),
            }

            if CmdbObjectFieldKey.TYPE in patch_field:
                new_field[CmdbObjectFieldKey.TYPE.value] = patch_field[CmdbObjectFieldKey.TYPE]

            merged_fields.append(new_field)
            fields_by_name[field_name] = new_field

    return merged_fields


def create_patch_multi_data_rows(
        stored_sections: list[dict[str, Any]],
        created_rows: list[dict[str, Any]],
        valid_mds_section_ids: set[str],
    ) -> list[dict[str, Any]]:
    """
    Appends new multi-data-section rows, assigning each row's ``multi_data_id`` server-side

    The client supplies only ``section_id`` + ``data`` (no id). Each new row gets the next id from
    the section's ``highest_id`` counter (starting at 1), and that counter is advanced - so several
    creates in the same section get consecutive ids. If the object has no container for a section
    yet, one is seeded (first-row-add) as long as the section is declared by the type
    (``valid_mds_section_ids``); a section the type does not declare is refused. The input is
    deep-copied — it is not mutated

    Args:
        stored_sections (list[dict[str, Any]]): The object's current multi_data_sections
        created_rows (list[dict[str, Any]]): Rows to add, each ``{section_id, data}``
        valid_mds_section_ids (set[str]): The MDS section_ids declared by the object's type

    Raises:
        HTTPException: 400 when a section_id to create a row in is not declared by the type

    Returns:
        list[dict[str, Any]]: The multi_data_sections list with the new rows appended
    """
    result_sections: list[dict[str, Any]] = copy.deepcopy(stored_sections)
    sections_by_id: dict[Any, dict[str, Any]] = {
        section.get(CmdbObjectMdsKey.SECTION_ID): section for section in result_sections
    }

    for created_row in created_rows:
        section_id: str = created_row[CmdbObjectMdsKey.SECTION_ID]
        stored_section: dict[str, Any] | None = sections_by_id.get(section_id)

        if stored_section is None:
            if section_id not in valid_mds_section_ids:
                abort(400, f"Cannot create a row in unknown multi_data_section '{section_id}'!")

            # First-row-add: the type declares this MDS section but the object has no container yet
            stored_section = {
                CmdbObjectMdsKey.SECTION_ID.value: section_id,
                CmdbObjectMdsKey.HIGHEST_ID.value: 0,
                CmdbObjectMdsKey.VALUES.value: [],
            }
            result_sections.append(stored_section)
            sections_by_id[section_id] = stored_section

        new_multi_data_id: int = stored_section.get(CmdbObjectMdsKey.HIGHEST_ID.value, 0) + 1
        stored_section[CmdbObjectMdsKey.HIGHEST_ID.value] = new_multi_data_id

        stored_section.setdefault(CmdbObjectMdsKey.VALUES.value, []).append({
            CmdbObjectMdsRowKey.MULTI_DATA_ID.value: new_multi_data_id,
            CmdbObjectMdsRowKey.DATA.value: [dict(field) for field in created_row.get(CmdbObjectMdsRowKey.DATA, [])],
        })

    return result_sections


def edit_patch_multi_data_rows(
        stored_sections: list[dict[str, Any]],
        edited_rows: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
    """
    Merges field values into existing multi-data-section rows

    Rows are matched by ``section_id`` + ``multi_data_id``; the row's field values are merged by
    name (see merge_patch_fields), fields not listed are kept. Editing a row in a section the
    object does not have, or a ``multi_data_id`` that is not present, is refused (use
    created_mds_rows to add a row). The input is deep-copied — it is not mutated

    Args:
        stored_sections (list[dict[str, Any]]): The object's current multi_data_sections
        edited_rows (list[dict[str, Any]]): Rows to edit, each ``{section_id, multi_data_id, data}``

    Raises:
        HTTPException: 400 when a section_id or a multi_data_id to edit is not present

    Returns:
        list[dict[str, Any]]: The multi_data_sections list with the matched rows merged
    """
    result_sections: list[dict[str, Any]] = copy.deepcopy(stored_sections)
    sections_by_id: dict[Any, dict[str, Any]] = {
        section.get(CmdbObjectMdsKey.SECTION_ID): section for section in result_sections
    }

    for edited_row in edited_rows:
        section_id: str = edited_row[CmdbObjectMdsKey.SECTION_ID]
        stored_section: dict[str, Any] | None = sections_by_id.get(section_id)

        if stored_section is None:
            abort(400, f"Cannot edit a row in unknown multi_data_section '{section_id}'!")

        multi_data_id: int = edited_row[CmdbObjectMdsRowKey.MULTI_DATA_ID]
        rows_by_id: dict[Any, dict[str, Any]] = {
            row.get(CmdbObjectMdsRowKey.MULTI_DATA_ID): row
            for row in stored_section.get(CmdbObjectMdsKey.VALUES.value, [])
        }
        stored_row: dict[str, Any] | None = rows_by_id.get(multi_data_id)

        if stored_row is None:
            abort(400, f"Cannot edit unknown row multi_data_id {multi_data_id} in section '{section_id}'!")

        stored_row[CmdbObjectMdsRowKey.DATA.value] = merge_patch_fields(
            stored_row.get(CmdbObjectMdsRowKey.DATA.value, []),
            edited_row.get(CmdbObjectMdsRowKey.DATA, []),
        )

    return result_sections


def delete_patch_multi_data_rows(
        stored_sections: list[dict[str, Any]],
        deleted_rows: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
    """
    Removes multi-data-section rows identified by ``section_id`` + ``multi_data_id``

    A section left with no rows is kept (its ``values`` become an empty list and its ``highest_id``
    counter is preserved). Deleting a row from a section the object does not have, or a row whose
    ``multi_data_id`` is not present, is refused so the client is told exactly what did not match.
    The input is deep-copied — it is not mutated

    Args:
        stored_sections (list[dict[str, Any]]): The object's current multi_data_sections
        deleted_rows (list[dict[str, Any]]): Rows to remove, each ``{section_id, multi_data_id}``

    Raises:
        HTTPException: 400 when a section_id or a multi_data_id to delete is not present

    Returns:
        list[dict[str, Any]]: The multi_data_sections list with the rows removed
    """
    remaining_sections: list[dict[str, Any]] = copy.deepcopy(stored_sections)
    sections_by_id: dict[Any, dict[str, Any]] = {
        section.get(CmdbObjectMdsKey.SECTION_ID): section for section in remaining_sections
    }

    for deleted_row in deleted_rows:
        section_id: str = deleted_row[CmdbObjectMdsKey.SECTION_ID]
        stored_section: dict[str, Any] | None = sections_by_id.get(section_id)

        if stored_section is None:
            abort(400, f"Cannot delete a row from unknown multi_data_section '{section_id}'!")

        multi_data_id: int = deleted_row[CmdbObjectMdsRowKey.MULTI_DATA_ID]
        rows: list[dict[str, Any]] = stored_section.get(CmdbObjectMdsKey.VALUES.value, [])
        kept_rows: list[dict[str, Any]] = [
            row for row in rows if row.get(CmdbObjectMdsRowKey.MULTI_DATA_ID) != multi_data_id
        ]

        if len(kept_rows) == len(rows):
            abort(400, f"Cannot delete unknown row multi_data_id {multi_data_id} in section '{section_id}'!")

        stored_section[CmdbObjectMdsKey.VALUES.value] = kept_rows

    return remaining_sections


def build_patched_object_data(
        current_object: CmdbObject,
        patch_data: dict[str, Any],
        valid_mds_section_ids: set[str],
    ) -> dict[str, Any]:
    """
    Builds a complete object payload by applying a validated patch onto the stored object

    Starts from the stored object's canonical JSON, then merges the patched regular ``fields`` and
    applies the MDS row operations in order - create, edit, delete - carrying the optional edit
    ``comment`` through. The result is a full object dict suitable for the shared apply_object_update
    pipeline (which owns the version bump, invariants, persistence and side effects)

    Args:
        current_object (CmdbObject): The stored CmdbObject being patched
        patch_data (dict[str, Any]): The validated patch payload
        valid_mds_section_ids (set[str]): The MDS section_ids declared by the object's type,
            used to allow first-row-add into a section the object has no container for yet

    Returns:
        dict[str, Any]: The merged full-object payload
    """
    merged_data: dict[str, Any] = CmdbObject.to_json(current_object)

    patch_fields: list[dict[str, Any]] = patch_data.get(ObjectPatchKey.FIELDS.value, [])

    if patch_fields:
        merged_data[CmdbObjectKey.FIELDS.value] = merge_patch_fields(
            merged_data.get(CmdbObjectKey.FIELDS.value, []), patch_fields
        )

    created_rows: list[dict[str, Any]] = patch_data.get(ObjectPatchKey.CREATED_MDS_ROWS.value, [])
    edited_rows: list[dict[str, Any]] = patch_data.get(ObjectPatchKey.EDITED_MDS_ROWS.value, [])
    deleted_rows: list[dict[str, Any]] = patch_data.get(ObjectPatchKey.DELETED_MDS_ROWS.value, [])

    sections: list[dict[str, Any]] = merged_data.get(CmdbObjectKey.MULTI_DATA_SECTIONS.value, [])

    if created_rows:
        sections = create_patch_multi_data_rows(sections, created_rows, valid_mds_section_ids)

    if edited_rows:
        sections = edit_patch_multi_data_rows(sections, edited_rows)

    if deleted_rows:
        sections = delete_patch_multi_data_rows(sections, deleted_rows)

    if created_rows or edited_rows or deleted_rows:
        merged_data[CmdbObjectKey.MULTI_DATA_SECTIONS.value] = sections

    if ObjectPatchKey.COMMENT.value in patch_data:
        merged_data[ObjectPatchKey.COMMENT.value] = patch_data[ObjectPatchKey.COMMENT.value]

    if ObjectPatchKey.LOCATION_NAME.value in patch_data:
        merged_data[ObjectPatchKey.LOCATION_NAME.value] = patch_data[ObjectPatchKey.LOCATION_NAME.value]

    return merged_data


# --------------------------------------------------- DELETE GUARD --------------------------------------------------- #

def guard_object_delete(
        objects_manager: ObjectsManager,
        types_manager: TypesManager,
        request_user: CmdbUser,
        target_object: dict[str, Any],
    ) -> None:
    """
    Runs the full pre-delete guard for a single CmdbObject: IPAM license + IPAM invariants

    Combines the two checks every object-delete route performs up front: the IPAM license guard
    (blocks deleting an IPAM special-type object when IPAM is unlicensed) and the IPAM delete
    invariants (e.g. a SUPERNET / SUBNET still referenced by other IPAM objects). Aborts on the
    first violation; a no-op for a non-IPAM object with no dangling references

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        request_user (CmdbUser): The CmdbUser performing the deletion
        target_object (dict[str, Any]): The CmdbObject document being deleted

    Raises:
        HTTPException: 403 when a gated delete is unlicensed, 400 on an IPAM invariant violation
    """
    guard_object_delete_license(types_manager, request_user, target_object)

    ipam_delete_errors: list[dict[str, Any]] = enforce_delete_guards(
        objects_manager,
        types_manager,
        target_object,
    )

    if ipam_delete_errors:
        abort(400, format_errors_for_abort(ipam_delete_errors))


# ------------------------------------------------ OBJECT STATE CHANGE ----------------------------------------------- #

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


# ------------------------------------------------- OBJECT RE-ALIGNMENT ---------------------------------------------- #

def realign_objects_to_type(
        objects_manager: ObjectsManager,
        type_instance: CmdbType,
    ) -> set[str]:
    """
    Re-aligns every CmdbObject of a CmdbType with that type's current field definition

    Drops fields the object carries but the type no longer declares, and adds fields the type now
    declares but the object is missing (seeded with the type's default value under ``value`` or
    None). At most one ``$pull`` and one ``$addToSet`` per affected object are applied in a single
    bulk write. Returns the field names removed from at least one object so the caller can clean
    the type's reports once afterwards

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        type_instance (CmdbType): The CmdbType whose objects should be re-aligned

    Raises:
        HTTPException: 500 when the bulk write of the re-aligned objects fails

    Returns:
        set[str]: The field names dropped from at least one object of the type
    """
    type_fields: list[dict[str, Any]] = type_instance.fields
    type_fields_by_name: dict[str, dict[str, Any]] = {t_field["name"]: t_field for t_field in type_fields}
    type_field_names: set[str] = set(type_fields_by_name)

    objects_by_type: list[CmdbObject] = objects_manager.get_objects_by(type_id=type_instance.public_id)

    # One $pull (stale fields) and one $addToSet (missing fields) per affected object, applied in a
    # single bulk write instead of a write per object/field. Removed names accumulate for the caller
    object_ops: list[UpdateOne] = []
    removed_field_names: set[str] = set()

    for obj in objects_by_type:
        obj_field_names: set[str] = {field["name"] for field in obj.get_all_fields()}

        # Fields the object carries but the type no longer declares
        stale_field_names: set[str] = obj_field_names - type_field_names
        # Fields the type now declares but the object is missing
        missing_field_names: set[str] = type_field_names - obj_field_names

        if stale_field_names:
            object_ops.append(UpdateOne(
                {'public_id': obj.public_id},
                {'$pull': {'fields': {'name': {'$in': list(stale_field_names)}}}}
            ))
            removed_field_names |= stale_field_names

        if missing_field_names:
            # A field entry is a name+type+value triple; new fields start from the type's default
            # value (stored under 'value' on the field definition) or None
            new_field_entries: list[dict[str, Any]] = [
                {
                    "name": name,
                    "type": type_fields_by_name[name]["type"],
                    "value": type_fields_by_name[name].get("value"),
                }
                for name in missing_field_names
            ]
            object_ops.append(UpdateOne(
                {'public_id': obj.public_id},
                {'$addToSet': {'fields': {'$each': new_field_entries}}}
            ))

    if object_ops:
        try:
            objects_manager.bulk_write(object_ops)
        except Exception as error:
            LOGGER.error(
                "[realign_objects_to_type] Clean objects Exception: %s, Type: %s", error, type(error)
            )
            abort(500, "An internal server error occured while cleaning objects!")

    return removed_field_names


def clean_type_reports(
        reports_manager: ReportsManager,
        reports_for_type: list[dict[str, Any]],
        removed_field_names: set[str],
        type_instance: CmdbType,
    ) -> None:
    """
    Strips removed field occurrences from a CmdbType's reports and rebuilds their queries

    The route-layer wrapper around ``ReportsManager.strip_removed_fields_from_reports``: it owns only
    the HTTP error mapping, so the same cleanup can be reused by the non-route callers (the global
    section-template removal and the database updaters). A no-op when no field names were removed

    Args:
        reports_manager (ReportsManager): db interface for CmdbReports
        reports_for_type (list[dict[str, Any]]): The stored reports belonging to the type
        removed_field_names (set[str]): Field names that were dropped from the objects
        type_instance (CmdbType): The CmdbType the reports belong to (for the query rebuild)

    Raises:
        HTTPException: 500 when the bulk write of the cleaned reports fails
    """
    try:
        reports_manager.strip_removed_fields_from_reports(reports_for_type, removed_field_names, type_instance)
    except Exception as error:
        LOGGER.error(
            "[clean_type_reports] Clean Reports Exception: %s, Type: %s", error, type(error)
        )
        abort(500, "An internal server error occured while cleaning reports!")
