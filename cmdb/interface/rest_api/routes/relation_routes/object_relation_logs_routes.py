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
Implementation of all API routes for CmdbObjectRelationLogs

A CmdbObjectRelationLog is an append-only audit record: it is written internally by
``ObjectRelationLogsManager.build_object_relation_log`` whenever a CmdbObjectRelation is created,
edited or deleted, which is why there is no create and no update route here - only two reads and a
delete. Every route is gated by an ACL right (see ``ObjectRelationLogRight``) and requires the LOCKED
API level; the feature itself is not license-gated, matching the two relation blueprints it records

A log is as readable as the relation it records: readable while the caller may read the objects at both ends,
judged by the two type ids stamped on the log (a side with none stamped is not refused). The list leaves the other
logs out - the condition runs ahead of the client's filter - and the single read and the delete answer 404 for a
missing log, then 403 for one the caller may not read

The frontend reads the paged list and a single log (``relation-log.service.ts``) and offers the delete
behind a confirmation modal, so all three routes are live FE contract
"""
from logging import Logger, getLogger
from typing import Any

from flask import request, abort
from werkzeug import Response

from cmdb.manager import ObjectRelationLogsManager
from cmdb.manager.query_builder import BuilderParameters
from cmdb.manager.object_relations_manager import build_readable_endpoints_condition
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType

from cmdb.models.user_model import CmdbUser
from cmdb.models.log_model import CmdbObjectRelationLog
from cmdb.framework.results import IterationResult
from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.route_utils import (
    abort_if_query_too_slow,
    handle_route_errors,
    insert_request_user,
    verify_api_access,
)
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.rest_api.responses.response_parameters import CollectionParameters
from cmdb.interface.rest_api.responses import (
    GetMultiResponse,
    GetSingleResponse,
    DeleteSingleResponse,
)

from cmdb.interface.rest_api.routes.relation_routes.relation_constants import (
    OBJECT_RELATION_LOG_NOT_FOUND_MESSAGE,
    ObjectRelationLogRight,
)
from cmdb.interface.rest_api.routes.relation_routes.relations_helper import (
    build_readable_object_relation_criteria,
    read_object_relation_log_or_abort,
    resolve_unreadable_type_ids_or_abort,
)
from cmdb.interface.rest_api.routes.routes_helper import request_wants_body

from cmdb.errors.manager import BaseManagerDeleteError
from cmdb.errors.manager.object_relation_logs_manager import (
    ObjectRelationLogsManagerIterationError,
    ObjectRelationLogsManagerGetError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

object_relation_logs_blueprint = APIBlueprint('object_relation_logs', __name__)

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

@object_relation_logs_blueprint.route('/', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@object_relation_logs_blueprint.protect(auth=True, right=ObjectRelationLogRight.VIEW.value)
@object_relation_logs_blueprint.parse_collection_parameters()
@handle_route_errors("while iterating ObjectRelationLogs")
def get_cmdb_object_relation_logs(params: CollectionParameters, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route for getting multiple CmdbObjectRelationLogs

    Requires the ``base.framework.objectRelationLog.view`` right. Only the logs whose two objects the caller may
    read are listed, and the total counts only those

    Args:
        params (CollectionParameters): Filter for requested CmdbObjectRelationLogs
        request_user (CmdbUser): CmdbUser requesting this data

    Raises:
        HTTPException: 403 when the user lacks the right; 400 when the iteration fails or the types the
            user may not read could not be resolved; 500 on an unexpected error

    Returns:
        GetMultiResponse: The readable CmdbObjectRelationLogs matching the CollectionParameters
    """
    try:
        object_relation_logs_manager: ObjectRelationLogsManager = ManagerProvider.get_manager(
            ManagerType.OBJECT_RELATION_LOGS,
            request_user,
        )

        denied_type_ids: list[int] = resolve_unreadable_type_ids_or_abort(request_user)

        builder_params = BuilderParameters(**CollectionParameters.get_builder_params(params))

        readable_condition: dict[str, Any] = build_readable_endpoints_condition(denied_type_ids)

        if readable_condition:
            builder_params.add_criteria(readable_condition)

        iteration_result: IterationResult[CmdbObjectRelationLog] = object_relation_logs_manager.iterate(builder_params)

        object_relation_logs_list = [CmdbObjectRelationLog.to_json(object_relation_log) for
                                     object_relation_log in iteration_result.results]

        api_response = GetMultiResponse(object_relation_logs_list,
                                        total=iteration_result.total,
                                        params=params,
                                        url=request.url,
                                        body=request_wants_body())

        return api_response.make_response()
    except ObjectRelationLogsManagerIterationError as err:
        abort_if_query_too_slow(err)
        LOGGER.error("[get_cmdb_object_relation_logs] %s", err, exc_info=True)
        abort(400, "Failed to retrieve ObjectRelationLogs from database!")


