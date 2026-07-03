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
Implementation of all API routes for the CmdbObjectGroups
"""
from logging import Logger, getLogger
from typing import Any

from flask import request, abort
from werkzeug import Response
from werkzeug.exceptions import HTTPException

from cmdb.manager import ObjectGroupsManager
from cmdb.manager.query_builder import BuilderParameters
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType

from cmdb.models.user_model import CmdbUser
from cmdb.models.object_group_model import CmdbObjectGroup
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

from cmdb.errors.manager.object_groups_manager import (
    ObjectGroupsManagerInsertError,
    ObjectGroupsManagerGetError,
    ObjectGroupsManagerUpdateError,
    ObjectGroupsManagerDeleteError,
    ObjectGroupsManagerIterationError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

object_group_blueprint = APIBlueprint('object_group', __name__)

# ---------------------------------------------------- CRUD-CREATE --------------------------------------------------- #

@object_group_blueprint.route('/', methods=['POST'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@object_group_blueprint.protect(auth=True, right='base.framework.objectGroup.add')
@object_group_blueprint.validate(CmdbObjectGroup.SCHEMA)
def insert_cmdb_object_group(data: dict[str, Any], request_user: CmdbUser) -> Response:
    """
    HTTP `POST` route to insert an CmdbObjectGroup into the database

    Args:
        data (CmdbObjectGroup.SCHEMA): Data of the CmdbObjectGroup which should be inserted
        request_user (CmdbUser): User requesting this data

    Returns:
        InsertSingleResponse: The new CmdbObjectGroup and its public_id
    """
    try:
        object_groups_manager: ObjectGroupsManager = ManagerProvider.get_manager(
            ManagerType.OBJECT_GROUP,
            request_user
        )

        result_id: int = object_groups_manager.insert_item(data)

        created_object_group: dict[str, Any] = object_groups_manager.get_item(result_id, as_dict=True)

        if not created_object_group:
            abort(404, "Could not retrieve the created ObjectGroup from the database!")

        return InsertSingleResponse(created_object_group, result_id).make_response()
    except HTTPException as http_err:
        raise http_err
    except ObjectGroupsManagerInsertError as err:
        LOGGER.error("[insert_cmdb_object_group] ObjectGroupsManagerInsertError: %s", err, exc_info=True)
        abort(400, "Could not insert the new ObjectGroup in the database!")
    except ObjectGroupsManagerGetError as err:
        LOGGER.error("[insert_cmdb_object_group] ObjectGroupsManagerGetError: %s", err, exc_info=True)
        abort(400, "Failed to retrieve the created ObjectGroup from the database!")
    except Exception as err:
        LOGGER.error("[insert_cmdb_object_group] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while creating the ObjectGroup!")

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

@object_group_blueprint.route('/', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@object_group_blueprint.protect(auth=True, right='base.framework.objectGroup.view')
@object_group_blueprint.parse_collection_parameters()
def get_cmdb_object_groups(params: CollectionParameters, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route for getting multiple CmdbObjectGroups

    Args:
        params (CollectionParameters): Filter for requested CmdbObjectGroups
        request_user (CmdbUser): User requesting this data

    Returns:
        GetMultiResponse: All the CmdbObjectGroups matching the CollectionParameters
    """
    try:
        body: bool = request.method == 'HEAD'

        object_groups_manager: ObjectGroupsManager = ManagerProvider.get_manager(
            ManagerType.OBJECT_GROUP,
            request_user
        )

        builder_params = BuilderParameters(**CollectionParameters.get_builder_params(params))
        iteration_result: IterationResult[CmdbObjectGroup] = object_groups_manager.iterate_items(builder_params)

        object_groups_list: list[dict[str, Any]] = [
            CmdbObjectGroup.to_json(object_group) for object_group in iteration_result.results
        ]

        api_response = GetMultiResponse(
            object_groups_list,
            iteration_result.total,
            params,
            request.url,
            body
        )

        return api_response.make_response()
    except ObjectGroupsManagerIterationError as err:
        LOGGER.error("[get_cmdb_object_groups] ObjectGroupsManagerIterationError: %s", err, exc_info=True)
        abort(400, "Failed to retrieve ObjectGroups from the database!")
    except Exception as err:
        LOGGER.error("[get_cmdb_object_groups] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while retrieving the ObjectGroups!")


