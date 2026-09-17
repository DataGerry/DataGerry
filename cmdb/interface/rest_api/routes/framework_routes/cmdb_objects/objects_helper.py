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
Helper functions behind the CmdbObject routes

Everything the object routes do beyond request parsing lives here, grouped by the write path it
serves. The routes stay thin: they validate the request, resolve managers and delegate.

* **Create / update** - ``apply_object_insert`` and ``apply_object_update`` are the two pipelines; both
  resolve the type, enforce the licence and the per-feature write invariants, persist, then run the
  side effects. DataGerry has no partial-update semantics on this path: the complete object is always
  sent, so the payload is authoritative
* **Partial update (PATCH)** - the one route that does take a subset. ``validate_object_patch_payload``
  guards the body, the ``*_patch_multi_data_rows`` helpers apply the row operations, and
  ``build_patched_object_data`` merges the result into a full payload that is then handed to the
  SHARED ``apply_object_update`` pipeline, so a patch gets identical invariants, versioning and events
* **Delete** - ``guard_object[s]_delete`` refuses what may not be deleted (IPAM licence + invariants,
  and a Cable CI a Port connection still uses) and is shared by the single AND the bulk route so a new
  rule lands on both; ``delete_one_cascade`` runs the consequences (locations, object groups, relations,
  ports, racks, webhooks, log, cloud config-item sync)
* **Side effects** - ``handle_notify_webhooks``, ``handle_create_object_log`` and
  ``emit_object_*_events`` are **best-effort**: each catches and logs its own failures so a webhook or
  logging problem never rolls back a stored object. The trade-off is that a successful write can leave
  no audit entry, with nothing surfaced to the caller - recorded as discussion-backlog #160
* **Re-alignment** - ``realign_objects_to_type`` and ``clean_type_reports`` repair stored objects after
  their CmdbType changed

