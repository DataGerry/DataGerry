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
Implementation of all API routes for CmdbObjectRelations
"""
from logging import Logger, getLogger
from typing import Any
from datetime import datetime, timezone

from flask import request, abort
from werkzeug import Response
from werkzeug.exceptions import HTTPException

from cmdb.manager import ObjectRelationsManager, ObjectRelationLogsManager, RelationsManager
from cmdb.manager.query_builder import BuilderParameters
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType

from cmdb.models.user_model import CmdbUser
from cmdb.models.object_relation_model import CmdbObjectRelation
from cmdb.models.log_model import LogInteraction

from cmdb.framework.results import IterationResult

from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.route_utils import insert_request_user, verify_api_access
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.rest_api.responses.response_parameters import CollectionParameters
from cmdb.interface.rest_api.responses import (
    InsertSingleResponse,
    GetMultiResponse,
    GetSingleResponse,
    UpdateSingleResponse,
    DeleteSingleResponse,
    DefaultResponse,
)

from cmdb.interface.rest_api.routes.relation_routes.relation_constants import ObjectRelationRight
from cmdb.interface.rest_api.routes.relation_routes.relations_helper import (
    get_existing_relation_or_abort,
    validate_object_relation_endpoints,
)

from cmdb.errors.manager.object_relations_manager import (
    ObjectRelationsManagerInsertError,
    ObjectRelationsManagerGetError,
    ObjectRelationsManagerIterationError,
    ObjectRelationsManagerUpdateError,
    ObjectRelationsManagerDeleteError,
)
from cmdb.errors.manager.object_relation_logs_manager import (
    ObjectRelationLogsManagerBuildError,
    ObjectRelationLogsManagerInsertError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

object_relations_blueprint = APIBlueprint('object_relations', __name__)

# Document field names of a CmdbObjectRelation payload, named so the routes do not repeat literals
RELATION_ID_FIELD: str = 'relation_id'
RELATION_PARENT_ID_FIELD: str = 'relation_parent_id'
RELATION_CHILD_ID_FIELD: str = 'relation_child_id'
AUTHOR_ID_FIELD: str = 'author_id'
CREATION_TIME_FIELD: str = 'creation_time'
LAST_EDIT_TIME_FIELD: str = 'last_edit_time'
PUBLIC_ID_FIELD: str = 'public_id'
TARGET_IDS_FIELD: str = 'target_ids'

# ---------------------------------------------------- CRUD-CREATE --------------------------------------------------- #

@object_relations_blueprint.route('/', methods=['POST'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@object_relations_blueprint.protect(auth=True, right=ObjectRelationRight.ADD.value)
@object_relations_blueprint.validate(CmdbObjectRelation.SCHEMA)
def insert_cmdb_object_relation(data: dict[str, Any], request_user: CmdbUser) -> Response:
    """
    HTTP `POST` route to insert a CmdbObjectRelation into the database

    Args:
        data (CmdbObjectRelation.SCHEMA): Data of the CmdbObjectRelation which should be inserted
        request_user (CmdbUser): User requesting this data

    Returns:
        InsertSingleResponse: The new CmdbObjectRelation and its public_id
    """
    try:
        object_relations_manager: ObjectRelationsManager = ManagerProvider.get_manager(
                                                                ManagerType.OBJECT_RELATIONS,
                                                                request_user)
        object_relation_logs_manager: ObjectRelationLogsManager = ManagerProvider.get_manager(
                                                                ManagerType.OBJECT_RELATION_LOGS,
                                                                request_user)
        relations_manager: RelationsManager = ManagerProvider.get_manager(
                                                                ManagerType.RELATIONS,
                                                                request_user)

        get_existing_relation_or_abort(relations_manager, data.get(RELATION_ID_FIELD))
        validate_object_relation_endpoints(data.get(RELATION_PARENT_ID_FIELD), data.get(RELATION_CHILD_ID_FIELD))

        # Stamp server-controlled fields: the author and creation time are never trusted from the body
        data[AUTHOR_ID_FIELD] = request_user.get_public_id()
        data[CREATION_TIME_FIELD] = datetime.now(timezone.utc)

        result_id: int = object_relations_manager.insert_object_relation(data)

        created_object_relation = object_relations_manager.get_object_relation(result_id)

        if not created_object_relation:
            abort(404, "Could not retrieve the created ObjectRelation from the database!")

        try:
            object_relation_logs_manager.build_object_relation_log(
                                            LogInteraction.CREATE,
                                            request_user,
                                            None,
                                            created_object_relation)
        except (ObjectRelationLogsManagerBuildError, ObjectRelationLogsManagerInsertError) as error:
            LOGGER.error("[insert_cmdb_object_relation] Failed to create an ObjectRelationLog: %s", error,
                         exc_info=True)

        return InsertSingleResponse(created_object_relation, result_id).make_response()
    except HTTPException as http_err:
        raise http_err
    except ObjectRelationsManagerInsertError as err:
        LOGGER.error("[insert_cmdb_object_relation] %s", err, exc_info=True)
        abort(400, "Could not insert the new ObjectRelation in the database!")
    except ObjectRelationsManagerGetError as err:
        LOGGER.error("[insert_cmdb_object_relation] %s", err, exc_info=True)
        abort(400, "Failed to retrieve the created ObjectRelation from the database!")
    except Exception as err:
        LOGGER.error("[insert_cmdb_object_relation] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while creating the ObjectRelation!")

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

@object_relations_blueprint.route('/', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@object_relations_blueprint.protect(auth=True, right=ObjectRelationRight.VIEW.value)
@object_relations_blueprint.parse_collection_parameters()
def get_cmdb_object_relations(params: CollectionParameters, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route for getting multiple CmdbObjectRelations

    Args:
        params (CollectionParameters): Filter for requested CmdbObjectRelations
        request_user (CmdbUser): User requesting this data

    Returns:
        GetMultiResponse: All the CmdbObjectRelations matching the CollectionParameters
    """
    try:
        body = request.method == 'HEAD'

        object_relations_manager: ObjectRelationsManager = ManagerProvider.get_manager(
                                                                ManagerType.OBJECT_RELATIONS,
                                                                request_user)

        builder_params = BuilderParameters(**CollectionParameters.get_builder_params(params))

        iteration_result: IterationResult[CmdbObjectRelation] = object_relations_manager.iterate(builder_params)

        object_relation_list = [CmdbObjectRelation.to_json(object_relation) for object_relation
                                in iteration_result.results]

        api_response = GetMultiResponse(object_relation_list,
                                        iteration_result.total,
                                        params,
                                        request.url,
                                        body)

        return api_response.make_response()
    except ObjectRelationsManagerIterationError as err:
        LOGGER.error("[get_cmdb_object_relations] %s", err, exc_info=True)
        abort(400, "Failed to retrieve the ObjectRelations from database!")
    except Exception as err:
        LOGGER.error("[get_cmdb_object_relations] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while iterating the ObjectRelations!")


