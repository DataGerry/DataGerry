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
    CiExplorerProfileManager,
    ObjectGroupsManager,
    SectionTemplatesManager,
)

from cmdb.models.object_group_model import ObjectGroupMode
from cmdb.models.type_model.cmdb_type import CmdbType
from cmdb.models.type_model.field_type_enum import FieldType
from cmdb.models.user_model.cmdb_user import CmdbUser
from cmdb.models.object_model.cmdb_object import CmdbObject
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.interface.rest_api.responses.response_parameters import TypeIterationParameters, CollectionParameters
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #

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
        type_with_name: dict[str, Any] | None = types_manager.get_one_by({'name': name})

        if type_with_name:
            abort(400, f"Type with name:{name} already exists!")
    else:
        abort(400, "Type data does not contain 'name' of the Type!")

    if special_type:
        special_type_exists: bool = types_manager.check_special_type_exists(special_type)

        if special_type_exists:
            abort(400, f"SpecialType: {special_type} already exists!")


def handle_special_types(
    types_manager: TypesManager,
    special_type: SpecialType,
    section_templates_manager: SectionTemplatesManager,
    special_type_id: int
) -> None:
    """
    Cross-wires the reference fields of IPAM SpecialTypes (SUPERNET, SUBNET, VLAN) and the
    'dg-ipam-interface' section template so their 'ref_types' lists include each newly created
    or updated SpecialType. Idempotent: no write happens when 'ref_types' is already correct

    Args:
        types_manager (TypesManager): db interface for CmdbTypes
        special_type (SpecialType): The SpecialType of the CmdbType that triggered the wiring
        section_templates_manager (SectionTemplatesManager): db interface for section templates
        special_type_id (int): public_id of the CmdbType carrying 'special_type'
    """
    if special_type == SpecialType.SUPERNET:
        subnet_type: dict[str, Any] | None = types_manager.get_one_by({'special_type': SpecialType.SUBNET})

        if not subnet_type:
            return

        updated: bool = ensure_ref_type(subnet_type['fields'], 'dg-supernet-ref', special_type_id)

        if updated:
            types_manager.update_type(subnet_type['public_id'], subnet_type)

    elif special_type == SpecialType.SUBNET:
        interface_template: dict[str, Any] | None = section_templates_manager.get_one_by({'name': 'dg-ipam-interface'})

        if interface_template:
            tpl_updated: bool = ensure_ref_type(interface_template['fields'], 'dg-interface-subnet', special_type_id)

            if tpl_updated:
                section_templates_manager.update_section_template(interface_template["public_id"], interface_template)

        vlan_type: dict[str, Any] | None = types_manager.get_one_by({'special_type': SpecialType.VLAN})

        if vlan_type:
            vlan_updated: bool = ensure_ref_type(vlan_type['fields'], 'dg-subnet-ref', special_type_id)

            if vlan_updated:
                types_manager.update_type(vlan_type['public_id'], vlan_type)

        subnet_type: dict[str, Any] | None = types_manager.get_one_by({'public_id': special_type_id})

        if not subnet_type:
            return

        supernet_type: dict[str, Any] | None = types_manager.get_one_by({'special_type': SpecialType.SUPERNET})

        subnet_updated: bool = False

        if supernet_type:
            subnet_updated |= ensure_ref_type(subnet_type['fields'], 'dg-supernet-ref', supernet_type['public_id'])

        subnet_updated |= ensure_ref_type(subnet_type['fields'], 'dg-parent-subnet-ref', special_type_id)

        if subnet_updated:
            types_manager.update_type(special_type_id, subnet_type)

    elif special_type == SpecialType.VLAN:
        subnet_type: dict[str, Any] | None = types_manager.get_one_by({'special_type': SpecialType.SUBNET})

        if not subnet_type:
            return

        vlan_type: dict[str, Any] | None = types_manager.get_one_by({'public_id': special_type_id})

        if not vlan_type:
            return

        updated = ensure_ref_type(vlan_type['fields'], 'dg-subnet-ref', subnet_type['public_id'])

        if updated:
            types_manager.update_type(vlan_type['public_id'], vlan_type)


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
                type_params.filter.update({'active': type_params.active})
            else:
                type_params.filter = [{'$match': {'active': type_params.active}}, {'$match': type_params.filter}]
        elif isinstance(type_params.filter, list):
            type_params.filter.append({'$match': {'active': type_params.active}})

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
        "author": None,
        "author_image": None,
        "last_editor": None,
        "last_editor_image": None,
    }

    author: CmdbUser = user_lookup.get(author_id)
    last_editor: CmdbUser| None = user_lookup.get(editor_id)

    if author:
        user_data["author"] = author.get_display_name()
        user_data["author_image"] = author.image

    if last_editor:
        user_data["last_editor"] = last_editor.get_display_name()
        user_data["last_editor_image"] = last_editor.image

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
        "type_label": (old_type.label, updated_type.label),
        "type_icon": (old_type.render_meta.icon, updated_type.render_meta.icon),
        "type_selectable": (old_type.selectable_as_parent, updated_type.selectable_as_parent),
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
    objects_to_update: list[CmdbObject] = types_manager.handle_mutli_data_sections(old_type, updated_type)

    if objects_to_update:
        objects_manager.bulk_update_multi_data_sections(objects_to_update)


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
    location_field: dict[str, Any] | None = next(
        (f for f in target_type.get_fields() if f.get('type') == FieldType.LOCATION),
        None,
    )

    if not location_field:
        return []

    objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)

    criteria: dict[str, Any] = {
        'type_id': target_type.get_public_id(),
        'fields': {
            '$elemMatch': {
                'name': location_field['name'],
                'value': {'$gt': 0},
            },
        },
    }

    matching_objects: list[dict[str, Any]] = objects_manager.find_objects(criteria, as_dict=True)

    return [obj['public_id'] for obj in matching_objects]


