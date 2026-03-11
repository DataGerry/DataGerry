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
Implementation of all API routes for CmdbTypes
"""
from logging import Logger, getLogger
from typing import Any
from datetime import datetime, timezone

from flask import abort, request
from werkzeug import Response
from werkzeug.exceptions import HTTPException

from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.manager.query_builder import BuilderParameters
from cmdb.manager import (
    TypesManager,
    LocationsManager,
    ObjectsManager,
    ReportsManager,
    RelationsManager,
    UsersManager,
)

from cmdb.models.relation_model import CmdbRelation
from cmdb.models.user_model import CmdbUser
from cmdb.models.type_model import CmdbType
from cmdb.models.location_model.cmdb_location import CmdbLocation
from cmdb.models.object_model import CmdbObject
from cmdb.framework.results import IterationResult
from cmdb.interface.route_utils import insert_request_user, verify_api_access
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.rest_api.responses.response_parameters import (
    CollectionParameters,
    TypeIterationParameters,
)
from cmdb.interface.rest_api.responses import (
    DeleteSingleResponse,
    UpdateSingleResponse,
    InsertSingleResponse,
    GetMultiResponse,
    GetSingleResponse,
    DefaultResponse,
)

from cmdb.errors.manager import BaseManagerGetError
from cmdb.errors.manager.objects_manager import ObjectsManagerGetError, ObjectsManagerUpdateError
from cmdb.errors.manager.types_manager import (
    TypesManagerGetError,
    TypesManagerInsertError,
    TypesManagerDeleteError,
    TypesManagerIterationError,
    TypesManagerUpdateError,
    TypesManagerUpdateMDSError,
)
from cmdb.errors.manager.locations_manager import (
    LocationsManagerGetError,
    LocationsManagerUpdateError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

types_blueprint = APIBlueprint('types', __name__)

# --------------------------------------------------- CRUD - CREATE -------------------------------------------------- #

@types_blueprint.route('/', methods=['POST'])
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@insert_request_user
@types_blueprint.protect(auth=True, right='base.framework.type.add')
@types_blueprint.validate(CmdbType.SCHEMA)
def insert_cmdb_type(data: dict[str, Any], request_user: CmdbUser) -> Response:
    """
    HTTP `POST` route to insert a CmdbType into the database

    Args:
        data (CmdbType.SCHEMA): Data of the CmdbType which should be inserted
        request_user (CmdbUser): CmdbUser requesting this data

    Returns:
        InsertSingleResponse: The new CmdbType and its public_id
    """
    try:
        types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)

        data.setdefault('creation_time', datetime.now(timezone.utc))
        possible_id: Any | None = data.get('public_id')

        if possible_id:
            possible_type: dict[str, Any] | None = types_manager.get_type(possible_id)

            if possible_type:
                abort(400, f"Type with ID:{possible_id} already exists!")

        type_with_name = types_manager.get_one_by({'name': data['name']})

        if type_with_name:
            abort(400, f"Type with name:{data['name']} already exists!")

        result_id: int = types_manager.insert_type(data)
        created_type: dict[str, Any] | None = types_manager.get_type(result_id)

        if not created_type:
            abort(404, "Could not retrieve the created Type from the database!")

        return InsertSingleResponse(result_id=result_id, raw=created_type).make_response()
    except HTTPException as http_err:
        raise http_err
    except TypesManagerGetError as err:
        LOGGER.error("[insert_cmdb_type] %s: %s", type(err).__name__, err, exc_info=True)
        abort(400, "Failed to retrieve the created Type from the database!")
    except TypesManagerInsertError as err:
        LOGGER.error("[insert_cmdb_type] %s: %s", type(err), err, exc_info=True)
        abort(400, "Failed to insert the new Type into the database!")
    except Exception as err:
        LOGGER.error("[insert_cmdb_type] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while creating the new Type!")

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

@types_blueprint.route('/', methods=['GET', 'HEAD'])
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@insert_request_user
@types_blueprint.protect(auth=True, right='base.framework.type.view')
@types_blueprint.parse_parameters(TypeIterationParameters)
def get_cmdb_types(params: TypeIterationParameters, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route for getting multiple CmdbTypes

    Args:
        params (CollectionParameters): Filter for requested CmdbTypes
        request_user (CmdbUser): CmdbUser requesting this data

    Returns:
        GetMultiResponse: All the CmdbTypes matching the CollectionParameters
    """
    try:
        types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)

        view = params.active

        if view:
            if isinstance(params.filter, dict):
                if params.filter.keys():
                    params.filter.update({'active': view})
                else:
                    params.filter = [{'$match': {'active': view}}, {'$match': params.filter}]
            elif isinstance(params.filter, list):
                params.filter.append({'$match': {'active': view}})

        builder_params = BuilderParameters(**CollectionParameters.get_builder_params(params))

        iteration_result: IterationResult[CmdbType] = types_manager.iterate(builder_params)

        types = [CmdbType.to_json(type) for type in iteration_result.results]

        api_response = GetMultiResponse(types,
                                        total=iteration_result.total,
                                        params=params,
                                        url=request.url,
                                        body=request.method == 'HEAD')
        return api_response.make_response()
    except TypesManagerIterationError as err:
        LOGGER.error("[get_cmdb_types] %s: %s", type(err), err, exc_info=True)
        abort(400, "Failed to iterate Types from the database!")
    except Exception as err:
        LOGGER.error("[get_cmdb_types] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while retrieving the Types!")