@object_group_blueprint.route('/<int:public_id>', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@object_group_blueprint.protect(auth=True, right='base.framework.objectGroup.view')
def get_cmdb_object_group(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route to retrieve a single CmdbObjectGroup

    Args:
        public_id (int): public_id of the CmdbObjectGroup
        request_user (CmdbUser): User requesting this data

    Returns:
        GetSingleResponse: The requested CmdbObjectGroup
    """
    try:
        object_groups_manager: ObjectGroupsManager = ManagerProvider.get_manager(
            ManagerType.OBJECT_GROUP,
            request_user
        )

        requested_object_group: dict[str, Any] | None = object_groups_manager.get_item(public_id, as_dict=True)

        if not requested_object_group:
            abort(404, f"The ObjectGroup with ID:{public_id} was not found!")

        return GetSingleResponse(requested_object_group, body = request.method == 'HEAD').make_response()
    except HTTPException as http_err:
        raise http_err
    except ObjectGroupsManagerGetError as err:
        LOGGER.error("[get_cmdb_object_group] ObjectGroupsManagerGetError: %s", err, exc_info=True)
        abort(400, f"Failed to retrieve the ObjectGroup with ID: {public_id} from the database!")
    except Exception as err:
        LOGGER.error("[get_cmdb_object_group] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while retrieving the ObjectGroup with ID:{public_id}!")

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

@object_group_blueprint.route('/<int:public_id>', methods=['PUT', 'PATCH'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@object_group_blueprint.protect(auth=True, right='base.framework.objectGroup.edit')
@object_group_blueprint.validate(CmdbObjectGroup.SCHEMA)
def update_cmdb_object_group(public_id: int, data: dict[str, Any], request_user: CmdbUser) -> Response:
    """
    HTTP `PUT`/`PATCH` route to update a single CmdbObjectGroup

    Args:
        public_id (int): public_id of the CmdbObjectGroup which should be updated
        data (CmdbObjectGroup.SCHEMA): New CmdbObjectGroup data
        request_user (CmdbUser): User requesting this data

    Returns:
        UpdateSingleResponse: The new data of the CmdbObjectGroup
    """
    try:
        object_groups_manager: ObjectGroupsManager = ManagerProvider.get_manager(
            ManagerType.OBJECT_GROUP,
            request_user
        )

        to_update_object_group: dict[str, Any] | None = object_groups_manager.get_item(public_id, as_dict=True)

        if not to_update_object_group:
            abort(404, f"The ObjectGroup with ID:{public_id} was not found!")

        # Pin the public_id from the URL so the body cannot overwrite or drop it
        data['public_id'] = public_id

        object_groups_manager.update_item(public_id, CmdbObjectGroup.from_data(data))

        return UpdateSingleResponse(data).make_response()
    except HTTPException as http_err:
        raise http_err
    except ObjectGroupsManagerGetError as err:
        LOGGER.error("[update_cmdb_object_group] ObjectGroupsManagerGetError: %s", err, exc_info=True)
        abort(400, f"Failed to retrieve the ObjectGroup with ID: {public_id} from the database!")
    except ObjectGroupsManagerUpdateError as err:
        LOGGER.error("[update_cmdb_object_group] ObjectGroupsManagerUpdateError: %s", err, exc_info=True)
        abort(400, f"Failed to update the ObjectGroup with ID: {public_id}!")
    except Exception as err:
        LOGGER.error("[update_cmdb_object_group] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while updating the ObjectGroup with ID:{public_id}!")

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

@object_group_blueprint.route('/<int:public_id>', methods=['DELETE'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@object_group_blueprint.protect(auth=True, right='base.framework.objectGroup.delete')
def delete_cmdb_object_group(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `DELETE` route to delete a single CmdbObjectGroup

    Args:
        public_id (int): public_id of the CmdbObjectGroup which should be deleted
        request_user (CmdbUser): User requesting this data

    Returns:
        DeleteSingleResponse: The deleted CmdbObjectGroup data
    """
    try:
        object_groups_manager: ObjectGroupsManager = ManagerProvider.get_manager(
            ManagerType.OBJECT_GROUP,
            request_user
        )

        to_delete_object_group: dict[str, Any] | None = object_groups_manager.get_item(public_id, as_dict=True)

        if not to_delete_object_group:
            abort(404, f"The ObjectGroup with ID:{public_id} was not found!")

        object_groups_manager.delete_with_follow_up(public_id)

        return DeleteSingleResponse(to_delete_object_group).make_response()
    except HTTPException as http_err:
        raise http_err
    except ObjectGroupsManagerDeleteError as err:
        LOGGER.error("[delete_cmdb_object_group] ObjectGroupsManagerDeleteError: %s", err, exc_info=True)
        abort(400, f"Failed to delete the ObjectGroup with ID:{public_id}!")
    except ObjectGroupsManagerGetError as err:
        LOGGER.error("[delete_cmdb_object_group] ObjectGroupsManagerGetError: %s", err, exc_info=True)
        abort(400, f"Failed to retrieve the ObjectGroup with ID:{public_id} from the database!")
    except Exception as err:
        LOGGER.error("[delete_cmdb_object_group] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while deleting the ObjectGroup with ID:{public_id}!")
