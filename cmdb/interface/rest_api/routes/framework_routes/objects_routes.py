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
Implementation of all API routes for CmdbObjects
"""
import json
import copy
from logging import Logger, getLogger
from typing import Any
from datetime import datetime, timezone
from bson import json_util
from flask import abort, current_app, request
from werkzeug import Response
from werkzeug.exceptions import HTTPException

from cmdb.database.database_utils import default, object_hook
from cmdb.database import MongoDBQueryBuilder
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.manager.query_builder import BuilderParameters
from cmdb.manager import (
    LocationsManager,
    LogsManager,
    ObjectsManager,
    ObjectLinksManager,
    ReportsManager,
    WebhooksManager,
    ObjectRelationsManager,
    ObjectRelationLogsManager,
    ObjectGroupsManager,
)

from cmdb.security.acl.permission import AccessControlPermission
from cmdb.models.type_model.cmdb_type import CmdbType
from cmdb.models.object_relation_model import CmdbObjectRelation
from cmdb.models.user_model import CmdbUser
from cmdb.models.webhook_model.webhook_event_type_enum import WebhookEventType
from cmdb.models.location_model.cmdb_location import CmdbLocation
from cmdb.models.object_model import CmdbObject
from cmdb.models.log_model import LogInteraction
from cmdb.models.log_model.log_action_enum import LogAction
from cmdb.models.log_model.cmdb_object_log import CmdbObjectLog
from cmdb.models.reports_model.cmdb_report import CmdbReport
from cmdb.framework.results import IterationResult
from cmdb.framework.rendering.cmdb_render import CmdbRender
from cmdb.framework.rendering.render_list import RenderList
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.route_utils import insert_request_user, sync_config_items, verify_api_access, handle_db_errors
from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.rest_api.responses import (
    GetListResponse,
    UpdateMultiResponse,
    UpdateSingleResponse,
    GetMultiResponse,
    DefaultResponse,
)
from cmdb.interface.rest_api.responses.response_parameters import CollectionParameters

from cmdb.errors.manager.objects_manager import (
    ObjectsManagerGetError,
    ObjectsManagerUpdateError,
    ObjectsManagerDeleteError,
    ObjectsManagerInsertError,
    ObjectsManagerIterationError,
)
from cmdb.errors.manager.object_relations_manager import ObjectRelationsManagerDeleteError
from cmdb.errors.manager.object_relation_logs_manager import ObjectRelationLogsManagerBuildError
from cmdb.errors.security import AccessDeniedError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

objects_blueprint = APIBlueprint('objects', __name__)

# --------------------------------------------------- CRUD - CREATE -------------------------------------------------- #

#TODO: REFACTOR-FIX (reduce complexity)
@objects_blueprint.route('/', methods=['POST'])
@handle_db_errors
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@objects_blueprint.protect(auth=True, right='base.framework.object.add')
def insert_cmdb_object(request_user: CmdbUser) -> Response:
    """
    HTTP `POST` route to insert a CmdbRelation into the database

    Args:
        request_user (CmdbUser): User requesting this data

    Returns:
        InsertSingleResponse: The new CmdbRelation and its public_id
    """
    try:
        #TODO: REFACTOR-FIX (pass the data same way as on other routes and add schema validation)
        new_object_json = json.dumps(request.json)

        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
        logs_manager: LogsManager = ManagerProvider.get_manager(ManagerType.LOGS, request_user)
        webhooks_manager: WebhooksManager = ManagerProvider.get_manager(ManagerType.WEBHOOKS, request_user)

        objects_count: int = objects_manager.count_objects()

        if current_app.cloud_mode:
            if check_config_item_limit_reached(request_user, objects_count):
                abort(400, "The maximum amout of ConfigItems is reached!")

        new_object_data = json.loads(new_object_json, object_hook=json_util.object_hook)

        if "public_id" not in new_object_data:
            new_object_data['public_id'] = objects_manager.get_new_object_public_id()
        else:
            existing_object: dict[str, Any] | None = objects_manager.get_object(new_object_data['public_id'])

            if existing_object:
                abort(400, f'Object with ID: {new_object_data["public_id"]} already exists!')

        if 'active' not in new_object_data:
            new_object_data['active'] = True

        new_object_data['creation_time'] = datetime.now(timezone.utc)
        new_object_data['version'] = '1.0.0'

        # Validate fields have type
        validate_and_fill_object_fields(objects_manager, new_object_data)

        new_object_id = objects_manager.insert_object(new_object_data, request_user, AccessControlPermission.CREATE)

        current_type_instance: CmdbType | None = objects_manager.get_object_type(new_object_data['type_id'])

        current_object: dict[str, Any] | None = objects_manager.get_object(new_object_id)

        if not current_object:
            abort(404, "Could not retrieve the created object from the database!")

        current_object: CmdbObject = CmdbObject.from_data(current_object)

        # Handle Webhook Events
        try:
            webhooks_manager.send_webhook_event(WebhookEventType.CREATE,
                                                object_after=CmdbObject.to_json(current_object))
        except Exception as err:
            #TODO: ERROR-FIX
            LOGGER.error(
                "[insert_cmdb_object] Unable to send Webhook Event. Error: %s , Type: %s",
                err, type(err), exc_info=True
            )

        # Render CmdbObject
        try:
            current_object_render_result = CmdbRender(
                                                current_object,
                                                current_type_instance,
                                                request_user,
                                                False
                                            ).result()
        except Exception as err:
            #TODO: ERROR-FIX
            LOGGER.error("[insert_cmdb_object] Error: %s , Type: %s", err, type(err), exc_info=True)
            abort(500, "Object could not be rendered!")

        try:
            if current_app.cloud_mode:
                objects_count = objects_manager.count_objects()

                success = sync_config_items(request_user.email, request_user.database, objects_count)

                if not success:
                    LOGGER.error(
                        "[insert_cmdb_object] Config items for User: '%s' not synced (StatusCode not 200)!",
                        request_user.email
                    )
        except Exception as error:
            LOGGER.error(
                "[insert_cmdb_object] Failed to sync config items count to service portal. Error: %s", error
            )

        # Generate new insert log
        try:
            log_params: dict[str, Any] = {
                "object_id": new_object_id,
                "user_id": request_user.get_public_id(),
                "user_name": request_user.get_display_name(),
                "comment": "Object created",
                "render_state": json.dumps(current_object_render_result, default=default).encode('UTF-8'),
                "version": current_object.version
            }

            logs_manager.insert_log(action=LogAction.CREATE, log_type=CmdbObjectLog.__name__, **log_params)
        except Exception as error:
            #TODO: ERROR-FIX
            LOGGER.error("[insert_cmdb_object] Failed to create ObjectLog. Error: %s", error)

        return DefaultResponse(new_object_id).make_response()
    except HTTPException as http_err:
        raise http_err
    except ObjectsManagerInsertError as err:
        LOGGER.error("[insert_cmdb_object] ObjectsManagerInsertError: %s", err, exc_info=True)
        abort(400, "Could not insert the new Object in the database!")
    except ObjectsManagerGetError as err:
        LOGGER.error("[insert_cmdb_object] ObjectsManagerGetError: %s", err, exc_info=True)
        abort(400, "Failed to retrieve Object related data from the database!")
    except AccessDeniedError as err:
        LOGGER.error("[insert_cmdb_object] AccessDeniedError: %s", err, exc_info=True)
        abort(403, "No permission to insert the Object!")
    except Exception as err:
        LOGGER.error("[insert_cmdb_object] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while creating the Object!")

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

@objects_blueprint.route('/<int:public_id>', methods=['GET'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@objects_blueprint.protect(auth=True, right='base.framework.object.view')
def get_cmdb_object(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `GET` route to retrieve a single CmdbObject with render information

    Args:
        public_id (int): public_id of the CmdbObject
        request_user (CmdbUser): User requesting this data

    Returns:
        DefaultResponse: The requested CmdbObject with render information
    """
    try:
        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)

        requested_object = objects_manager.get_object(public_id, request_user, AccessControlPermission.READ)

        if not requested_object:
            abort(404, f"Object with ID: {public_id} not found!")

        requested_object = CmdbObject.from_data(requested_object)
        type_instance = objects_manager.get_object_type(requested_object.get_type_id())

        if not type_instance:
            abort(500, "The Type of the requested Object could not be retrieved from the database!")

        try:
            render_result = CmdbRender(requested_object,
                                       type_instance,
                                       request_user,
                                       True
                                       ).result()
        except Exception as err:
            LOGGER.error("[get_cmdb_object] Error: %s , Type: %s", err, type(err), exc_info=True)
            abort(500, f"Object with ID: {public_id} could not be rendered!")

        return DefaultResponse(render_result).make_response()
    except HTTPException as http_err:
        raise http_err
    except ObjectsManagerGetError as err:
        LOGGER.error("[get_cmdb_object] ObjectsManagerGetError: %s", err, exc_info=True)
        abort(400, f"Failed to retrieve the Object with ID: {public_id} from the database!")
    except AccessDeniedError as err:
        LOGGER.error("[get_cmdb_object] AccessDeniedError: %s", err, exc_info=True)
        abort(403, "No permission to retrieve the object!")
    except Exception as err:
        LOGGER.error("[get_cmdb_object] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while retrieving the Object with ID: {public_id}!")


