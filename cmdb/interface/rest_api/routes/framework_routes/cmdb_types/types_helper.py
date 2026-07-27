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
Helper methods for CmdbType API routes
"""
from logging import Logger, getLogger
from typing import Any

from flask import abort

from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.manager.query_builder import BuilderParameters
from cmdb.manager import (
    TypesManager,
    LocationsManager,
    ObjectsManager,
    ReportsManager,
    RelationsManager,
    CategoriesManager,
    CiExplorerProfileManager,
    ObjectGroupsManager,
    SectionTemplatesManager,
)

from cmdb.models.object_group_model import ObjectGroupMode
from cmdb.models.type_model.cmdb_type import CmdbType
from cmdb.models.type_model.field_type_enum import FieldType
from cmdb.models.type_model.field_key_enum import FieldKey
from cmdb.models.type_model.type_schema_key_enum import TypeSchemaKey
from cmdb.models.user_model.cmdb_user import CmdbUser
from cmdb.models.object_model.cmdb_object import CmdbObject
from cmdb.models.object_model import CmdbObjectKey, CmdbObjectFieldKey
from cmdb.models.reports_model.cmdb_report import CmdbReport
from cmdb.database.predefined_data.predefined_data_constants import LocationKey
from cmdb.framework.ipam.special_type_wiring import (
    handle_special_types,
    cleanup_type_references_from_all_types,
    cleanup_special_type_references,
)
from cmdb.interface.rest_api.responses.response_parameters import TypeIterationParameters, CollectionParameters
from cmdb.interface.rest_api.routes.cmdb_license.license_guard import abort_if_feature_locked
from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_helper import (
    realign_objects_to_type,
    clean_type_reports,
)
from cmdb.interface.rest_api.routes.framework_routes.cmdb_types.types_constants import (
    TYPE_NOT_FOUND_MESSAGE,
    TypeUserDataKey,
    TypeOverviewKey,
)
from cmdb.security.license.license_constants import LicenseFeature
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #

def enforce_special_type_license(request_user: CmdbUser, is_special_type: bool) -> None:
    """
    Blocks managing an IPAM special type when the IPAM feature is not licensed

    A no-op unless the write targets an IPAM special type (SUPERNET/SUBNET/VLAN). For a special type
    it delegates to the shared license guard, which aborts with HTTP 403 on-premise when IPAM is not
    licensed and is itself a no-op in cloud/local mode. Used by the create/update/delete type routes
    so the IPAM type gate lives in one place

    Args:
        request_user (CmdbUser): The user performing the type create/edit/delete
        is_special_type (bool): Whether the targeted type carries an IPAM special_type marker
    """
    if is_special_type:
        abort_if_feature_locked(LicenseFeature.IPAM, request_user)


def get_type_or_404(types_manager: TypesManager, public_id: int) -> dict[str, Any]:
    """
    Fetches a CmdbType document by public_id, aborting the request with HTTP 404 when it does not exist

    Centralizes the "look it up or 404" pattern shared by the CmdbType read / update routes so
    the lookup and its not-found message stay identical across them. Use
    `get_type_instance_or_404` when a CmdbType object is needed instead

    Args:
        types_manager (TypesManager): db interface for CmdbTypes
        public_id (int): public_id of the CmdbType to fetch

    Raises:
        HTTPException: 404 if no CmdbType has that public_id

    Returns:
        dict[str, Any]: The requested CmdbType document (never None - aborts 404 instead)
    """
    target_type: dict[str, Any] | None = types_manager.get_type(public_id)

    if not target_type:
        abort(404, TYPE_NOT_FOUND_MESSAGE.format(public_id=public_id))

    return target_type


def get_type_instance_or_404(types_manager: TypesManager, public_id: int) -> CmdbType:
    """
    Fetches a CmdbType by public_id as a hydrated CmdbType, aborting with HTTP 404 when it is missing

    The CmdbType counterpart of `get_type_or_404`, sharing its not-found message so the two are
    indistinguishable to the caller

    Args:
        types_manager (TypesManager): db interface for CmdbTypes
        public_id (int): public_id of the CmdbType to fetch

    Raises:
        HTTPException: 404 if no CmdbType has that public_id

    Returns:
        CmdbType: The requested CmdbType (never None - aborts 404 instead)
    """
    target_type: CmdbType | None = types_manager.get_type_instance(public_id)

    if not target_type:
        abort(404, TYPE_NOT_FOUND_MESSAGE.format(public_id=public_id))

    return target_type


def get_location_field(target_type: CmdbType) -> dict[str, Any] | None:
    """
    Returns the location-typed field dict of a CmdbType, or None when it has no location field

    A CmdbType has at most one location-typed field (see CLAUDE.md type invariants)

    Args:
        target_type (CmdbType): The CmdbType to inspect

    Returns:
        dict[str, Any] | None: The location field dict, or None when absent
    """
    return next(
        (f for f in target_type.get_fields() if f.get(FieldKey.TYPE) == FieldType.LOCATION),
        None,
    )


def verify_type_is_unique(
    types_manager: TypesManager,
    name: str,
    public_id: int | None = None,
    special_type: str | None = None
) -> None:
    """
    Validates that a candidate CmdbType's identifying attributes are unique in the database

    Aborts the request with HTTP 400 when the public_id is already taken, when the name
    collides with an existing CmdbType, when the name is missing, or when another CmdbType
    already carries the given SpecialType marker

    Args:
        types_manager (TypesManager): db interface for CmdbTypes
        name (str): Name of the CmdbType which should be created
        public_id (int | None): Pre-assigned public_id of the CmdbType, when present
        special_type (str | None): SpecialType marker of the CmdbType, when present
    """
    # Check public_id already exists
    if public_id:
        possible_type: dict[str, Any] | None = types_manager.get_type(public_id)

        if possible_type:
            abort(400, f"Type with ID:{public_id} already exists!")

    if name:
        # Check name is unique
        type_with_name: dict[str, Any] | None = types_manager.get_one_by({TypeSchemaKey.NAME: name})

        if type_with_name:
            abort(400, f"Type with name:{name} already exists!")
    else:
        abort(400, "Type data does not contain 'name' of the Type!")

    if special_type:
        special_type_exists: bool = types_manager.check_special_type_exists(special_type)

        if special_type_exists:
            abort(400, f"SpecialType: {special_type} already exists!")


def special_type_is_unchanged(old_st: str | None, new_st: str | None) -> bool:
    """
    Reports whether a CmdbType's 'special_type' value is the same before and after an update

    Args:
        old_st (str | None): The 'special_type' before the update
        new_st (str | None): The 'special_type' from the update payload

    Returns:
        bool: True if both sides match (including both being None), False otherwise
    """
    return old_st == new_st


def prepare_builder_parameters(type_params: TypeIterationParameters) -> BuilderParameters:
    """
    Prepares BuilderParameters for running a db query

    Args:
        type_params (TypeIterationParameters): the recieved Type request parameters

    Returns:
        BuilderParameters: The prepared BuilderParameters
    """
    if type_params.active:
        if isinstance(type_params.filter, dict):
            if type_params.filter.keys():
                type_params.filter.update({TypeSchemaKey.ACTIVE: type_params.active})
            else:
                type_params.filter = [
                    {'$match': {TypeSchemaKey.ACTIVE: type_params.active}},
                    {'$match': type_params.filter},
                ]
        elif isinstance(type_params.filter, list):
            type_params.filter.append({'$match': {TypeSchemaKey.ACTIVE: type_params.active}})

    return BuilderParameters(**CollectionParameters.get_builder_params(type_params))


def get_types_user_data(
        user_lookup: dict[int, CmdbUser],
        author_id: int | None = None,
        editor_id: int | None = None
    ) -> dict[str, Any]:
    """
    Formats relevant user data for a type

    Args:
        user_lookup (dict[int, CmdbUser]): lookup table of relevant CmdbUsers
        author_id (int | None, optional): public_id of author CmdbUser
        editor_id (int | None, optional): public_id of last editor CmdbUser

    Returns:
        dict[str, Any]: The formatted data of the author and editor
    """
    user_data: dict[str, Any] = {
        TypeUserDataKey.AUTHOR: None,
        TypeUserDataKey.AUTHOR_IMAGE: None,
        TypeUserDataKey.LAST_EDITOR: None,
        TypeUserDataKey.LAST_EDITOR_IMAGE: None,
    }

    author: CmdbUser = user_lookup.get(author_id)
    last_editor: CmdbUser | None = user_lookup.get(editor_id)

    if author:
        user_data[TypeUserDataKey.AUTHOR] = author.get_display_name()
        user_data[TypeUserDataKey.AUTHOR_IMAGE] = author.image

    if last_editor:
        user_data[TypeUserDataKey.LAST_EDITOR] = last_editor.get_display_name()
        user_data[TypeUserDataKey.LAST_EDITOR_IMAGE] = last_editor.image

    return user_data


def apply_type_changes_to_locations(request_user: CmdbUser, old_type: CmdbType, updated_type: CmdbType) -> None:
    """
    Checks if there are any relevant changes to the CmdbType which needs to be applied on CmdbLocations and
    applies them

    Args:
        request_user (CmdbUser): CmdbUser requesting this data
        old_type (CmdbType): State of the CmdbType before update
        updated_type (CmdbType): State of the CmdbType after update
    """
    # Only add changed fields to changed_data
    field_mapping: dict[str, Any] = {
        LocationKey.TYPE_LABEL: (old_type.label, updated_type.label),
        LocationKey.TYPE_ICON: (old_type.render_meta.icon, updated_type.render_meta.icon),
        LocationKey.TYPE_SELECTABLE: (old_type.selectable_as_parent, updated_type.selectable_as_parent),
    }

    changed_data: dict[str, Any] = {k: new for k, (old, new) in field_mapping.items() if old != new}

    # Early out if nothing changed
    if not changed_data:
        return

    locations_manager: LocationsManager = ManagerProvider.get_manager(ManagerType.LOCATIONS, request_user)

    # Update all affected CmdbLocations
    locations_manager.update_locations_by_type(updated_type.get_public_id(), changed_data)


def apply_type_changes_to_mds(request_user: CmdbUser, old_type: CmdbType, updated_type: dict[str, Any]) -> None:
    """
    Applies changes to all multi-data sections (MDS) for a given CmdbType

    Args:
        request_user (CmdbUser): The user performing the update
        old_type (CmdbType): The existing CmdbType object before changes
        updated_type (dict): The updated CmdbType data
    """
    objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
    types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)

    # Check and update all MDS for the CmdbType if required
    objects_to_update: list[CmdbObject] = types_manager.handle_multi_data_sections(old_type, updated_type)

    if objects_to_update:
        objects_manager.bulk_update_multi_data_sections(objects_to_update)


def realign_type_objects_if_fields_changed(
    request_user: CmdbUser,
    old_type: CmdbType,
    updated_type: CmdbType,
) -> None:
    """
    Re-aligns a CmdbType's objects and reports with its field set, only when the field names changed

    A pure metadata edit (label / icon / regex / default value / section reorder) leaves the set of
    field names unchanged, so the potentially large object sweep is skipped. When a field name was
    added or removed, every object of the type gains the newly declared fields (seeded with their
    default ``value``) and loses the fields the type no longer declares, and the removed field names
    are stripped from the type's reports. The matching MDS-row alignment is handled separately by
    ``apply_type_changes_to_mds`` (this reconciles the flat ``fields`` list; that reconciles the
    ``multi_data_sections`` rows)

    Args:
        request_user (CmdbUser): User performing the request
        old_type (CmdbType): State of the CmdbType before the update
        updated_type (CmdbType): The re-read CmdbType after the base update
    """
    old_field_names: set[str] = {field[FieldKey.NAME] for field in old_type.fields}
    new_field_names: set[str] = {field[FieldKey.NAME] for field in updated_type.fields}

    # Gate: only reconcile objects when the set of field names actually changed (add/remove)
    if old_field_names == new_field_names:
        return

    objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
    reports_manager: ReportsManager = ManagerProvider.get_manager(ManagerType.REPORTS, request_user)

    reports_for_type: list[dict[str, Any]] = objects_manager.get_many_from_other_collection(
        CmdbReport.COLLECTION,
        type_id=updated_type.public_id,
    )

    # Re-align every object of the type with its current field set, then strip any removed field
    # from the type's reports once
    removed_field_names: set[str] = realign_objects_to_type(objects_manager, updated_type)
    clean_type_reports(reports_manager, reports_for_type, removed_field_names, updated_type)


def get_objects_using_location_field(
    request_user: CmdbUser,
    target_type: CmdbType,
) -> list[int]:
    """
    Returns the public_ids of CmdbObjects that currently store a location value
    (an integer > 0) in the location-typed field of the given CmdbType

    Returns an empty list if the CmdbType has no location field

    Args:
        request_user (CmdbUser): User performing the request
        target_type (CmdbType): The CmdbType to inspect

    Returns:
        list[int]: public_ids of CmdbObjects that have a value in the location field
    """
    location_field: dict[str, Any] | None = get_location_field(target_type)

    if not location_field:
        return []

    objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)

    criteria: dict[str, Any] = {
        CmdbObjectKey.TYPE_ID: target_type.get_public_id(),
        CmdbObjectKey.FIELDS: {
            '$elemMatch': {
                CmdbObjectFieldKey.NAME: location_field[FieldKey.NAME],
                CmdbObjectFieldKey.VALUE: {'$gt': 0},
            },
        },
    }

    matching_objects: list[dict[str, Any]] = objects_manager.find_objects(criteria, as_dict=True)

    return [obj[CmdbObjectKey.PUBLIC_ID] for obj in matching_objects]


def build_location_usage_payload(request_user: CmdbUser, target_type: CmdbType) -> dict[str, Any]:
    """
    Builds the shared "is this Type's location placement in use" pre-check payload

    Resolves the CmdbObjects of the given CmdbType that currently store a location value and packs
    them into the {in_use, count, object_public_ids} shape returned by the location-field-usage and
    selectable-as-parent-usage GET routes. Both routes answer the same underlying question - are any
    objects of this type placed in the location tree - so they share this builder

    Args:
        request_user (CmdbUser): User performing the request
        target_type (CmdbType): The CmdbType to inspect

    Returns:
        dict[str, Any]: {in_use: bool, count: int, object_public_ids: list[int]}
    """
    object_public_ids: list[int] = get_objects_using_location_field(request_user, target_type)

    return {
        'in_use': bool(object_public_ids),
        'count': len(object_public_ids),
        'object_public_ids': object_public_ids,
    }


def guard_selectable_as_parent_change(request_user: CmdbUser, old_type: CmdbType, new_type: CmdbType) -> None:
    """
    Aborts 400 when an update turns 'selectable_as_parent' off while objects of the type are placed

    A CmdbType may only stop being selectable as a parent once no CmdbObject of that type is placed
    in the location tree; otherwise a placed object of a now-non-selectable type would remain in the
    tree (and could still act as a parent) while its type forbids it. Only the true -> false
    transition is guarded - keeping it off, or turning it on, is always allowed. 400 follows the
    codebase convention for business-rule rejections (the same as the location-field removal guard)

    Args:
        request_user (CmdbUser): User performing the request
        old_type (CmdbType): State of the CmdbType before the update
        new_type (CmdbType): State of the CmdbType the update would persist
    """
    turning_off: bool = old_type.selectable_as_parent and not new_type.selectable_as_parent

    if not turning_off:
        return

    object_public_ids: list[int] = get_objects_using_location_field(request_user, old_type)

    if object_public_ids:
        abort(
            400,
            "Cannot disable 'selectable as parent': "
            f"{len(object_public_ids)} Object(s) of this Type are placed in the location tree. "
        )


def verify_type_deletable(
    request_user: CmdbUser,
    public_id: int,
    to_delete_type: dict[str, Any] | None = None
) -> None:
    """
    Confirms a CmdbType can be safely deleted, aborting the request when it cannot

    Aborts with HTTP 404 when the CmdbType does not exist, HTTP 400 when at least one
    CmdbObject of this CmdbType still exists, or HTTP 400 when at least one CmdbReport
    still references the CmdbType. 400 follows the codebase convention for business-rule
    rejections (CLAUDE.md) - the same convention the location-field removal guard uses

    Args:
        request_user (CmdbUser): User performing the request
        public_id (int): public_id of the CmdbType being checked
        to_delete_type (dict[str, Any] | None): The CmdbType document to delete, or None
            when the lookup already returned no result
    """
    objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
    reports_manager: ReportsManager = ManagerProvider.get_manager(ManagerType.REPORTS, request_user)

    if not to_delete_type:
        abort(404, TYPE_NOT_FOUND_MESSAGE.format(public_id=public_id))

    objects_count = objects_manager.count_documents({CmdbObjectKey.TYPE_ID: public_id})

    # Only possible to delete types when there are no objects
    if objects_count > 0:
        abort(400, "Delete not possible if Objects of this Type exist!")

    # Only possible to delete types when there are no reports using it
    reports_count = reports_manager.count_documents({CmdbObjectKey.TYPE_ID: public_id})

    if reports_count > 0:
        abort(400, "Delete not possible if Reports exist which are using this Type!")


def type_deletion_followup(
    request_user: CmdbUser,
    public_id: int,
    special_type: str | None = None,
) -> None:
    """
    Performs cleanup actions that must run after a CmdbType has been deleted

    Removes the deleted type's id from relations, CiExplorerProfiles, dynamic object
    groups and the 'types' arrays of all CmdbCategories, and strips it from every other
    CmdbType's field-level 'ref_types' arrays so no surviving type still offers the
    deleted type as a reference target. When the deleted type carried a SpecialType
    marker, additionally drops the id from any 'ref_types' arrays that
    handle_special_types had cross-wired on the IPAM section template, so newly added
    'dg-ipam-interface' sections no longer offer it either

    Args:
        request_user (CmdbUser): User performing the request
        public_id (int): public_id of the CmdbType that was just deleted
        special_type (str | None): SpecialType marker of the deleted CmdbType, if any
    """
    relations_manager: RelationsManager = ManagerProvider.get_manager(ManagerType.RELATIONS, request_user)
    object_groups_manager: ObjectGroupsManager = ManagerProvider.get_manager(ManagerType.OBJECT_GROUP, request_user)
    ci_explorer_profile_manager: CiExplorerProfileManager = ManagerProvider.get_manager(
        ManagerType.CI_EXPLORER_PROFILE,
        request_user
    )
    types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)
    categories_manager: CategoriesManager = ManagerProvider.get_manager(ManagerType.CATEGORIES, request_user)

    # Delete this type_id from all relations parent and child ids
    relations_manager.remove_type_from_relations(public_id)

    # Delete this type_id from all CiExplorerProfiles
    ci_explorer_profile_manager.remove_type_from_profiles(public_id)

    # Delete the type from all dynamic groups
    object_groups_manager.remove_ids_from_groups(public_id, ObjectGroupMode.DYNAMIC)

    # Delete this type_id from the 'types' array of every CmdbCategory
    categories_manager.remove_type_from_categories(public_id)

    # Strip the deleted type id from every other CmdbType's field-level 'ref_types'
    updated_count: int = cleanup_type_references_from_all_types(types_manager, public_id)

    if updated_count:
        LOGGER.info(
            "Cleaned references to deleted CmdbType %s from %s sibling CmdbType(s)",
            public_id, updated_count,
        )

    # Drop the deleted type's id from cross-wired SpecialType 'ref_types' arrays
    if special_type:
        section_templates_manager: SectionTemplatesManager = ManagerProvider.get_manager(
            ManagerType.SECTION_TEMPLATES,
            request_user,
        )
        cleanup_special_type_references(
            types_manager,
            section_templates_manager,
            special_type,
            public_id,
        )


def guard_location_field_removal(request_user: CmdbUser, old_type: CmdbType, new_type: CmdbType) -> None:
    """
    Aborts 400 when an update removes the location field while CmdbObjects still hold a location value

    A CmdbType's location field may only be dropped once no CmdbObject of that type still stores a
    location value, otherwise those stored values would be silently orphaned

    Args:
        request_user (CmdbUser): User performing the request
        old_type (CmdbType): State of the CmdbType before the update
        new_type (CmdbType): State of the CmdbType the update would persist
    """
    removing_location_field: bool = get_location_field(old_type) is not None and get_location_field(new_type) is None

    if not removing_location_field:
        return

    object_public_ids: list[int] = get_objects_using_location_field(request_user, old_type)

    if object_public_ids:
        abort(
            400,
            "Cannot remove the location field: "
            f"{len(object_public_ids)} Object(s) of this Type still have a location value. "
        )


def compute_removed_global_templates(
    old_type: CmdbType,
    incoming_template_ids: set[str],
) -> tuple[set[str], dict[str, tuple[list[str], str]]]:
    """
    Determines which global section templates an update drops, snapshotting each one's section info

    Compares the pre-update template set to the incoming payload's set and, for each removed
    template still present on old_type, records its section field names and section type while
    they are still available - the blind update wipes those sections afterwards

    Args:
        old_type (CmdbType): State of the CmdbType before the update
        incoming_template_ids (set[str]): global_template_ids carried by the update payload

    Returns:
        tuple[set[str], dict[str, tuple[list[str], str]]]: the removed template names, and a map of
            template name -> (section field names, section type) for each removed template
    """
    removed_template_ids: set[str] = set(old_type.global_template_ids or []) - incoming_template_ids

    removed_template_hints: dict[str, tuple[list[str], str]] = {}

    for template_name in removed_template_ids:
        section = old_type.get_section(template_name)

        if section is not None:
            removed_template_hints[template_name] = (section.get_fields(), section.type)

    return removed_template_ids, removed_template_hints


def apply_removed_global_template_cleanup(
    section_templates_manager: SectionTemplatesManager,
    type_public_id: int,
    removed_template_ids: set[str],
    removed_template_hints: dict[str, tuple[list[str], str]],
) -> None:
    """
    Removes each dropped global section template from the updated CmdbType

    Args:
        section_templates_manager (SectionTemplatesManager): db interface for section templates
        type_public_id (int): public_id of the updated CmdbType to clean
        removed_template_ids (set[str]): names of the global templates being removed
        removed_template_hints (dict[str, tuple[list[str], str]]): map of template name ->
            (expected section field names, expected section type) snapshotted before the update
    """
    for template_name in removed_template_ids:
        expected_fields, expected_section_type = removed_template_hints.get(template_name, (None, None))
        section_templates_manager.cleanup_global_section_from_type(
            type_public_id,
            template_name,
            expected_field_names=expected_fields,
            expected_section_type=expected_section_type,
        )


def build_types_overview_items(
    types: list[dict[str, Any]],
    user_lookup: dict[int, CmdbUser],
) -> list[dict[str, Any]]:
    """
    Builds the per-type response items for the types overview listing

    Each item bundles the CmdbType document with its resolved author/editor display block, so the
    overview can render author/editor names without a per-type user lookup (they are pre-resolved
    from a single bulk ``get_user_lookup``)

    Args:
        types (list[dict[str, Any]]): The CmdbType documents to bundle
        user_lookup (dict[int, CmdbUser]): Lookup of the relevant author / editor CmdbUsers

    Returns:
        list[dict[str, Any]]: One {type_data, user_data} item per type
    """
    response_items: list[dict[str, Any]] = []

    for type_data in types:
        types_user_data: dict[str, Any] = get_types_user_data(
            user_lookup,
            type_data.get(TypeSchemaKey.AUTHOR_ID),
            type_data.get(TypeSchemaKey.EDITOR_ID),
        )

        response_items.append({
            TypeOverviewKey.TYPE_DATA: type_data,
            TypeOverviewKey.USER_DATA: types_user_data,
        })

    return response_items


def apply_type_update_side_effects(
    request_user: CmdbUser,
    types_manager: TypesManager,
    old_type: CmdbType,
    updated_type: CmdbType,
    removed_templates: tuple[set[str], dict[str, tuple[list[str], str]]],
) -> None:
    """
    Runs the persistence side effects that follow a CmdbType update

    In order: removes the dropped global section templates from the type, re-applies SpecialType
    ref_types cross-wiring, propagates label/icon/selectable changes to the type's CmdbLocations,
    and applies MDS field add/remove changes to the type's CmdbObjects

    Args:
        request_user (CmdbUser): User performing the request
        types_manager (TypesManager): db interface for CmdbTypes
        old_type (CmdbType): State of the CmdbType before the update
        updated_type (CmdbType): The re-read CmdbType after the base update
        removed_templates (tuple): (removed template names, per-template section hints) as returned
            by compute_removed_global_templates
    """
    removed_template_ids, removed_template_hints = removed_templates

    section_templates_manager: SectionTemplatesManager = ManagerProvider.get_manager(
        ManagerType.SECTION_TEMPLATES,
        request_user,
    )

    apply_removed_global_template_cleanup(
        section_templates_manager, updated_type.public_id, removed_template_ids, removed_template_hints,
    )

    if updated_type.special_type:
        handle_special_types(
            types_manager, updated_type.special_type, section_templates_manager, updated_type.public_id,
        )

    # Propagate label/icon/selectable changes to the type's CmdbLocations
    apply_type_changes_to_locations(request_user, old_type, updated_type)

    # Apply MDS field add/remove changes to the type's CmdbObjects (multi_data_sections rows)
    apply_type_changes_to_mds(request_user, old_type, CmdbType.to_json(updated_type))

    # Re-align the objects' flat field set (and the type's reports) when the field names changed -
    # this replaces the former manual "clean" step, applied automatically and only when needed
    realign_type_objects_if_fields_changed(request_user, old_type, updated_type)
