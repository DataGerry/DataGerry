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
Implementation of all API routes for CmdbRelations
"""
import logging
from typing import Any
from flask import request, abort
from werkzeug import Response
from werkzeug.exceptions import HTTPException

from cmdb.manager import RelationsManager, ObjectRelationsManager
from cmdb.manager.query_builder import BuilderParameters
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType

from cmdb.models.user_model import CmdbUser
from cmdb.models.relation_model import CmdbRelation
from cmdb.models.object_relation_model import CmdbObjectRelation
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

from cmdb.errors.manager.relations_manager import (
    RelationsManagerInsertError,
    RelationsManagerGetError,
    RelationsManagerIterationError,
    RelationsManagerUpdateError,
    RelationsManagerDeleteError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER = logging.getLogger(__name__)

relations_blueprint = APIBlueprint('relations', __name__)

# ---------------------------------------------------- CRUD-CREATE --------------------------------------------------- #

@relations_blueprint.route('/', methods=['POST'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@relations_blueprint.protect(auth=True, right='base.framework.relation.add')
@relations_blueprint.validate(CmdbRelation.SCHEMA)
def insert_cmdb_relation(data: dict[str, Any], request_user: CmdbUser) -> Response:
    """
    HTTP `POST` route to insert a CmdbRelation into the database

    Args:
        data (CmdbRelation.SCHEMA): Data of the CmdbRelation which should be inserted
        request_user (CmdbUser): User requesting this data

    Returns:
        InsertSingleResponse: The new CmdbRelation and its public_id
    """
    try:
        relations_manager: RelationsManager = ManagerProvider.get_manager(ManagerType.RELATIONS,
                                                                           request_user)

        result_id: int = relations_manager.insert_relation(data)

        created_relation: dict = relations_manager.get_relation(result_id)

        if created_relation:
            return InsertSingleResponse(created_relation, result_id).make_response()

        abort(404, "Could not retrieve the created Relation from the database!")
    except HTTPException as http_err:
        raise http_err
    except RelationsManagerInsertError as err:
        LOGGER.error("[insert_cmdb_relation] RelationsManagerInsertError: %s", err, exc_info=True)
        abort(400, "Failed to insert the new Relation in the database!")
    except RelationsManagerGetError as err:
        LOGGER.error("[insert_cmdb_relation] RelationsManagerGetError: %s", err, exc_info=True)
        abort(400, "Failed to retrieve the created Relation from the database!")
    except Exception as err:
        LOGGER.error("[insert_cmdb_relation] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while creating the new Relation!")

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

@relations_blueprint.route('/', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@relations_blueprint.protect(auth=True, right='base.framework.relation.view')
@relations_blueprint.parse_collection_parameters()
def get_cmdb_relations(params: CollectionParameters, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route for getting multiple CmdbRelations

    Args:
        params (CollectionParameters): Filter for requested CmdbRelations
        request_user (CmdbUser): User requesting this data

    Returns:
        GetMultiResponse: All the CmdbRelations matching the CollectionParameters
    """
    try:
        body = request.method == 'HEAD'

        relations_manager: RelationsManager = ManagerProvider.get_manager(ManagerType.RELATIONS,
                                                                          request_user)

        builder_params = BuilderParameters(**CollectionParameters.get_builder_params(params))

        iteration_result: IterationResult[CmdbRelation] = relations_manager.iterate(builder_params)
        relation_list = [CmdbRelation.to_json(relation) for relation in iteration_result.results]

        api_response = GetMultiResponse(relation_list,
                                        iteration_result.total,
                                        params,
                                        request.url,
                                        body)

        return api_response.make_response()
    except RelationsManagerIterationError as err:
        LOGGER.error("[get_cmdb_relations] RelationsManagerIterationError: %s", err, exc_info=True)
        abort(400, "Failed to retrieve Relations from the database!")
    except Exception as err:
        LOGGER.error("[get_cmdb_relations] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while iterating Relations!")


