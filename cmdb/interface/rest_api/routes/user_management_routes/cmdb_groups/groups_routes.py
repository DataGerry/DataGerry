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
HTTP routes for the CmdbUserGroup resource

Five endpoints: POST / (create), GET|HEAD / (list), GET|HEAD /<id> (single), PUT|PATCH /<id>
(update), DELETE /<id> (delete with optional user-redistribution). Every endpoint requires an
authenticated user with API level ADMIN; per-route ``protect`` decorators check the matching
``base.user-management.group.*`` right. The delete endpoint additionally handles users that
belonged to the deleted group via the ``action`` + ``group_id`` query parameters
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
from cmdb.models.object_model.cmdb_object_key_enum import CmdbObjectKey
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
from cmdb.errors.manager.users_manager import (
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
    HTTP ``POST`` to insert a single CmdbUserGroup

    Validates the payload against ``CmdbUserGroup.SCHEMA`` (decorator), inserts via the
    ``GroupsManager``, and immediately re-reads the row to return the persisted form

    Status codes:
        201 CREATED: Group created; body is ``{ result_id, raw }``
        400 BAD_REQUEST: Insert failed at the manager layer
        404 NOT_FOUND: Insert succeeded but the row could not be re-read (defensive)
        500: Unexpected error

    Args:
        data (CmdbUserGroup.SCHEMA): Validated body of the new CmdbUserGroup
        request_user (CmdbUser): User making the request (injected by ``@insert_request_user``)

    Returns:
        Response: ``InsertSingleResponse`` carrying the public_id and serialized group
    """
    try:
        groups_manager: GroupsManager = ManagerProvider.get_manager(ManagerType.GROUPS, request_user)

        result_id: int = groups_manager.insert_group(data)

        created_group: CmdbUserGroup | None = groups_manager.get_group(result_id)

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
    HTTP ``GET`` / ``HEAD`` route for listing CmdbUserGroups with filter / sort / pagination

    Status codes:
        200 OK: Returns ``GetMultiResponse`` envelope ``{ results, total, count, ... }``
        400 BAD_REQUEST: Iteration failed at the manager layer
        500: Unexpected error

    Args:
        params (CollectionParameters): Filter / sort / page parameters parsed from the query string
        request_user (CmdbUser): User making the request (injected by ``@insert_request_user``)

    Returns:
        Response: ``GetMultiResponse`` envelope; body is omitted on HEAD
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
    HTTP ``GET`` / ``HEAD`` route to retrieve a single CmdbUserGroup by id

    Status codes:
        200 OK: Returns ``GetSingleResponse`` with the serialized group as ``result``
        400 BAD_REQUEST: Lookup failed at the manager layer
        404 NOT_FOUND: No group with the given public_id exists
        500: Unexpected error

    Args:
        public_id (int): public_id of the requested CmdbUserGroup
        request_user (CmdbUser): User making the request (injected by ``@insert_request_user``)

    Returns:
        Response: ``GetSingleResponse`` carrying the serialized group; body omitted on HEAD
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
    HTTP ``PUT`` / ``PATCH`` route to update a single CmdbUserGroup

    Validates the payload against ``CmdbUserGroup.SCHEMA``, pins the identity to the URL public_id
    (so a payload ``public_id`` can never rewrite the document's id), hydrates the submitted right
    names through the manager's cached right tree, then persists with ``insert_mode`` serialization
    (rights stored as name strings)

    Status codes:
        202 ACCEPTED: Update applied; body is the persisted serialization
        400 BAD_REQUEST: Lookup or update failed at the manager layer
        404 NOT_FOUND: No group with the given public_id exists
        500: Unexpected error

    Args:
        public_id (int): public_id of the CmdbUserGroup to update
        data (CmdbUserGroup.SCHEMA): Validated new payload for the group
        request_user (CmdbUser): User making the request (injected by ``@insert_request_user``)

    Returns:
        Response: ``UpdateSingleResponse`` carrying the persisted serialization
    """
    try:
        groups_manager: GroupsManager = ManagerProvider.get_manager(ManagerType.GROUPS, request_user)

        to_update_group: CmdbUserGroup | None = groups_manager.get_group(public_id)

        if not to_update_group:
            abort(404, f"The UserGroup with ID:{public_id} was not found!")

        # Pin the identity to the URL: a payload public_id can never rewrite the document's id
        data[CmdbObjectKey.PUBLIC_ID] = public_id

        group_dict: dict[str, Any] = groups_manager.hydrate_group(data)

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
    HTTP ``DELETE`` route to remove a CmdbUserGroup with optional user redistribution

    Protected bootstrap groups (admin / user group) are refused up front, before any member
    redistribution, so a rejected delete never leaves users half-moved or half-deleted.
    Delete-mode flow driven by ``params.action``:
      * ``MOVE`` — every user currently in the deleted group is reassigned to the group named
        by ``params.group_id``; that target group must exist
      * ``DELETE`` — every user currently in the deleted group is deleted alongside the group;
        the bootstrap admin user is protected and the request is refused if it would be deleted
      * ``None`` — the group is deleted without touching its members

    Status codes:
        200 OK: Deleted; body is the serialized deleted group
        400 BAD_REQUEST: Protected group, ``MOVE`` requested without a target ``group_id``, target
            lookup failed, or the admin user is a member on ``DELETE``
        404 NOT_FOUND: Source group not found, or ``MOVE`` target group not found
        500: Unexpected error

    Args:
        public_id (int): public_id of the CmdbUserGroup to delete
        params (GroupDeletionParameters): ``action`` + optional ``group_id``, parsed from the query string
        request_user (CmdbUser): User making the request (injected by ``@insert_request_user``)

    Returns:
        Response: ``DeleteSingleResponse`` carrying the serialization of the deleted group
    """
    try:
        groups_manager: GroupsManager = ManagerProvider.get_manager(ManagerType.GROUPS, request_user)
        users_manager: UsersManager = ManagerProvider.get_manager(ManagerType.USERS, request_user)

        to_delete_group: CmdbUserGroup | None = groups_manager.get_group(public_id)

        if not to_delete_group:
            abort(404, f"The UserGroup with ID:{public_id} was not found!")

        # Refuse protected bootstrap groups up front, before any user-redistribution side effects
        if groups_manager.is_protected_group(public_id):
            abort(400, f"Deletion of the UserGroup with ID:{public_id} is not allowed!")

        if params.action == GroupDeleteMode.MOVE:
            if not params.group_id:
                abort(400, "The target group for moving users was not provided!")

            target_group: CmdbUserGroup | None = groups_manager.get_group(params.group_id)

            if not target_group:
                abort(404, f"The target UserGroup for moving users with ID:{params.group_id} was not found!")

        if params.action is not None:
            users_manager.handle_users_on_group_delete(public_id, params.action, params.group_id)

        groups_manager.delete_group(public_id)

        return DeleteSingleResponse(CmdbUserGroup.to_json(to_delete_group)).make_response()
    except HTTPException as http_err:
        raise http_err
    except UsersManagerDeleteError as err:
        # The members helper raises this only as the admin-protection business rule -> 400, not 500
        LOGGER.error("[delete_cmdb_user_group] UsersManagerDeleteError: %s", err, exc_info=True)
        abort(400, "This UserGroup cannot be deleted because the admin user is part of it!")
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
        LOGGER.error("[delete_cmdb_user_group] GroupsManagerGetError: %s", err, exc_info=True)
        abort(400, f"Failed to retrieve the UserGroup with ID:{public_id}!")
    except Exception as err:
        LOGGER.error("[delete_cmdb_user_group] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while deleting the UserGroup with ID:{public_id}!")