@objects_blueprint.route('/', methods=['GET', 'HEAD'])
@objects_blueprint.parse_collection_parameters(view='native')
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@objects_blueprint.protect(auth=True, right='base.framework.object.view')
def get_cmdb_objects(params: CollectionParameters, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route for getting multiple CmdbObjects

    Args:
        params (CollectionParameters): Filter for requested CmdbObjects
        request_user (CmdbUser): User requesting this data

    Returns:
        GetMultiResponse: All the CmdbObjects matching the CollectionParameters
    """
    try:
        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)

        view = params.optional.get('view', 'native')

        if _fetch_only_active_objs():
            if isinstance(params.filter, dict):
                params.filter = [{'$match': params.filter}]
                params.filter.append({'$match': {'active': {"$eq": True}}})
            elif isinstance(params.filter, list):
                params.filter.append({'$match': {'active': {"$eq": True}}})

        builder_params = BuilderParameters(**CollectionParameters.get_builder_params(params))

        iteration_result: IterationResult[CmdbObject] = objects_manager.iterate(builder_params,
                                                                                request_user,
                                                                                AccessControlPermission.READ)

        result_data = None
        if view == 'native':
            result_data: list[dict] = [object_.__dict__ for object_ in iteration_result.results]
        elif view == 'render':
            result_data = RenderList(object_list=iteration_result.results,
                                       request_user=request_user,
                                       ref_render=True,
                                       objects_manager=objects_manager).render_result_list(raw=True)
        else:
            abort(400, "Invalid or unprovided 'view' parameter!")

        api_response = GetMultiResponse(result_data,
                                        total=iteration_result.total,
                                        params=params,
                                        url=request.url,
                                        body=request.method == 'HEAD')

        return api_response.make_response()
    except HTTPException as http_err:
        raise http_err
    except ObjectsManagerIterationError as err:
        LOGGER.error("[get_cmdb_objects] ObjectsManagerIterationError: %s", err, exc_info=True)
        abort(400, "Failed to retrieve Objects from the database!")
    except Exception as err:
        LOGGER.error("[get_cmdb_objects] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while retrieving Objects from the database!")


@objects_blueprint.route('/count', methods=['GET'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@objects_blueprint.protect(auth=True, right='base.framework.object.view')
def get_cmdb_object_count(request_user: CmdbUser) -> Response:
    """
    HTTP `GET` route to retrieve the amount of CmdbObjects in database

    Args:
        request_user (CmdbUser): User requesting this data

    Returns:
        DefaultResponse: The amount of CmdbObject in database
    """
    try:
        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)

        if _fetch_only_active_objs():
            count_of_objects: int = objects_manager.count_objects({"active": True})
        else:
            count_of_objects = objects_manager.count_objects()

        return DefaultResponse(count_of_objects).make_response()
    except ObjectsManagerGetError as err:
        LOGGER.error("[get_cmdb_object_count] %s: %s", type(err), err, exc_info=True)
        abort(400, "Failed to retrieve the number of Objects stored in database!")
    except Exception as err:
        LOGGER.error("[get_cmdb_object_count] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "Internal server error while retrieving the number of Objects stored in database!")


#TODO: API-Documentation-FIX
@objects_blueprint.route('/count/<int:type_id>', methods=['GET'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@objects_blueprint.protect(auth=True, right='base.framework.object.view')
def get_cmdb_object_for_type_count(type_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `GET` route to retrieve the amount of CmdbObjects for a Type

    Args:
        type_id (int): The public_id of CmdbType for which the CmdbObjects should be counted
        request_user (CmdbUser): User requesting this data

    Returns:
        DefaultResponse: The amount of CmdbObject in database
    """
    try:
        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
        if _fetch_only_active_objs():
            count_of_objects: int = objects_manager.count_objects({"active": True, "type_id": type_id})
        else:
            count_of_objects = objects_manager.count_objects({"type_id": type_id})

        return DefaultResponse(count_of_objects).make_response()
    except ObjectsManagerGetError as err:
        LOGGER.error("[get_cmdb_object_for_type_count] ObjectsManagerGetError: %s", err, exc_info=True)
        abort(400, "Failed to retrieve the number of Objects for Type stored in database!")
    except Exception as err:
        LOGGER.error("[get_cmdb_object_for_type_count] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "Internal server error while retrieving the number of Objects for Type stored in database!")


@objects_blueprint.route('/native/<int:public_id>', methods=['GET'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@objects_blueprint.protect(auth=True, right='base.framework.object.view')
def get_native_cmdb_object(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `GET` route to retrieve a single CmdbObject

    Args:
        public_id (int): public_id of the CmdbObject
        request_user (CmdbUser): User requesting this data

    Returns:
        DefaultResponse: The requested CmdbObject
    """
    try:
        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)

        object_instance = objects_manager.get_object(public_id, request_user, AccessControlPermission.READ)

        if not object_instance:
            abort(404, f"The Object with ID:{public_id} was not found!")

        return DefaultResponse(object_instance).make_response()
    except HTTPException as http_err:
        raise http_err
    except ObjectsManagerGetError as err:
        LOGGER.error("[get_native_cmdb_object] ObjectsManagerGetError: %s", err, exc_info=True)
        abort(400, f"Failed to retrieve the Object with ID: {public_id} from the database!")
    except AccessDeniedError as err:
        LOGGER.error("[get_native_cmdb_object] AccessDeniedError: %s", err, exc_info=True)
        abort(403, "No permission to retrieve the object!")
    except Exception as err:
        LOGGER.error("[get_native_cmdb_object] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while retrieving the native Object with ID: {public_id}!")


@objects_blueprint.route('/group/<string:value>', methods=['GET'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@objects_blueprint.protect(auth=True, right='base.framework.object.view')
def group_cmdb_objects_by_type_id(value: str, request_user: CmdbUser) -> Response:
    """
    Groups CmdbObjects by their type_id and returns a structured response
    
    Note:
        Only used for the dashboard chart

    Args:
        value (str): The value used for grouping CmdbObjects
        request_user (CmdbUser): The CmdbUser making the request

    Returns:
        DefaultResponse: A JSON response containing grouped CmdbObjects
    """
    try:
        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)

        filter_state = {'active': {'$eq': True}} if _fetch_only_active_objs() else None

        result = []
        cursor = objects_manager.group_objects_by_value(value,
                                                        filter_state,
                                                        request_user,
                                                        AccessControlPermission.READ)

        for index, document in enumerate(cursor):
            cur_type = objects_manager.get_object_type(document['_id'])
            document['label'] = cur_type.label
            document['type_color'] = cur_type.ci_explorer_color
            result.append(document)

            if index + 1 == 5:  # Stop after processing 5 items
                break

        return DefaultResponse(result).make_response()
    except ObjectsManagerGetError as err:
        LOGGER.error("[get_native_cmdb_object] ObjectsManagerGetError: %s", err, exc_info=True)
        abort(400, "Failed to retrieve the Type of an Object from the database!")
    except ObjectsManagerIterationError as err:
        LOGGER.error("[group_cmdb_objects_by_type_id] ObjectsManagerIterationError: %s", err, exc_info=True)
        abort(400, "Failed to retrieve Objects from the database!")
    except Exception as err:
        LOGGER.error("[group_cmdb_objects_by_type_id] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while trying to retrieve data for dashboard chart!")


@objects_blueprint.route('/<int:public_id>/mds_reference', methods=['GET'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@objects_blueprint.protect(auth=True, right='base.framework.object.view')
def get_cmdb_object_mds_reference(public_id: int, request_user: CmdbUser) -> Response:
    """
    Retrieves the MDS reference for a given CmdbObject

    Args:
        public_id (int): The public_id of the CmdbObject
        request_user (CmdbUser): The CmdbUser making the request, used for access control

    Returns:
        DefaultResponse: A JSON response containing the MDS reference of the object
    """
    try:
        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)

        referenced_object = objects_manager.get_object(public_id,
                                                       request_user,
                                                       AccessControlPermission.READ)

        if not referenced_object:
            abort(404, f"The Object with ID:{public_id} was not found!")

        referenced_object = CmdbObject.from_data(referenced_object)

        referenced_type = objects_manager.get_object_type(referenced_object.get_type_id())

        if not referenced_type:
            abort(500, f"The Type of the Object with ID:{public_id} was not found in the database!")

        mds_reference = CmdbRender(referenced_object,
                                   referenced_type,
                                   request_user,
                                   True).get_mds_reference(public_id)

        return DefaultResponse(mds_reference).make_response()
    except HTTPException as http_err:
        raise http_err
    except ObjectsManagerGetError as err:
        LOGGER.error("[get_cmdb_object_mds_reference] ObjectsManagerGetError: %s", err, exc_info=True)
        abort(400, "Failed to retrieve the requested Object from the database!")
    except AccessDeniedError as err:
        LOGGER.error("[get_cmdb_object_mds_reference] AccessDeniedError: %s", err, exc_info=True)
        abort(403, "No permission for this action!")
    except Exception as err:
        LOGGER.error("[get_cmdb_object_mds_reference] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500,
            f"An internal server error occured while retrieving the MDS reference for Object with ID: {public_id}!"
        )


@objects_blueprint.route('/<int:public_id>/mds_references', methods=['GET'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@objects_blueprint.protect(auth=True, right='base.framework.object.view')
def get_cmdb_object_mds_references(public_id: int, request_user: CmdbUser) -> Response:
    """
    Retrieves the MDS references for one or more CmdbObjects

    Args:
        public_id (int): The public_id of the CmdbObject
        request_user (CmdbUser): The user making the request, used for access control

    Returns:
        DefaultResponse: A JSON response containing the MDS references of the objects, or an error message
    """
    try:
        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)

        summary_lines = {}

        object_ids = request.args.get("objectIDs", "").split(",")
        object_ids = [int(obj_id) for obj_id in object_ids if obj_id.isdigit()] or [public_id]

        for object_id in object_ids:
            referenced_object = objects_manager.get_object(object_id,
                                                            request_user,
                                                            AccessControlPermission.READ)

            if not referenced_object:
                abort(404, f"The Object with ID:{public_id} was not found!")

            referenced_object = CmdbObject.from_data(referenced_object)

            referenced_type = objects_manager.get_object_type(referenced_object.get_type_id())

            if not referenced_type:
                abort(500, f"The Type of the Object with ID:{public_id} was not found in the database!")

            mds_reference = CmdbRender(referenced_object,
                                        referenced_type,
                                        request_user,
                                        True).get_mds_reference(object_id)

            summary_lines[object_id] = mds_reference

        return DefaultResponse(summary_lines).make_response()
    except HTTPException as http_err:
        raise http_err
    except ObjectsManagerGetError as err:
        LOGGER.error("[get_cmdb_object_mds_references] ObjectsManagerGetError: %s", err, exc_info=True)
        abort(400, "Failed to retrieve an Object from the database!")
    except AccessDeniedError as err:
        LOGGER.error("[get_cmdb_object_mds_references] AccessDeniedError: %s", err, exc_info=True)
        abort(403, "No permission for this action!")
    except Exception as err:
        LOGGER.error("[get_cmdb_object_mds_references] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while retrieving MDS references!")


@objects_blueprint.route('/references/<int:public_id>', methods=['GET', 'HEAD'])
@objects_blueprint.parse_collection_parameters(view='native')
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@objects_blueprint.protect(auth=True, right='base.framework.object.view')
def get_cmdb_object_references(public_id: int, params: CollectionParameters, request_user: CmdbUser) -> Response:
    """
    Retrieves references for a given CmdbObject based on specified criteria

    Args:
        public_id (int): The public_id of the CmdbObject
        params (CollectionParameters): Filtering, sorting, and pagination parameters
        request_user (CmdbUser): The CmdbUser making the request, used for access control

    Returns:
        GetMultiResponse: A JSON response containing the referenced CmdbObjects
    """
    try:
        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)

        view = params.optional.get('view', 'native')

        # Apply active object filter if necessary
        match_filter = {"$match": {"active": {"$eq": True}}} if _fetch_only_active_objs() else {"$match": {}}

        if isinstance(params.filter, dict):
            params.filter.update(match_filter)
        elif isinstance(params.filter, list):
            params.filter.append(match_filter)

        referenced_object = objects_manager.get_object(public_id, request_user, AccessControlPermission.READ)
        referenced_object = CmdbObject.from_data(referenced_object)

        iteration_result: IterationResult[CmdbObject] = objects_manager.references(
                                                                    object_=referenced_object,
                                                                    criteria=params.filter,
                                                                    limit=params.limit,
                                                                    skip=params.skip,
                                                                    sort=params.sort,
                                                                    order=params.order,
                                                                    user=request_user,
                                                                    permission=AccessControlPermission.READ)

        request_data = None
        if view == 'native':
            request_data: list[dict] = [object_.__dict__ for object_ in iteration_result.results]
        elif view == 'render':
            request_data = RenderList(object_list=iteration_result.results,
                                      request_user=request_user,
                                      ref_render=True,
                                      objects_manager=objects_manager).render_result_list(raw=True)
        else:
            abort(400, "Invalid or unprovided 'view' parameter!")

        api_response = GetMultiResponse(
                            request_data,
                            total=iteration_result.total,
                            params=params,
                            url=request.url,
                            body=request.method == 'HEAD')

        return api_response.make_response()
    except HTTPException as http_err:
        raise http_err
    except ObjectsManagerGetError as err:
        LOGGER.error("[get_cmdb_object_references] ObjectsManagerGetError: %s", err, exc_info=True)
        abort(400, "Failed to retrieve an Object from the database!")
    except ObjectsManagerIterationError as err:
        LOGGER.error("[get_cmdb_object_references] ObjectsManagerIterationError: %s", err, exc_info=True)
        abort(400, "Failed to retrieve Objects from the database!")
    except AccessDeniedError as err:
        LOGGER.error("[get_cmdb_object_references] AccessDeniedError: %s", err, exc_info=True)
        abort(403, "No permission for this action!")
    except Exception as err:
        LOGGER.error("[get_cmdb_object_references] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error while retrieving references for Object with ID: {public_id}!")


@objects_blueprint.route('/state/<int:public_id>', methods=['GET'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@objects_blueprint.protect(auth=True, right='base.framework.object.activation')
def get_cmdb_object_state(public_id: int, request_user: CmdbUser) -> Response:
    """
    Retrieves the state (active/inactive) of a CmdbObject

    Args:
        public_id (int): The public_id of the CmdbObject whose state is being requested
        request_user (CmdbUser): The CmdbUser making the request

    Returns:
        DefaultResponse: API response indicating whether the object is active or not.
    """
    try:
        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)

        target_object_data = objects_manager.get_object(public_id, request_user, AccessControlPermission.READ)
        target_object: CmdbObject = CmdbObject.from_data(target_object_data)

        if not target_object:
            abort(404, f"Object with ID:{public_id} not found!")

        return DefaultResponse(target_object.active).make_response()
    except HTTPException as http_err:
        raise http_err
    except ObjectsManagerGetError as err:
        LOGGER.error("[get_cmdb_object_state] ObjectsManagerGetError: %s", err, exc_info=True)
        abort(400, "Failed to retrieve the requested Object from the database!")
    except AccessDeniedError:
        abort(403, "Access denied: You do not have sufficient permissions to perform this action!")
    except Exception as err:
        LOGGER.error("[get_cmdb_object_state] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error while retrieving the object state of ID:{public_id}!")


@objects_blueprint.route('/clean/<int:public_id>', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@objects_blueprint.protect(auth=True, right='base.framework.type.clean')
def get_unstructured_cmdb_objects(public_id: int, request_user: CmdbUser):
    """
    HTTP `GET`/`HEAD` route for a multiple CmdbObjects which are not formatted according the CmdbType structure

    Args:
        public_id (int): public_id of the CmdbType of the CmdbObject
        request_user (CmdbUser): The CmdbUser making the request

    Returns:
        GetListResponse: Which includes the json data of multiple Objects
    """
    try:
        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)

        type_instance = objects_manager.get_object_type(public_id)

        if not type_instance:
            abort(500, f"Type with ID: {public_id} not found!")

        builder_params = BuilderParameters({'type_id': public_id},
                                           limit=0,
                                           skip=0,
                                           sort='public_id',
                                           order=1)

        objects: list[CmdbObject] = objects_manager.iterate(builder_params, request_user).results

        type_fields = {field.get('name') for field in type_instance.fields}
        unstructured: list[dict] = []

        for object_ in objects:
            object_fields = {field.get('name') for field in object_.fields}
            if object_fields != type_fields:
                unstructured.append(object_.__dict__)

        return GetListResponse(unstructured, body=request.method == 'HEAD').make_response()
    except HTTPException as http_err:
        raise http_err
    except ObjectsManagerGetError as err:
        LOGGER.error("[get_unstructured_cmdb_objects] ObjectsManagerGetError: %s", err, exc_info=True)
        abort(400, "Failed to retrieve the Type of the Object from the database!")
    except ObjectsManagerIterationError as err:
        LOGGER.error("[get_unstructured_cmdb_objects] ObjectsManagerIterationError: %s", err, exc_info=True)
        abort(400, "Failed to retrieve Objects from the database!")
    except Exception as err:
        LOGGER.error("[get_unstructured_cmdb_objects] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while retrieving unstructured Objects!")

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

#TODO: REFACTOR-FIX (reduce complexity)
@objects_blueprint.route('/<int:public_id>', methods=['PUT', 'PATCH'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@objects_blueprint.protect(auth=True, right='base.framework.object.edit')
@objects_blueprint.validate(CmdbObject.SCHEMA)
def update_cmdb_object(public_id: int, data: dict, request_user: CmdbUser):
    """
    Updates an existing CmdbObject with new data

    Args:
        public_id (int): The public_id of the CmdbObject to update
        data (dict): The updated data for the CmdbObject
        request_user (CmdbUser): The user making the update request

    Returns:
        UpdateMultiResponse: A JSON response indicating the result of the update operation
    """
    try:
        logs_manager: LogsManager = ManagerProvider.get_manager(ManagerType.LOGS, request_user)
        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
        webhooks_manager: WebhooksManager = ManagerProvider.get_manager(ManagerType.WEBHOOKS, request_user)

        object_ids = request.args.getlist('objectIDs')

        object_ids = list(map(int, object_ids)) if object_ids else [public_id]

        results: list[dict] = []

        for obj_id in object_ids:
            # deep copy
            active_state = request.get_json().get('active', None)
            new_data = copy.deepcopy(data)

            current_object_instance = objects_manager.get_object(obj_id, request_user, AccessControlPermission.READ)

            if not current_object_instance:
                abort(404, f"Object with ID:{public_id} not found!")

            current_object_instance = CmdbObject.from_data(current_object_instance)
            current_type_instance = objects_manager.get_object_type(current_object_instance.get_type_id())

            if not current_type_instance:
                abort(500, "Type of Object not found in database!")

            current_object_render_result = CmdbRender(current_object_instance,
                                                    current_type_instance,
                                                    request_user,
                                                    False).result()

            new_data.update({
                'public_id': obj_id,
                'creation_time': current_object_instance.creation_time,
                'author_id': current_object_instance.author_id,
                'active': active_state if active_state in [True, False] else current_object_instance.active,
                'version': data.get('version', current_object_instance.version),
                'last_edit_time': datetime.now(timezone.utc),
                'editor_id': request_user.public_id,
            })

            old_fields = list(map(lambda x: {k: v for k, v in x.items() if k in ['name', 'value']},
                                current_object_render_result.fields))

            new_fields = data['fields']
            for item in new_fields:
                for old in old_fields:
                    if item['name'] == old['name']:
                        old['value'] = item['value']
            new_data['fields'] = old_fields

            update_comment = new_data.pop('comment', "")

            # Validate fields have type
            validate_and_fill_object_fields(objects_manager, new_data)

            update_object_instance = CmdbObject(**json.loads(json.dumps(new_data, default=default),
                                                            object_hook=object_hook))

            # calc version
            changes = current_object_instance / update_object_instance

            if len(changes['new']) == 1:
                version_type = update_object_instance.VERSIONING_PATCH
            elif len(changes['new']) == len(update_object_instance.fields):
                version_type = update_object_instance.VERSIONING_MAJOR
            elif len(changes['new']) > (len(update_object_instance.fields) / 2):
                version_type = update_object_instance.VERSIONING_MINOR
            else:
                version_type = update_object_instance.VERSIONING_PATCH
            new_data['version'] = update_object_instance.update_version(version_type)

            objects_manager.update_object(obj_id, new_data, request_user, AccessControlPermission.UPDATE)
            results.append(new_data)

            object_after = objects_manager.get_object(obj_id, request_user, AccessControlPermission.READ)

            if not object_after:
                abort(404, f"Updated Object with ID:{public_id} not found in database!")

            object_after = CmdbObject.from_data(object_after)

            #EVENT: UPDATE-EVENT
            try:
                webhooks_manager.send_webhook_event(WebhookEventType.UPDATE,
                                                    CmdbObject.to_json(current_object_instance),
                                                    CmdbObject.to_json(object_after),
                                                    changes)
            except Exception as error:
                LOGGER.error(
                    "[update_cmdb_object] Send Webhook Event Exception: %s, Type:%s", error, type(error)
                )

            # Generate log entry
            try:
                log_data = {
                    'object_id': obj_id,
                    'version': update_object_instance.get_version(),
                    'user_id': request_user.get_public_id(),
                    'user_name': request_user.get_display_name(),
                    'comment': update_comment,
                    'changes': changes,
                    'render_state': json.dumps(update_object_instance, default=default).encode('UTF-8')
                }
                logs_manager.insert_log(action=LogAction.EDIT, log_type=CmdbObjectLog.__name__, **log_data)
            except Exception as error:
                #TODO: ERROR-FIX
                LOGGER.error("[update_cmdb_object] Failed to create Log. Error: %s", error)

        return UpdateMultiResponse(results=results).make_response()
    except HTTPException as http_err:
        raise http_err
    except ObjectsManagerGetError as err:
        LOGGER.error("[update_cmdb_object] ObjectsManagerGetError: %s", err, exc_info=True)
        abort(400, "Failed to retrieve the requested Object from the database!")
    except ObjectsManagerUpdateError as err:
        LOGGER.error("[update_cmdb_object] ObjectsManagerUpdateError: %s", err, exc_info=True)
        abort(400, "Failed to update the requested Object in the database!")
    except AccessDeniedError:
        abort(403, "Access denied: You do not have sufficient permissions to perform this action!")
    except Exception as err:
        LOGGER.error("[update_cmdb_object] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while updating Object with ID:{public_id}!")


@objects_blueprint.route('/state/<int:public_id>', methods=['PUT'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@objects_blueprint.protect(auth=True, right='base.framework.object.activation')
def update_cmdb_object_state(public_id: int, request_user: CmdbUser) -> Response:
    """
    Updates the active state of a CmdbObject

    This function allows toggling the active status of a CMDB object (enabled/disabled).
    It verifies the object's existence, ensures the state value is a boolean, and updates
    the object accordingly. Additionally, it triggers webhook events and logs the change.

    Args:
        public_id (int): The public_id of the CmdbObject to be updated
        request_user (CmdbUser): The user making the update request

    Returns:
        UpdateSingleResponse: The updated CmdbObject as JSON or False if the given state equals the current state
    """
    try:
        logs_manager: LogsManager = ManagerProvider.get_manager(ManagerType.LOGS, request_user)
        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
        webhooks_manager: WebhooksManager = ManagerProvider.get_manager(ManagerType.WEBHOOKS, request_user)

        state = None

        if isinstance(request.json, bool):
            state = request.json
        else:
            abort(400, "Object state is not a boolean value (true/false)!")

        found_object = objects_manager.get_object(public_id, request_user, AccessControlPermission.READ)

        if not found_object:
            abort(404, f"Object with ID:{public_id} not found!")

        found_object: CmdbObject = CmdbObject.from_data(found_object)

        if found_object.active == state:
            return DefaultResponse(False).make_response()

        found_object.active = state
        objects_manager.update_object(public_id,
                                    found_object,
                                    request_user,
                                    AccessControlPermission.UPDATE)

        # get current object state
        current_type_instance = objects_manager.get_object_type(found_object.get_type_id())

        if not current_type_instance:
            abort(500, "Type of Object not found in database!")

        current_object_render_result = CmdbRender(found_object,
                                                  current_type_instance,
                                                  request_user,
                                                  False).result()

        object_after = objects_manager.get_object(public_id, request_user, AccessControlPermission.READ)

        if not object_after:
            abort(404, f"Updated Object with ID:{public_id} not found in database!")

        object_after = CmdbObject.from_data(object_after)

        #EVENT: UPDATE-EVENT
        try:
            webhooks_manager.send_webhook_event(WebhookEventType.UPDATE,
                                                CmdbObject.to_json(found_object),
                                                CmdbObject.to_json(object_after),
                                                {'state': state})
        except Exception as error:
            LOGGER.error(
                "[update_cmdb_object] Send Webhook Event Exception: %s, Type:%s", error, type(error)
            )

        try:
            # generate log
            change: dict[str, bool] = {
                'old': not state,
                'new': state
            }
            log_data = {
                'object_id': public_id,
                'version': found_object.version,
                'user_id': request_user.get_public_id(),
                'user_name': request_user.get_display_name(),
                'render_state': json.dumps(current_object_render_result, default=default).encode('UTF-8'),
                'comment': 'Active status has changed',
                'changes': change,
            }

            logs_manager.insert_log(action=LogAction.ACTIVE_CHANGE, log_type=CmdbObjectLog.__name__, **log_data)
        except Exception as error:
            #TODO: ERROR-FIX
            LOGGER.error("[update_cmdb_object_state] Failed to create Log. Error: %s", error)

        return UpdateSingleResponse(result=found_object.__dict__).make_response()
    except HTTPException as http_err:
        raise http_err
    except ObjectsManagerGetError as err:
        LOGGER.error("[update_cmdb_object_state] ObjectsManagerGetError: %s", err, exc_info=True)
        abort(400, "Failed to retrieve the requested Object from the database!")
    except ObjectsManagerUpdateError as err:
        LOGGER.error("[update_cmdb_object_state] ObjectsManagerUpdateError: %s", err, exc_info=True)
        abort(400, "Failed to update the Object in the database!")
    except AccessDeniedError:
        abort(403, "Access denied: You do not have sufficient permissions to perform this action!")
    except Exception as err:
        LOGGER.error("[update_cmdb_object_state] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while updating Object state of ID:{public_id}!")


#TODO: REFACOTR-FIX (reduce complexity)
@objects_blueprint.route('/clean/<int:public_id>', methods=['PUT', 'PATCH'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@objects_blueprint.protect(auth=True, right='base.framework.type.clean')
def update_unstructured_cmdb_objects(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `PUT`/`PATCH` route for a multi resources which will be formatted based on the CmdbType

    Args:
        public_id (int): public_id of the CmdbType
        request_user (CmdbUser): The user making the update request

    Returns:
        UpdateMultiResponse: Which includes the json data of multiple updated objects.
    """
    try:
        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
        reports_manager: ReportsManager = ManagerProvider.get_manager(ManagerType.REPORTS, request_user)

        update_type_instance = objects_manager.get_object_type(public_id)

        if not update_type_instance:
            abort(500, f"Type with ID:{public_id} not found!")

        type_fields: list[dict[str, Any]] = update_type_instance.fields

        builder_params = BuilderParameters({'type_id': public_id})

        objects_by_type: list[CmdbObject] = objects_manager.iterate(builder_params, request_user).results
        reports_for_type: list[dict[str, Any]] = objects_manager.get_many_from_other_collection(
                                                    CmdbReport.COLLECTION,
                                                    type_id=public_id
                                                 )

        for obj in objects_by_type:
            incorrect: list[str] = []
            correct: list[str] = []
            obj_fields: list[dict[str, Any]] = obj.get_all_fields()

            for t_field in type_fields:
                name: str = t_field["name"]

                for field in obj_fields:
                    if name == field["name"]:
                        correct.append(field["name"])
                    else:
                        incorrect.append(field["name"])

            removed_type_fields: list[str] = [item for item in incorrect if not item in correct]

            for field in removed_type_fields:
                try:
                    objects_manager.update(
                        criteria={'public_id': obj.public_id},
                        data={'$pull': {'fields': {"name": field}}},
                        add_to_set=False
                    )
                except Exception as error:
                    LOGGER.debug(
                        "[update_unstructured_cmdb_objects] Clean objects Exception: %s, Type: %s", error, type(error)
                    )
                    abort(500, "An interlal server error occured while cleaning objects!")

                # Check all reports and clear selected_fields and conditions
                try:
                    for a_report in reports_for_type:
                        tmp_report: CmdbReport = CmdbReport.from_data(a_report)
                        tmp_report.remove_field_occurences(field)
                        tmp_report.report_query = {
                            'data': str(MongoDBQueryBuilder(tmp_report.conditions, update_type_instance).build())
                        }

                        reports_manager.update_item(tmp_report.public_id, tmp_report.__dict__)
                except Exception as error:
                    LOGGER.debug(
                        "[update_unstructured_cmdb_objects] Clean Reports Exception: %s, Type: %s", error, type(error)
                    )
                    abort(500, "An interlal server error occured while cleaning reports!")

        objects_by_type = objects_manager.iterate(builder_params, request_user).results

        try:
            for obj in objects_by_type:
                for t_field in type_fields:
                    name = t_field["name"]
                    value = None

                    if [item for item in obj.get_all_fields() if item["name"] == name]:
                        continue

                    if "value" in t_field:
                        value = t_field["value"]

                    objects_manager.update_many_objects(query={'public_id': obj.public_id},
                                                        update={'fields': {"name": name, "value": value}},
                                                        add_to_set=True)
        except Exception as error:
            LOGGER.debug("Clean Update Type Fields: %s, Type: %s", error, type(error))
            abort(500, "Could not clean objects!")

        return UpdateMultiResponse([]).make_response()
    except HTTPException as http_err:
        raise http_err
    except ObjectsManagerIterationError as err:
        LOGGER.error("[update_unstructured_cmdb_objects] ObjectsManagerIterationError: %s", err, exc_info=True)
        abort(400, "Failed to retrieve Objects from the database!")
    except ObjectsManagerGetError as err:
        LOGGER.error("[update_unstructured_cmdb_objects] ObjectsManagerGetError: %s", err, exc_info=True)
        abort(400, "Failed to retrieve the requested Object from the database!")
    except ObjectsManagerUpdateError as err:
        LOGGER.error("[update_unstructured_cmdb_objects] ObjectsManagerUpdateError: %s", err, exc_info=True)
        abort(400, "Failed to update the Object in the database!")
    except Exception as err:
        LOGGER.error("[update_unstructured_cmdb_objects] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while updating unstructured Objects!")

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

#TODO: REFACTOR-FIX (reduce complexity)
@objects_blueprint.route('/<int:public_id>', methods=['DELETE'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@objects_blueprint.protect(auth=True, right='base.framework.object.delete')
def delete_cmdb_object(public_id: int, request_user: CmdbUser) -> Response:
    """
    Deletes an CmdbObject and logs the deletion

    Params:
        public_id (int): public_id of the CmdbObject which should be deleted
        request_user (CmdbUser): The user requesting the deletion of the CmdbObject

    Returns:
        Response: Acknowledgment of database
    """
    try:
        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
        logs_manager: LogsManager = ManagerProvider.get_manager(ManagerType.LOGS, request_user)
        locations_manager: LocationsManager = ManagerProvider.get_manager(ManagerType.LOCATIONS, request_user)
        webhooks_manager: WebhooksManager = ManagerProvider.get_manager(ManagerType.WEBHOOKS, request_user)
        object_relations_manager: ObjectRelationsManager = ManagerProvider.get_manager(
            ManagerType.OBJECT_RELATIONS,
            request_user
        )
        object_relation_logs_manager: ObjectRelationLogsManager = ManagerProvider.get_manager(
            ManagerType.OBJECT_RELATION_LOGS,
            request_user
        )
        object_groups_manager: ObjectGroupsManager = ManagerProvider.get_manager(
            ManagerType.OBJECT_GROUP,
            request_user
        )
        object_links_manager: ObjectLinksManager = ManagerProvider.get_manager(
            ManagerType.OBJECT_LINKS,
            request_user
        )

        current_object_instance: CmdbObject | None = objects_manager.get_object(public_id, as_dict=False)

        if not current_object_instance:
            abort(404, f"Object with ID:{public_id} not found!")

        current_type_instance = objects_manager.get_object_type(current_object_instance.get_type_id())

        if not current_type_instance:
            abort(500, "Type of Object not found in database!")

        # Remove object links and references
        try:
            object_links_manager.delete_object_links(public_id)
            objects_manager.delete_all_object_references(public_id)
        except Exception as error:
            LOGGER.error(
                "[delete_cmdb_object] Links + Refenreces Exception: %s. Type: %s", error, type(error), exc_info=True
            )

        current_object_render_result = CmdbRender(current_object_instance,
                                                  current_type_instance,
                                                  request_user,
                                                  False).result()

        #an object can not be deleted if it has a location AND the location is a parent for other locations
        try:
            current_location = locations_manager.get_location_for_object(public_id)
            child_location = None

            if current_location:
                child_location = locations_manager.get_one_by({'parent': current_location['public_id']})

            if child_location and len(child_location) > 0:
                abort(405, "The Location of this Object has child Locations and therefore not deletable!")

            if current_location:
                locations_manager.delete_location(current_location['public_id'])
        except Exception as error:
            LOGGER.error(
                "[delete_cmdb_object] Locations Exception: %s. Type: %s", error, type(error), exc_info=True
            )
            abort(500, "An internal server error occured while handling Locations of this Object!")

        # Remove the object from all static groups
        object_groups_manager.remove_ids_from_static_groups(public_id)

        is_deleted = objects_manager.delete_with_follow_up(public_id, request_user, AccessControlPermission.DELETE)

        try:
            #EVENT: DELETE-EVENT
            webhooks_manager.send_webhook_event(
                WebhookEventType.DELETE,
                object_before=CmdbObject.to_json(current_object_instance)
            )
        except Exception as error:
            LOGGER.error(
                "[delete_cmdb_object] Send Webhook Event Exception: %s, Type:%s", error, type(error)
            )

        try:
            # Generate Log
            log_data = {
                'object_id': public_id,
                'version': current_object_render_result.object_information['version'],
                'user_id': request_user.get_public_id(),
                'user_name': request_user.get_display_name(),
                'comment': 'Object was deleted',
                'render_state': json.dumps(current_object_render_result, default=default).encode('UTF-8')
            }

            logs_manager.insert_log(action=LogAction.DELETE, log_type=CmdbObjectLog.__name__, **log_data)
        except Exception as error:
            LOGGER.error("[delete_cmdb_object] Failed to create ObjectLog. Error: %s", error)

        try:
            if current_app.cloud_mode:
                objects_count = objects_manager.count_objects()

                sync_config_items(request_user.email, request_user.database, objects_count)
        except Exception as err:
            LOGGER.error("[delete_cmdb_object] Could not sync config items count to service portal. Error: %s", err)

        # Handle corresponding CmdbObjectRelations
        delete_invalid_object_relations(public_id,
                                        request_user,
                                        object_relations_manager,
                                        object_relation_logs_manager)

        return DefaultResponse(is_deleted).make_response()
    except HTTPException as http_err:
        raise http_err
    except ObjectsManagerGetError as err:
        LOGGER.error("[delete_cmdb_object] ObjectsManagerGetError: %s", err, exc_info=True)
        abort(400, "Failed to retrieve the requested Object from the database!")
    except ObjectsManagerDeleteError as err:
        LOGGER.error("[delete_cmdb_object] ObjectsManagerUpdateError: %s", err, exc_info=True)
        abort(500, "Failed to delete the Object in the database!")
    except Exception as err:
        LOGGER.error("[delete_cmdb_object] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while deleting the Object with ID: {public_id}!")


@objects_blueprint.route('/<int:public_id>/locations', methods=['DELETE'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@objects_blueprint.protect(auth=True, right='base.framework.object.delete')
def delete_cmdb_object_with_child_locations(public_id: int, request_user: CmdbUser):
    """
    Deletes a CmdbObject along with its associated child locations.

    This function performs the following steps:
    1. Verifies the existence of the CMDB object
    2. Removes all links and references associated with the CmdbObject
    3. Checks for the location associated with the CmdbObject
    4. If a location exists, retrieves and deletes all child locations
    5. Deletes the CmdbObject and its location
    6. Synchronizes configuration items if running in cloud mode
    7. Removes invalid CmdbObjectRelations

    Args:
        public_id (int): The public_id of the CmdbObject object to be deleted
        request_user (CmdbUser): The user requesting the deletion

    Returns:
        DefaultResponse: A JSON response indicating success or failure
    """
    try:
        locations_manager: LocationsManager = ManagerProvider.get_manager(ManagerType.LOCATIONS, request_user)
        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
        object_relations_manager: ObjectRelationsManager = ManagerProvider.get_manager(
                                                                            ManagerType.OBJECT_RELATIONS,
                                                                            request_user)
        object_relation_logs_manager: ObjectRelationLogsManager = ManagerProvider.get_manager(
                                                                            ManagerType.OBJECT_RELATION_LOGS,
                                                                            request_user)
        object_groups_manager: ObjectGroupsManager = ManagerProvider.get_manager(
            ManagerType.OBJECT_GROUP,
            request_user
        )
        object_links_manager: ObjectLinksManager = ManagerProvider.get_manager(
            ManagerType.OBJECT_LINKS,
            request_user
        )

        # check if object exists
        current_object_instance = objects_manager.get_object(public_id)

        if not current_object_instance:
            abort(404, f"Object with ID:{public_id} not found!")

        current_object_instance = CmdbObject.from_data(current_object_instance)

        # Remove object links and references
        try:
            object_links_manager.delete_object_links(public_id)
            objects_manager.delete_all_object_references(public_id)
        except Exception as error:
            LOGGER.error(
                "[delete_cmdb_object_with_child_locations] Links + Refenreces Exception: %s. Type: %s",
                error, type(error), exc_info=True
            )

        # check if location for this object exists
        current_location = locations_manager.get_location_for_object(public_id)

        deleted = None
        if current_location:
            # get all child locations for this location
            build_params = BuilderParameters([{"$match":{"public_id":{"$gt":1}}}])

            iteration_result: IterationResult[CmdbLocation] = locations_manager.iterate(build_params)

            all_locations: list[dict] = [location_.__dict__ for location_ in iteration_result.results]
            all_children = locations_manager.get_all_children(current_location['public_id'], all_locations)

            # delete all child locations
            for child in all_children:
                locations_manager.delete_location(child['public_id'])

            # delete the current object and its location
            locations_manager.delete_location(current_location['public_id'])

            # Remove the object from all static groups
            object_groups_manager.remove_ids_from_static_groups(public_id)

            deleted = objects_manager.delete_with_follow_up(public_id,
                                                            request_user,
                                                            permission=AccessControlPermission.DELETE)

            try:
                if current_app.cloud_mode:
                    objects_count = objects_manager.count_objects()

                    sync_config_items(request_user.email, request_user.database, objects_count)
            except Exception as error:
                LOGGER.error(
                    "[delete_cmdb_object_with_child_locations] Could not sync config items count. Error: %s", error
                )
        else:
            abort(404, "Location for the Object not found!")

        # Handle corresponding CmdbObjectRelations
        delete_invalid_object_relations(public_id,
                                        request_user,
                                        object_relations_manager,
                                        object_relation_logs_manager)

        return DefaultResponse(deleted).make_response()
    except HTTPException as http_err:
        raise http_err
    except ObjectsManagerGetError as err:
        LOGGER.error("[delete_cmdb_object_with_child_locations] ObjectsManagerGetError: %s", err, exc_info=True)
        abort(400, "Failed to retrieve the requested Object from the database!")
    except ObjectsManagerDeleteError as err:
        LOGGER.error("[delete_cmdb_object_with_child_locations] ObjectsManagerUpdateError: %s", err, exc_info=True)
        abort(500, "Failed to delete the Object in the database!")
    except Exception as err:
        LOGGER.error(
            "[delete_cmdb_object_with_child_locations] Exception: %s. Type: %s", err, type(err), exc_info=True
        )
        abort(500, "An internal server error occured while deleting Object with child Locations!")


#TODO: REFACTOR-FIX (reduce complexity)
@objects_blueprint.route('/<int:public_id>/children', methods=['DELETE'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@objects_blueprint.protect(auth=True, right='base.framework.object.delete')
def delete_object_with_child_objects(public_id: int, request_user: CmdbUser):
    """
    Deletes an object and all objects which are child objects of it in the location tree
    The corresponding locations of each object are also deleted

    Args:
        public_id (int): public_id of the CmdbObject which should be deleted with its children
        request_user (CmdbUser): User requesting this operation

    Returns:
        (int): Success of this operation
    """
    try:
        locations_manager: LocationsManager = ManagerProvider.get_manager(ManagerType.LOCATIONS, request_user)
        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
        webhooks_manager: WebhooksManager = ManagerProvider.get_manager(ManagerType.WEBHOOKS, request_user)
        object_relations_manager: ObjectRelationsManager = ManagerProvider.get_manager(
                                                                            ManagerType.OBJECT_RELATIONS,
                                                                            request_user)
        object_relation_logs_manager: ObjectRelationLogsManager = ManagerProvider.get_manager(
                                                                            ManagerType.OBJECT_RELATION_LOGS,
                                                                            request_user)
        object_groups_manager: ObjectGroupsManager = ManagerProvider.get_manager(
            ManagerType.OBJECT_GROUP,
            request_user
        )
        object_links_manager: ObjectLinksManager = ManagerProvider.get_manager(
            ManagerType.OBJECT_LINKS,
            request_user
        )
        # check if object exists
        current_object_instance = objects_manager.get_object(public_id)

        if not current_object_instance:
            abort(404, f"Object with ID:{public_id} not found!")

        current_object_instance = CmdbObject.from_data(current_object_instance)

        # Remove object links and references
        try:
            object_links_manager.delete_object_links(public_id)
            objects_manager.delete_all_object_references(public_id)
        except Exception as error:
            LOGGER.error(
                "[delete_object_with_child_objects] Links + Refenreces Exception: %s. Type: %s",
                error, type(error), exc_info=True
            )

        # check if location for this object exists
        current_location = locations_manager.get_location_for_object(public_id)

        deleted = None
        if current_location:
            # get all child locations for this location
            builder_params = BuilderParameters([{"$match":{"public_id":{"$gt":1}}}])

            iteration_result: IterationResult[CmdbLocation] = locations_manager.iterate(builder_params)

            all_locations: list[dict] = [location_.__dict__ for location_ in iteration_result.results]
            all_children_locations = locations_manager.get_all_children(current_location['public_id'], all_locations)

            children_object_ids = []

            # delete all child locations and extract their corresponding object_ids
            for child in all_children_locations:
                children_object_ids.append(child['object_id'])
                locations_manager.delete_location(child['public_id'])

            # Remove the objects from all static groups
            if children_object_ids:
                object_groups_manager.remove_ids_from_static_groups(children_object_ids)

            # delete the objects of child locations
            for child_object_id in children_object_ids:
                objects_manager.delete_with_follow_up(child_object_id,
                                                      request_user,
                                                      AccessControlPermission.DELETE)

                # Handle corresponding CmdbObjectRelations
                delete_invalid_object_relations(child_object_id,
                                                request_user,
                                                object_relations_manager,
                                                object_relation_logs_manager)

            # # delete the current object and its location
            locations_manager.delete_location(current_location['public_id'])

            # Remove the objects from all static groups
            object_groups_manager.remove_ids_from_static_groups(public_id)

            deleted = objects_manager.delete_with_follow_up(public_id,
                                                            request_user,
                                                            AccessControlPermission.DELETE)

            # Handle corresponding CmdbObjectRelations
            delete_invalid_object_relations(public_id,
                                            request_user,
                                            object_relations_manager,
                                            object_relation_logs_manager)

            #EVENT: DELETE-EVENT
            try:
                webhooks_manager.send_webhook_event(WebhookEventType.DELETE,
                                                    object_before=CmdbObject.to_json(current_object_instance))
            except Exception as error:
                LOGGER.error(
                    "[delete_object_with_child_objects] Failed to send webhook event. Error: %s", error
                )

            try:
                if current_app.cloud_mode:
                    objects_count = objects_manager.count_objects()

                    sync_config_items(request_user.email, request_user.database, objects_count)
            except Exception as error:
                LOGGER.error(
                    "[delete_object_with_child_objects] Could not sync config items count. Error: %s", error
                )
        else:
            abort(404, "Location for the Object not found!")

        return DefaultResponse(deleted).make_response()
    except HTTPException as http_err:
        raise http_err
    except ObjectsManagerGetError as err:
        LOGGER.error("[delete_object_with_child_objects] ObjectsManagerGetError: %s", err, exc_info=True)
        abort(400, "Failed to retrieve the requested Object from the database!")
    except ObjectsManagerDeleteError as err:
        LOGGER.error("[delete_object_with_child_objects] ObjectsManagerUpdateError: %s", err, exc_info=True)
        abort(500, "Failed to delete the Object in the database!")
    except Exception as err:
        LOGGER.error("[delete_object_with_child_objects] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while deleting an Object with child Objects!")


@objects_blueprint.route('/delete/<string:public_ids>', methods=['DELETE'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@objects_blueprint.protect(auth=True, right='base.framework.object.delete')
def delete_many_cmdb_objects(public_ids: str, request_user: CmdbUser):
    """
    Deletes multiple CmdbObjects by their public_ids

    This function removes multiple CmdbObjects, ensuring they do not have associated locations,
    deleting their links, references, and related object relations. It also logs the deletion
    and triggers a webhook event.

    Args:
        public_ids (str): A comma-separated string of CmdbObject public_ids to delete
        request_user (CmdbUser): The user requesting the deletion

    Returns:
        Response: A JSON response indicating the success or failure of the operation
    """
    try:
        logs_manager: LogsManager = ManagerProvider.get_manager(ManagerType.LOGS, request_user)
        locations_manager: LocationsManager = ManagerProvider.get_manager(ManagerType.LOCATIONS, request_user)
        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
        webhooks_manager: WebhooksManager = ManagerProvider.get_manager(ManagerType.WEBHOOKS, request_user)
        object_relations_manager: ObjectRelationsManager = ManagerProvider.get_manager(
                                                                            ManagerType.OBJECT_RELATIONS,
                                                                            request_user)
        object_relation_logs_manager: ObjectRelationLogsManager = ManagerProvider.get_manager(
                                                                            ManagerType.OBJECT_RELATION_LOGS,
                                                                            request_user)
        object_groups_manager: ObjectGroupsManager = ManagerProvider.get_manager(
            ManagerType.OBJECT_GROUP,
            request_user
        )
        object_links_manager: ObjectLinksManager = ManagerProvider.get_manager(
            ManagerType.OBJECT_LINKS,
            request_user
        )

        ids = []
        operator_in = {'$in': []}
        filter_public_ids = {'public_id': {}}

        for v in public_ids.split(","):
            try:
                ids.append(int(v))
            except (ValueError, TypeError):
                abort(400, "Invalid request data!")

        operator_in.update({'$in': ids})
        filter_public_ids.update({'public_id': operator_in})

        ack = []
        objects = objects_manager.get_objects_by(**filter_public_ids)

        # At the current state it is not possible to bulk delete objects with locations
        # check if any object has a location
        for current_object_instance in objects:
            try:
                location_for_object = locations_manager.get_location_for_object(current_object_instance.public_id)

                if location_for_object:
                    abort(400, "It is not possible to bulk delete objects if any of them has a location!")
            except Exception:
                #TODO: ERROR-FIX (catch locations specific error)
                abort(500, "Failed to check locations for objects!")

        current_object_instance: CmdbObject
        for current_object_instance in objects:
            try:
                # Remove object links and references
                object_links_manager.delete_object_links(current_object_instance.public_id)
                objects_manager.delete_all_object_references(current_object_instance.public_id)
            except Exception as error:
                LOGGER.error(
                    "[delete_many_cmdb_objects] Links + Refenreces Exception: %s. Type: %s",
                    error, type(error), exc_info=True
                )

            current_type_instance = objects_manager.get_object_type(current_object_instance.get_type_id())
            current_object_render_result = CmdbRender(current_object_instance,
                                                        current_type_instance,
                                                        request_user,
                                                        False).result()

            # Remove the objects from all static groups
            object_groups_manager.remove_ids_from_static_groups(current_object_instance.get_public_id())

            objects_manager.delete_with_follow_up(current_object_instance.get_public_id(),
                                                  request_user,
                                                  AccessControlPermission.DELETE)

            # Handle corresponding CmdbObjectRelations
            delete_invalid_object_relations(current_object_instance.get_public_id(),
                                            request_user,
                                            object_relations_manager,
                                            object_relation_logs_manager)
            #EVENT: DELETE-EVENT
            try:
                webhooks_manager.send_webhook_event(WebhookEventType.DELETE,
                                                    object_before=CmdbObject.to_json(current_object_instance))
            except Exception as error:
                LOGGER.error(
                    "[delete_many_cmdb_objects] Failed to send webhook event. Error: %s", error
                )

            try:
                if current_app.cloud_mode:
                    objects_count = objects_manager.count_objects()

                    sync_config_items(request_user.email, request_user.database, objects_count)
            except Exception as error:
                LOGGER.error(
                    "[delete_many_cmdb_objects] Could not sync config items count to service portal. Error: %s", error
                )

            try:
                # generate log
                log_data: dict[str, Any] = {
                    'object_id': current_object_instance.get_public_id(),
                    'version': current_object_render_result.object_information['version'],
                    'user_id': request_user.get_public_id(),
                    'user_name': request_user.get_display_name(),
                    'comment': 'Object was deleted',
                    'render_state': json.dumps(current_object_render_result, default=default).encode('UTF-8')
                }
                logs_manager.insert_log(action=LogAction.DELETE, log_type=CmdbObjectLog.__name__, **log_data)
            except Exception as error:
                LOGGER.error("[delete_many_cmdb_objects] Failed to create ObjectLog. Error: %s", error)

        return DefaultResponse({'successfully': ack}).make_response()
    except HTTPException as http_err:
        raise http_err
    except ObjectsManagerGetError as err:
        LOGGER.error("[delete_many_cmdb_objects] ObjectsManagerGetError: %s", err, exc_info=True)
        abort(400, "Failed to retrieve the requested Object from the database!")
    except ObjectsManagerDeleteError as err:
        LOGGER.error("[delete_many_cmdb_objects] ObjectsManagerUpdateError: %s", err, exc_info=True)
        abort(500, "Failed to delete the Object in the database!")
    except Exception as err:
        LOGGER.error("[delete_many_cmdb_objects] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while deleting multiple Objects!")

# -------------------------------------------------- HELPER METHODS -------------------------------------------------- #

#TODO: REFACTOR-FIX (move to helper file since identical method in search_routes.py)
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


def check_config_item_limit_reached(request_user: CmdbUser, objects_count: int) -> bool:
    """
    Checks if the configuration item limit for the user has been reached

    Args:
        request_user (CmdbUser): The user whose configuration item limit is being checked
        objects_count (int): Amount of current CmdbObjects
    Returns:
        bool: True if the user has reached or exceeded their config item limit, False otherwise
    """
    return objects_count >= request_user.config_items_limit


#TODO: REFACTOR-FIX (move the functionality of ObjectRelationsManager to a method in it)
def delete_invalid_object_relations(public_id: int,
                            request_user: CmdbUser,
                            object_relations_manager: ObjectRelationsManager,
                            object_relation_logs_manager: ObjectRelationLogsManager) -> None:
    """
    Deletes all object relations where the given public ID is either the parent or child  

    This function retrieves all relations that reference the given public_id, removes them
        and attempts to log the deletion

    Args:
        public_id (int): The public_id of the CmdbObject whose CmdbObjectRelations need to be deleted
        request_user (CmdbUser): The user requesting the deletion
        object_relations_manager (ObjectRelationsManager): Manages CmdbObjectRelations
        object_relation_logs_manager (ObjectRelationLogsManager): Manages CmdbObjectRelationLogs

    Raises:
        ObjectRelationsManagerDeleteError: If deletion of a CmdbObjectRelation failed
        ObjectRelationLogsManagerBuildError: If creating a CmdbObjectRelationLog fails
    """
    relations_query = {"$or": [{"relation_parent_id": public_id}, {"relation_child_id": public_id}]}
    builder_params = BuilderParameters(criteria=relations_query)

    iteration_result: IterationResult[CmdbObjectRelation] = object_relations_manager.iterate(builder_params)
    object_relation_list: list[CmdbObjectRelation] = list(iteration_result.results)


    for object_relation in object_relation_list:
        try:
            object_relations_manager.delete_object_relation(object_relation.public_id)

            object_relation_logs_manager.build_object_relation_log(
                                            LogInteraction.DELETE,
                                            request_user,
                                            CmdbObjectRelation.to_json(object_relation),
                                            None
                                        )
        except ObjectRelationsManagerDeleteError as error:
            LOGGER.error(
                "[delete_invalid_object_relations] Failed to create an ObjectRelationLog: %s", error, exc_info=True
            )
        except ObjectRelationLogsManagerBuildError as error:
            LOGGER.error(
                "[delete_invalid_object_relations] Failed to create an ObjectRelationLog: %s", error, exc_info=True
            )
        except Exception as err:
            LOGGER.error("[delete_invalid_object_relations] Exception: %s. Type: %s", err, type(err), exc_info=True)


def validate_and_fill_object_fields(objects_manager: ObjectsManager, object_data: dict[str, Any]) -> None:
    """
    Validates that all fields in `object_data['fields']` exist in the type schema
    and fills in missing `type` properties from the type schema.

    Args:
        objects_manager (ObjectsManager): manager to access type schemas
        object_data (dict[str, Any]): the incoming object data to validate/enrich

    Raises:
        abort(400) if any field name is not in the type schema
    """
    type_id = object_data.get("type_id")
    if not type_id:
        abort(400, "Missing type_id in object data!")

    # Retrieve type schema as dict (field_name -> field_type)
    type_schema = objects_manager.get_object_type(type_id, raw=True)
    type_field_map = {f["name"]: f["type"] for f in type_schema["fields"]}

    for field in object_data.get("fields", []):
        field_name = field.get("name")
        if not field_name:
            abort(400, "One of the fields is missing a 'name' property!")

        # Early abort if field not in type
        if field_name not in type_field_map:
            abort(400, f"Field '{field_name}' is not defined in type {type_id}!")

        # Fill missing 'type' property
        if "type" not in field or not field["type"]:
            field["type"] = type_field_map[field_name]
