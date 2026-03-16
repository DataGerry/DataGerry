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
Implementation of all API routes for CmdbUserGroups
"""
from logging import Logger, getLogger
from typing import Any
from flask import request, abort
from werkzeug import Response
from werkzeug.exceptions import HTTPException

from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.manager.query_builder import BuilderParameters
from cmdb.manager import (
    GroupsManager,
    UsersManager,
)

from cmdb.framework.results import IterationResult
from cmdb.models.group_model import CmdbUserGroup, GroupDeleteMode
from cmdb.models.user_model import CmdbUser
from cmdb.models.right_model.all_rights import flat_rights_tree, ALL_RIGHTS
from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.rest_api.responses.response_parameters import (
    GroupDeletionParameters,
    CollectionParameters,
)
from cmdb.interface.route_utils import insert_request_user, verify_api_access
from cmdb.interface.rest_api.api_level_enum import ApiLevel

from cmdb.interface.rest_api.responses import (
    DeleteSingleResponse,
    UpdateSingleResponse,
    InsertSingleResponse,
    GetMultiResponse,
    GetSingleResponse,
)

from cmdb.errors.manager.groups_manager import (
    GroupsManagerDeleteError,
    GroupsManagerGetError,
    GroupsManagerInsertError,
    GroupsManagerIterationError,
    GroupsManagerUpdateError,
)
from cmdb.manager.users_manager import (
    UsersManagerGetError,
    UsersManagerUpdateError,
    UsersManagerDeleteError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

groups_blueprint = APIBlueprint('groups', __name__)

# --------------------------------------------------- CRUD - CREATE -------------------------------------------------- #

@groups_blueprint.route('/', methods=['POST'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@groups_blueprint.protect(auth=True, right='base.user-management.group.add')
@groups_blueprint.validate(CmdbUserGroup.SCHEMA)
def insert_cmdb_user_group(data: dict[str, Any], request_user: CmdbUser) -> Response:
    """
    HTTP `POST` to insert a single CmdbUserGroup

    Args:
        data (CmdbUserGroup.SCHEMA): Data of the new CmdbUserGroup

    Returns:
        InsertSingleResponse: The public_id and the newly created CmdbUserGroup
    """
    try:
        groups_manager: GroupsManager = ManagerProvider.get_manager(ManagerType.GROUPS, request_user)

        result_id: int = groups_manager.insert_group(data)

        created_group: CmdbUserGroup = groups_manager.get_group(result_id)

        if not created_group:
            abort(404, "Could not retrieve the created UserGroup from the database!")

        return InsertSingleResponse(CmdbUserGroup.to_json(created_group), result_id).make_response()
    except HTTPException as http_err:
        raise http_err
    except GroupsManagerInsertError as err:
        LOGGER.error("[insert_cmdb_user_group] %s", err, exc_info=True)
        abort(400, "Failed to insert the new UserGroup in the database!")
    except GroupsManagerGetError as err:
        LOGGER.error("[insert_cmdb_user_group] %s", err, exc_info=True)
        abort(400, "Failed to retrieve the created UserGroup from the database!")
    except Exception as err:
        LOGGER.error("[insert_cmdb_user_group] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while creating the new UserGroup!")

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

@groups_blueprint.route('/', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@groups_blueprint.protect(auth=True, right='base.user-management.group.view')
@groups_blueprint.parse_collection_parameters()
def get_cmdb_user_groups(params: CollectionParameters, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route for getting multiple CmdbUserGroups

    Args:
        params (CollectionParameters): Filter for requested CmdbUserGroups

    Returns:
        GetMultiResponse: All the CmdbUserGroups matching the CollectionParameters
    """
    try:
        groups_manager: GroupsManager = ManagerProvider.get_manager(ManagerType.GROUPS, request_user)

        builder_params = BuilderParameters(**CollectionParameters.get_builder_params(params))

        iteration_result: IterationResult[CmdbUserGroup] = groups_manager.iterate(builder_params)
        groups: list[dict[str, Any]] = [CmdbUserGroup.to_json(group) for group in iteration_result.results]

        api_response = GetMultiResponse(
            groups,
            total=iteration_result.total,
            params=params,
            url=request.url,
            body=request.method == 'HEAD'
        )

        return api_response.make_response()
    except GroupsManagerIterationError as err:
        LOGGER.error("[get_cmdb_user_groups] %s", err, exc_info=True)
        abort(400, "Failed to iterate the UserGroups!")
    except Exception as err:
        LOGGER.error("[get_cmdb_user_groups] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while iterating UserGroups!")


