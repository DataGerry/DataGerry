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
Implementation of all API routes for CmdbUsers
"""
import json
import logging
from typing import Any
from datetime import datetime, timezone
from flask import abort, request, current_app
from werkzeug import Response
from werkzeug.exceptions import HTTPException

from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.manager.query_builder import BuilderParameters
from cmdb.manager import (
    SecurityManager,
    UsersManager,
)

from cmdb.framework.results import IterationResult
from cmdb.models.user_model import CmdbUser
from cmdb.interface.route_utils import insert_request_user, verify_api_access
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.rest_api.responses.response_parameters import CollectionParameters
from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.rest_api.responses import (
    DeleteSingleResponse,
    UpdateSingleResponse,
    InsertSingleResponse,
    GetMultiResponse,
    GetSingleResponse,
)

from cmdb.errors.manager.users_manager import (
    UsersManagerGetError,
    UsersManagerInsertError,
    UsersManagerIterationError,
    UsersManagerUpdateError,
    UsersManagerDeleteError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER = logging.getLogger(__name__)

users_blueprint = APIBlueprint('users', __name__)

# --------------------------------------------------- CRUD - CREATE -------------------------------------------------- #

@users_blueprint.route('/', methods=['POST'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.SUPER_ADMIN)
@users_blueprint.protect(auth=True, right='base.user-management.user.add')
@users_blueprint.validate(CmdbUser.SCHEMA)
def insert_cmdb_user(data: dict[str, Any], request_user: CmdbUser) -> Response:
    """
    HTTP `POST` route to insert a CmdbUser into the database

    Args:
        data (CmdbUser.SCHEMA): Data of a new CmdbUser

    Returns:
        InsertSingleResponse: Insert response with the new CmdbUser and the corresponding public_id
    """
    #TODO: REFATOR-FIX (reduce complexity)
    try:
        users_manager: UsersManager = ManagerProvider.get_manager(ManagerType.USERS, request_user)
        security_manager: SecurityManager = ManagerProvider.get_manager(ManagerType.SECURITY, request_user)

        user_password = data['password']
        data['password'] = security_manager.generate_hmac(data['password'])
        data['registration_time'] = datetime.now(timezone.utc)

        try:
            if current_app.cloud_mode:
                # Confirm database is available from the request
                data['database'] = request_user.database
        except KeyError:
            abort(400, "The database of the user could not be retrieved!")

        if current_app.cloud_mode:
            # Confirm an email was provided when creating the user
            user_email = data.get('email')

            if not user_email:
                LOGGER.error("[insert_user] No email was provided!")
                abort(400, "The email is mandatory to create a new user!")

        # Check if email already exists
        try:
            if current_app.cloud_mode:
                user_with_given_email = users_manager.get_user_by({'email': user_email})

                if user_with_given_email:
                    abort(400, "The email is already in use!")
        except UsersManagerGetError:
            abort(400, "Failed to retrieve User from database!")

        if current_app.cloud_mode and current_app.local_mode:
            # Open file and check if user exists
            with open('etc/test_users.json', 'r', encoding='utf-8') as users_file:
                users_data = json.load(users_file)

                if user_email in users_data:
                    abort(400, "A user with this email already exists!")

            # Create the user in the dict
            users_data[user_email] = {
                "user_name": data["user_name"],
                "password": user_password,
                "email": data["email"],
                "database": data["database"]
            }

            with open('etc/test_users.json', 'w', encoding='utf-8') as cur_users_file:
                json.dump(users_data, cur_users_file, ensure_ascii=False, indent=4)

        result_id = users_manager.insert_user(data)

        #Confirm that user is created
        created_user = users_manager.get_user(result_id)

        if not created_user:
            abort(404, "Could not retrieve the created User from the database!")

        return InsertSingleResponse(CmdbUser.to_json(created_user), result_id).make_response()
    except HTTPException as http_err:
        raise http_err
    except UsersManagerInsertError as err:
        LOGGER.error("[insert_cmdb_user] %s", err, exc_info=True)
        abort(400, "Failed to create the User in database!")
    except UsersManagerGetError as err:
        LOGGER.error("[insert_cmdb_user] %s", err, exc_info=True)
        abort(500, "Failed to retrieve the created User from the database!")
    except Exception as err:
        LOGGER.error("[insert_cmdb_user] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while creating the new User!")

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

@users_blueprint.route('/', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@users_blueprint.protect(auth=True, right='base.user-management.user.view')
@users_blueprint.parse_collection_parameters()
def get_cmdb_users(params: CollectionParameters, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route for retrieving multiple CmdbUsers with a filter

    Args:
        params (CollectionParameters): Passed parameters over the http query string

    Returns:
        GetMultiResponse: The CmdbUsers matching the given filter
    """
    try:
        users_manager: UsersManager = ManagerProvider.get_manager(ManagerType.USERS, request_user)

        builder_params = BuilderParameters(**CollectionParameters.get_builder_params(params))

        iteration_result: IterationResult[CmdbUser] = users_manager.iterate(builder_params)
        users = [CmdbUser.to_json(user) for user in iteration_result.results]

        api_response = GetMultiResponse(users,
                                        total=iteration_result.total,
                                        params=params,
                                        url=request.url,
                                        body=request.method == 'HEAD')

        return api_response.make_response()
    except UsersManagerIterationError as err:
        LOGGER.error("[get_cmdb_users] %s", err, exc_info=True)
        abort(400, "Could not iterate the requested Users!")
    except Exception as err:
        LOGGER.error("[get_cmdb_users] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while iterating the requested Users!")