@relations_blueprint.route('/<int:public_id>', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@relations_blueprint.protect(auth=True, right='base.framework.relation.view')
def get_cmdb_relation(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route to retrieve a single CmdbRelation

    Args:
        public_id (int): public_id of the CmdbRelation
        request_user (CmdbUser): User requesting this data

    Returns:
        GetSingleResponse: The requested CmdbRelation
    """
    try:
        relations_manager: RelationsManager = ManagerProvider.get_manager(ManagerType.RELATIONS,
                                                                          request_user)

        requested_relation = relations_manager.get_relation(public_id)

        if requested_relation:
            return GetSingleResponse(requested_relation, body = request.method == 'HEAD').make_response()

        abort(404, f"The Relation with ID:{public_id} was not found!")
    except HTTPException as http_err:
        raise http_err
    except RelationsManagerGetError as err:
        LOGGER.error("[get_cmdb_relation] RelationsManagerGetError: %s", err, exc_info=True)
        abort(400, f"Failed to retrieve the Relation with ID: {public_id} from the database!")
    except Exception as err:
        LOGGER.error("[get_cmdb_relation] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while retrieving Relation with ID: {public_id}!")

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

@relations_blueprint.route('/<int:public_id>', methods=['PUT', 'PATCH'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@relations_blueprint.protect(auth=True, right='base.framework.relation.edit')
@relations_blueprint.validate(CmdbRelation.SCHEMA)
def update_cmdb_relation(public_id: int, data: dict[str, Any], request_user: CmdbUser) -> Response:
    """
    HTTP `PUT`/`PATCH` route to update a single CmdbRelation

    Args:
        public_id (int): public_id of the CmdbRelation which should be updated
        data (CmdbRelation.SCHEMA): New CmdbRelation data
        request_user (CmdbUser): User requesting this data

    Returns:
        UpdateSingleResponse: The new data of the CmdbRelation
    """
    try:
        relations_manager: RelationsManager = ManagerProvider.get_manager(ManagerType.RELATIONS,
                                                                          request_user)
        object_relations_manager: ObjectRelationsManager = ManagerProvider.get_manager(
                                                                                ManagerType.OBJECT_RELATIONS,
                                                                                request_user)

        to_update_relation = relations_manager.get_relation(public_id)

        if to_update_relation:
            handle_deleted_type_ids(to_update_relation, data, object_relations_manager)

            changed_fields: dict = relations_manager.get_added_and_removed_fields(to_update_relation, data)

            object_relations_manager.update_changed_fields(public_id, changed_fields)

            relation: CmdbRelation = CmdbRelation.from_data(data)

            relations_manager.update_relation(public_id, relation)

            return UpdateSingleResponse(data).make_response()

        abort(404, f"The Relation with ID:{public_id} was not found!")
    except HTTPException as http_err:
        raise http_err
    except RelationsManagerGetError as err:
        LOGGER.error("[update_cmdb_relation] RelationsManagerGetError: %s", err, exc_info=True)
        abort(400, f"Failed to retrieve the Relation with ID: {public_id} from the database!")
    except RelationsManagerUpdateError as err:
        LOGGER.error("[update_cmdb_relation] RelationsManagerUpdateError: %s", err, exc_info=True)
        abort(400, f"Failed to update the Relation with ID: {public_id}!")
    except Exception as err:
        LOGGER.error("[update_cmdb_relation] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while updating Relation with ID: {public_id}!")

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

@relations_blueprint.route('/<int:public_id>', methods=['DELETE'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@relations_blueprint.protect(auth=True, right='base.framework.relation.delete')
def delete_cmdb_relation(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `DELETE` route to delete a single CmdbRelation

    Args:
        public_id (int): public_id of the CmdbRelation which should be deleted
        request_user (CmdbUser): User requesting this data

    Returns:
        DeleteSingleResponse: The deleted CmdbRelation data
    """
    try:
        relations_manager: RelationsManager = ManagerProvider.get_manager(ManagerType.RELATIONS,
                                                                           request_user)

        to_delete_relation = relations_manager.get_relation(public_id)

        if not to_delete_relation:
            abort(404, f"The Relation with ID:{public_id} was not found!")

        # Check if the CmdbRelation is currently used
        if relations_manager.get_one_by({"relation_id": public_id}, CmdbObjectRelation.COLLECTION):
            abort(403, f"The Relation with ID:{public_id} is currently in use and cannot be deleted!")

        relations_manager.delete_relation(public_id)

        return DeleteSingleResponse(raw=to_delete_relation).make_response()
    except HTTPException as http_err:
        raise http_err
    except RelationsManagerDeleteError as err:
        LOGGER.error("[delete_cmdb_relation] RelationsManagerDeleteError: %s", err, exc_info=True)
        abort(400, f"Failed to delete the Relation with ID:{public_id}!")
    except RelationsManagerGetError as err:
        LOGGER.error("[delete_cmdb_relation] RelationsManagerGetError: %s", err, exc_info=True)
        abort(400, f"Failed to retrieve the Relation with ID:{public_id} from the database!")
    except Exception as err:
        LOGGER.error("[delete_cmdb_relation] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while deleting Relation with ID:{public_id}!")

# -------------------------------------------------- HELPER METHODS -------------------------------------------------- #

def handle_deleted_type_ids(old_relation: dict,
                            new_relation: dict,
                            object_relations_manager: ObjectRelationsManager) -> None:
    """
    Checks if the allowed parent and child CmdbTypes have changed especially if some were deleted.
    If some of them were deleted then all corresponding ObjectRelations will be deleted.

    Args:
        old_relation (dict): old relation data
        new_relation (dict): new relation data
        object_relations_manager (ObjectRelationsManager): Database interaction for CmdbObjectRelations
    """
    deleted_parent_ids = get_deleted_type_ids(old_relation["parent_type_ids"], new_relation["parent_type_ids"])

    if deleted_parent_ids:
        object_relations_manager.delete_invalidated_object_relations(old_relation["public_id"],
                                                                     deleted_parent_ids,
                                                                     True)

    deleted_child_ids = get_deleted_type_ids(old_relation["child_type_ids"], new_relation["child_type_ids"])

    if deleted_child_ids:
        object_relations_manager.delete_invalidated_object_relations(old_relation["public_id"],
                                                                     deleted_child_ids,
                                                                     False)


def get_deleted_type_ids(old_ids: list[int], new_ids: list[int]) -> list[int]:
    """
    Identifies the IDs that have been deleted when comparing two lists

    Args:
        old_ids (list[int]): The previous list of IDs
        new_ids (list[int]): The updated list of IDs

    Returns:
        list[int]: A list containing the deleted IDs
    """
    return list(set(old_ids) - set(new_ids))