@groups_blueprint.route('/<int:public_id>', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@groups_blueprint.protect(auth=True, right='base.user-management.group.view')
def get_cmdb_user_group(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route to retrieve a single CmdbUserGroup

    Args:
        public_id (int): public_id of the requested CmdbUserGroup

    Returns:
        GetSingleResponse: The requested CmdbUserGroup
    """
    try:
        groups_manager: GroupsManager = ManagerProvider.get_manager(ManagerType.GROUPS, request_user)

        requested_group: CmdbUserGroup | None = groups_manager.get_group(public_id)

        if not requested_group:
            abort(404, f"The UserGroup with ID:{public_id} was not found!")

        return GetSingleResponse(
            CmdbUserGroup.to_json(requested_group),
            body=request.method == 'HEAD'
        ).make_response()
    except HTTPException as http_err:
        raise http_err
    except GroupsManagerGetError as err:
        LOGGER.error("[get_cmdb_user_group] %s", err, exc_info=True)
        abort(400, f"Failed to retrieve the UserGroup with ID:{public_id}!")
    except Exception as err:
        LOGGER.error("[get_cmdb_user_group] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while retrieving UserGroup with ID:{public_id}!")

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

@groups_blueprint.route('/<int:public_id>', methods=['PUT', 'PATCH'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@groups_blueprint.protect(auth=True, right='base.user-management.group.edit')
@groups_blueprint.validate(CmdbUserGroup.SCHEMA)
def update_cmdb_user_group(public_id: int, data: dict[str, Any], request_user: CmdbUser) -> Response:
    """
    HTTP `PUT`/`PATCH` route fto update a single CmdbUserGroup

    Args:
        public_id (int): public_id of the CmdbUserGroup which should be updated
        data (CmdbUserGroup.SCHEMA): New version for the CmdbUserGroup

    Returns:
        UpdateSingleResponse: The new version of the CmdbUserGroup
    """
    try:
        groups_manager: GroupsManager = ManagerProvider.get_manager(ManagerType.GROUPS, request_user)

        to_update_group: CmdbUserGroup = groups_manager.get_group(public_id)

        if not to_update_group:
            abort(404, f"The UserGroup with ID:{public_id} was not found!")

        group: CmdbUserGroup = CmdbUserGroup.from_data(data=data, rights=flat_rights_tree(ALL_RIGHTS))
        group_dict: dict[str, Any] = CmdbUserGroup.to_json(group)
        group_dict['rights'] = [right.get('name') for right in group_dict.get('rights', [])]

        groups_manager.update_group(public_id, group_dict)

        return UpdateSingleResponse(group_dict).make_response()
    except HTTPException as http_err:
        raise http_err
    except GroupsManagerUpdateError as err:
        LOGGER.error("[update_cmdb_user_group] %s", err, exc_info=True)
        abort(400, f"User group with public_id:{public_id} could not be updated!")
    except GroupsManagerGetError as err:
        LOGGER.error("[update_cmdb_user_group] %s", err, exc_info=True)
        abort(400, f"Failed to retrieve the UserGroup with ID:{public_id}!")
    except Exception as err:
        LOGGER.error("[update_cmdb_user_group] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while updating the UserGroup with ID:{public_id}!")

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

@groups_blueprint.route('/<int:public_id>', methods=['DELETE'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@groups_blueprint.protect(auth=True, right='base.user-management.group.delete')
@groups_blueprint.parse_parameters(GroupDeletionParameters)
def delete_cmdb_user_group(public_id: int, params: GroupDeletionParameters, request_user: CmdbUser) -> Response:
    """
    HTTP `DELETE` route to delete a single CmdbUserGroup

    Args:
        public_id (int): public_id of the CmdbUserGroup
        params (GroupDeletionParameters): Optional action parameters for handling users when the group is deleted

    Returns:
        DeleteSingleResponse: The deleted CmdbUserGroup
    """
    try:
        groups_manager: GroupsManager = ManagerProvider.get_manager(ManagerType.GROUPS, request_user)
        users_manager: UsersManager = ManagerProvider.get_manager(ManagerType.USERS, request_user)

        to_delete_group: CmdbUserGroup | None = groups_manager.get_group(public_id)

        if not to_delete_group:
            abort(404, f"The UserGroup with ID:{public_id} was not found!")

        if GroupDeleteMode.MOVE and not params.group_id:
            abort(404, "The target group for moving users was not provided!")

        target_group: CmdbUserGroup | None = groups_manager.get_group(params.group_id)

        if not target_group:
            abort(404, f"The target UserGroup for moving users with ID:{params.group_id} was not found!")

        if GroupDeleteMode.DELETE:
            admin_user = users_manager.get_one_by({
                "group_id": public_id,
                "public_id": 1
            })

            if admin_user:
                raise UsersManagerDeleteError("This Group can not be deleted because the admin user is part of it!")

        if params.action is not None:
            users_manager.handle_users_on_group_delete(public_id, params.action, params.group_id)

        groups_manager.delete_group(public_id)

        return DeleteSingleResponse(CmdbUserGroup.to_json(to_delete_group)).make_response()
    except HTTPException as http_err:
        raise http_err
    except UsersManagerDeleteError as err:
        LOGGER.error("[delete_user_group]  UsersManagerDeleteError: %s", err, exc_info=True)
        abort(500, 'Failed to delete User from Group!')
    except UsersManagerUpdateError as err:
        LOGGER.error("[delete_cmdb_user_group] UsersManagerUpdateError: %s", err, exc_info=True)
        abort(400, f"Failed to move User to Group with ID: {params.group_id}!")
    except UsersManagerGetError as err:
        LOGGER.error("[delete_cmdb_user_group] UsersManagerGetError: %s", err, exc_info=True)
        abort(400, f"Failed to retrieve users which are in the UserGroup with ID: {public_id}!")
    except GroupsManagerDeleteError as err:
        LOGGER.error("[delete_cmdb_user_group] GroupsManagerDeleteError: %s", err, exc_info=True)
        abort(400, f"Failed to delete the UserGroup with ID: {public_id}!")
    except GroupsManagerGetError as err:
        LOGGER.error("[update_cmdb_user_group] GroupsManagerGetError: %s", err, exc_info=True)
        abort(400, f"Failed to retrieve the UserGroup with ID:{public_id}!")
    except Exception as err:
        LOGGER.error("[delete_cmdb_user_group] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while deleting the UserGroup with ID:{public_id}!")
