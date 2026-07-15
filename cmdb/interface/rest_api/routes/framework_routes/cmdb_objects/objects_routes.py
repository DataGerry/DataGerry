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
from logging import Logger, getLogger
from typing import Any
from flask import abort, current_app, request
from werkzeug import Response
from werkzeug.exceptions import HTTPException

from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.manager.query_builder import BuilderParameters
from cmdb.manager import (
    LocationsManager,
    LogsManager,
    ObjectsManager,
    ReportsManager,
    TypesManager,
)
from cmdb.security.acl.permission import AccessControlPermission
from cmdb.models.type_model.cmdb_type import CmdbType
from cmdb.models.type_model.field_type_enum import FieldType
from cmdb.models.user_model import CmdbUser
from cmdb.models.webhook_model.webhook_event_type_enum import WebhookEventType
from cmdb.models.object_model import CmdbObject
from cmdb.models.log_model.log_action_enum import LogAction
from cmdb.models.reports_model.cmdb_report import CmdbReport
from cmdb.framework.results import IterationResult
from cmdb.framework.rendering.cmdb_multi_render import CmdbMultiRender
from cmdb.framework.rendering.render_result import RenderResult
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.route_utils import insert_request_user, verify_api_access, handle_db_errors
from cmdb.interface.rest_api.routes.routes_helper import (
    fetch_only_active_objects,
    extract_public_ids,
)
from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_helper import (
    delete_one_cascade,
    handle_notify_webhooks,
    handle_create_object_log,
    handle_sync_config_item_count,
    handle_delete_invalid_object_relations,
    handle_delete_from_object_groups,
    handle_delete_object_location,
    sync_select_field_options,
    render_or_native,
    build_new_object_data,
    apply_object_update,
    validate_object_patch_payload,
    build_patched_object_data,
    guard_object_write_license,
    guard_object_delete,
    emit_object_state_change_events,
    realign_objects_to_type,
    clean_type_reports,
)
from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_constants import ObjectViewMode
from cmdb.interface.rest_api.routes.framework_routes.cmdb_locations.location_helper import (
    extract_object_location_parent,
    validate_object_location_change,
    sync_object_location,
)
from cmdb.framework.ipam.enforcement import (
    enforce_object_invariants,
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
from cmdb.errors.manager.types_manager import TypesManagerGetError
from cmdb.errors.security import AccessDeniedError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

objects_blueprint = APIBlueprint('objects', __name__)

# Maximum number of type groups returned for the dashboard chart by the group-by route
MAX_DASHBOARD_GROUPS: int = 5

# --------------------------------------------------- CRUD - CREATE -------------------------------------------------- #

@objects_blueprint.route('/', methods=['POST'])
@handle_db_errors
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@objects_blueprint.protect(auth=True, right='base.framework.object.add')
def insert_cmdb_object(request_user: CmdbUser) -> Response:  # pylint: disable=too-many-statements
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
        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
        types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)

        objects_count: int = 0

        if current_app.cloud_mode:
            objects_count = objects_manager.count_documents()
            if request_user.is_config_item_limit_reached(objects_count):
                abort(400, "The maximum amout of ConfigItems is reached!")

        # The custom CmdbLocation tree name (if any) travels in the object body; the parent itself is
        # the object's location field value. location_name is transient - build_new_object_data strips it
        location_name: str | None = (request.json or {}).get('location_name')

        # Normalise the payload: assign/verify public_id, resolve the type, stamp defaults + version
        new_object_data, object_type = build_new_object_data(objects_manager, request.json)

        # Creating an IPAM special-type object (or linking a subnet on an interface) needs an IPAM license
        guard_object_write_license(types_manager, request_user, new_object_data)

        ipam_errors: list[dict[str, Any]] = enforce_object_invariants(
            objects_manager,
            types_manager,
            new_object_data,
            previous_object=None,
        )

        if ipam_errors:
            abort(400, format_errors_for_abort(ipam_errors))

        # Validate the location placement (parent exists) before the object is written
        has_location_field, location_parent = extract_object_location_parent(new_object_data.get('fields', []))
        locations_manager: LocationsManager | None = None

        if has_location_field:
            locations_manager = ManagerProvider.get_manager(ManagerType.LOCATIONS, request_user)
            validate_object_location_change(new_object_data['public_id'], location_parent, locations_manager)

        new_object_id: int = objects_manager.insert_object(
            new_object_data,
            request_user,
            AccessControlPermission.CREATE
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

        current_object: dict[str, Any] | None = objects_manager.get_object(new_object_id)

        if not current_object:
            abort(404, "Could not retrieve the created object from the database!")

        current_object: CmdbObject = CmdbObject.from_data(current_object)

        # sync select fields
        if current_object.has_fields_of_type(FieldType.SELECT):
            sync_select_field_options(request_user, current_object, object_type)

        # Handle Webhook Events
        handle_notify_webhooks(request_user, current_object, WebhookEventType.CREATE)

        if current_app.cloud_mode:
            # Recount AFTER the insert so the synced total includes the just-created object
            # (the pre-insert objects_count above is only for the config-item limit check)
            handle_sync_config_item_count(request_user, objects_manager.count_documents())

        # Generate new insert log
        handle_create_object_log(request_user, current_object, LogAction.CREATE)

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

        view = params.optional.get('view', ObjectViewMode.NATIVE)

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

        result_data = render_or_native(view, iteration_result.results, request_user)

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
        types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)

        filter_state = {'active': {'$eq': True}} if fetch_only_active_objects() else None

        result = []
        grouped_documents: list[dict[str, Any]] = list(objects_manager.group_objects_by_value(
            value,
            filter_state,
            request_user,
            AccessControlPermission.READ,
        ))

        # Resolve every group's Type in a single lookup instead of one query per group (N+1)
        type_map: dict[int, CmdbType] = types_manager.get_types_lookup(
            [document['_id'] for document in grouped_documents]
        )

        for document in grouped_documents:
            cur_type: CmdbType | None = type_map.get(document['_id'])

            # Skip groups whose Type no longer exists (e.g. orphaned objects of a deleted Type)
            if not cur_type:
                continue

            document['label'] = cur_type.label
            document['type_color'] = cur_type.ci_explorer_color
            result.append(document)

            if len(result) == MAX_DASHBOARD_GROUPS:  # Stop after collecting the chart's group cap
                break

        return DefaultResponse(result).make_response()
    except TypesManagerGetError as err:
        LOGGER.error("[group_cmdb_objects_by_type_id] TypesManagerGetError: %s", err, exc_info=True)
        abort(400, "Failed to retrieve the Type of an Object from the database!")
    except ObjectsManagerGetError as err:
        LOGGER.error("[group_cmdb_objects_by_type_id] ObjectsManagerGetError: %s", err, exc_info=True)
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

        # NOTE: each object is rendered in its OWN CmdbMultiRender on purpose - do not collapse the
        # loop into a single multi-object render. CmdbMultiRender.get_mds_reference resolves the id
        # from objects_cache, which a shared render would populate with the OTHER objects' references
        # too, so a cross-referenced id would resolve differently. Per-object keeps the result exact
        for object_id in object_ids:
            referenced_object = objects_manager.get_object(object_id,
                                                            request_user,
                                                            AccessControlPermission.READ)

            if not referenced_object:
                abort(404, f"The Object with ID:{object_id} was not found!")

            referenced_object = CmdbObject.from_data(referenced_object)

            referenced_type = objects_manager.get_object_type(referenced_object.get_type_id())

            if not referenced_type:
                abort(404, f"The Type of the Object with ID:{object_id} was not found in the database!")

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

        view = params.optional.get('view', ObjectViewMode.NATIVE)

        # references() consumes params.filter as aggregation pipeline stage(s): wrap a raw filter
        # dict into a $match stage, then append the active-only stage when the filter is enabled
        if isinstance(params.filter, dict):
            params.filter = [{'$match': params.filter}]

        if fetch_only_active_objects():
            params.filter.append({'$match': {'active': {"$eq": True}}})

        referenced_object = objects_manager.get_object(public_id, request_user, AccessControlPermission.READ)

        if not referenced_object:
            abort(404, f"Object with ID: {public_id} not found!")

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

        request_data = render_or_native(view, iteration_result.results, request_user)

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

        if not target_object_data:
            abort(404, f"Object with ID:{public_id} not found!")

        target_object: CmdbObject = CmdbObject.from_data(target_object_data)

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

        # Only the field names are needed to detect structural drift, so project them server-side
        # instead of loading every full object document
        all_type_objects: list[dict[str, Any]] = objects_manager.find_objects(
            criteria={'type_id': public_id},
            as_dict=True,
            projection={'public_id': 1, 'fields.name': 1},
        )

        type_fields = {field.get('name') for field in object_type.fields}

        unstructured: list[int] = [
            obj['public_id']
            for obj in all_type_objects
            if {f.get('name') for f in obj.get('fields', [])} != type_fields
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

@objects_blueprint.route('/<int:public_id>', methods=['PUT'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@objects_blueprint.protect(auth=True, right='base.framework.object.edit')
@objects_blueprint.validate(CmdbObject.SCHEMA)
def update_cmdb_object(public_id: int, data: dict, request_user: CmdbUser) -> Response:
    """
    HTTP `PUT` route to fully replace one or more CmdbObjects with the same payload

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
        types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)

        object_ids: list[int] = request.args.getlist('objectIDs')
        object_ids = list(map(int, object_ids)) if object_ids else [public_id]

        # The active flag comes from the shared (validated) payload and applies to every target
        active_state = data.get('active', None)

        # DataGerry sends the complete object on every update (no PATCH/subset semantics), so the
        # same payload is applied to each target; apply_object_update runs the per-object side effects
        results: list[dict[str, Any]] = [
            apply_object_update(
                obj_id,
                data,
                active_state,
                request_user,
                objects_manager,
                types_manager,
                logs_manager,
            )
            for obj_id in object_ids
        ]

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


@objects_blueprint.route('/<int:public_id>', methods=['PATCH'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@objects_blueprint.protect(auth=True, right='base.framework.object.edit')
def patch_cmdb_object(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `PATCH` route to partially update a single CmdbObject

    Unlike the full-replace `PUT`, the body carries only a SUBSET of the object's data: a list of
    regular `fields` ({name, value}) plus three MDS row lists - `created_mds_rows` ({section_id,
    data}; the backend assigns the new multi_data_id and bumps the section counter, seeding the
    section container on first-row-add when the type declares that section), `edited_mds_rows`
    ({section_id, multi_data_id, data}) and `deleted_mds_rows` ({section_id, multi_data_id}).
    Listed values are merged onto the stored object; everything not mentioned is
    left untouched. Immutable identifiers and server-managed fields (public_id, type_id,
    creation_time, author_id, special_type, version, last_edit_time, editor_id) are rejected with
    400. The merged object then runs the same pipeline as PUT (field validation, IPAM license +
    invariants, version bump from the real diff, UPDATE webhook and edit log)

    Args:
        public_id (int): public_id of the CmdbObject to patch
        request_user (CmdbUser): The CmdbUser making the request

    Returns:
        UpdateSingleResponse: The patched CmdbObject payload
    """
    try:
        logs_manager: LogsManager = ManagerProvider.get_manager(ManagerType.LOGS, request_user)
        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
        types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)

        patch_data: dict[str, Any] = validate_object_patch_payload(request.get_json(silent=True))

        current_object: CmdbObject | None = objects_manager.get_object(
            public_id,
            request_user,
            AccessControlPermission.READ,
            as_dict=False,
        )

        if not current_object:
            abort(404, f"Object with ID:{public_id} not found!")

        current_type: CmdbType | None = objects_manager.get_object_type(current_object.get_type_id())

        if not current_type:
            abort(500, "Type of Object not found in database!")

        merged_data: dict[str, Any] = build_patched_object_data(
            current_object, patch_data, current_type.get_mds_section_ids()
        )

        # The merged payload is a complete object, so it runs the shared full-update pipeline
        result: dict[str, Any] = apply_object_update(
            public_id,
            merged_data,
            None,
            request_user,
            objects_manager,
            types_manager,
            logs_manager,
        )

        return UpdateSingleResponse(result).make_response()
    except HTTPException as http_err:
        raise http_err
    except ObjectsManagerGetError as err:
        LOGGER.error("[patch_cmdb_object] ObjectsManagerGetError: %s", err, exc_info=True)
        abort(400, "Failed to retrieve the requested Object from the database!")
    except ObjectsManagerUpdateError as err:
        LOGGER.error("[patch_cmdb_object] ObjectsManagerUpdateError: %s", err, exc_info=True)
        abort(400, "Failed to update the requested Object in the database!")
    except AccessDeniedError:
        abort(403, "Access denied: You do not have sufficient permissions to perform this action!")
    except Exception as err:
        LOGGER.error("[patch_cmdb_object] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while patching Object with ID:{public_id}!")


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

        # Emit the UPDATE webhook + write the ACTIVE_CHANGE log (best-effort, isolated)
        emit_object_state_change_events(
            request_user,
            logs_manager,
            found_object,
            object_after,
            current_object_render_result,
            state,
        )

        return UpdateSingleResponse(result=CmdbObject.to_json(found_object)).make_response()
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

        reports_for_type: list[dict[str, Any]] = objects_manager.get_many_from_other_collection(
            CmdbReport.COLLECTION,
            type_id=public_id,
        )

        # Re-align every object of the Type with its current field set (bulk write), then strip any
        # removed field from the Type's reports once
        removed_field_names: set[str] = realign_objects_to_type(objects_manager, update_type_instance)
        clean_type_reports(reports_manager, reports_for_type, removed_field_names, update_type_instance)

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

        # Deleting an IPAM special-type object needs a valid IPAM license + passes the delete guards
        guard_object_delete(objects_manager, types_manager, request_user, CmdbObject.to_json(to_delete_object))

        # An object can not be deleted if it has a location AND the location is a parent for other locations
        handle_delete_object_location(request_user, public_id)

        # Delete the Object (reusing the already-resolved type to skip a per-object type lookup)
        objects_manager.delete_with_follow_up(
            public_id, request_user, AccessControlPermission.DELETE, object_type=to_delete_object_type
        )

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
        abort(400, "Failed to retrieve the requested Object from the database!")
    except ObjectsManagerDeleteError as err:
        LOGGER.error("[delete_cmdb_object] ObjectsManagerDeleteError: %s", err, exc_info=True)
        abort(500, "Failed to delete the Object in the database!")
    except Exception as err:
        LOGGER.error("[delete_cmdb_object] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while deleting the Object with ID: {public_id}!")


@objects_blueprint.route('/delete/<string:public_ids>', methods=['DELETE'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@objects_blueprint.protect(auth=True, right='base.framework.object.delete')
# Cohesive bulk delete: location guard -> IPAM guard -> RA cascade -> per-object delete + side
# effects -> reference scrub -> cloud count sync; the locals are inherent to the sequence
# pylint: disable=too-many-locals
def delete_many_cmdb_objects(public_ids: str, request_user: CmdbUser) -> Response:
    """
    HTTP `DELETE` route to bulk-delete CmdbObjects by a comma-separated id list

    Each located target has its CmdbLocation deleted and that location's direct children promoted
    onto its parent (their grandparent), keeping the location tree connected. The IPAM delete guard
    is evaluated atomically up front: if any one target would orphan IPAM references, no delete
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
        # Resolved once and reused for every target's location cleanup in the loop below
        locations_manager: LocationsManager = ManagerProvider.get_manager(ManagerType.LOCATIONS, request_user)

        to_delete_object_ids: list[int] = extract_public_ids(public_ids)

        to_delete_objects: list[dict[str, Any]] = objects_manager.find(
            criteria={'public_id': {"$in": to_delete_object_ids}}
        )

        # Get types of all objects which should be deleted
        object_type_ids: list[int] = [
            obj["type_id"]
            for obj in to_delete_objects
            if obj.get("type_id") is not None
        ]

        type_map: dict[int, CmdbType] = types_manager.get_types_lookup(object_type_ids)

        # Atomic IPAM guard: refuse the whole bulk delete if any object would orphan references
        # or - when IPAM is unlicensed - if any target is an IPAM special-type object
        for to_check in to_delete_objects:
            guard_object_delete(objects_manager, types_manager, request_user, to_check)

        # RiskAssessment/ControlMeasureAssignment cascade for all targets in one query pair instead
        # of the per-object cascade delete_with_follow_up would run for each object
        objects_manager.delete_objects_from_risk_assessment_cascade(to_delete_object_ids)

        ack: list[int] = []

        for current_object in to_delete_objects:
            current_object: CmdbObject = CmdbObject.from_data(current_object)
            current_object_type: CmdbType = type_map.get(current_object.get_type_id())

            if not current_object_type:
                abort(404, f"Type of Object with ID:{current_object.get_public_id()} not found in database!")

            # Delete the object's location (if any); its direct children are promoted onto the
            # location's own parent (their grandparent), keeping the location tree connected.
            # Managers are passed in so the loop doesn't re-resolve them per object
            handle_delete_object_location(
                request_user, current_object.get_public_id(), locations_manager, objects_manager
            )

            # RA cascade already handled in bulk above; reuse the resolved type (skip the per-object lookup)
            objects_manager.delete_object(
                current_object.get_public_id(),
                request_user,
                AccessControlPermission.DELETE,
                object_type=current_object_type,
            )

            # Remove invalid CmdbObjectRelations since the object no longer exists
            handle_delete_invalid_object_relations(request_user, current_object.get_public_id())

            # Send deletion event to all active webhooks
            handle_notify_webhooks(request_user, current_object, WebhookEventType.DELETE)

            # Create ObjectLog of the deletion
            handle_create_object_log(request_user, current_object, LogAction.DELETE)

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
        LOGGER.error("[delete_many_cmdb_objects] ObjectsManagerDeleteError: %s", err, exc_info=True)
        abort(500, "Failed to delete the Object in the database!")
    except Exception as err:
        LOGGER.error("[delete_many_cmdb_objects] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while deleting multiple Objects!")