def verify_type_deletable(
    request_user: CmdbUser,
    public_id: int,
    to_delete_type: dict[str, Any] | None = None
) -> None:
    """
    Confirms a CmdbType can be safely deleted, aborting the request when it cannot

    Aborts with HTTP 404 when the CmdbType does not exist, HTTP 403 when at least one
    CmdbObject of this CmdbType still exists, or HTTP 403 when at least one CmdbReport
    still references the CmdbType

    Args:
        request_user (CmdbUser): User performing the request
        public_id (int): public_id of the CmdbType being checked
        to_delete_type (dict[str, Any] | None): The CmdbType document to delete, or None
            when the lookup already returned no result
    """
    objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
    reports_manager: ReportsManager = ManagerProvider.get_manager(ManagerType.REPORTS, request_user)

    if not to_delete_type:
        abort(404, f"The Type with ID:{public_id} was not found!")

    objects_count = objects_manager.count_documents({'type_id':public_id})

    # Only possible to delete types when there are no objects
    if objects_count > 0:
        abort(403, "Delete not possible if Objects of this Type exist!")

    # Only possible to delete types when there are no reports using it
    reports_count = reports_manager.count_documents({'type_id':public_id})

    if reports_count > 0:
        abort(403, "Delete not possible if Reports exist which are using this Type!")


