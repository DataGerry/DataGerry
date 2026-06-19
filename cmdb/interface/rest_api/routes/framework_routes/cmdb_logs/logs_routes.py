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
REST API endpoints for the ``/logs`` resource (CmdbObjectLog read + delete)

Exposes the single-log read, the list endpoints (logs by object, deleted-action logs, and the
object-still-exists vs object-deleted split via the framework.objects join) plus the
corresponding-edit-log lookup and single-log delete. Every handler delegates its query work to
``LogsManager``; the list handlers share ``logs_helper.build_object_logs_response``.
"""
from logging import Logger, getLogger
from typing import Any
from flask import request, abort
from werkzeug import Response
from werkzeug.exceptions import HTTPException

from cmdb.manager.query_builder import BuilderParameters
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.manager import LogsManager

from cmdb.models.user_model import CmdbUser
from cmdb.models.log_model.log_action_enum import LogAction
from cmdb.models.log_model.cmdb_object_log import CmdbObjectLog
from cmdb.interface.route_utils import insert_request_user, verify_api_access
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.rest_api.responses import DefaultResponse
from cmdb.interface.rest_api.responses.response_parameters import CollectionParameters
from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.rest_api.routes.framework_routes.cmdb_logs.logs_constants import (
    LogRight,
    LogKey,
    LogQueryOperator,
)
from cmdb.interface.rest_api.routes.framework_routes.cmdb_logs.logs_helper import build_object_logs_response

from cmdb.errors.manager import BaseManagerIterationError, BaseManagerGetError, BaseManagerDeleteError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

logs_blueprint = APIBlueprint('logs', __name__)

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

@logs_blueprint.route('/<int:public_id>', methods=['GET'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@logs_blueprint.protect(auth=True, right=LogRight.VIEW.value)
def get_log(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `GET` route to retrieve a single log by its public_id

    Args:
        public_id (int): public_id of the requested log
        request_user (CmdbUser): User requesting this data

    Raises:
        HTTPException: 404 if no log has the given public_id, 400 on a database read error,
                       500 on any unexpected failure

    Returns:
        Response: A DefaultResponse wrapping the requested log document
    """
    try:
        logs_manager: LogsManager = ManagerProvider.get_manager(ManagerType.LOGS, request_user)

        requested_log: dict[str, Any] = logs_manager.get_one(public_id)

        if not requested_log:
            abort(404, f"The Log with ID:{public_id} was not found!")

        return DefaultResponse(requested_log).make_response()
    except HTTPException as http_err:
        raise http_err
    except BaseManagerGetError as err:
        LOGGER.error("[get_log] BaseManagerGetError: %s", err, exc_info=True)
        abort(400, "Failed to retrieve the requested log from database!")
    except Exception as err:
        LOGGER.error("[get_log] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured when trying to retrieve the Log with ID:{public_id}!")