@types_blueprint.route('/with_clean_status', methods=['GET', 'HEAD'])
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@insert_request_user
@types_blueprint.protect(auth=True, right='base.framework.type.view')
@types_blueprint.parse_parameters(TypeIterationParameters)
def get_cmdb_types_with_status(params: TypeIterationParameters, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route for getting multiple CmdbTypes with clean status

    Args:
        params (CollectionParameters): Filter for requested CmdbTypes
        request_user (CmdbUser): CmdbUser requesting this data

    Returns:
        GetMultiResponse: All the CmdbTypes matching the CollectionParameters
    """
    try:
        types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)
        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
        users_manager: UsersManager = ManagerProvider.get_manager(ManagerType.USERS, request_user)

        view: bool = params.active

        if view:
            if isinstance(params.filter, dict):
                if params.filter.keys():
                    params.filter.update({'active': view})
                else:
                    params.filter = [{'$match': {'active': view}}, {'$match': params.filter}]
            elif isinstance(params.filter, list):
                params.filter.append({'$match': {'active': view}})

        builder_params = BuilderParameters(**CollectionParameters.get_builder_params(params))

        iteration_result: IterationResult[CmdbType] = types_manager.iterate(builder_params)

        types: list[dict[str, Any]] = [CmdbType.to_json(type) for type in iteration_result.results]

        # Retrieve all type_ids
        type_ids: list[int] = [t["public_id"] for t in types if t.get("public_id") is not None]

        objects_of_types: list[CmdbObject] = objects_manager.find_objects(criteria={'type_id': {"$in": type_ids}})

        # Group objects
        objects_by_type: dict[int, list[CmdbObject]] = {}

        for obj in objects_of_types:
            objects_by_type.setdefault(obj.type_id, []).append(obj)

        # Get clean status of types
        response_items: list[dict[str, Any]] = []

        # Get all users for types
        user_ids = {
            uid
            for t in types
            for uid in (t.get("author_id"), t.get("editor_id"))
            if uid is not None
        }

        users: list[dict[str, Any]] = users_manager.find(criteria={"public_id": {"$in": list(user_ids)}})
        users: list[CmdbUser] = [CmdbUser.from_data(a_user) for a_user in users]

        user_lookup: dict[int, str] = {
            user.public_id: user.get_display_name()
            for user in users
        }

        for type_data in types:
            type_id = type_data["public_id"]
            expected_fields = {f["name"] for f in type_data["fields"]}

            type_objects: list[CmdbObject] = objects_by_type.get(type_id, [])

            clean = True

            for obj in type_objects:
                obj_fields = {f["name"] for f in obj.fields}

                if obj_fields != expected_fields:
                    clean = False
                    break

            author: str | None = user_lookup.get(type_data.get("author_id"))
            last_editor: str | None = user_lookup.get(type_data.get("editor_id"))

            response_items.append({
                "type_data": type_data,
                "author": author,
                "last_editor": last_editor,
                "clean_status": clean
            })

        api_response = GetMultiResponse(
            response_items,
            total=iteration_result.total,
            params=params,
            url=request.url,
            body=request.method == 'HEAD'
        )

        return api_response.make_response()
    except TypesManagerIterationError as err:
        LOGGER.error("[get_cmdb_types] %s: %s", type(err), err, exc_info=True)
        abort(400, "Failed to iterate Types from the database!")
    except Exception as err:
        LOGGER.error("[get_cmdb_types] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while retrieving the Types with clean status!")


@types_blueprint.route('/<int:public_id>', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@types_blueprint.protect(auth=True, right='base.framework.type.view')
def get_cmdb_type(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route to retrieve a single CmdbType

    Args:
        public_id (int): public_id of the CmdbType
        request_user (CmdbUser): CmdbUser requesting this data

    Returns:
        GetSingleResponse: The requested CmdbType
    """
    try:
        types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)

        requested_type = types_manager.get_type(public_id)

        if requested_type:
            return GetSingleResponse(requested_type, body=request.method == 'HEAD').make_response()

        abort(404, f"The Type with ID:{public_id} was not found!")
    except HTTPException as http_err:
        raise http_err
    except TypesManagerGetError as err:
        LOGGER.error("[get_cmdb_type] %s: %s", type(err), err, exc_info=True)
        abort(400, f"Failed to retrieve the Type with ID: {public_id} from the database!")
    except Exception as err:
        LOGGER.error("[get_cmdb_type] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while retrieving Type with ID:{public_id}!")