Field values are always stored as complete ``{name, value, type}`` triples;
``validate_and_fill_object_fields`` is what guarantees that, backfilling the ``type`` from the type
schema on every write path, so a caller (including PATCH) never has to supply it
"""
import copy
import json
from datetime import datetime, timezone
from logging import Logger, getLogger
from typing import Any

from bson import json_util
from pymongo import UpdateOne
from flask import abort, current_app

from cmdb.database.json_codec import default, object_hook
from cmdb.framework.rendering.render_list import RenderList
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.manager import (
    LogsManager,
    LocationsManager,
    ObjectsManager,
    ReportsManager,
    SectionTemplatesManager,
    TypesManager,
)

from cmdb.models.type_model.cmdb_type import CmdbType
from cmdb.models.type_model.field_type_enum import FieldType
from cmdb.models.type_model.field_key_enum import FieldKey
from cmdb.models.type_model.type_schema_key_enum import TypeSchemaKey
from cmdb.models.user_model.cmdb_user import CmdbUser
from cmdb.models.object_model.cmdb_object import CmdbObject
from cmdb.models.object_model import (
    CmdbObjectKey,
    CmdbObjectFieldKey,
    CmdbObjectMdsKey,
    CmdbObjectMdsRowKey,
)
from cmdb.models.log_model.log_action_enum import LogAction
from cmdb.models.webhook_model.webhook_event_type_enum import WebhookEventType
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
from cmdb.framework.object_required_fields import (
    build_missing_required_errors,
    collect_missing_required_values,
    collect_required_field_names,
    mds_section_field_names,
    split_required_field_names,
)
from cmdb.interface.rest_api.routes.port_routes.port_object_hooks import (
    guard_cable_objects_delete,
    handle_object_deleted as handle_port_object_deleted,
)
from cmdb.interface.rest_api.routes.rack_routes.rack_object_hooks import (
    guard_rack_location_change,
    reconcile_object_rack_membership,
    handle_object_deleted as handle_rack_object_deleted,
    handle_rack_object_updated,
)
from cmdb.security.acl.permission import AccessControlPermission
from cmdb.interface.rest_api.routes.cmdb_license.license_guard import abort_if_feature_locked
from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_side_effects_helper import (
    emit_object_update_events,
    handle_create_object_log,
    handle_delete_from_object_groups,
    handle_delete_invalid_object_relations,
    handle_notify_webhooks,
    handle_sync_config_item_count,
)
from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_constants import (
    ObjectViewMode,
    ObjectPatchKey,
    REQUIRED_FIELD_ERROR_SEPARATOR,
)
from cmdb.interface.rest_api.routes.framework_routes.cmdb_locations.location_helper import (
    extract_object_location_parent, validate_object_location_change, sync_object_location,
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


def build_field_value_map(fields: Any) -> dict[str, Any]:
    """
    Reshapes a stored ``fields`` list into a name-keyed value map

    The read-optimised half of ``ObjectViewMode.VALUES``: a consumer asking "what is 'hostname' worth"
    does a dict lookup instead of scanning the array. Only the value survives - each entry's ``type``
    is dropped, which is what makes the result unusable for a write (a stored entry must always be a
    complete {name, value, type} triple).

    Shared with the MDS reshaping, because an MDS row's ``data`` list stores the very same entry shape
    as the top-level ``fields`` list.

    Anything that is not a usable entry is skipped rather than raising: this runs on the read path, so
    a single malformed row must not cost the caller the whole response. A name that repeats resolves to
    the LAST entry, which cannot happen on a well-formed object (a field name is unique within its
    CmdbType) and is only reachable on corrupted data

    Args:
        fields (Any): The stored ``fields`` list, or an MDS row's ``data`` list

    Returns:
        dict[str, Any]: Field name mapped to its stored value, empty when there is nothing usable
    """
    value_map: dict[str, Any] = {}

    if not isinstance(fields, list):
        return value_map

    for field in fields:
        if not isinstance(field, dict):
            continue

        name: Any = field.get(CmdbObjectFieldKey.NAME.value)

        # A non-string name cannot be a JSON key; an empty one is kept deliberately, so the map stays a
        # faithful picture of what is stored rather than silently losing a field (backlog #199)
        if not isinstance(name, str):
            continue

        value_map[name] = field.get(CmdbObjectFieldKey.VALUE.value)

    return value_map


def build_mds_value_map(multi_data_sections: Any) -> dict[str, list[dict[str, Any]]]:
    """
    Reshapes a stored ``multi_data_sections`` list into a section-keyed map of row value maps

    Each section becomes one key - its ``section_id``, which is the section's name - holding its rows
    in stored order, and each row becomes a name-keyed value map built by ``build_field_value_map``.

    Two things are deliberately dropped, and both are why the result is read-only: the section's
    ``highest_id`` (the row-id counter) and every row's ``multi_data_id``. A row's identity IS its
    multi_data_id and never its position in the list, so the array index of a row in this map must not
    be mistaken for one.

    A section with no rows is kept as an empty list rather than omitted, so a consumer can tell "this
    section exists and is empty" from "this object has no such section"

    Args:
        multi_data_sections (Any): The stored ``multi_data_sections`` list

    Returns:
        dict[str, list[dict[str, Any]]]: Section name mapped to its rows as name-keyed value maps
    """
    value_map: dict[str, list[dict[str, Any]]] = {}

    if not isinstance(multi_data_sections, list):
        return value_map

    for section in multi_data_sections:
        if not isinstance(section, dict):
            continue

        section_id: Any = section.get(CmdbObjectMdsKey.SECTION_ID.value)

        if not isinstance(section_id, str):
            continue

        rows: Any = section.get(CmdbObjectMdsKey.VALUES.value)
        rows = rows if isinstance(rows, list) else []

        value_map[section_id] = [
            build_field_value_map(row.get(CmdbObjectMdsRowKey.DATA.value))
            for row in rows if isinstance(row, dict)
        ]

    return value_map


def build_object_value_view(object_data: dict[str, Any]) -> dict[str, Any]:
    """
    Serialises one stored CmdbObject document for ``ObjectViewMode.VALUES``

    Only ``fields`` and ``multi_data_sections`` change shape - both become name-keyed maps. Every other
    top-level key (``public_id``, ``type_id``, ``active``, the audit fields, ...) is passed through
    exactly as the native view returns it, so the two views differ in those two keys and nowhere else.

    The copy is SHALLOW on purpose: the two reshaped keys are replaced with freshly built objects, so
    nothing the caller receives aliases the stored document's field arrays, and the untouched values
    are shared rather than duplicated - this runs once per object on a list page, where a deep copy of
    every document would be the most expensive thing on the path

    Args:
        object_data (dict[str, Any]): The stored CmdbObject document

    Returns:
        dict[str, Any]: The document with its two field-carrying keys reshaped into name-keyed maps
    """
    value_view: dict[str, Any] = dict(object_data)

    value_view[CmdbObjectKey.FIELDS.value] = build_field_value_map(
        object_data.get(CmdbObjectKey.FIELDS.value),
    )
    value_view[CmdbObjectKey.MULTI_DATA_SECTIONS.value] = build_mds_value_map(
        object_data.get(CmdbObjectKey.MULTI_DATA_SECTIONS.value),
    )

    return value_view


def render_or_native(
        view: str,
        results: list[CmdbObject],
        request_user: CmdbUser,
    ) -> list[dict[str, Any]]:
    """
    Serialises a list of CmdbObjects according to the requested ``view`` mode

    Shared by the object list and the object reference routes so both apply the same
    native / values / render dispatch and the same 400 on an unknown view

    Args:
        view (str): The requested view mode (see ObjectViewMode); 'native' returns the stored
            documents, 'render' returns their rendered representation, 'values' returns the
            stored documents with their fields and multi_data_sections as name-keyed maps
        results (list[CmdbObject]): The CmdbObjects to serialise
        request_user (CmdbUser): The CmdbUser making the request (used by the renderer)

    Returns:
        list[dict[str, Any]]: One serialised entry per CmdbObject

    Raises:
        HTTPException: Aborts with 400 when ``view`` is not a known ObjectViewMode value
    """
    if view == ObjectViewMode.NATIVE:
        return [object_.__dict__ for object_ in results]

    if view == ObjectViewMode.VALUES:
        # Built from the native document, never from a render: the renderer's field entries are
        # whole type-field definitions, and this view wants the values alone (backlog #200)
        return [build_object_value_view(object_.__dict__) for object_ in results]

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

    # A port is stored outside its owner's document, so nothing else removes it
    handle_port_object_deleted(request_user, CmdbObject.to_json(deleted_object))

    # Send deletion event to all active webhooks
    handle_notify_webhooks(request_user, deleted_object, WebhookEventType.DELETE)

    # Create ObjectLog of the deletion
    handle_create_object_log(request_user, deleted_object, log_action)

    # Sync config item count in CLOUD_MODE. The total comes from the breakdown aggregation the sync
    # runs anyway, so the delete does not also pay for an unfiltered full-collection count
    if current_app.cloud_mode:
        handle_sync_config_item_count(request_user)


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
    type_id: int | None = object_data.get(CmdbObjectKey.TYPE_ID.value)
    if not type_id:
        abort(400, "Missing type_id in object data!")

    type_schema: dict[str, Any] | None = objects_manager.get_object_type(type_id, as_dict=True)

    if not type_schema:
        abort(400, f"Type with ID {type_id} of the Object was not found!")

    type_field_map = {
        field[FieldKey.NAME.value]: field[FieldKey.TYPE.value]
        for field in type_schema[TypeSchemaKey.FIELDS.value]
    }

    def validate_field_list(fields: list[dict[str, Any]]) -> None:
        """Validates every field in a list against the type and backfills missing 'type' keys"""
        for field in fields:
            field_name: str | None = field.get(FieldKey.NAME)

            if not field_name:
                abort(400, "One of the fields is missing a 'name' property!")

            if field_name not in type_field_map:
                abort(400, f"Field '{field_name}' is not defined in type {type_id}!")

            if not field.get(FieldKey.TYPE.value):
                field[FieldKey.TYPE.value] = type_field_map[field_name]

    # Validate normal object fields
    validate_field_list(object_data.get(CmdbObjectKey.FIELDS.value, []))

    # Validate multi-data sections
    for section in object_data.get(CmdbObjectKey.MULTI_DATA_SECTIONS.value, []):
        for value in section.get(CmdbObjectMdsKey.VALUES.value, []):
            validate_field_list(value.get(CmdbObjectMdsRowKey.DATA.value, []))


def validate_required_object_fields(object_data: dict[str, Any], object_type: CmdbType) -> None:
    """
    Rejects an object write that leaves a field its CmdbType marks 'required' without a value

    The same rule the object form applies in the frontend and the object importer applies to an
    uploaded row (see cmdb.framework.object_required_fields), enforced here for every write that
    reaches the REST routes: a required field must be carried by the payload with a value that is
    neither None nor the empty string. DataGerry always sends the complete object, so a required
    field the payload does not carry at all is missing too.

    A required field of a multi-data section is checked in every row the object carries for that
    section; a section without rows requires nothing

    Args:
        object_data (dict[str, Any]): The about-to-be-saved CmdbObject document
        object_type (CmdbType): The CmdbType of the object

    Raises:
        HTTPException: 400 when a required field of the type holds no value
    """
    required_top_level, required_by_section = split_required_field_names(
        collect_required_field_names(object_type.get_fields()),
        mds_section_field_names(object_type),
    )

    if not required_top_level and not required_by_section:
        return

    errors: list[str] = build_missing_required_errors(
        *collect_missing_required_values(object_data, required_top_level, required_by_section)
    )

    if errors:
        abort(400, REQUIRED_FIELD_ERROR_SEPARATOR.join(errors))


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
        new_object_data[CmdbObjectKey.PUBLIC_ID.value] = objects_manager.get_new_object_public_id()
    else:
        existing_object: dict[str, Any] | None = objects_manager.get_object(
            new_object_data[CmdbObjectKey.PUBLIC_ID.value]
        )

        if existing_object:
            abort(400, f'Object with ID: {new_object_data[CmdbObjectKey.PUBLIC_ID.value]} already exists!')

    object_type: CmdbType | None = objects_manager.get_object_type(new_object_data[CmdbObjectKey.TYPE_ID.value])

    if not object_type:
        abort(404, f"Type with ID:{new_object_data[CmdbObjectKey.TYPE_ID.value]} of new Object not found!")

    if 'active' not in new_object_data:
        new_object_data[CmdbObjectKey.ACTIVE.value] = True

    new_object_data[CmdbObjectKey.CREATION_TIME.value] = datetime.now(timezone.utc)
    new_object_data[CmdbObjectKey.VERSION.value] = CmdbObject.DEFAULT_VERSION
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
        abort(400, "The maximum amount of ConfigItems is reached!")


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

    # A field the type marks required may not be saved without a value
    validate_required_object_fields(new_object_data, object_type)

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
        # A new object is nobody's rack member yet, so only the Racks-do-not-nest half can bite here
        guard_rack_location_change(
            request_user, new_object_data[CmdbObjectKey.PUBLIC_ID.value], location_parent, locations_manager,
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
        # A location pointing at a Rack's node means membership of it, so the new object joins that Rack
        reconcile_object_rack_membership(
            request_user, new_object_id, location_parent, objects_manager, types_manager, locations_manager,
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
        handle_sync_config_item_count(request_user)

    handle_create_object_log(request_user, created_instance, LogAction.CREATE)

    return new_object_id


def compute_object_version(current_object: CmdbObject, updated_object: CmdbObject) -> tuple[str, dict[str, Any]]:
    """
    Derives the field-level diff and applies the resulting semantic version bump

    The bump is chosen from how many fields changed relative to the total field count: a single
    changed field is a PATCH, all fields a MAJOR, more than half a MINOR, and anything else a PATCH.
    ``updated_object`` is mutated in place with the new version, which is what makes the edit log's
    ``get_version()`` read agree with the version written into the document - until 2026-09-08
    ``update_version`` only returned the string, so the log recorded every edit one bump behind

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

