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
from cmdb.manager.ports_manager import PortsManager
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
from cmdb.models.type_model.section_key_enum import SectionKey
from cmdb.models.type_model.section_type_enum import SectionType
from cmdb.models.type_model.section_reference_key_enum import SectionReferenceKey
from cmdb.models.type_model.type_reference_section import TypeReferenceSection
from cmdb.models.type_model.type_reference_section_entry import resolve_pulled_field_names
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.user_model.cmdb_user import CmdbUser
from cmdb.models.object_model.cmdb_object import CmdbObject
from cmdb.models.object_model import CmdbObjectKey, CmdbObjectFieldKey
from cmdb.models.port_model import PortKey
from cmdb.models.reports_model.cmdb_report import CmdbReport
from cmdb.models.location_model.location_constants import LocationKey
from cmdb.framework.ipam.special_type_wiring import (
    handle_special_types,
    cleanup_type_references_from_all_types,
    cleanup_special_type_template_references,
)
from cmdb.interface.rest_api.responses.response_parameters import TypeIterationParameters, CollectionParameters
from cmdb.interface.rest_api.routes.cmdb_license.license_guard import abort_if_feature_locked
from cmdb.interface.rest_api.routes.report_routes.report_constants import ReportKey
from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_helper import (
    realign_objects_to_type,
    clean_type_reports,
)
from cmdb.interface.rest_api.routes.framework_routes.cmdb_types.types_constants import (
    TYPE_NOT_FOUND_MESSAGE,
    USES_PORTS_DISABLE_MESSAGE,
    UsesPortsUsageKey,
    REFERENCED_SECTION_REMOVAL_MESSAGE,
    REFERENCED_SECTION_DEPENDENT_FORMAT,
    REFERENCED_SECTION_DEPENDENT_TYPE_FORMAT,
    REFERENCED_SECTION_EMPTIED_MESSAGE,
    REFERENCED_SECTION_EMPTIED_DETAIL_FORMAT,
    REFERENCED_TYPE_DELETE_MESSAGE,
    ReferencedSectionUsageKey,
    TypeUserDataKey,
    TypeOverviewKey,
)
from cmdb.security.license.license_constants import LicenseFeature
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #

def enforce_special_type_license(request_user: CmdbUser, *special_types: Any) -> None:
    """
    Blocks managing a license-gated special type when its feature is not licensed

    A no-op unless one of the given markers names a license-gated SpecialType; for those it delegates
    to the shared license guard, which aborts with HTTP 403 on-premise when the feature is not
    licensed and is itself a no-op in cloud/local mode. The markers are matched per member rather
    than by the mere presence of a marker. Used by the create/update/delete type routes so the gate
    lives in one place

    Every gated member currently maps to LicenseFeature.IPAM - RACK included, as an interim decision
    (see SpecialType.get_license_gated_types)

    Args:
        request_user (CmdbUser): The user performing the type create/edit/delete
        *special_types (Any): The 'special_type' markers the write touches - the stored one, the
            requested one, or both on an update. None and non-SpecialType values are ignored
    """
    if any(SpecialType.is_license_gated(special_type) for special_type in special_types):
        abort_if_feature_locked(LicenseFeature.IPAM, request_user)


def enforce_uses_ports_license(request_user: CmdbUser, requested_uses_ports: Any) -> None:
    """
    Blocks turning 'uses_ports' on when the IPAM feature is not licensed

    Port Connectivity is gated by LicenseFeature.IPAM, and 'uses_ports' is the flag that opts a
    CmdbType into it, so it is the flag that has to be guarded: an unlicensed instance may not
    declare a type as port-bearing. Delegates to the shared license guard, which aborts with HTTP 403
    on-premise and is a no-op in cloud/local mode

    Gated on the REQUESTED value only, never on the stored one, which is deliberate and matches the
    rack precedent (`rack_object_hooks`): turning the flag **off** stays possible without the
    license, because cleanup is never blocked. A type that already carries it can therefore always be
    switched back

    Args:
        request_user (CmdbUser): The user performing the type create/edit
        requested_uses_ports (Any): The 'uses_ports' value the payload asks for. Anything falsy -
            including an absent key - is a no-op

    Raises:
        HTTPException: 403 when the payload turns 'uses_ports' on without the IPAM license
    """
    if requested_uses_ports:
        abort_if_feature_locked(LicenseFeature.IPAM, request_user)