@object_relation_logs_blueprint.route('/<int:public_id>', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@object_relation_logs_blueprint.protect(auth=True, right=ObjectRelationLogRight.VIEW.value)
@handle_route_errors("while retrieving ObjectRelationLog with ID:{public_id}")
def get_cmdb_object_relation_log(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route to retrieve a single CmdbObjectRelationLog

    Requires the ``base.framework.objectRelationLog.view`` right

    Args:
        public_id (int): public_id of the CmdbObjectRelationLog
        request_user (CmdbUser): User requesting this data

    Raises:
        HTTPException: 403 when the user lacks the right or may not read one of the logged relation's two
            objects; 404 when no CmdbObjectRelationLog carries the public_id; 400 when the read fails or the
            types the user may not read could not be resolved; 500 on an unexpected error

    Returns:
        GetSingleResponse: The requested CmdbObjectRelationLog
    """
    try:
        object_relation_logs_manager: ObjectRelationLogsManager = ManagerProvider.get_manager(
            ManagerType.OBJECT_RELATION_LOGS,
            request_user,
        )

        denied_type_ids: list[int] = resolve_unreadable_type_ids_or_abort(request_user)

        requested_object_relation_log: dict[str, Any] = read_object_relation_log_or_abort(
            object_relation_logs_manager, public_id, denied_type_ids,
        )

        return GetSingleResponse(requested_object_relation_log, body=request_wants_body()).make_response()
    except ObjectRelationLogsManagerGetError as err:
        LOGGER.error("[get_cmdb_object_relation_log] %s", err, exc_info=True)
        abort(400, f"Failed to retrieve the ObjectRelationLog with ID: {public_id} from the database!")

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

@object_relation_logs_blueprint.route('/<int:public_id>', methods=['DELETE'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@object_relation_logs_blueprint.protect(auth=True, right=ObjectRelationLogRight.DELETE.value)
@handle_route_errors("while deleting the ObjectRelationLog with ID:{public_id}")
def delete_object_relation_log(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `DELETE` route to delete a single CmdbObjectRelationLog

    Requires the ``base.framework.objectRelationLog.delete`` right. A log the caller may not read is refused
    before anything is deleted, and the delete itself is one atomic read-and-delete, so the response hands back
    exactly the document this request removed

    Args:
        public_id (int): public_id of the CmdbObjectRelationLog which should be deleted
        request_user (CmdbUser): CmdbUser requesting this data

    Raises:
        HTTPException: 403 when the user lacks the right or may not read one of the logged relation's two
            objects; 404 when no CmdbObjectRelationLog carries the public_id (also when another request
            deleted it first); 400 when the read or the deletion fails or the types the user may not read
            could not be resolved; 500 on an unexpected error

    Returns:
        DeleteSingleResponse: The deleted CmdbObjectRelationLog data
    """
    try:
        object_relation_logs_manager: ObjectRelationLogsManager = ManagerProvider.get_manager(
            ManagerType.OBJECT_RELATION_LOGS,
            request_user,
        )

        denied_type_ids: list[int] = resolve_unreadable_type_ids_or_abort(request_user)

        read_object_relation_log_or_abort(object_relation_logs_manager, public_id, denied_type_ids)

        deleted_object_relation_log: dict[str, Any] | None = object_relation_logs_manager.find_one_and_delete(
            build_readable_object_relation_criteria(public_id, denied_type_ids)
        )

        if deleted_object_relation_log is None:
            abort(404, OBJECT_RELATION_LOG_NOT_FOUND_MESSAGE.format(public_id=public_id))

        return DeleteSingleResponse(raw=deleted_object_relation_log).make_response()
    except BaseManagerDeleteError as err:
        LOGGER.error("[delete_object_relation_log] %s", err, exc_info=True)
        abort(400, f"Failed to delete the ObjectRelationLog with ID:{public_id}!")
    except ObjectRelationLogsManagerGetError as err:
        LOGGER.error("[delete_object_relation_log] %s", err, exc_info=True)
        abort(400, f"Failed to retrieve the ObjectRelationLog ID:{public_id} from the database!")
