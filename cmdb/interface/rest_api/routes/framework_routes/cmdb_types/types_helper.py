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
from cmdb.manager import TypesManager, LocationsManager, ObjectsManager, ReportsManager

from cmdb.models.type_model.cmdb_type import CmdbType
from cmdb.models.user_model.cmdb_user import CmdbUser
from cmdb.models.object_model.cmdb_object import CmdbObject
from cmdb.interface.rest_api.responses.response_parameters import TypeIterationParameters, CollectionParameters
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #

def verify_type_is_unique(types_manager: TypesManager, name: str, public_id: int | None = None) -> None:
    """
    Checks the possible public_id and name of the CmdbType for Validity

    Args:
        types_manager (TypesManager): db interface for CmdbTypes
        name (str): name of the CmdbType which should be created
        public_id (int | None): already assigned public_id of the CmdbType which should be created
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


def prepare_builder_parameters(type_params: TypeIterationParameters) -> BuilderParameters:
    """
    Prepares BuilderParameters for running a db query

    Args:
        type_params (TypeIterationParameters): the recieved Type request parameters

    Returns:
        BuilderParameters: The prepared BuilderParameters
    """
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


def verify_type_deletable(
    request_user: CmdbUser,
    public_id: int,
    to_delete_type: dict[str, Any] | None = None
) -> None:
    """
    Checks if the Type is deletable. Issues trigger direct responses

    Args:
        request_user (CmdbUser): User requesting this data
        target_type (dict[str, Any] | None): The CmdbType which should be deleted
    """
    objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
    reports_manager: ReportsManager = ManagerProvider.get_manager(ManagerType.REPORTS, request_user)

    if not to_delete_type:
        abort(404, f"The Type with ID:{public_id} was not found!")

    objects_count = objects_manager.count_objects({'type_id':public_id})

    # Only possible to delete types when there are no objects
    if objects_count > 0:
        abort(403, "Delete not possible if Objects of this Type exist!")

    # Only possible to delete types when there are no reports using it
    reports_count = reports_manager.count_items({'type_id':public_id})

    if reports_count > 0:
        abort(403, "Delete not possible if Reports exist which are using this Type!")