def enforce_rack_selectable_as_parent(special_type: Any, data: dict[str, Any]) -> None:
    """
    Keeps a RACK CmdbType selectable as a parent Location, aborting 400 on an attempt to disable it

    A Rack holds its mounted objects by parenting their location nodes, and
    validate_object_location_change refuses a parent whose type is not selectable_as_parent - so a
    Rack type with the flag off could never have anything placed in it. The flag is therefore not a
    user choice for Racks: an explicit False is rejected, and a missing value is filled in. Mutates
    'data' in place. A no-op for every other type

    Note the existing guard_selectable_as_parent_change only blocks the flip while objects are
    already placed, which would leave a fresh Rack type free to turn it off

    Args:
        special_type (Any): The 'special_type' marker of the type being written
        data (dict[str, Any]): The type payload, updated in place when it is a Rack

    Raises:
        HTTPException: 400 when the payload explicitly disables selectable_as_parent for a Rack
    """
    if special_type != SpecialType.RACK:
        return

    if data.get(TypeSchemaKey.SELECTABLE_AS_PARENT) is False:
        abort(400, "A Rack type must stay selectable as a parent Location, "
                   "otherwise no object could ever be placed in a Rack!")

    data[TypeSchemaKey.SELECTABLE_AS_PARENT] = True


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
        updated_type (CmdbType): The CmdbType as just written by the base update
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

    Returns an empty list if the CmdbType has no location field. The result is unbounded - every
    matching public_id is returned, which for a large type is a large list (discussion backlog #187)

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

    # Only the public_ids are used, so the query projects them instead of loading whole documents -
    # this runs on every type-edit page load and inside both update guards
    matching_objects: list[dict[str, Any]] = objects_manager.find_objects(
        criteria,
        as_dict=True,
        projection={CmdbObjectKey.PUBLIC_ID: 1},
    )

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


def get_port_usage_of_type(request_user: CmdbUser, target_type: CmdbType) -> dict[str, int]:
    """
    Counts the CmdbPorts that exist on the CmdbObjects of one CmdbType

    A port stores its owner CmdbObject, not its type, so the question is two steps: which objects
    belong to this type, and how many ports name one of them. Resolved that way round on purpose - the
    alternative, a `$lookup` from framework.ports into framework.objects, would pay a join on every
    type-edit page load, and storing a type_id on the port would duplicate a fact the owner already
    holds and go stale if an object ever changed type.

    Only the object public_ids are read, never whole documents. Both counts are returned because the
    refusal message names them; the caller that only needs "any" reads the port count

    Args:
        request_user (CmdbUser): User performing the request
        target_type (CmdbType): The CmdbType to inspect

    Returns:
        dict[str, int]: {'port_count': ports in total, 'object_count': objects of the type carrying at
            least one port}. Both zero when the type has no objects or none of them has ports
    """
    objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
    ports_manager: PortsManager = ManagerProvider.get_manager(ManagerType.PORTS, request_user)

    object_documents: list[dict[str, Any]] = objects_manager.find_objects(
        {CmdbObjectKey.TYPE_ID: target_type.get_public_id()},
        as_dict=True,
        projection={CmdbObjectKey.PUBLIC_ID: 1},
    )
    object_ids: list[int] = [document[CmdbObjectKey.PUBLIC_ID] for document in object_documents]

    if not object_ids:
        return {UsesPortsUsageKey.PORT_COUNT.value: 0, UsesPortsUsageKey.OBJECT_COUNT.value: 0}

    owned_criteria: dict[str, Any] = {PortKey.OBJECT_ID.value: {'$in': object_ids}}

    port_count: int = ports_manager.count_documents(owned_criteria)
    owners_with_ports: list[Any] = ports_manager.get_distinct(PortKey.OBJECT_ID.value, owned_criteria)

    return {
        UsesPortsUsageKey.PORT_COUNT.value: port_count,
        UsesPortsUsageKey.OBJECT_COUNT.value: len(owners_with_ports),
    }


def build_uses_ports_usage_payload(request_user: CmdbUser, target_type: CmdbType) -> dict[str, Any]:
    """
    Builds the "may 'uses_ports' be turned off" pre-check payload

    Counts only, never an id list - the equivalent location payload is unbounded for a large type
    (discussion backlog #187) and the type builder only needs to know whether the flag may be cleared.
    `in_use: false` means it may

    Args:
        request_user (CmdbUser): User performing the request
        target_type (CmdbType): The CmdbType to inspect

    Returns:
        dict[str, Any]: {in_use, port_count, object_count}
    """
    usage: dict[str, int] = get_port_usage_of_type(request_user, target_type)

    return {
        UsesPortsUsageKey.IN_USE.value: usage[UsesPortsUsageKey.PORT_COUNT.value] > 0,
        **usage,
    }


def uses_ports_change_blocker(
    request_user: CmdbUser,
    old_type: CmdbType,
    new_type: CmdbType,
) -> str | None:
    """
    Reports why an update may not turn 'uses_ports' off, if it may not

    A CmdbType may only stop using ports once no port of its objects is left: the frontend renders the
    ports panel only for a port-bearing type, so clearing the flag would leave those ports as rows
    nothing in the UI can reach - and the port create route would refuse to recreate them.

    Only the true -> false transition is guarded. Turning it ON is always allowed here (step 1's
    license guard is what governs that direction), and keeping it off is a no-op. The reason is
    returned instead of raised so both write paths can use it: the route aborts with it
    (`guard_uses_ports_change`), the type import reports it per entry

    Args:
        request_user (CmdbUser): User performing the request
        old_type (CmdbType): State of the CmdbType before the update
        new_type (CmdbType): State of the CmdbType the update would persist

    Returns:
        str | None: The reason the change is refused, or None when the update is allowed
    """
    turning_off: bool = bool(old_type.uses_ports) and not bool(new_type.uses_ports)

    if not turning_off:
        return None

    usage: dict[str, int] = get_port_usage_of_type(request_user, old_type)

    if not usage[UsesPortsUsageKey.PORT_COUNT.value]:
        return None

    return USES_PORTS_DISABLE_MESSAGE.format(
        port_count=usage[UsesPortsUsageKey.PORT_COUNT.value],
        object_count=usage[UsesPortsUsageKey.OBJECT_COUNT.value],
    )


def guard_uses_ports_change(request_user: CmdbUser, old_type: CmdbType, new_type: CmdbType) -> None:
    """
    Aborts 400 when an update turns 'uses_ports' off while ports of the Type still exist

    The route-level wrapper around `uses_ports_change_blocker`. 400 follows the codebase convention
    for business-rule rejections, like the location-field and selectable-as-parent guards beside it

    Args:
        request_user (CmdbUser): User performing the request
        old_type (CmdbType): State of the CmdbType before the update
        new_type (CmdbType): State of the CmdbType the update would persist

    Raises:
        HTTPException: 400 when the flag may not be turned off
    """
    blocker: str | None = uses_ports_change_blocker(request_user, old_type, new_type)

    if blocker:
        abort(400, blocker)


def selectable_as_parent_change_blocker(
    request_user: CmdbUser,
    old_type: CmdbType,
    new_type: CmdbType,
) -> str | None:
    """
    Reports why an update may not turn 'selectable_as_parent' off, if it may not

    A CmdbType may only stop being selectable as a parent once no CmdbObject of that type is placed
    in the location tree; otherwise a placed object of a now-non-selectable type would remain in the
    tree (and could still act as a parent) while its type forbids it. Only the true -> false
    transition is guarded - keeping it off, or turning it on, is always allowed. The reason is
    returned instead of raised so both write paths can use it: the route aborts with it
    (`guard_selectable_as_parent_change`), the type import reports it per entry

    Args:
        request_user (CmdbUser): User performing the request
        old_type (CmdbType): State of the CmdbType before the update
        new_type (CmdbType): State of the CmdbType the update would persist

    Returns:
        str | None: The reason the change is refused, or None when the update is allowed
    """
    turning_off: bool = old_type.selectable_as_parent and not new_type.selectable_as_parent

    if not turning_off:
        return None

    object_public_ids: list[int] = get_objects_using_location_field(request_user, old_type)

    if not object_public_ids:
        return None

    return (
        "Cannot disable 'selectable as parent': "
        f"{len(object_public_ids)} Object(s) of this Type are placed in the location tree. "
    )


def guard_selectable_as_parent_change(request_user: CmdbUser, old_type: CmdbType, new_type: CmdbType) -> None:
    """
    Aborts 400 when an update turns 'selectable_as_parent' off while objects of the type are placed

    The route-level wrapper around `selectable_as_parent_change_blocker`. 400 follows the codebase
    convention for business-rule rejections (the same as the location-field removal guard)

    Args:
        request_user (CmdbUser): User performing the request
        old_type (CmdbType): State of the CmdbType before the update
        new_type (CmdbType): State of the CmdbType the update would persist

    Raises:
        HTTPException: 400 when 'selectable_as_parent' may not be turned off
    """
    blocker: str | None = selectable_as_parent_change_blocker(request_user, old_type, new_type)

    if blocker:
        abort(400, blocker)


def verify_type_deletable(
    request_user: CmdbUser,
    public_id: int,
    to_delete_type: dict[str, Any] | None = None
) -> None:
    """
    Confirms a CmdbType can be safely deleted, aborting the request when it cannot

    Aborts with HTTP 404 when the CmdbType does not exist, and with HTTP 400 when at least one
    CmdbObject of this CmdbType still exists, at least one CmdbReport still references it, or at
    least one other CmdbType pulls fields from it through a reference section. 400 follows the
    codebase convention for business-rule rejections (CLAUDE.md) - the same convention the
    location-field removal guard uses.

    The reference-section check is the type-level half of
    `referenced_section_removal_blocker`: deleting the referenced type leaves the dependent's
    ref-section pointing at a type_id that no longer resolves, which loses the referenced block from
    every object view of that type just as deleting the single section does

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
    reports_count = reports_manager.count_documents({ReportKey.TYPE_ID: public_id})

    if reports_count > 0:
        abort(400, "Delete not possible if Reports exist which are using this Type!")

    # Only possible to delete types no other type references in a ref-section. Self-references are
    # excluded: a type whose own ref-section points at itself goes away with it
    referencing_types: list[dict[str, Any]] = get_types_referencing_section(
        request_user, public_id, exclude_type_id=public_id,
    )

    if referencing_types:
        abort(400, REFERENCED_TYPE_DELETE_MESSAGE.format(
            dependents=describe_section_dependents(referencing_types),
        ))


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
    marker, the 'dg-ipam-interface' section template - the one document that type-level
    sweep cannot reach - is un-wired too, so newly added 'dg-ipam-interface' sections no
    longer offer it either

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

    # The type-level sweep above cannot reach the 'dg-ipam-interface' section template document, so a
    # deleted SpecialType is additionally un-wired there (template-only, no overlap with the sweep)
    if special_type:
        section_templates_manager: SectionTemplatesManager = ManagerProvider.get_manager(
            ManagerType.SECTION_TEMPLATES,
            request_user,
        )
        cleanup_special_type_template_references(
            section_templates_manager,
            special_type,
            public_id,
        )


def location_field_removal_blocker(
    request_user: CmdbUser,
    old_type: CmdbType,
    new_type: CmdbType,
) -> str | None:
    """
    Reports why an update may not remove the CmdbType's location field, if it may not

    A CmdbType's location field may only be dropped once no CmdbObject of that type still stores a
    location value, otherwise those stored values would be silently orphaned. The reason is returned
    instead of raised so both write paths can use it: the route aborts with it
    (`guard_location_field_removal`), the type import reports it per entry

    Args:
        request_user (CmdbUser): User performing the request
        old_type (CmdbType): State of the CmdbType before the update
        new_type (CmdbType): State of the CmdbType the update would persist

    Returns:
        str | None: The reason the removal is refused, or None when the update is allowed
    """
    removing_location_field: bool = get_location_field(old_type) is not None and get_location_field(new_type) is None

    if not removing_location_field:
        return None

    object_public_ids: list[int] = get_objects_using_location_field(request_user, old_type)

    if not object_public_ids:
        return None

    return (
        "Cannot remove the location field: "
        f"{len(object_public_ids)} Object(s) of this Type still have a location value. "
    )


def guard_location_field_removal(request_user: CmdbUser, old_type: CmdbType, new_type: CmdbType) -> None:
    """
    Aborts 400 when an update removes the location field while CmdbObjects still hold a location value

    The route-level wrapper around `location_field_removal_blocker`

    Args:
        request_user (CmdbUser): User performing the request
        old_type (CmdbType): State of the CmdbType before the update
        new_type (CmdbType): State of the CmdbType the update would persist

    Raises:
        HTTPException: 400 when the location field may not be removed
    """
    blocker: str | None = location_field_removal_blocker(request_user, old_type, new_type)

    if blocker:
        abort(400, blocker)


def get_types_referencing_section(
    request_user: CmdbUser,
    referenced_type_id: int,
    section_name: str | None = None,
    exclude_type_id: int | None = None,
) -> list[dict[str, Any]]:
    """
    Returns the CmdbTypes whose reference section pulls fields from the given Type (and section)

    A ref-section stores `{type_id, section_name, selected_fields}` and resolves the section by NAME
    at render time, so removing that section - or renaming it, which is a removal plus an addition -
    leaves the dependent type pointing at nothing: `_merge_reference_section` finds no section and
    drops the whole reference field, silently.

    The section list is matched with `$elemMatch` rather than two dotted paths, because dotted paths
    are satisfied by DIFFERENT array elements: a type with any ref-section plus an unrelated section
    naming this type_id would match, and be refused for a dependency it does not have

    Args:
        request_user (CmdbUser): User performing the request
        referenced_type_id (int): public_id of the CmdbType being referenced
        section_name (str | None): Name of the referenced section; None matches a reference to the
            type regardless of which of its sections is pulled. Defaults to None
        exclude_type_id (int | None): public_id of a CmdbType to leave out of the result - used to
            skip the type being written, whose own sections come from the payload rather than the
            database. Defaults to None

    Returns:
        list[dict[str, Any]]: The dependent types as {public_id, name, label} dicts, empty when none
    """
    return _find_referencing_types(
        request_user,
        referenced_type_id,
        section_name,
        exclude_type_id,
        # Only the identity of the dependents is reported, so whole type documents are never loaded.
        # '_id' is excluded explicitly: dbm.find only drops it when NO projection is passed, and these
        # dicts go straight into a REST response, where an ObjectId is not serialisable
        projection={
            '_id': 0,
            TypeSchemaKey.PUBLIC_ID.value: 1,
            TypeSchemaKey.NAME.value: 1,
            TypeSchemaKey.LABEL.value: 1,
        },
    )


def _find_referencing_types(
    request_user: CmdbUser,
    referenced_type_id: int,
    section_name: str | None,
    exclude_type_id: int | None,
    projection: dict[str, Any],
) -> list[dict[str, Any]]:
    """
    Runs the ref-section dependency query with the caller's projection

    Args:
        request_user (CmdbUser): User performing the request
        referenced_type_id (int): public_id of the CmdbType being referenced
        section_name (str | None): Name of the referenced section, None to match any
        exclude_type_id (int | None): public_id of a CmdbType to leave out of the result
        projection (dict[str, Any]): The MongoDB projection to read the dependents with

    Returns:
        list[dict[str, Any]]: The matching type documents, projected
    """
    types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)

    reference_key: str = SectionKey.REFERENCE.value
    element_match: dict[str, Any] = {
        SectionKey.TYPE.value: SectionType.REF_SECTION.value,
        f'{reference_key}.{SectionReferenceKey.TYPE_ID.value}': referenced_type_id,
    }

    if section_name is not None:
        element_match[f'{reference_key}.{SectionReferenceKey.SECTION_NAME.value}'] = section_name

    criteria: dict[str, Any] = {
        f'{TypeSchemaKey.RENDER_META.value}.{TypeSchemaKey.SECTIONS.value}': {'$elemMatch': element_match},
    }

    if exclude_type_id is not None:
        criteria[TypeSchemaKey.PUBLIC_ID.value] = {'$ne': exclude_type_id}

    return types_manager.find(criteria=criteria, projection=projection)


def get_removed_section_names(old_type: CmdbType, new_type: CmdbType) -> set[str]:
    """
    Returns the names of the sections an update would remove from a CmdbType

    A rename shows up here as a removal, which is correct: a ref-section resolves its target by name,
    so renaming the target breaks it exactly as deleting it does

    Args:
        old_type (CmdbType): State of the CmdbType before the update
        new_type (CmdbType): State of the CmdbType the update would persist

    Returns:
        set[str]: The removed section names, empty when the update removes none
    """
    old_names: set[str] = {section.name for section in old_type.get_sections()}
    new_names: set[str] = {section.name for section in new_type.get_sections()}

    return old_names - new_names


def get_own_section_references(type_instance: CmdbType, referenced_type_id: int) -> list[dict[str, Any]]:
    """
    Returns the reference sections of one Type that point at another Type's sections

    Needed for the self-referencing case: a CmdbType may hold a ref-section aimed at its own
    sections. That dependency cannot be read from the database during an update, because the type's
    sections are exactly what the payload is replacing - it has to be read from the payload

    Args:
        type_instance (CmdbType): The CmdbType whose reference sections are inspected
        referenced_type_id (int): public_id of the referenced CmdbType

    Returns:
        list[dict[str, Any]]: One {section_name, selected_fields} entry per matching reference section
    """
    return [
        {
            SectionReferenceKey.SECTION_NAME.value: section.reference.section_name,
            SectionReferenceKey.SELECTED_FIELDS.value: getattr(section.reference, 'selected_fields', None) or [],
        }
        for section in type_instance.get_sections()
        if isinstance(section, TypeReferenceSection)
        and getattr(section.reference, 'type_id', None) == referenced_type_id
        and getattr(section.reference, 'section_name', None)
    ]


def get_own_referenced_section_names(type_instance: CmdbType, referenced_type_id: int) -> set[str]:
    """
    Returns the section names of one Type that another Type's OWN reference sections point at

    Args:
        type_instance (CmdbType): The CmdbType whose reference sections are inspected
        referenced_type_id (int): public_id of the referenced CmdbType

    Returns:
        set[str]: The referenced section names, empty when none point at that type
    """
    return {
        reference[SectionReferenceKey.SECTION_NAME.value]
        for reference in get_own_section_references(type_instance, referenced_type_id)
    }


def describe_section_dependents(dependents: list[dict[str, Any]]) -> str:
    """
    Renders the dependent CmdbTypes of one section for a refusal message

    Args:
        dependents (list[dict[str, Any]]): The dependent types as {public_id, name, label} dicts

    Returns:
        str: The dependents as a comma separated "'label' (ID:n)" list
    """
    return ', '.join(
        REFERENCED_SECTION_DEPENDENT_TYPE_FORMAT.format(
            label=dependent.get(TypeSchemaKey.LABEL.value) or dependent.get(TypeSchemaKey.NAME.value),
            public_id=dependent.get(TypeSchemaKey.PUBLIC_ID.value),
        )
        for dependent in dependents
    )


def get_section_reference_selections(
    request_user: CmdbUser,
    referenced_type_id: int,
    section_name: str,
    exclude_type_id: int | None = None,
) -> list[dict[str, Any]]:
    """
    Returns each dependent of one referenced section together with the fields it pulls

    Same query as `get_types_referencing_section`, but it also reads the dependents' reference entries,
    because deciding whether an edit would leave a dependent with nothing to show needs its selection.
    A dependent holding two reference sections aimed at the same section yields one entry per section

    Args:
        request_user (CmdbUser): User performing the request
        referenced_type_id (int): public_id of the CmdbType being referenced
        section_name (str): Name of the referenced section
        exclude_type_id (int | None): public_id of a CmdbType to leave out. Defaults to None

    Returns:
        list[dict[str, Any]]: One {public_id, name, label, selected_fields} entry per reference
    """
    sections_path: str = f'{TypeSchemaKey.RENDER_META.value}.{TypeSchemaKey.SECTIONS.value}'

    dependents: list[dict[str, Any]] = _find_referencing_types(
        request_user,
        referenced_type_id,
        section_name,
        exclude_type_id,
        projection={
            '_id': 0,
            TypeSchemaKey.PUBLIC_ID.value: 1,
            TypeSchemaKey.NAME.value: 1,
            TypeSchemaKey.LABEL.value: 1,
            sections_path: 1,
        },
    )

    selections: list[dict[str, Any]] = []

    for dependent in dependents:
        render_meta: dict[str, Any] = dependent.get(TypeSchemaKey.RENDER_META.value) or {}

        for section in render_meta.get(TypeSchemaKey.SECTIONS.value) or []:
            reference: dict[str, Any] = section.get(SectionKey.REFERENCE.value) or {}

            # The query matched the DOCUMENT; which of its sections matched has to be re-established
            # here, because the projection returns the whole sections list
            if (section.get(SectionKey.TYPE.value) == SectionType.REF_SECTION.value
                    and reference.get(SectionReferenceKey.TYPE_ID.value) == referenced_type_id
                    and reference.get(SectionReferenceKey.SECTION_NAME.value) == section_name):
                selections.append({
                    TypeSchemaKey.PUBLIC_ID.value: dependent.get(TypeSchemaKey.PUBLIC_ID.value),
                    TypeSchemaKey.NAME.value: dependent.get(TypeSchemaKey.NAME.value),
                    TypeSchemaKey.LABEL.value: dependent.get(TypeSchemaKey.LABEL.value),
                    SectionReferenceKey.SELECTED_FIELDS.value:
                        reference.get(SectionReferenceKey.SELECTED_FIELDS.value) or [],
                })

    return selections


def get_section_field_names(type_instance: CmdbType) -> dict[str, list[str]]:
    """
    Returns the field names of every section of a CmdbType, keyed by section name

    Args:
        type_instance (CmdbType): The CmdbType to read

    Returns:
        dict[str, list[str]]: Section name mapped to its field names, in the section's own order
    """
    return {
        section.name: list(getattr(section, 'fields', None) or [])
        for section in type_instance.get_sections()
    }


def referenced_section_field_removal_blocker(
    request_user: CmdbUser,
    old_type: CmdbType,
    new_type: CmdbType,
) -> str | None:
    """
    Reports why an update may not leave a referenced section with nothing to show, if it may not

    The field-side half of the reference guard. A ref-section keeps working while at least one field
    it pulls is still in the referenced section: losing the column of a field that was just deleted is
    the direct consequence of deleting it, and moving fields between sections has to stay possible. But
    once the LAST pulled field leaves, the dependent renders an empty block - the same blank area a
    deleted section produces, reached from the field side. That is what this refuses.

    The trigger is a field leaving the SECTION, not the type: moving a field to a sibling section
    breaks a dependent identically. A section that already showed nothing is not protected, so an
    already-broken configuration cannot block unrelated edits.

    The reason is returned instead of raised so both write paths can use it: the route aborts with it
    (`guard_referenced_section_removal`), the type import reports it per entry

    Args:
        request_user (CmdbUser): User performing the request
        old_type (CmdbType): State of the CmdbType before the update
        new_type (CmdbType): State of the CmdbType the update would persist

    Returns:
        str | None: The reason the update is refused, or None when it is allowed
    """
    old_section_fields: dict[str, list[str]] = get_section_field_names(old_type)
    new_section_fields: dict[str, list[str]] = get_section_field_names(new_type)
    type_id: int = old_type.get_public_id()
    blocked: list[str] = []

    for section_name, old_field_names in old_section_fields.items():
        # A removed section is the other blocker's business; an unchanged one costs no lookup
        if section_name not in new_section_fields:
            continue

        new_field_names: list[str] = new_section_fields[section_name]

        if new_field_names == old_field_names:
            continue

        emptied: list[dict[str, Any]] = [
            selection for selection in _selections_of_section(request_user, new_type, type_id, section_name)
            if _reference_would_be_emptied(selection, old_field_names, new_field_names)
        ]

        if emptied:
            blocked.append(REFERENCED_SECTION_EMPTIED_DETAIL_FORMAT.format(
                section_name=section_name,
                dependents=describe_section_dependents(emptied),
            ))

    if not blocked:
        return None

    return REFERENCED_SECTION_EMPTIED_MESSAGE.format(details='; '.join(blocked))


def _selections_of_section(
    request_user: CmdbUser,
    new_type: CmdbType,
    type_id: int,
    section_name: str,
) -> list[dict[str, Any]]:
    """
    Returns every reference aimed at one section: the other Types' and the Type's own

    The stored copy of the type being written is excluded from the query and its own references are
    read from the payload instead, for the same reason as in the section-removal blocker: during its
    own update, what the database holds about its sections is already stale

    Args:
        request_user (CmdbUser): User performing the request
        new_type (CmdbType): State of the CmdbType the update would persist
        type_id (int): public_id of the CmdbType being written
        section_name (str): Name of the referenced section

    Returns:
        list[dict[str, Any]]: One {public_id, name, label, selected_fields} entry per reference
    """
    selections: list[dict[str, Any]] = get_section_reference_selections(
        request_user, type_id, section_name, exclude_type_id=type_id,
    )

    for own_reference in get_own_section_references(new_type, type_id):
        if own_reference[SectionReferenceKey.SECTION_NAME.value] == section_name:
            selections.append({
                TypeSchemaKey.PUBLIC_ID.value: type_id,
                TypeSchemaKey.NAME.value: new_type.name,
                TypeSchemaKey.LABEL.value: new_type.label,
                SectionReferenceKey.SELECTED_FIELDS.value:
                    own_reference[SectionReferenceKey.SELECTED_FIELDS.value],
            })

    return selections


def _reference_would_be_emptied(
    selection: dict[str, Any],
    old_field_names: list[str],
    new_field_names: list[str],
) -> bool:
    """
    Reports whether an update takes the last field a single reference section shows

    Both sides are resolved through the model's own selection rule, so this cannot disagree with what
    the renderer displays - including the case that makes a plain intersection wrong, an EMPTY
    selection meaning "every field of the section"

    Args:
        selection (dict[str, Any]): One reference's {..., selected_fields} entry
        old_field_names (list[str]): Field names the section carried before the update
        new_field_names (list[str]): Field names the section would carry after it

    Returns:
        bool: True when the reference showed something before and would show nothing after
    """
    selected_fields: list[str] = selection.get(SectionReferenceKey.SELECTED_FIELDS.value) or []

    shown_before: list[str] = resolve_pulled_field_names(selected_fields, old_field_names)
    shown_after: list[str] = resolve_pulled_field_names(selected_fields, new_field_names)

    return bool(shown_before) and not shown_after


def referenced_section_removal_blocker(
    request_user: CmdbUser,
    old_type: CmdbType,
    new_type: CmdbType,
) -> str | None:
    """
    Reports why an update may not remove a section another CmdbType references, if it may not

    A section may only be removed once no other CmdbType pulls its fields through a ref-section,
    otherwise that reference is left dangling and the dependent type's object view loses the whole
    referenced block without a word. An update that removes the section AND the ref-section pointing
    at it in the same payload is allowed - the self-reference is therefore judged against the NEW
    type, and the stored copy of the type being written is excluded from the database lookup.

    The reason is returned instead of raised so both write paths can use it: the route aborts with it
    (`guard_referenced_section_removal`), the type import reports it per entry

    Args:
        request_user (CmdbUser): User performing the request
        old_type (CmdbType): State of the CmdbType before the update
        new_type (CmdbType): State of the CmdbType the update would persist

    Returns:
        str | None: The reason the removal is refused, or None when the update is allowed
    """
    removed_sections: set[str] = get_removed_section_names(old_type, new_type)

    if not removed_sections:
        return None

    type_id: int = old_type.get_public_id()
    self_referenced: set[str] = get_own_referenced_section_names(new_type, type_id)
    blocked: list[str] = []

    for section_name in sorted(removed_sections):
        dependents: list[dict[str, Any]] = get_types_referencing_section(
            request_user, type_id, section_name, exclude_type_id=type_id,
        )

        if section_name in self_referenced:
            dependents = dependents + [{
                TypeSchemaKey.PUBLIC_ID.value: type_id,
                TypeSchemaKey.NAME.value: new_type.name,
                TypeSchemaKey.LABEL.value: new_type.label,
            }]

        if dependents:
            blocked.append(REFERENCED_SECTION_DEPENDENT_FORMAT.format(
                section_name=section_name,
                dependents=describe_section_dependents(dependents),
            ))

    if not blocked:
        return None

    return REFERENCED_SECTION_REMOVAL_MESSAGE.format(details='; '.join(blocked))


def guard_referenced_section_removal(request_user: CmdbUser, old_type: CmdbType, new_type: CmdbType) -> None:
    """
    Aborts 400 when an update breaks a section another CmdbType references in a ref-section

    The route-level wrapper around both halves of the rule: `referenced_section_removal_blocker`
    (the section itself is gone or renamed) and `referenced_section_field_removal_blocker` (the
    section survives but no longer carries any field the dependent shows)

    Args:
        request_user (CmdbUser): User performing the request
        old_type (CmdbType): State of the CmdbType before the update
        new_type (CmdbType): State of the CmdbType the update would persist

    Raises:
        HTTPException: 400 when the section may not be removed
    """
    blocker: str | None = (
        referenced_section_removal_blocker(request_user, old_type, new_type)
        or referenced_section_field_removal_blocker(request_user, old_type, new_type)
    )

    if blocker:
        abort(400, blocker)


def build_referenced_section_usage_payload(request_user: CmdbUser, target_type: CmdbType) -> dict[str, Any]:
    """
    Builds the "which of this Type's sections are referenced elsewhere" pre-check payload

    REFERENCING_TYPE_IDS answers whether the type may be deleted at all; SECTIONS answers it per
    section, so the type builder can disable the delete action on exactly the sections another Type
    depends on instead of learning about it from a 400 after the fact.

    A dependent naming a section that does not exist (data from before the guard) shows up in
    REFERENCING_TYPE_IDS but under no section, which is correct: no section of this type may be
    deleted on its account, but the type itself is still referenced

    Args:
        request_user (CmdbUser): User performing the request
        target_type (CmdbType): The CmdbType to inspect

    Returns:
        dict[str, Any]: {in_use, count, referencing_type_ids, sections}
    """
    type_id: int = target_type.get_public_id()
    dependents: list[dict[str, Any]] = get_types_referencing_section(
        request_user, type_id, exclude_type_id=type_id,
    )
    referencing_type_ids: list[int] = sorted(
        dependent[TypeSchemaKey.PUBLIC_ID.value] for dependent in dependents
    )

    sections: dict[str, list[dict[str, Any]]] = {}

    for section in target_type.get_sections():
        section_dependents = get_types_referencing_section(
            request_user, type_id, section.name, exclude_type_id=type_id,
        )

        if section_dependents:
            sections[section.name] = section_dependents

    return {
        ReferencedSectionUsageKey.IN_USE.value: bool(referencing_type_ids),
        ReferencedSectionUsageKey.COUNT.value: len(referencing_type_ids),
        ReferencedSectionUsageKey.REFERENCING_TYPE_IDS.value: referencing_type_ids,
        ReferencedSectionUsageKey.SECTIONS.value: sections,
    }


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
        updated_type (CmdbType): The CmdbType as just written by the base update
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