@object_relations_blueprint.route('/<int:public_id>', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@object_relations_blueprint.protect(auth=True, right=ObjectRelationRight.VIEW.value)
def get_cmdb_object_relation(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route to retrieve a single CmdbObjectRelation

    Args:
        public_id (int): public_id of the CmdbObjectRelation
        request_user (CmdbUser): User requesting this data

    Returns:
        GetSingleResponse: The requested CmdbObjectRelation
    """
    try:
        object_relations_manager: ObjectRelationsManager = ManagerProvider.get_manager(
                                                                ManagerType.OBJECT_RELATIONS,
                                                                request_user)

        requested_object_relation = object_relations_manager.get_object_relation(public_id)

        if requested_object_relation:
            api_response = GetSingleResponse(requested_object_relation, body=request.method == 'HEAD')

            return api_response.make_response()

        abort(404, f"The ObjectRelation with ID:{public_id} was not found!")
    except HTTPException as http_err:
        raise http_err
    except ObjectRelationsManagerGetError as err:
        LOGGER.error("[get_cmdb_object_relation] %s", err, exc_info=True)
        abort(400, f"Failed to retrieve the requested ObjectRelation with ID:{public_id} from the database!")
    except Exception as err:
        LOGGER.error("[get_cmdb_object_relation] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while retrieving the ObjectRelation with ID:{public_id}!")

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

@object_relations_blueprint.route('/<int:public_id>', methods=['PUT', 'PATCH'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@object_relations_blueprint.protect(auth=True, right=ObjectRelationRight.EDIT.value)
@object_relations_blueprint.validate(CmdbObjectRelation.SCHEMA)
def update_cmdb_object_relation(public_id: int, data: dict[str, Any], request_user: CmdbUser) -> Response:
    """
    HTTP `PUT`/`PATCH` route to update a single CmdbObjectRelation

    Args:
        public_id (int): public_id of the CmdbObjectRelation which should be updated
        data (CmdbObjectRelation.SCHEMA): New CmdbObjectRelation data
        request_user (CmdbUser): User requesting this data

    Returns:
        UpdateSingleResponse: The new data of the CmdbObjectRelation
    """
    try:
        object_relations_manager: ObjectRelationsManager = ManagerProvider.get_manager(
                                                                ManagerType.OBJECT_RELATIONS,
                                                                request_user)
        object_relation_logs_manager: ObjectRelationLogsManager = ManagerProvider.get_manager(
                                                                ManagerType.OBJECT_RELATION_LOGS,
                                                                request_user)
        relations_manager: RelationsManager = ManagerProvider.get_manager(
                                                                ManagerType.RELATIONS,
                                                                request_user)

        get_existing_relation_or_abort(relations_manager, data.get(RELATION_ID_FIELD))

        to_update_object_relation = object_relations_manager.get_object_relation(public_id)

        if not to_update_object_relation:
            abort(404, f"The ObjectRelation with ID: {public_id} was not found!")

        # Preserve the original creation time and author; only stamp the edit time. Without this the
        # stored creation_time would be reset to "now" whenever the body omits it
        data[CREATION_TIME_FIELD] = to_update_object_relation.get(CREATION_TIME_FIELD)
        data[AUTHOR_ID_FIELD] = request_user.get_public_id()
        data[LAST_EDIT_TIME_FIELD] = datetime.now(timezone.utc)

        try:
            object_relation_changed = object_relation_logs_manager.check_related_object_changed(
                                                                        to_update_object_relation,
                                                                        data)

            if not object_relation_changed:  # Just field changes
                object_relation_logs_manager.build_object_relation_log(
                                                LogInteraction.EDIT,
                                                request_user,
                                                to_update_object_relation,
                                                data)
            else:  # Old relation deleted and a new one created
                object_relation_logs_manager.build_object_relation_log(
                                                LogInteraction.DELETE,
                                                request_user,
                                                to_update_object_relation,
                                                None)
                object_relation_logs_manager.build_object_relation_log(
                                                LogInteraction.CREATE,
                                                request_user,
                                                None,
                                                data)
        except (ObjectRelationLogsManagerBuildError, ObjectRelationLogsManagerInsertError) as error:
            LOGGER.error("[update_cmdb_object_relation] Failed to create an ObjectRelationLog: %s", error,
                         exc_info=True)

        object_relations_manager.update_object_relation(public_id, CmdbObjectRelation.from_data(data))

        return UpdateSingleResponse(result=data).make_response()
    except HTTPException as http_err:
        raise http_err
    except ObjectRelationsManagerGetError as err:
        LOGGER.error("[update_cmdb_object_relation] %s", err, exc_info=True)
        abort(400, f"Failed to retrieve the ObjectRelation with ID:{public_id} which should be updated!")
    except ObjectRelationsManagerUpdateError as err:
        LOGGER.error("[update_cmdb_object_relation] %s", err, exc_info=True)
        abort(400, f"Failed to update the ObjectRelation with ID:{public_id}!")
    except Exception as err:
        LOGGER.error("[update_cmdb_object_relation] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while updating ObjectRelation with ID:{public_id}!")

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

@object_relations_blueprint.route('/<int:public_id>', methods=['DELETE'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@object_relations_blueprint.protect(auth=True, right=ObjectRelationRight.DELETE.value)
def delete_cmdb_object_relation(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `DELETE` route to delete a single CmdbObjectRelation

    Args:
        public_id (int): public_id of the CmdbObjectRelation which should be deleted
        request_user (CmdbUser): User requesting this data

    Returns:
        DeleteSingleResponse: The deleted CmdbObjectRelation data
    """
    try:
        object_relations_manager: ObjectRelationsManager = ManagerProvider.get_manager(
                                                                ManagerType.OBJECT_RELATIONS,
                                                                request_user)
        object_relation_logs_manager: ObjectRelationLogsManager = ManagerProvider.get_manager(
                                                                ManagerType.OBJECT_RELATION_LOGS,
                                                                request_user)

        to_delete_object_relation = object_relations_manager.get_object_relation(public_id)

        if not to_delete_object_relation:
            abort(404, f"The ObjectRelation with ID: {public_id} was not found!")

        object_relations_manager.delete_object_relation(public_id)

        try:
            object_relation_logs_manager.build_object_relation_log(
                                            LogInteraction.DELETE,
                                            request_user,
                                            to_delete_object_relation,
                                            None)
        except (ObjectRelationLogsManagerBuildError, ObjectRelationLogsManagerInsertError) as error:
            LOGGER.error("[delete_cmdb_object_relation] Failed to create ObjectRelationLog: %s", error, exc_info=True)

        return DeleteSingleResponse(to_delete_object_relation).make_response()
    except HTTPException as http_err:
        raise http_err
    except ObjectRelationsManagerDeleteError as err:
        LOGGER.error("[delete_cmdb_object_relation] %s", err, exc_info=True)
        abort(400, f"Could not delete the ObjectRelation with ID:{public_id}!")
    except ObjectRelationsManagerGetError as err:
        LOGGER.error("[delete_cmdb_object_relation] %s", err, exc_info=True)
        abort(400, f"Failed to retrieve the ObjectRelation with ID:{public_id} from the database!")
    except Exception as err:
        LOGGER.error("[delete_cmdb_object_relation] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while deleting the ObjectRelation with ID:{public_id}!")


@object_relations_blueprint.route('/delete/many', methods=['POST'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@object_relations_blueprint.protect(auth=True, right=ObjectRelationRight.DELETE.value)
def delete_many_object_relations(request_user: CmdbUser) -> Response:
    """
    HTTP `POST` route to delete multiple CmdbObjectRelations at once

    Args:
        request_user (CmdbUser): CmdbUser which is using this route

    Returns:
        DefaultResponse: True when the matched CmdbObjectRelations were deleted
    """
    try:
        data: dict[str, Any] = request.get_json()
        target_ids: list[Any] | None = data.get(TARGET_IDS_FIELD)

        if not target_ids:
            abort(400, "No public_ids provided of ObjectRelations which should be deleted!")

        normalized_ids: list[int] = _normalize_target_ids(target_ids)

        object_relations_manager: ObjectRelationsManager = ManagerProvider.get_manager(
                                                                ManagerType.OBJECT_RELATIONS,
                                                                request_user)
        object_relation_logs_manager: ObjectRelationLogsManager = ManagerProvider.get_manager(
                                                                ManagerType.OBJECT_RELATION_LOGS,
                                                                request_user)

        # Retrieve all ObjectRelations which should be deleted
        to_delete_object_relations: list[dict[str, Any]] = object_relations_manager.find(
            criteria={PUBLIC_ID_FIELD: {"$in": normalized_ids}}
        )

        if not to_delete_object_relations:
            abort(400, "No ObjectRelations exist with these IDs!")

        # Delete all ObjectRelations with the provided target_ids
        object_relations_manager.delete_many({PUBLIC_ID_FIELD: {"$in": normalized_ids}})

        try:
            _create_deletion_logs(object_relation_logs_manager, request_user, to_delete_object_relations)
        except Exception as error:
            LOGGER.error("[delete_many_object_relations] Failed to create deletion Logs: %s", error, exc_info=True)

        return DefaultResponse(True).make_response()
    except HTTPException as http_err:
        raise http_err
    except ObjectRelationsManagerDeleteError as err:
        LOGGER.error("[delete_many_object_relations] %s", err, exc_info=True)
        abort(500, "Failed to delete the ObjectRelations!")
    except Exception as err:
        LOGGER.error("[delete_many_object_relations] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while deleting the ObjectRelations!")

# -------------------------------------------------- HELPER FUNCTIONS ------------------------------------------------ #

def _normalize_target_ids(target_ids: list[Any]) -> list[int]:
    """
    Normalises a list of public_ids from the request body into integers

    Aborts with 400 if any entry is neither an int nor a digit string.

    Args:
        target_ids (list[Any]): The raw public_ids provided in the request body

    Returns:
        list[int]: The normalised integer public_ids
    """
    normalized_ids: list[int] = []

    for tid in target_ids:
        if isinstance(tid, int):
            normalized_ids.append(tid)
        elif isinstance(tid, str) and tid.isdigit():
            normalized_ids.append(int(tid))
        else:
            abort(400, f"Invalid public_id for ObjectRelation deletion: {tid}")

    return normalized_ids


def _create_deletion_logs(object_relation_logs_manager: ObjectRelationLogsManager,
                          request_user: CmdbUser,
                          deleted_object_relations: list[dict[str, Any]]) -> None:
    """
    Creates one DELETE ObjectRelationLog per deleted CmdbObjectRelation in a single batch insert

    Args:
        object_relation_logs_manager (ObjectRelationLogsManager): Manager for the logs
        request_user (CmdbUser): The user performing the deletion
        deleted_object_relations (list[dict[str, Any]]): The CmdbObjectRelations that were deleted
    """
    logs_to_create: list[dict[str, Any]] = [
        object_relation_logs_manager.format_object_relation_log_data(
            LogInteraction.DELETE,
            request_user,
            object_relation,
            None,
        )
        for object_relation in deleted_object_relations
    ]

    if not logs_to_create:
        return

    reserved_log_ids: list[int] = object_relation_logs_manager.reserve_public_ids(len(logs_to_create))

    for log_doc, new_id in zip(logs_to_create, reserved_log_ids):
        log_doc[PUBLIC_ID_FIELD] = new_id

    object_relation_logs_manager.insert_many(logs_to_create, skip_public=True)
