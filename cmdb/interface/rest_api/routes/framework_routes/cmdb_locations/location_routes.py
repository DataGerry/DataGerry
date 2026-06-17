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
Implementation of all API routes for CmdbLocations
"""
from logging import Logger, getLogger
from typing import Any
from flask import request, abort
from werkzeug import Response
from werkzeug.exceptions import HTTPException

from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.manager.query_builder import BuilderParameters
from cmdb.manager import (
    LocationsManager,
    TypesManager,
    ObjectsManager,
)

from cmdb.models.type_model.cmdb_type import CmdbType
from cmdb.models.user_model import CmdbUser
from cmdb.models.location_model.cmdb_location import CmdbLocation
from cmdb.framework.results import IterationResult
from cmdb.interface.route_utils import insert_request_user, verify_api_access
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.rest_api.responses.response_parameters import CollectionParameters
from cmdb.interface.rest_api.responses import (
    UpdateSingleResponse,
    GetMultiResponse,
    DefaultResponse,
)
from cmdb.interface.rest_api.routes.framework_routes.cmdb_locations.location_helper import (
    resolve_location_name,
    build_location_forest,
)

from cmdb.errors.manager.types_manager import TypesManagerGetError
from cmdb.errors.manager.objects_manager import ObjectsManagerGetError
from cmdb.errors.manager.locations_manager import (
    LocationsManagerInsertError,
    LocationsManagerGetError,
    LocationsManagerUpdateError,
    LocationsManagerDeleteError,
    LocationsManagerIterationError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

location_blueprint = APIBlueprint('locations', __name__)

# --------------------------------------------------- CRUD - CREATE -------------------------------------------------- #

@location_blueprint.route('/', methods=['POST'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@location_blueprint.protect(auth=True, right='base.framework.object.edit')
@location_blueprint.parse_request_body()
def insert_cmdb_location(data: dict[str, Any], request_user: CmdbUser) -> Response:
    """
    HTTP `POST` route to insert a CmdbLocation into the database

    Args:
        data (dict): JSON payload of the CmdbLocation which should be inserted
                     (expects `object_id`, `parent`, `type_id` and `name`)
        request_user (CmdbUser): User requesting this data

    Returns:
        DefaultResponse: The public_id of the newly created CmdbLocation
    """
    try:
        types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)
        locations_manager: LocationsManager = ManagerProvider.get_manager(ManagerType.LOCATIONS, request_user)
        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)

        location_creation_params: dict[str, Any] = {}

        location_creation_params['object_id'] = int(data['object_id'])
        location_creation_params['parent'] = int(data['parent'])
        location_creation_params['type_id'] = int(data['type_id'])

        object_type = types_manager.get_type(location_creation_params['type_id'])

        if not object_type:
            abort(404, "The Type of the linked Object was not found in the database!")

        object_type = CmdbType.from_data(object_type)

        location_creation_params['type_label'] = object_type.label
        location_creation_params['type_icon'] = object_type.get_icon()
        location_creation_params['type_selectable'] = object_type.selectable_as_parent

        location_creation_params['name'] = resolve_location_name(
            data.get('name'),
            location_creation_params['object_id'],
            objects_manager,
            request_user,
        )

        created_location_id = locations_manager.insert_location(location_creation_params)

        return DefaultResponse(created_location_id).make_response()
    except HTTPException as http_err:
        raise http_err
    except TypesManagerGetError as err:
        LOGGER.error("[insert_cmdb_location] TypesManagerGetError: %s", err, exc_info=True)
        abort(400, "Failed to retrieve the Type of the linked Object from the database!")
    except ObjectsManagerGetError as err:
        LOGGER.error("[insert_cmdb_location] ObjectsManagerGetError: %s", err, exc_info=True)
        abort(400, "Failed to retrieve the linked Object from the database!")
    except LocationsManagerInsertError as err:
        LOGGER.error("[insert_cmdb_location] LocationsManagerInsertError: %s", err, exc_info=True)
        abort(400, "Failed to insert the new Location in the database!")
    except Exception as err:
        LOGGER.error("[insert_cmdb_location] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while creating the new Location!")

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

@location_blueprint.route('/', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@location_blueprint.protect(auth=True, right='base.framework.object.view')
@location_blueprint.parse_collection_parameters()
def get_cmdb_locations(params: CollectionParameters, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route for getting multiple CmdbLocations

    Args:
        params (CollectionParameters): Filter for requested CmdbLocations
        request_user (CmdbUser): User requesting this data

    Returns:
        Response: All the CmdbLocations matching the CollectionParameters (GetMultiResponse)
    """
    try:
        locations_manager: LocationsManager = ManagerProvider.get_manager(ManagerType.LOCATIONS, request_user)

        builder_params = BuilderParameters(**CollectionParameters.get_builder_params(params))
        iteration_result: IterationResult[CmdbLocation] = locations_manager.iterate(builder_params)

        location_list: list[dict] = [CmdbLocation.to_json(location) for location in iteration_result.results]

        api_response = GetMultiResponse(location_list,
                                        iteration_result.total,
                                        params,
                                        request.url,
                                        request.method == 'HEAD')

        return api_response.make_response()
    except LocationsManagerIterationError as err:
        LOGGER.error("[get_cmdb_locations] LocationsManagerIterationError: %s", err, exc_info=True)
        abort(400, "Failed to retrieve Locations from the database!")
    except Exception as err:
        LOGGER.error("[get_cmdb_locations] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while iterating Locations!")