@logs_blueprint.route('/object/exists', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@logs_blueprint.protect(auth=True, right=LogRight.VIEW.value)
@logs_blueprint.parse_collection_parameters()
def get_logs_with_existing_objects(params: CollectionParameters, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route for object logs whose referenced object still exists

    Args:
        params (CollectionParameters): Pagination/sort parameters for the query
        request_user (CmdbUser): User requesting this data

    Raises:
        HTTPException: 400 on a database iteration error, 500 on any unexpected failure

    Returns:
        Response: A GetMultiResponse with the object logs whose object still exists
    """
    try:
        logs_manager: LogsManager = ManagerProvider.get_manager(ManagerType.LOGS, request_user)

        query = logs_manager.query_builder.prepare_log_query()

        return build_object_logs_response(logs_manager, query, params, request)
    except BaseManagerIterationError as err:
        LOGGER.debug("[get_logs_with_existing_objects] BaseManagerIterationError: %s", err, exc_info=True)
        abort(400, "Failed to retrieve existing ObjectLogs from database!")
    except Exception as err:
        LOGGER.error("[get_logs_with_existing_objects] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured when trying to retrieve existing ObjectLogs!")


@logs_blueprint.route('/object/notexists', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@logs_blueprint.protect(auth=True, right=LogRight.VIEW.value)
@logs_blueprint.parse_collection_parameters()
def get_logs_with_deleted_objects(params: CollectionParameters, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route for object logs whose referenced object has been deleted

    Args:
        params (CollectionParameters): Pagination/sort parameters for the query
        request_user (CmdbUser): User requesting this data

    Raises:
        HTTPException: 400 on a database iteration error, 500 on any unexpected failure

    Returns:
        Response: A GetMultiResponse with the object logs whose object no longer exists
    """
    try:
        logs_manager: LogsManager = ManagerProvider.get_manager(ManagerType.LOGS, request_user)

        query = logs_manager.query_builder.prepare_log_query(False)

        return build_object_logs_response(logs_manager, query, params, request)
    except BaseManagerIterationError as err:
        LOGGER.debug("[get_logs_with_deleted_objects]BaseManagerIterationError: %s", err, exc_info=True)
        abort(400, "Failed to retrieve Logs of deleted Objects from database!")
    except Exception as err:
        LOGGER.error("[get_logs_with_deleted_objects] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured when trying to retrieve Logs of deleted Objects!")


@logs_blueprint.route('/object/deleted', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@logs_blueprint.protect(auth=True, right=LogRight.VIEW.value)
@logs_blueprint.parse_collection_parameters()
def get_object_delete_logs(params: CollectionParameters, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route for logs recording an object deletion (action DELETE)

    Args:
        params (CollectionParameters): Pagination/sort parameters for the query
        request_user (CmdbUser): User requesting this data

    Raises:
        HTTPException: 400 on a database iteration error, 500 on any unexpected failure

    Returns:
        Response: A GetMultiResponse with the object logs whose action is DELETE
    """
    try:
        logs_manager: LogsManager = ManagerProvider.get_manager(ManagerType.LOGS, request_user)

        query: dict[str, Any] = {
            LogKey.LOG_TYPE.value: CmdbObjectLog.__name__,
            LogKey.ACTION.value: LogAction.DELETE.value,
        }

        return build_object_logs_response(logs_manager, query, params, request)
    except BaseManagerIterationError as err:
        LOGGER.debug("[get_object_delete_logs] BaseManagerIterationError: %s", err, exc_info=True)
        abort(400, "Failed to retrieve the deleted object logs from database!")
    except Exception as err:
        LOGGER.error("[get_object_delete_logs] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured when trying to retrieve deleted object logs!")


@logs_blueprint.route('/object/<int:object_id>', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@logs_blueprint.protect(auth=True, right=LogRight.VIEW.value)
@logs_blueprint.parse_collection_parameters()
def get_logs_by_object(object_id: int, params: CollectionParameters, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route for all logs belonging to a single object

    Args:
        object_id (int): public_id of the object whose logs are requested
        params (CollectionParameters): Pagination/sort parameters for the query
        request_user (CmdbUser): User requesting this data

    Raises:
        HTTPException: 400 on a database iteration error, 500 on any unexpected failure

    Returns:
        Response: A GetMultiResponse with all logs referencing the given object_id
    """
    try:
        logs_manager: LogsManager = ManagerProvider.get_manager(ManagerType.LOGS, request_user)

        query: dict[str, Any] = {LogKey.OBJECT_ID.value: object_id}

        return build_object_logs_response(logs_manager, query, params, request)
    except BaseManagerIterationError as err:
        LOGGER.debug("[get_logs_by_object] BaseManagerIterationError: %s", err, exc_info=True)
        abort(400, f"Failed to retrieve logs for Object with ID:{object_id}!")
    except Exception as err:
        LOGGER.error("[get_logs_by_object] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while retrieving logs for Object with ID:{object_id}!")


@logs_blueprint.route('/<int:public_id>/corresponding', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@logs_blueprint.protect(auth=True, right=LogRight.VIEW.value)
def get_corresponding_object_log(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route for the other edit logs of the same object as the given log

    Looks up the source log, then returns every other EDIT log for that object (excluding the
    source log itself via the ``$nor`` clause).

    Args:
        public_id (int): public_id of the source log whose siblings are requested
        request_user (CmdbUser): User requesting this data

    Raises:
        HTTPException: 404 if the source log does not exist, 400 on a database read/iteration
                       error, 500 on any unexpected failure

    Returns:
        Response: A DefaultResponse wrapping the list of corresponding object logs
    """
    try:
        logs_manager: LogsManager = ManagerProvider.get_manager(ManagerType.LOGS, request_user)

        selected_log: dict[str, Any] = logs_manager.get_one(public_id)

        if not selected_log:
            abort(404, f"The Log with ID:{public_id} was not found!")

        query: dict[str, Any] = {
            LogKey.LOG_TYPE.value: CmdbObjectLog.__name__,
            LogKey.OBJECT_ID.value: selected_log[LogKey.OBJECT_ID.value],
            LogKey.ACTION.value: LogAction.EDIT.value,
            LogQueryOperator.NOR.value: [{
                LogKey.PUBLIC_ID.value: public_id
            }]
        }

        builder_params = BuilderParameters(query)

        logs = logs_manager.iterate(builder_params)
        corresponding_logs = [CmdbObjectLog.to_json(log) for log in logs.results]

        return DefaultResponse(corresponding_logs).make_response()
    except HTTPException as http_err:
        raise http_err
    except BaseManagerGetError as err:
        LOGGER.error("[get_corresponding_object_logs] BaseManagerGetError: %s", err, exc_info=True)
        abort(400, f"Failed to retrieve corresponding logs for ID:{public_id}!")
    except BaseManagerIterationError as err:
        LOGGER.debug("[get_corresponding_object_logs] BaseManagerIterationError: %s", err, exc_info=True)
        abort(400, f"Failed to iterate corresponding logs for ID:{public_id}!")
    except Exception as err:
        LOGGER.error("[get_corresponding_object_logs] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while retrieving corresponding logs for ID:{public_id}!")

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

@logs_blueprint.route('/<int:public_id>', methods=['DELETE'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@logs_blueprint.protect(auth=True, right=LogRight.DELETE.value)
def delete_log(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `DELETE` route to delete a single log by its public_id

    Args:
        public_id (int): public_id of the log which should be deleted
        request_user (CmdbUser): User requesting this data

    Raises:
        HTTPException: 404 if no log has the given public_id, 400 on a database read/delete error,
                       500 on any unexpected failure

    Returns:
        Response: A DefaultResponse wrapping the delete result count
    """
    try:
        logs_manager: LogsManager = ManagerProvider.get_manager(ManagerType.LOGS, request_user)

        to_delete_log: dict[str, Any] = logs_manager.get_one(public_id)

        if not to_delete_log:
            abort(404, f"The Log with ID:{public_id} was not found!")

        deleted = logs_manager.delete({LogKey.PUBLIC_ID.value: public_id})

        return DefaultResponse(deleted).make_response()
    except HTTPException as http_err:
        raise http_err
    except BaseManagerGetError as err:
        LOGGER.error("[delete_log] BaseManagerGetError: %s", err, exc_info=True)
        abort(400, f"Failed to retrieve the log with ID:{public_id} from database!")
    except BaseManagerDeleteError as err:
        LOGGER.error("[delete_log] BaseManagerDeleteError: %s", err, exc_info=True)
        abort(400, f"Failed to delete the log with the ID:{public_id}!")
    except Exception as err:
        LOGGER.debug("[delete_log] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while deleting Log with ID:{public_id}!")