def type_deletion_followup(
    request_user: CmdbUser,
    public_id: int,
    special_type: str | None = None,
) -> None:
    """
    Performs cleanup actions that must run after a CmdbType has been deleted

    Removes the deleted type's id from relations, CiExplorerProfiles and dynamic object
    groups. When the deleted type carried a SpecialType marker, also drops the id from any
    'ref_types' arrays that handle_special_types had cross-wired, so the surviving IPAM
    CmdbTypes and the 'dg-ipam-interface' section template no longer offer the deleted type
    as a valid reference target

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
    # Delete this type_id from all relations parent and child ids
    relations_manager.remove_type_from_relations(public_id)

    # Delete this type_id from all CiExplorerProfiles
    ci_explorer_profile_manager.remove_type_from_profiles(public_id)

    # Delete the type from all dynamic groups
    object_groups_manager.remove_ids_from_groups(public_id, ObjectGroupMode.DYNAMIC)

    # Drop the deleted type's id from cross-wired SpecialType 'ref_types' arrays
    if special_type:
        types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)
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


def ensure_ref_type(fields: list[dict[str, Any]], field_name: str, ref_id: int) -> bool:
    """
    Ensures 'ref_id' is present in the named field's 'ref_types' list

    Mutates the matching field's 'ref_types' in place, creating an empty list when missing.
    Idempotent: returns False when the field does not exist or the id is already present, so
    callers can branch on the return to decide whether a persist is required

    Args:
        fields (list[dict[str, Any]]): The CmdbType / section-template field list to mutate
        field_name (str): The target field's 'name'
        ref_id (int): The CmdbType public_id to add to 'ref_types'

    Returns:
        bool: True when 'ref_types' was modified, False otherwise
    """
    for field in fields:
        if field.get('name') == field_name:
            ref_types: list[int] = field.setdefault('ref_types', [])

            if ref_id not in ref_types:
                ref_types.append(ref_id)
                return True

            return False

    return False


def remove_ref_type(fields: list[dict[str, Any]], field_name: str, ref_id: int) -> bool:
    """
    Removes ref_id from field.ref_types if present

    Mirror of ensure_ref_type for cleanup paths. Idempotent: returns False when the field
    does not exist on the given list, when the field has no 'ref_types' list, or when
    'ref_id' is not in 'ref_types'

    Args:
        fields (list[dict[str, Any]]): The CmdbType / section-template field list to mutate
        field_name (str): The target field's 'name'
        ref_id (int): The CmdbType public_id to drop from 'ref_types'

    Returns:
        bool: True when 'ref_types' was modified, False otherwise
    """
    for field in fields:
        if field.get('name') == field_name:
            ref_types: Any = field.get('ref_types')

            if isinstance(ref_types, list) and ref_id in ref_types:
                ref_types.remove(ref_id)
                return True

            return False

    return False


def cleanup_special_type_references(
    types_manager: TypesManager,
    section_templates_manager: SectionTemplatesManager,
    special_type: str,
    deleted_type_id: int,
) -> None:
    """
    Inverse of handle_special_types: removes 'deleted_type_id' from any 'ref_types' arrays
    that handle_special_types would have populated for the given SpecialType

    SUPERNET: drops the id from SUBNET's 'dg-supernet-ref'.
    SUBNET:   drops the id from VLAN's 'dg-subnet-ref' and the 'dg-ipam-interface' section
              template's 'dg-interface-subnet'. The deleted SUBNET's own
              'dg-parent-subnet-ref' self-reference disappears with the type.
    VLAN:     no schema points at VLAN, no cleanup required.

    Idempotent: silently no-ops when the cross-wired CmdbTypes / section template do not
    exist, or when 'deleted_type_id' is not present in their 'ref_types'

    Args:
        types_manager (TypesManager): db interface for CmdbTypes
        section_templates_manager (SectionTemplatesManager): db interface for section templates
        special_type (str): SpecialType marker of the CmdbType that was just deleted
        deleted_type_id (int): public_id of the CmdbType that was just deleted
    """
    if special_type == SpecialType.SUPERNET:
        subnet_type: dict[str, Any] | None = types_manager.get_one_by(
            {'special_type': SpecialType.SUBNET},
        )

        if subnet_type and remove_ref_type(subnet_type['fields'], 'dg-supernet-ref', deleted_type_id):
            types_manager.update_type(subnet_type['public_id'], subnet_type)

    elif special_type == SpecialType.SUBNET:
        vlan_type: dict[str, Any] | None = types_manager.get_one_by(
            {'special_type': SpecialType.VLAN},
        )

        if vlan_type and remove_ref_type(vlan_type['fields'], 'dg-subnet-ref', deleted_type_id):
            types_manager.update_type(vlan_type['public_id'], vlan_type)

        interface_template: dict[str, Any] | None = section_templates_manager.get_one_by(
            {'name': 'dg-ipam-interface'},
        )

        if interface_template and remove_ref_type(
            interface_template['fields'], 'dg-interface-subnet', deleted_type_id,
        ):
            section_templates_manager.update_section_template(
                interface_template['public_id'],
                interface_template,
            )
