# DataGerry - OpenSource Enterprise CMDB
# Copyright (C) 2025 becon GmbH
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
import logging
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

LOGGER = logging.getLogger(__name__)

object_relations_blueprint = APIBlueprint('object_relations', __name__)

# ---------------------------------------------------- CRUD-CREATE --------------------------------------------------- #

@object_relations_blueprint.route('/', methods=['POST'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@object_relations_blueprint.protect(auth=True, right='base.framework.objectRelation.add')
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
                                                                               request_user
                                                                           )
        object_relation_logs_manager: ObjectRelationLogsManager = ManagerProvider.get_manager(
                                                            ManagerType.OBJECT_RELATION_LOGS,
                                                            request_user)
        relations_manager: RelationsManager = ManagerProvider.get_manager(
                                                            ManagerType.RELATIONS,
                                                            request_user)

        relation_id = data.get('relation_id')
        target_relation = relations_manager.get_relation(relation_id)

        if not target_relation:
            abort(400, f"The Relation with ID:{relation_id} does not exist anymore!")

        data.setdefault('creation_time', datetime.now(timezone.utc))

        parent_id = data.get('relation_parent_id')
        child_id = data.get('relation_child_id')

        if not parent_id or not child_id:
            abort(400, "Both 'relation_parent_id' and 'relation_child_id' must be provided!")
        if parent_id == child_id:
            abort(400, "Parent and child cannot be the same Object in an ObjectRelation!")

        result_id: int = object_relations_manager.insert_object_relation(data)

        created_object_relation = object_relations_manager.get_object_relation(result_id)

        if created_object_relation:

            try:
                object_relation_logs_manager.build_object_relation_log(
                                                LogInteraction.CREATE,
                                                request_user,
                                                None,
                                                created_object_relation
                                            )
            except (ObjectRelationLogsManagerBuildError, ObjectRelationLogsManagerInsertError) as error:
                LOGGER.error("[insert_cmdb_object_relation] Failed to create an ObjectRelationLog: %s",error,
                                                                                                       exc_info=True)

            api_response = InsertSingleResponse(created_object_relation, result_id)

            return api_response.make_response()

        abort(404, "Could not retrieve the created ObjectRelation from the database!")
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
@object_relations_blueprint.protect(auth=True, right='base.framework.objectRelation.view')
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
                                                                               request_user
                                                                           )

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
@object_relations_blueprint.protect(auth=True, right='base.framework.objectRelation.view')
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
                                                                               request_user
                                                                           )

        requested_object_relation = object_relations_manager.get_object_relation(public_id)

        if requested_object_relation:
            api_response = GetSingleResponse(requested_object_relation, body = request.method == 'HEAD')

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
@object_relations_blueprint.protect(auth=True, right='base.framework.objectRelation.edit')
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
                                                                               request_user
                                                                           )
        object_relation_logs_manager: ObjectRelationLogsManager = ManagerProvider.get_manager(
                                                            ManagerType.OBJECT_RELATION_LOGS,
                                                            request_user)
        relations_manager: RelationsManager = ManagerProvider.get_manager(
                                                            ManagerType.RELATIONS,
                                                            request_user)

        relation_id = data.get('relation_id')
        target_relation = relations_manager.get_relation(relation_id)

        if not target_relation:
            abort(400, f"The Relation with ID:{relation_id} does not exist anymore!")

        to_update_object_relation = object_relations_manager.get_object_relation(public_id)

        if to_update_object_relation:
            data['last_edit_time'] = datetime.now(timezone.utc)

            try:
                object_relation_changed = object_relation_logs_manager.check_related_object_changed(
                                                                            to_update_object_relation,
                                                                            data,
                                                                        )

                if not object_relation_changed: # Just field changes
                    object_relation_logs_manager.build_object_relation_log(
                                                    LogInteraction.EDIT,
                                                    request_user,
                                                    to_update_object_relation,
                                                    data
                                                )
                else: # Only Relation deleted and a new one created
                    object_relation_logs_manager.build_object_relation_log(
                                                    LogInteraction.DELETE,
                                                    request_user,
                                                    to_update_object_relation,
                                                    None
                                                )

                    object_relation_logs_manager.build_object_relation_log(
                                                    LogInteraction.CREATE,
                                                    request_user,
                                                    None,
                                                    data
                                                )
            except (ObjectRelationLogsManagerBuildError, ObjectRelationLogsManagerInsertError) as error:
                LOGGER.error("[insert_cmdb_object_relation] Failed to create an ObjectRelationLog: %s",error,
                                                                                                       exc_info=True)

            updated_object_relation = CmdbObjectRelation.from_data(data)

            object_relations_manager.update_object_relation(public_id, updated_object_relation)

            return UpdateSingleResponse(result=data).make_response()
        abort(404, f"The ObjectRelation with ID: {public_id} was not found!")
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
@object_relations_blueprint.protect(auth=True, right='base.framework.objectRelation.delete')
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
                                                                               request_user
                                                                           )
        object_relation_logs_manager: ObjectRelationLogsManager = ManagerProvider.get_manager(
                                                            ManagerType.OBJECT_RELATION_LOGS,
                                                            request_user)

        to_delete_object_relation = object_relations_manager.get_object_relation(public_id)

        if to_delete_object_relation:
            object_relations_manager.delete_object_relation(public_id)

            try:
                object_relation_logs_manager.build_object_relation_log(
                                                LogInteraction.DELETE,
                                                request_user,
                                                to_delete_object_relation,
                                                None
                                            )
            except (ObjectRelationLogsManagerBuildError, ObjectRelationLogsManagerInsertError) as error:
                LOGGER.error("[insert_cmdb_object_relation] Failed to create an ObjectRelationLog: %s",error,
                                                                                                       exc_info=True)

            return DeleteSingleResponse(to_delete_object_relation).make_response()
        abort(404, f"The ObjectRelation with ID: {public_id} was not found!")
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
