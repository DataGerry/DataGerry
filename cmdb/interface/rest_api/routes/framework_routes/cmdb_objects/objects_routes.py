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
from pymongo import UpdateOne
from flask import abort, current_app, request
from werkzeug import Response
from werkzeug.exceptions import HTTPException

from cmdb.database.database_utils import default, object_hook
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.manager.query_builder import BuilderParameters
from cmdb.manager import (
    LocationsManager,
    LogsManager,
    ObjectsManager,
    ReportsManager,
    WebhooksManager,
    TypesManager,
    ObjectRelationsManager,
    ObjectRelationLogsManager,
)

from cmdb.security.acl.permission import AccessControlPermission
from cmdb.models.type_model.cmdb_type import CmdbType
from cmdb.models.object_relation_model import CmdbObjectRelation
from cmdb.models.user_model import CmdbUser
from cmdb.models.webhook_model.webhook_event_type_enum import WebhookEventType
from cmdb.models.object_model import CmdbObject
from cmdb.models.log_model import LogInteraction
from cmdb.models.log_model.log_action_enum import LogAction
from cmdb.models.log_model.cmdb_object_log import CmdbObjectLog
from cmdb.models.reports_model.cmdb_report import CmdbReport
from cmdb.framework.results import IterationResult
from cmdb.framework.rendering.cmdb_multi_render import CmdbMultiRender
from cmdb.framework.rendering.render_list import RenderList
from cmdb.framework.rendering.render_result import RenderResult
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.route_utils import insert_request_user, verify_api_access, handle_db_errors
from cmdb.interface.rest_api.routes.routes_helper import (
    fetch_only_active_objects,
    extract_public_ids,
    object_has_location,
)
from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_helper import (
    delete_one_cascade,
    handle_notify_webhooks,
    handle_creat_object_log,
    handle_sync_config_item_count,
    handle_delete_invalid_object_relations,
    handle_delete_from_object_groups,
    handle_delete_object_location,
    handle_delete_location_and_child_locations,
    validate_and_fill_object_fields,
    sync_select_field_options,
    is_special_type_changed,
)
from cmdb.interface.rest_api.routes.report_routes.report_helper import build_report_query
from cmdb.framework.ipam.enforcement import (
    enforce_object_invariants,
    enforce_delete_guards,
    format_errors_for_abort,
)
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
    HTTP `POST` route to insert a CmdbObject into the database

    In cloud mode the request is rejected when the user's ConfigItem limit is reached. IPAM
    invariants are enforced before the insert: SUPERNET / SUBNET / VLAN candidates and any
    dg-ipam-interface MDS rows are validated and the request aborts 400 on violation

    Args:
        request_user (CmdbUser): The CmdbUser making the request

    Returns:
        DefaultResponse: The public_id of the newly inserted CmdbObject
    """
    try:
        #TODO: REFACTOR-FIX (pass the data same way as on other routes and add schema validation)
        new_object_json = json.dumps(request.json)

        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
        types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)

        objects_count: int = 0

        if current_app.cloud_mode:
            objects_count: int = objects_manager.count_documents()
            if request_user.is_config_item_limit_reached(objects_count):
                abort(400, "The maximum amout of ConfigItems is reached!")

        new_object_data = json.loads(new_object_json, object_hook=json_util.object_hook)

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

        # Validate fields have type property
        validate_and_fill_object_fields(objects_manager, new_object_data)

        ipam_errors: list[dict[str, Any]] = enforce_object_invariants(
            objects_manager,
            types_manager,
            new_object_data,
            previous_object=None,
        )

        if ipam_errors:
            abort(400, format_errors_for_abort(ipam_errors))

        new_object_id: int = objects_manager.insert_object(
            new_object_data,
            request_user,
            AccessControlPermission.CREATE
        )

        current_object: dict[str, Any] | None = objects_manager.get_object(new_object_id)

        if not current_object:
            abort(404, "Could not retrieve the created object from the database!")

        current_object: CmdbObject = CmdbObject.from_data(current_object)

        # sync select fields
        if current_object.has_fields_of_type("select"):
            sync_select_field_options(request_user, current_object, object_type)

        # Handle Webhook Events
        handle_notify_webhooks(request_user, current_object, WebhookEventType.CREATE)

        if current_app.cloud_mode:
            handle_sync_config_item_count(request_user, objects_count)

        # Generate new insert log
        handle_creat_object_log(request_user, current_object, LogAction.CREATE)

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
            render_result = CmdbMultiRender(
                [requested_object],
                request_user,
                True
            ).result(single_object=True)
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

        if fetch_only_active_objects():
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
            result_data = RenderList(
                iteration_result.results,
                request_user,
                True
            ).render_result_list(raw=True)
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

        if fetch_only_active_objects():
            count_of_objects: int = objects_manager.count_documents({"active": True})
        else:
            count_of_objects = objects_manager.count_documents()

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
    HTTP `GET` route to retrieve the number of CmdbObjects belonging to a given CmdbType

    Honors the active-only filter when fetch_only_active_objects() is enabled

    Args:
        type_id (int): public_id of the CmdbType whose CmdbObjects should be counted
        request_user (CmdbUser): The CmdbUser making the request

    Returns:
        DefaultResponse: The number of CmdbObjects of the given Type in the database
    """
    try:
        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
        if fetch_only_active_objects():
            count_of_objects: int = objects_manager.count_documents({"active": True, "type_id": type_id})
        else:
            count_of_objects = objects_manager.count_documents({"type_id": type_id})

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
    HTTP `GET` route to retrieve a single CmdbObject in its raw (un-rendered) form

    Unlike GET /<public_id>, no render result, references or summary is computed; the stored
    document is returned as-is

    Args:
        public_id (int): public_id of the CmdbObject
        request_user (CmdbUser): The CmdbUser making the request

    Returns:
        DefaultResponse: The raw CmdbObject document
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
    Groups CmdbObjects by the given field name and returns at most the first five groups

    Each group is enriched with the corresponding CmdbType's label and ci_explorer_color so the
    dashboard chart can render it directly. Honors the active-only filter when enabled

    Args:
        value (str): The CmdbObject field name to group by (typically 'type_id')
        request_user (CmdbUser): The CmdbUser making the request

    Returns:
        DefaultResponse: List of group dicts (cap 5) with 'label', 'type_color' and counts
    """
    try:
        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)

        filter_state = {'active': {'$eq': True}} if fetch_only_active_objects() else None

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
    HTTP `GET` route returning the rendered MDS reference summary for a single CmdbObject

    The MDS reference summary is the data shape used by other objects to display this object
    inside their multi-data-section reference fields

    Args:
        public_id (int): public_id of the referenced CmdbObject
        request_user (CmdbUser): The CmdbUser making the request

    Returns:
        DefaultResponse: The MDS reference summary for the requested CmdbObject
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

        mds_reference = CmdbMultiRender([referenced_object], request_user, True).get_mds_reference(public_id)

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
    HTTP `GET` route returning rendered MDS reference summaries for one or more CmdbObjects

    Resolves the target ids from the 'objectIDs' query parameter (comma-separated). When the
    parameter is missing or empty, falls back to the path-supplied 'public_id'

    Args:
        public_id (int): Fallback public_id used when 'objectIDs' query param is absent
        request_user (CmdbUser): The CmdbUser making the request

    Returns:
        DefaultResponse: Mapping of public_id to its MDS reference summary
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
                abort(404, f"The Type of the Object with ID:{public_id} was not found in the database!")

            mds_reference = CmdbMultiRender([referenced_object], request_user, True).get_mds_reference(object_id)

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
        match_filter: dict[str, Any] = {"$match": {}}

        if fetch_only_active_objects():
            match_filter = {"$match": {"active": {"$eq": True}}}

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
            request_data = RenderList(
                iteration_result.results,
                request_user,
                True
            ).render_result_list(raw=True)
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
    HTTP `GET` route returning the active state of a single CmdbObject

    Args:
        public_id (int): public_id of the CmdbObject whose state is requested
        request_user (CmdbUser): The CmdbUser making the request

    Returns:
        DefaultResponse: True when the object is active, False otherwise
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
def get_unstructured_cmdb_objects(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route returning the public_ids of CmdbObjects of the given CmdbType
    whose 'fields' set no longer matches the type's current field definition

    Used as the dirty-data probe behind the 'clean' admin tool

    Args:
        public_id (int): public_id of the CmdbType whose CmdbObjects are inspected
        request_user (CmdbUser): The CmdbUser making the request

    Returns:
        GetListResponse: List of public_ids of structurally inconsistent CmdbObjects
    """
    try:
        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)

        object_type: CmdbType | None = objects_manager.get_object_type(public_id)

        if not object_type:
            abort(404, f"Type with ID: {public_id} not found!")

        all_type_objects: list[CmdbObject] = objects_manager.find_objects(criteria={'type_id': public_id})

        type_fields = {field.get('name') for field in object_type.fields}

        unstructured: list[int] = [
            obj.get_public_id()
            for obj in all_type_objects
            if {f["name"] for f in obj.fields} != type_fields
        ]

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
    HTTP `PUT`/`PATCH` route to update one or more CmdbObjects with the same payload

    When the 'objectIDs' query parameter is set, every listed CmdbObject is updated with the
    same payload; otherwise only the path-supplied 'public_id' is updated. Refuses any change
    of an object's special_type. IPAM invariants (subnet / vlan / interface row validation)
    are enforced before the write. CIDR edits on SUPERNET / SUBNET objects are no longer
    blocked when they would push child rows outside the new range; those children surface as
    is_valid=False in the IPAM overviews instead. Computes a major / minor / patch version
    bump from the field-level diff and records an edit log per updated CmdbObject

    Args:
        public_id (int): public_id of the CmdbObject; used as the only target when no
            'objectIDs' query parameter is provided
        data (dict): The new CmdbObject payload, validated against CmdbObject.SCHEMA
        request_user (CmdbUser): The CmdbUser making the request

    Returns:
        UpdateMultiResponse: One updated payload per CmdbObject that was processed
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

            current_object_instance: CmdbObject | None = objects_manager.get_object(
                obj_id,
                request_user,
                AccessControlPermission.READ,
                as_dict=False
            )

            if not current_object_instance:
                abort(404, f"Object with ID:{public_id} not found!")

            if is_special_type_changed(current_object_instance.special_type, new_data.get('special_type')):
                abort(400, f"SpecialType of an Object is not changable. Occured for Object with ID: {public_id}")

            current_type_instance = objects_manager.get_object_type(current_object_instance.get_type_id())

            if not current_type_instance:
                abort(500, "Type of Object not found in database!")

            current_object_render_result = CmdbMultiRender(
                [current_object_instance],
                request_user
            ).result(single_object=True)

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

            types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)
            ipam_errors: list[dict[str, Any]] = enforce_object_invariants(
                objects_manager,
                types_manager,
                new_data,
                previous_object=CmdbObject.to_json(current_object_instance),
            )

            if ipam_errors:
                abort(400, format_errors_for_abort(ipam_errors))

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

            object_after: CmdbObject = CmdbObject.from_data(object_after)

            # sync select fields
            if object_after.has_fields_of_type("select"):
                sync_select_field_options(request_user, object_after, current_type_instance)

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

        found_object: CmdbObject | None = objects_manager.get_object(
            public_id,
            request_user,
            AccessControlPermission.READ,
            as_dict=False
        )

        if not found_object:
            abort(404, f"Object with ID:{public_id} not found!")

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

        current_object_render_result: RenderResult = CmdbMultiRender(
            [found_object],
            request_user
        ).result(single_object=True)

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
    HTTP `PUT`/`PATCH` route that re-aligns every CmdbObject of the given CmdbType with that
    type's current field definition: drops fields the type no longer declares and adds fields
    the type now requires (with empty values)

    Counterpart to GET /clean/<public_id>. Used by the 'clean' admin tool to repair structurally
    dirty objects after a Type's field set changed

    Args:
        public_id (int): public_id of the CmdbType whose CmdbObjects should be re-aligned
        request_user (CmdbUser): The CmdbUser making the request

    Returns:
        UpdateMultiResponse: One updated payload per CmdbObject that was re-aligned
    """
    try:
        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
        reports_manager: ReportsManager = ManagerProvider.get_manager(ManagerType.REPORTS, request_user)

        update_type_instance = objects_manager.get_object_type(public_id)

        if not update_type_instance:
            abort(500, f"Type with ID:{public_id} not found!")

        type_fields: list[dict[str, Any]] = update_type_instance.fields

        objects_by_type: list[CmdbObject] = objects_manager.get_objects_by(type_id=public_id)
        reports_for_type: list[dict[str, Any]] = objects_manager.get_many_from_other_collection(
                                                    CmdbReport.COLLECTION,
                                                    type_id=public_id
                                                 )

        # Field names dropped from any object of this type, accumulated across all objects so the
        # type's reports can be cleaned once afterwards rather than per object/field
        removed_field_names: set[str] = set()

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

                removed_field_names.add(field)

        # Reports belong to the Type, not individual objects: strip every removed field from each
        # report once, rebuild its query, and apply all reports in a single bulk write
        if removed_field_names:
            try:
                report_ops: list[UpdateOne] = []

                for a_report in reports_for_type:
                    tmp_report: CmdbReport = CmdbReport.from_data(a_report)

                    for field in removed_field_names:
                        tmp_report.remove_field_occurences(field)

                    tmp_report.report_query = build_report_query(tmp_report.conditions, update_type_instance)
                    report_ops.append(
                        UpdateOne({'public_id': tmp_report.public_id}, {'$set': tmp_report.__dict__})
                    )

                if report_ops:
                    reports_manager.bulk_write(report_ops)
            except Exception as error:
                LOGGER.debug(
                    "[update_unstructured_cmdb_objects] Clean Reports Exception: %s, Type: %s", error, type(error)
                )
                abort(500, "An interlal server error occured while cleaning reports!")

        objects_by_type: list[CmdbObject] = objects_manager.get_objects_by(type_id=public_id)

        try:
            for obj in objects_by_type:
                for t_field in type_fields:
                    name = t_field["name"]
                    field_type: str = t_field["type"]
                    value = None

                    if [item for item in obj.get_all_fields() if item["name"] == name]:
                        continue

                    if "value" in t_field:
                        value = t_field["value"]

                    objects_manager.update_many_objects(
                        query={'public_id': obj.public_id},
                        update={
                            'fields': {
                                "name": name,
                                "type": field_type,
                                "value": value
                            }
                        },
                        add_to_set=True
                    )
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

@objects_blueprint.route('/<int:public_id>', methods=['DELETE'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@objects_blueprint.protect(auth=True, right='base.framework.object.delete')
def delete_cmdb_object(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `DELETE` route to remove a single CmdbObject from the database

    Refuses the delete when the object is a SUPERNET / SUBNET still referenced by other IPAM
    objects (subnets, vlans or interface rows), or when its location is the parent of other
    locations. References from non-IPAM CmdbObjects are removed automatically after the delete

    Args:
        public_id (int): public_id of the CmdbObject to delete
        request_user (CmdbUser): The CmdbUser making the request

    Returns:
        DefaultResponse: True after a successful delete
    """
    try:
        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)

        to_delete_object: CmdbObject | None = objects_manager.get_object(public_id, as_dict=False)

        if not to_delete_object:
            abort(404, f"Object with ID:{public_id} not found!")

        to_delete_object_type: CmdbType | None = objects_manager.get_object_type(to_delete_object.get_type_id())

        if not to_delete_object_type:
            abort(500, f"Type of Object with ID:{public_id} not found in database!")

        types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)
        ipam_delete_errors: list[dict[str, Any]] = enforce_delete_guards(
            objects_manager,
            types_manager,
            CmdbObject.to_json(to_delete_object),
        )

        if ipam_delete_errors:
            abort(400, format_errors_for_abort(ipam_delete_errors))

        # An object can not be deleted if it has a location AND the location is a parent for other locations
        handle_delete_object_location(request_user, public_id)

        # Delete the Object
        objects_manager.delete_with_follow_up(public_id, request_user, AccessControlPermission.DELETE)

        # Remove all references to this object from other CmdbObjects
        objects_manager.delete_all_object_references(public_id)

        # Cascade the deletion to relevant collections
        delete_one_cascade(request_user, to_delete_object, objects_manager, LogAction.DELETE)

        return DefaultResponse(True).make_response()
    except HTTPException as http_err:
        raise http_err
    except ObjectsManagerUpdateError as err:
        LOGGER.error("[delete_cmdb_object] ObjectsManagerUpdateError: %s", err, exc_info=True)
        abort(500, "Failed to delete Object references from the database!")
    except ObjectsManagerGetError as err:
        LOGGER.error("[delete_cmdb_object] ObjectsManagerGetError: %s", err, exc_info=True)
        abort(500, "Failed to retrieve the requested Object from the database!")
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
def delete_cmdb_object_with_child_locations(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `DELETE` route that removes a CmdbObject and every CmdbLocation beneath its location

    Refuses the delete when the object is a SUPERNET / SUBNET still referenced by other IPAM
    objects (subnets, vlans or interface rows). The 404 case is hit when either the object or
    its location is missing

    Args:
        public_id (int): public_id of the CmdbObject to delete
        request_user (CmdbUser): The CmdbUser making the request

    Returns:
        DefaultResponse: True after a successful delete
    """
    try:
        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)

        # Check if object exists
        to_delete_object: CmdbObject | None = objects_manager.get_object(public_id, as_dict=False)

        if not to_delete_object:
            abort(404, f"Object with ID:{public_id} not found!")

        if not object_has_location(request_user, public_id):
            abort(404, f"Location of the Object with ID:{public_id} not found!")

        to_delete_object_type: CmdbType | None = objects_manager.get_object_type(to_delete_object.get_type_id())

        if not to_delete_object_type:
            abort(500, f"Type of Object with ID:{public_id} not found in database!")

        types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)
        ipam_delete_errors: list[dict[str, Any]] = enforce_delete_guards(
            objects_manager,
            types_manager,
            CmdbObject.to_json(to_delete_object),
        )

        if ipam_delete_errors:
            abort(400, format_errors_for_abort(ipam_delete_errors))

        # Delete the object
        objects_manager.delete_with_follow_up(public_id, request_user, permission=AccessControlPermission.DELETE)

        # Remove all child locations
        handle_delete_location_and_child_locations(request_user, public_id)

        # Remove all references to this object from other CmdbObjects
        objects_manager.delete_all_object_references(public_id)

        # Cascade the deletion to relevant collections
        delete_one_cascade(request_user, to_delete_object, objects_manager, LogAction.DELETE)

        return DefaultResponse(True).make_response()
    except HTTPException as http_err:
        raise http_err
    except ObjectsManagerUpdateError as err:
        LOGGER.error("[delete_cmdb_object_with_child_locations] ObjectsManagerUpdateError: %s", err, exc_info=True)
        abort(500, "Failed to delete Object references from the database!")
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


@objects_blueprint.route('/<int:public_id>/children', methods=['DELETE'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@objects_blueprint.protect(auth=True, right='base.framework.object.delete')
def delete_object_with_child_objects(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `DELETE` route that removes a CmdbObject together with every child CmdbObject in its
    location tree, and every CmdbLocation beneath the target's location

    The IPAM delete guard is run for the target and each cascade-deleted child up front, so a
    single offending object refuses the whole cascade before any write happens

    Args:
        public_id (int): public_id of the root CmdbObject to delete
        request_user (CmdbUser): The CmdbUser making the request

    Returns:
        DefaultResponse: True after a successful cascade delete
    """
    try:
        locations_manager: LocationsManager = ManagerProvider.get_manager(ManagerType.LOCATIONS, request_user)
        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)

        # check if object exists
        target_object: CmdbObject | None = objects_manager.get_object(public_id, as_dict=False)

        if not target_object:
            abort(404, f"Object with ID:{public_id} not found!")

        # check if location for this object exists
        if not object_has_location(request_user, public_id):
            abort(404, f"Location for the Object with ID:{public_id} not found!")

        to_delete_object_type: CmdbType | None = objects_manager.get_object_type(target_object.get_type_id())

        if not to_delete_object_type:
            abort(404, f"Type of Object with ID:{public_id} not found in database!")

        types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)

        children_object_ids_for_guard: list[int] = locations_manager.get_child_locations_object_ids(public_id)
        guard_targets: list[dict[str, Any]] = [CmdbObject.to_json(target_object)]

        if children_object_ids_for_guard:
            guard_targets.extend(objects_manager.find(criteria={"public_id": {"$in": children_object_ids_for_guard}}))

        for guard_target in guard_targets:
            ipam_delete_errors: list[dict[str, Any]] = enforce_delete_guards(
                objects_manager,
                types_manager,
                guard_target,
            )

            if ipam_delete_errors:
                abort(400, format_errors_for_abort(ipam_delete_errors))

        # Remove all child locations
        handle_delete_location_and_child_locations(request_user, public_id)

        children_object_ids: list[int] = locations_manager.get_child_locations_object_ids(public_id)

        if children_object_ids:
            children_objects: list[dict[str, Any]] = objects_manager.find(
                criteria={"public_id": {"$in": children_object_ids}}
            )

            for child_object in children_objects:
                child_object_id = child_object["public_id"]

                # Delete the current child object
                objects_manager.delete_with_follow_up(
                    child_object_id,
                    request_user,
                    AccessControlPermission.DELETE
                )

                # Remove invalid CmdbObjectRelations since the object no longer exists
                handle_delete_invalid_object_relations(request_user, child_object_id)

                # Notify via Webhooks
                handle_notify_webhooks(request_user, CmdbObject.from_data(child_object), WebhookEventType.DELETE)

                # Create object deletion log entry
                handle_creat_object_log(request_user, CmdbObject.from_data(child_object), LogAction.DELETE)

            # Remove all child objects from static object groups
            handle_delete_from_object_groups(request_user, children_object_ids)

            # Scrub dangling references to the deleted children from sibling CmdbObjects
            objects_manager.delete_all_object_references(children_object_ids)


        # Delete target Object
        objects_manager.delete_with_follow_up(public_id, request_user, AccessControlPermission.DELETE)

        # Remove all references to this object from other CmdbObjects
        objects_manager.delete_all_object_references(public_id)

        # Cascade the deletion to relevant collections
        delete_one_cascade(request_user, target_object, objects_manager, LogAction.DELETE)

        return DefaultResponse(True).make_response()
    except HTTPException as http_err:
        raise http_err
    except ObjectsManagerUpdateError as err:
        LOGGER.error("[delete_object_with_child_objects] ObjectsManagerUpdateError: %s", err, exc_info=True)
        abort(500, "Failed to delete Object references from the database!")
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
def delete_many_cmdb_objects(public_ids: str, request_user: CmdbUser) -> Response:
    """
    HTTP `DELETE` route to bulk-delete CmdbObjects by a comma-separated id list

    Refuses the operation when any target has a CmdbLocation. The IPAM delete guard is
    evaluated atomically up front: if any one target would orphan IPAM references, no delete
    happens. After deleting, removes references to the deleted objects, drops them from static
    object groups, emits a webhook + log per object, and syncs the cloud-mode item count

    Args:
        public_ids (str): Comma-separated CmdbObject public_ids to delete
        request_user (CmdbUser): The CmdbUser making the request

    Returns:
        DefaultResponse: {'successfully': [public_id, ...]} for every CmdbObject that was deleted
    """
    try:
        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
        types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)
        locations_manager: LocationsManager = ManagerProvider.get_manager(ManagerType.LOCATIONS, request_user)

        to_delete_object_ids: list[int] = extract_public_ids(public_ids)

        to_delete_objects: list[dict[str, Any]] = objects_manager.find(
            criteria={'public_id': {"$in": to_delete_object_ids}}
        )

        # At the current state it is not possible to bulk delete objects with locations
        # check if any object has a location
        object_locations: list[dict, Any] = locations_manager.find(
            criteria={'object_id': {"$in": to_delete_object_ids}}
        )

        if object_locations:
            abort(400, "It is not possible to bulk delete objects if any of them has a location!")

        # Get types of all objects which should be deleted
        object_type_ids: list[int] = [
            obj["type_id"]
            for obj in to_delete_objects
            if obj.get("type_id") is not None
        ]

        type_map: dict[int, CmdbType] = types_manager.get_types_lookup(object_type_ids)

        # Atomic IPAM guard: refuse the whole bulk delete if any object would orphan references
        for to_check in to_delete_objects:
            ipam_delete_errors: list[dict[str, Any]] = enforce_delete_guards(
                objects_manager,
                types_manager,
                to_check,
            )

            if ipam_delete_errors:
                abort(400, format_errors_for_abort(ipam_delete_errors))

        ack: list[int] = []

        for current_object in to_delete_objects:
            current_object: CmdbObject = CmdbObject.from_data(current_object)
            current_object_type: CmdbType = type_map.get(current_object.get_type_id())

            if not current_object_type:
                abort(404, f"Type of Object with ID:{current_object.get_public_id()} not found in database!")

            objects_manager.delete_with_follow_up(
                current_object.get_public_id(),
                request_user,
                AccessControlPermission.DELETE
            )

            # Remove invalid CmdbObjectRelations since the object no longer exists
            handle_delete_invalid_object_relations(request_user, current_object.get_public_id())

            # Send deletion event to all active webhooks
            handle_notify_webhooks(request_user, current_object, WebhookEventType.DELETE)

            # Create ObjectLog of the deletion
            handle_creat_object_log(request_user, current_object, LogAction.DELETE)

            ack.append(current_object.get_public_id())

        # Remove the deleted objects from all static object groups
        handle_delete_from_object_groups(request_user, to_delete_object_ids)

        # Remove all references of the deleted objects from other CmdbObjects
        objects_manager.delete_all_object_references(to_delete_object_ids)

        # Sync config item count in CLOUD_MODE
        if current_app.cloud_mode:
            objects_count: int = objects_manager.count_documents()
            handle_sync_config_item_count(request_user, objects_count)

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

#TODO: REFACTOR-FIX (move the functionality of ObjectRelationsManager to a method in it)
def delete_invalid_object_relations(public_id: int,
                            request_user: CmdbUser,
                            object_relations_manager: ObjectRelationsManager,
                            object_relation_logs_manager: ObjectRelationLogsManager) -> None:
    """
    Deletes every CmdbObjectRelation in which the given public_id appears as parent or child,
    and writes a CmdbObjectRelationLog for each deletion

    Per-relation manager errors are caught and logged so a partial failure does not abort the
    surrounding object deletion

    Args:
        public_id (int): public_id of the CmdbObject whose CmdbObjectRelations should be removed
        request_user (CmdbUser): The CmdbUser performing the deletion
        object_relations_manager (ObjectRelationsManager): db interface for CmdbObjectRelations
        object_relation_logs_manager (ObjectRelationLogsManager): db interface for CmdbObjectRelationLogs

    Raises:
        ObjectRelationsManagerDeleteError: When deletion of a CmdbObjectRelation fails
        ObjectRelationLogsManagerBuildError: When creating a CmdbObjectRelationLog fails
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