@types_blueprint.route('/count_objects/<int:public_id>', methods=['GET'])
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@insert_request_user
@types_blueprint.protect(auth=True, right='base.framework.type.view')
def count_objects_of_cmdb_type(public_id: int, request_user: CmdbUser) -> Response:
    """
    Counts the number of CmdbObjects in the database with the given public_id as the type_id

    Args:
        public_id (int): The public_id of the CmdbType to count CmdbObjects for
        request_user (CmdbUser): CmdbUser requesting this data

    Returns:
        DefaultResponse: An API response containing the count of CmdbObjects for the given type_id
    """
    try:
        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)

        if _fetch_only_active_objs():
            objects_count: int = objects_manager.count_objects({"type_id": public_id, "active": True})
        else:
            objects_count: int = objects_manager.count_objects({"type_id": public_id})

        return DefaultResponse(objects_count).make_response()
    except ObjectsManagerGetError as err:
        LOGGER.error("[count_objects_of_cmdb_type] ObjectsManagerGetError: %s", err, exc_info=True)
        abort(400, f"Failed to count Objects for Type with ID: {public_id}!")
    except Exception as err:
        LOGGER.error("[count_objects_of_cmdb_type] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while counting Objects for Type with ID: {public_id}!")

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

@types_blueprint.route('/<int:public_id>', methods=['PUT', 'PATCH'])
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@insert_request_user
@types_blueprint.protect(auth=True, right='base.framework.type.edit')
@types_blueprint.validate(CmdbType.SCHEMA)
def update_cmdb_type(public_id: int, data: dict[str, Any], request_user: CmdbUser) -> Response:
    """
    HTTP `PUT`/`PATCH` route to update a single CmdbType

    Args:
        public_id (int): public_id of the CmdbType which should be updated
        data (CmdbType.SCHEMA): New CmdbType data
        request_user (CmdbUser): CmdbUser requesting this data

    Returns:
        UpdateSingleResponse: The new data of the CmdbType
    """
    try:
        types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)
        locations_manager: LocationsManager = ManagerProvider.get_manager(ManagerType.LOCATIONS, request_user)
        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)

        unchanged_type = types_manager.get_type(public_id)

        if not unchanged_type:
            abort(404, f"The Type with ID:{public_id} was not found!")

        data['last_edit_time'] = datetime.now(timezone.utc)

        new_type_data = CmdbType.from_data(data)

        types_manager.update_type(public_id, CmdbType.to_json(new_type_data))

        updated_type = types_manager.get_type(public_id)
        updated_type = CmdbType.from_data(updated_type)

        # when type are updated, update all locations with relevant data from this type
        locations_with_type = locations_manager.get_locations_by(type_id=public_id)

        loc_data = {
            'type_label': updated_type.label,
            'type_icon': updated_type.render_meta.icon,
            'type_selectable': updated_type.selectable_as_parent
        }

        location: CmdbLocation
        for location in locations_with_type:
            locations_manager.update_location(location.public_id, loc_data, False)

        # check and update all multi data sections for the type if required
        updated_objects = types_manager.handle_mutli_data_sections(CmdbType.from_data(unchanged_type),
                                                                   data)

        # Update Objects
        an_object: CmdbObject
        for an_object in updated_objects:
            objects_manager.update_object(an_object.public_id, CmdbObject.to_json(an_object))

        return UpdateSingleResponse(data).make_response()
    except HTTPException as http_err:
        raise http_err
    except LocationsManagerGetError as err:
        LOGGER.error("[update_cmdb_type] LocationsManagerGetError: %s", err, exc_info=True)
        abort(400, "Although the Type got updated, retrieving the corresponding Locations failed!")
    except LocationsManagerUpdateError as err:
        LOGGER.error("[update_cmdb_type] LocationsManagerUpdateError: %s", err, exc_info=True)
        abort(400, "Although the Type got updated, the update of Locations failed!")
    except ObjectsManagerUpdateError as err:
        LOGGER.error("[update_cmdb_type] ObjectsManagerUpdateError: %s", err, exc_info=True)
        abort(400, "Although the Type got updated, the update of correspondings Objects failed!")
    except TypesManagerGetError as err:
        LOGGER.error("[update_cmdb_type] TypesManagerGetError: %s", err, exc_info=True)
        abort(400, f"Failed to retrieve the Type with ID: {public_id} from the database!")
    except TypesManagerUpdateError as err:
        LOGGER.error("[update_cmdb_type] TypesManagerUpdateError: %s", err, exc_info=True)
        abort(400, f"Failed to update the Type with ID: {public_id} from the database!")
    except TypesManagerUpdateMDSError as err:
        LOGGER.error("[update_cmdb_type] TypesManagerUpdateMDSError: %s", err, exc_info=True)
        abort(400, "Although the Type got updated, the Multi-Data-Section updates failed!")
    except Exception as err:
        LOGGER.error("[update_cmdb_type] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured when trying to update the Type with ID: {public_id}!")

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