@users_blueprint.route('/<int:public_id>', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@users_blueprint.protect(auth=True, right='base.user-management.user.view', excepted={'public_id': 'public_id'})
def get_cmdb_user(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route for a single CmdbUser

    Args:
        public_id (int): public_id of the requested CmdbUser

    Returns:
        GetSingleResponse: Raw data of the requested CmdbUser
    """
    try:
        users_manager: UsersManager = ManagerProvider.get_manager(ManagerType.USERS, request_user)

        requested_user = users_manager.get_user(public_id)

        if not requested_user:
            abort(404, f"The User with ID:{public_id} was not found!")

        return GetSingleResponse(CmdbUser.to_json(requested_user), body=request.method == 'HEAD').make_response()
    except HTTPException as http_err:
        raise http_err
    except UsersManagerGetError as err:
        LOGGER.error("[get_cmdb_user] %s", err, exc_info=True)
        abort(400, f"Failed to retrieve the User with ID: {public_id}!")
    except Exception as err:
        LOGGER.error("[get_cmdb_user] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while retrieving User with ID: {public_id}!")

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

@users_blueprint.route('/<int:public_id>', methods=['PUT', 'PATCH'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.SUPER_ADMIN)
@users_blueprint.protect(auth=True, right='base.user-management.user.edit', excepted={'public_id': 'public_id'})
@users_blueprint.validate(CmdbUser.SCHEMA)
def update_cmdb_user(public_id: int, data: dict, request_user: CmdbUser) -> Response:
    """
    HTTP `PUT`/`PATCH` route to update a single CmdbUser

    Args:
        public_id (int): public_id of the CmdbUser which should be updated
        data (CmdbUser.SCHEMA): New values for the CmdbUser

    Returns:
        UpdateSingleResponse: The updated raw data of the CmdbUser
    """
    try:
        users_manager: UsersManager = ManagerProvider.get_manager(ManagerType.USERS, request_user)

        to_update_user = users_manager.get_user(public_id)
        rt = data.get('registration_time')
        if isinstance(rt, dict) and '$date' in rt:
            date_val = rt['$date']
            if isinstance(date_val, str):
                data['registration_time'] = datetime.fromisoformat(date_val.replace('Z', '+00:00'))
            elif isinstance(date_val, int):  # assuming milliseconds since epoch
                data['registration_time'] = datetime.fromtimestamp(date_val / 1000, tz=timezone.utc)
        elif isinstance(rt, str):
            data['registration_time'] = datetime.fromisoformat(rt.replace('Z', '+00:00'))

        if not to_update_user:
            abort(404, f"The User with ID:{public_id} was not found!")

        user = CmdbUser.from_data(data=data)
        users_manager.update_user(public_id, user)

        return UpdateSingleResponse(CmdbUser.to_json(user)).make_response()
    except HTTPException as http_err:
        raise http_err
    except UsersManagerUpdateError as err:
        LOGGER.error("[update_cmdb_user] %s", err, exc_info=True)
        abort(400, f"Failed to update the User with public_id: {public_id}!")
    except Exception as err:
        LOGGER.error("[update_cmdb_user] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while updating the User with ID:{public_id}!")


@users_blueprint.route('/<int:public_id>/password', methods=['PATCH'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.SUPER_ADMIN)
@users_blueprint.protect(auth=True, right='base.user-management.user.edit', excepted={'public_id': 'public_id'})
def change_cmdb_user_password(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `PATCH` route for changing the password of a CmdbUser

    Args:
        public_id (int): public_id of the CmdbUser

    Returns:
        UpdateSingleResponse: The CmdbUser with new password
    """
    try:
        users_manager: UsersManager = ManagerProvider.get_manager(ManagerType.USERS, request_user)
        security_manager: SecurityManager = ManagerProvider.get_manager(ManagerType.SECURITY, request_user)

        to_update_user = users_manager.get_user(public_id)

        if not to_update_user:
            abort(404, f"The User with ID:{public_id} was not found!")

        password = security_manager.generate_hmac(request.json.get('password'))
        to_update_user.password = password
        users_manager.update_user(public_id, to_update_user)

        return UpdateSingleResponse(CmdbUser.to_json(to_update_user)).make_response()
    except HTTPException as http_err:
        raise http_err
    except UsersManagerGetError as err:
        LOGGER.error("[change_cmdb_user_password] %s", err, exc_info=True)
        abort(400, f"Failed to retrieve the User with ID: {public_id}!")
    except UsersManagerUpdateError as err:
        LOGGER.error("[change_cmdb_user_password] %s", err, exc_info=True)
        abort(400, f"Failed to change the password for User with ID: {public_id}!")
    except Exception as err:
        LOGGER.error("[change_cmdb_user_password] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while changing the password for User with ID: {public_id}!")

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

@users_blueprint.route('/<int:public_id>', methods=['DELETE'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.SUPER_ADMIN)
@users_blueprint.protect(auth=True, right='base.user-management.user.delete')
def delete_cmdb_user(public_id: int, request_user: CmdbUser) -> Response:
    """
    HTTP `DELETE` route to delete a single CmdbUser

    Args:
        public_id (int): public_id of the CmdbUser

    Returns:
        DeleteSingleResponse: Raw data of the deleted CmdbUser
    """
    try:
        users_manager: UsersManager = ManagerProvider.get_manager(ManagerType.USERS, request_user)

        to_delete_user = users_manager.get_user(public_id)

        if not to_delete_user:
            abort(404, f"The User with ID:{public_id} was not found!")

        users_manager.delete_user(public_id)

        return DeleteSingleResponse(raw=CmdbUser.to_json(to_delete_user)).make_response()
    except HTTPException as http_err:
        raise http_err
    except UsersManagerDeleteError as err:
        LOGGER.error("[delete_cmdb_user] %s", err, exc_info=True)
        abort(400, f"Failed to delete User with ID: {public_id}!")
    except UsersManagerGetError as err:
        LOGGER.error("[delete_cmdb_user] %s", err, exc_info=True)
        abort(404, f"Failed to retrieve the User with ID: {public_id}!")
    except Exception as err:
        LOGGER.error("[delete_cmdb_user] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, f"An internal server error occured while trying to delete the User with ID: {public_id}!")