@location_blueprint.route('/tree', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@location_blueprint.protect(auth=True, right='base.framework.object.view')
@location_blueprint.parse_collection_parameters()
def get_cmdb_locations_tree(params: CollectionParameters, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route to return all CmdbLocations as a location tree

    Args:
        params (CollectionParameters): params for location tree (excluding root location)
        request_user (CmdbUser): User requesting the data

    Returns:
        Response: The CmdbLocations as a nested tree (GetMultiResponse)
    """
    try:
        locations_manager: LocationsManager = ManagerProvider.get_manager(ManagerType.LOCATIONS, request_user)

        builder_params = BuilderParameters(**CollectionParameters.get_builder_params(params))
        iteration_result: IterationResult[CmdbLocation] = locations_manager.iterate(builder_params)

        location_list: list[dict[str, Any]] = [CmdbLocation.to_json(location) for location in iteration_result.results]

        packed_locations: list[dict[str, Any]] = build_location_forest(location_list)

        api_response = GetMultiResponse(packed_locations,
                                        iteration_result.total,
                                        params,
                                        request.url,
                                        request.method == 'HEAD')

        return api_response.make_response()
    except LocationsManagerIterationError as err:
        LOGGER.error("[get_cmdb_locations_tree] LocationsManagerIterationError: %s", err, exc_info=True)
        abort(400, "Failed to retrieve Locations from the database!")
    except Exception as err:
        LOGGER.error("[get_cmdb_locations_tree] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while requesting the Location tree!")


@location_blueprint.route('/<int:public_id>', methods=['GET'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@location_blueprint.protect(auth=True, right='base.framework.object.view')
def get_cmdb_location(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `GET` route to retrieve a single CmdbLocation

    Args:
        public_id (int): public_id of the CmdbLocation
        request_user (CmdbUser): User requesting this data

    Returns:
        Response: The requested CmdbLocation (DefaultResponse)
    """
    try:
        locations_manager: LocationsManager = ManagerProvider.get_manager(ManagerType.LOCATIONS, request_user)

        requested_location = locations_manager.get_location(public_id)

        if not requested_location:
            abort(404, f"The Location with ID:{public_id} was not found!")

        return DefaultResponse(requested_location).make_response()
    except HTTPException as http_err:
        raise http_err
    except LocationsManagerGetError as err:
        LOGGER.error("[get_cmdb_location] LocationsManagerGetError: %s", err, exc_info=True)
        abort(400, f"Failed to retrieve the Location with ID: {public_id} from the database!")
    except Exception as err:
        LOGGER.error("[get_cmdb_location] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while retrieving the Location with ID:{public_id}!")


@location_blueprint.route('/<int:object_id>/object', methods=['GET'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@location_blueprint.protect(auth=True, right='base.framework.object.view')
def get_cmdb_location_for_object(object_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `GET` route to return the selected CmdbLocation for a given object_id (public_id of CmdbObject)

    Args:
        object_id (int): public_id of CmdbObject
        request_user (CmdbUser): User which is requesting the data

    Returns:
        Response: The CmdbLocation linked to the given object_id (DefaultResponse)
    """
    try:
        locations_manager: LocationsManager = ManagerProvider.get_manager(ManagerType.LOCATIONS, request_user)

        requested_location = locations_manager.get_location_for_object(object_id)

        if not requested_location:
            abort(404, f"The Location for Object with ID:{object_id} was not found!")

        return DefaultResponse(requested_location).make_response()
    except HTTPException as http_err:
        raise http_err
    except LocationsManagerGetError as err:
        LOGGER.error("[get_cmdb_location_for_object] LocationsManagerGetError: %s", err, exc_info=True)
        abort(400, f"Failed to retrieve the Location for Object with ID: {object_id} from the database!")
    except Exception as err:
        LOGGER.error("[get_cmdb_location_for_object] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while retrieving the Location for Object with ID:{object_id}!")


@location_blueprint.route('/<int:object_id>/parent', methods=['GET'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@location_blueprint.protect(auth=True, right='base.framework.object.view')
def get_cmdb_location_parent(object_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `GET` route to return the parent CmdbLocation for a given object_id (public_id of CmdbObject)

    Args:
        object_id (int): public_id of CmdbObject
        request_user (CmdbUser): User which is requesting the data

    Returns:
        Response: The parent CmdbLocation, or None when the object has no location (DefaultResponse)
    """
    try:
        locations_manager: LocationsManager = ManagerProvider.get_manager(ManagerType.LOCATIONS, request_user)

        parent = None

        current_location = locations_manager.get_location_for_object(object_id)

        if current_location:
            parent_id = current_location['parent']
            parent = locations_manager.get_location(parent_id)

            if not parent:
                abort(404, f"The parent Location for Object with ID:{object_id} was not found!")

        return DefaultResponse(parent).make_response()
    except HTTPException as http_err:
        raise http_err
    except LocationsManagerGetError as err:
        LOGGER.error("[get_cmdb_location_parent] LocationsManagerGetError: %s", err, exc_info=True)
        abort(400, f"Failed to retrieve the parent Location for Object with ID: {object_id} from the database!")
    except Exception as err:
        LOGGER.error("[get_cmdb_location_parent] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500,
            f"An internal server error occured while retrieving the parent location for Object with ID:{object_id}!"
        )


@location_blueprint.route('/<int:object_id>/children', methods=['GET'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@location_blueprint.protect(auth=True, right='base.framework.object.view')
def get_cmdb_children(object_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `GET` route to get all direct child CmdbLocations for a given object_id

    Args:
        object_id (int): public_id of CmdbObject
        request_user (CmdbUser): User which is requesting the data

    Returns:
        Response: The direct child CmdbLocations for the given object_id (DefaultResponse)
    """
    try:
        locations_manager: LocationsManager = ManagerProvider.get_manager(ManagerType.LOCATIONS, request_user)

        children: list[dict[str, Any]] = []

        current_location = locations_manager.get_location_for_object(object_id)

        if current_location:
            location_public_id = current_location['public_id']
            child_locations: list[CmdbLocation] = locations_manager.get_locations_by(parent=location_public_id)
            children = [CmdbLocation.to_json(child) for child in child_locations]

        return DefaultResponse(children).make_response()
    except LocationsManagerGetError as err:
        LOGGER.error("[get_cmdb_children] LocationsManagerGetError: %s", err, exc_info=True)
        abort(400, f"Failed to retrieve Location for Object with ID: {object_id} from the database!")
    except Exception as err:
        LOGGER.error("[get_cmdb_children] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500,
            f"An internal server error occured while retrieving childen for Location of Object with ID: {object_id}!"
        )

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

@location_blueprint.route('/update_location', methods=['PUT', 'PATCH'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@location_blueprint.protect(auth=True, right='base.framework.object.edit')
@location_blueprint.parse_request_body()
def update_cmdb_location_for_object(data: dict[str, Any], request_user: CmdbUser) -> Response:
    """
    HTTP `PUT`/`PATCH` route to update the CmdbLocation linked to an object

    Args:
        data (dict[str, Any]): JSON payload with the location parameters
                               (expects `object_id`, `parent` and `name`)
        request_user (CmdbUser): User requesting the update

    Returns:
        Response: Echo of the submitted payload after the update (UpdateSingleResponse)
    """
    try:
        locations_manager: LocationsManager = ManagerProvider.get_manager(ManagerType.LOCATIONS, request_user)
        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)

        location_update_params: dict[str, Any] = {}

        object_id = int(data['object_id'])
        location_update_params['parent'] = int(data['parent'])

        to_update_location = locations_manager.get_location_for_object(object_id)

        if not to_update_location:
            abort(404, f"The Location for Object with ID:{object_id} was not found!")

        location_update_params['name'] = resolve_location_name(
            data.get('name'),
            object_id,
            objects_manager,
            request_user,
        )

        locations_manager.update_location(object_id, location_update_params)

        return UpdateSingleResponse(data).make_response()
    except HTTPException as http_err:
        raise http_err
    except ObjectsManagerGetError as err:
        LOGGER.error("[update_cmdb_location_for_object] ObjectsManagerGetError: %s", err, exc_info=True)
        abort(400, "Failed to retrieve the linked Object from the database!")
    except LocationsManagerUpdateError as err:
        LOGGER.error("[update_cmdb_location_for_object] LocationsManagerUpdateError: %s", err, exc_info=True)
        abort(400, "Failed to update the Location in the database!")
    except Exception as err:
        LOGGER.error("[update_cmdb_location_for_object] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while updating a Location!")

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

@location_blueprint.route('/<int:object_id>/object', methods=['DELETE'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@location_blueprint.protect(auth=True, right='base.framework.object.edit')
def delete_cmdb_location_for_object(object_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `DELETE` route to delete the CmdbLocation linked to the given object_id

    Args:
        object_id (int): public_id of the CmdbObject whose Location should be deleted
        request_user (CmdbUser): user making the request

    Returns:
        Response: Acknowledgement of the deletion (DefaultResponse)
    """
    try:
        locations_manager: LocationsManager = ManagerProvider.get_manager(ManagerType.LOCATIONS, request_user)

        to_delete_location = locations_manager.get_location_for_object(object_id)

        if not to_delete_location:
            abort(404, f"The Location linked to Object with ID: {object_id} was not found in the database!")

        location_public_id = to_delete_location['public_id']

        ack = locations_manager.delete_location(location_public_id)

        return DefaultResponse(ack).make_response()
    except HTTPException as http_err:
        raise http_err
    except LocationsManagerDeleteError as err:
        LOGGER.error("[delete_cmdb_location_for_object] LocationsManagerDeleteError: %s", err, exc_info=True)
        abort(400, f"Failed to delete the Location linked to Object with ID: {object_id} from the database!")
    except Exception as err:
        LOGGER.error("[delete_cmdb_location_for_object] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while deleting an Location for Object with ID:{object_id}!")