@types_blueprint.route('/<int:public_id>', methods=['DELETE'])
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@insert_request_user
@types_blueprint.protect(auth=True, right='base.framework.type.delete')
def delete_cmdb_type(public_id: int, request_user: CmdbUser):
    """
    HTTP `DELETE` route to delete a single CmdbType

    Args:
        public_id (int): public_id of the CmdbType which should be deleted
        request_user (CmdbUser): CmdbUser requesting this data

    Returns:
        DeleteSingleResponse: The deleted CmdbType data
    """
    try:
        types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)
        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
        reports_manager: ReportsManager = ManagerProvider.get_manager(ManagerType.REPORTS, request_user)
        relations_manager: RelationsManager = ManagerProvider.get_manager(ManagerType.RELATIONS, request_user)

        to_delete_type = types_manager.get_type(public_id)

        if to_delete_type:
            objects_count = objects_manager.count_objects({'type_id':public_id})

            # Only possible to delete types when there are no objects
            if objects_count > 0:
                abort(403, "Delete not possible if Objects of this Type exist!")

            # Only possible to delete types when there are no reports using it
            reports_count = reports_manager.count_items({'type_id':public_id})

            if reports_count > 0:
                abort(403, "Delete not possible if Reports exist which are using this Type!")

            types_manager.delete_type(public_id)

            # TODO: REFACTOR-FIX (move in seperate function)
            try:
                # Delete this type_id from all relations parent and child ids
                relevant_relations_filter = {'$or':[
                                {'parent_type_ids': {'$in': [public_id]}},
                                {'child_type_ids': {'$in': [public_id]}}
                            ]}


                builder_params = BuilderParameters(criteria=relevant_relations_filter)

                iteration_result: IterationResult[CmdbRelation] = relations_manager.iterate(builder_params)

                relation_list: list[CmdbRelation] = list(iteration_result.results)

                for relation in relation_list:
                    relation.remove_type_id_from_relation(public_id)

                    relations_manager.update_relation(relation.public_id, CmdbRelation.to_json(relation))
            except Exception as error:
                LOGGER.error("[delete_cmdb_type] Relation Exception: %s. Type: %s", error, type(error), exc_info=True)
                abort(400, "Although the Type got deleted, Relations could not be updated!")

            api_response = DeleteSingleResponse(to_delete_type)

            return api_response.make_response()

        abort(404, f"The Type with ID:{public_id} was not found!")
    except HTTPException as http_err:
        raise http_err
    except TypesManagerGetError as err:
        LOGGER.error("[delete_cmdb_type] TypesManagerGetError: %s", err, exc_info=True)
        abort(400, f"Failed to retrieve the Type with ID: {public_id}!")
    except ObjectsManagerGetError as err:
        LOGGER.error("[delete_cmdb_type] ObjectsManagerGetError: %s", err, exc_info=True)
        abort(400, f"Failed to count Objects for Type with ID: {public_id}!")
    except BaseManagerGetError as err:
        #TODO: ERROR-FIX (raise specific reports error)
        LOGGER.error("[delete_cmdb_type] BaseManagerGetError: %s", err, exc_info=True)
        abort(400, "Failed to count Reports with this Type!")
    except TypesManagerDeleteError as err:
        LOGGER.error("[delete_cmdb_type] TypesManagerDeleteError: %s", err, exc_info=True)
        abort(400, f"Failed to delete the Type with ID: {public_id}!")
    except Exception as err:
        LOGGER.error("[delete_cmdb_type] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while deleting Type with ID: {public_id}!")

# -------------------------------------------------- HELPER METHODS -------------------------------------------------- #

def _fetch_only_active_objs() -> bool:
    """
    Checking if request have cookie parameter for object active state
    Returns:
        True if cookie is set or value is true else false
    """
    if request.args.get('onlyActiveObjCookie') is not None:
        value = request.args.get('onlyActiveObjCookie')
        return value in ['True', 'true']

    return False