# Cohesive single-object update orchestration (fetch -> guard -> validate -> persist -> side effects);
# the local count is inherent to the sequence, so the too-many-locals check is scoped off here
# too-many-locals: this is the object update ORCHESTRATOR - 8 arguments plus one local per pipeline
# step (candidate payload, resolved type, location placement, invariants, version bump, re-read,
# events). Extracting a step does not help: every candidate split has to hand 9+ values across the
# seam, which trips max-args instead and hides the order the steps must run in. Getting under the
# limit needs a parameter object for the managers, which changes the signature the object routes and
# the PATCH path call - see discussion-backlog #161
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

    if is_special_type_changed(
        current_object_instance.special_type, new_data.get(CmdbObjectKey.SPECIAL_TYPE.value),
    ):
        abort(400, f"SpecialType of an Object is not changable. Occured for Object with ID: {obj_id}")

    current_type_instance: CmdbType = resolve_object_type(
        objects_manager, current_object_instance.get_type_id(), type_cache,
    )

    new_data.update({
        CmdbObjectKey.PUBLIC_ID.value: obj_id,
        CmdbObjectKey.CREATION_TIME.value: current_object_instance.creation_time,
        CmdbObjectKey.AUTHOR_ID.value: current_object_instance.author_id,
        CmdbObjectKey.ACTIVE.value: (
            active_state if active_state in [True, False] else current_object_instance.active
        ),
        CmdbObjectKey.VERSION.value: payload.get(CmdbObjectKey.VERSION.value, current_object_instance.version),
        CmdbObjectKey.LAST_EDIT_TIME.value: datetime.now(timezone.utc),
        CmdbObjectKey.EDITOR_ID.value: request_user.public_id,
    })

    update_comment: str = new_data.pop('comment', "")
    location_name: str | None = new_data.pop('location_name', None)  # transient, never stored

    # Validate fields have a type (and backfill it) - the full payload is the source of truth
    validate_and_fill_object_fields(objects_manager, new_data)

    # A field the type marks required may not be saved without a value
    validate_required_object_fields(new_data, current_type_instance)

    # Location placement is validated BEFORE the write; the CmdbLocation mirror runs best-effort after
    has_location_field, location_parent = extract_object_location_parent(
        new_data.get(CmdbObjectKey.FIELDS.value, []),
    )
    locations_manager: LocationsManager | None = None

    if has_location_field:
        locations_manager = ManagerProvider.get_manager(ManagerType.LOCATIONS, request_user)
        validate_object_location_change(obj_id, location_parent, locations_manager)
        # A Rack owns where its PLACED members sit, so one may not be pointed somewhere else from the
        # object form - unplace it in the Rack view first. An unassigned member may leave (its membership
        # follows below), and a Rack may not be pointed into another Rack at all
        guard_rack_location_change(request_user, obj_id, location_parent, locations_manager)

    previous_object: dict[str, Any] = CmdbObject.to_json(current_object_instance)

    # Editing an IPAM special-type object (or adding/changing an interface subnet) needs an IPAM license
    guard_object_write_license(types_manager, request_user, new_data, previous_object)

    # Every feature's write invariants (IPAM, Rack) - also canonicalises values on the candidate
    if invariant_error := enforce_object_write_invariants(
        objects_manager,
        types_manager,
        new_data,
        previous_object=previous_object,
    ):
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
    new_data[CmdbObjectKey.VERSION.value] = new_version

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

    # The other direction: a location pointing at a Rack's node IS membership of that Rack, so the mount
    # row is created, moved or removed to match what the object's location now says
    if has_location_field:
        reconcile_object_rack_membership(
            request_user, obj_id, location_parent, objects_manager, types_manager, locations_manager,
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


# --------------------------------------------------- DELETE GUARD --------------------------------------------------- #

def guard_objects_delete(
        objects_manager: ObjectsManager,
        types_manager: TypesManager,
        request_user: CmdbUser,
        target_objects: list[dict[str, Any]],
    ) -> None:
    """
    Runs the full pre-delete guard for a WHOLE delete selection: IPAM license + IPAM invariants + cables

    The one place both delete routes state what may not be deleted, so a rule added here lands on the
    single and the bulk delete at once. Evaluated before anything is deleted and aborting on the first
    violation, which is what makes a bulk delete all-or-nothing: refusing halfway would leave the
    earlier targets already gone.

    Per target: the IPAM license guard (deleting an IPAM special-type object needs a valid license) and
    the IPAM delete invariants (e.g. a SUPERNET / SUBNET still referenced by other IPAM objects). For
    the selection as a whole: the Cable CI guard, which costs one query however many objects are being
    deleted - see `guard_cable_objects_delete`. A non-IPAM, non-Cable selection with no dangling
    references is a no-op

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        request_user (CmdbUser): The CmdbUser performing the deletion
        target_objects (list[dict[str, Any]]): The CmdbObject documents being deleted

    Raises:
        HTTPException: 403 when a gated delete is unlicensed, 400 on an IPAM invariant violation or
            when a Cable CI in the selection is still used by a CmdbPortConnection
    """
    for target_object in target_objects:
        guard_object_delete_license(types_manager, request_user, target_object)

        ipam_delete_errors: list[dict[str, Any]] = enforce_delete_guards(
            objects_manager,
            types_manager,
            target_object,
        )

        if ipam_delete_errors:
            abort(400, format_errors_for_abort(ipam_delete_errors))

    # A Port connection describes a physical patch and outlives its cable record, so a used Cable CI
    # is refused rather than cascaded or left dangling
    guard_cable_objects_delete(request_user, types_manager, target_objects)


def guard_object_delete(
        objects_manager: ObjectsManager,
        types_manager: TypesManager,
        request_user: CmdbUser,
        target_object: dict[str, Any],
    ) -> None:
    """
    Runs the full pre-delete guard for a single CmdbObject

    The one-target form of `guard_objects_delete`, kept because the single-object delete route reads
    exactly one object; the rules themselves live in the batched function so both routes cannot drift

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        request_user (CmdbUser): The CmdbUser performing the deletion
        target_object (dict[str, Any]): The CmdbObject document being deleted

    Raises:
        HTTPException: 403 when a gated delete is unlicensed, 400 on an IPAM invariant violation or
            when the object is a Cable CI still used by a CmdbPortConnection
    """
    guard_objects_delete(objects_manager, types_manager, request_user, [target_object])



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
