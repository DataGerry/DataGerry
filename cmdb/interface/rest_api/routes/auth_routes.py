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
Implementation of all authentication related API routes
"""
import logging
from typing import Any, Tuple
from datetime import datetime, timezone
from flask import request, current_app, abort
from werkzeug import Response
from werkzeug.exceptions import HTTPException

from cmdb.database import MongoDatabaseManager
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.manager import (
    SecurityManager,
    SettingsManager,
    UsersManager,
)

from cmdb.models.user_model import CmdbUser
from cmdb.models.security_models.auth_settings import CmdbAuthSettings
from cmdb.security.auth.auth_module import AuthModule
from cmdb.security.token.generator import TokenGenerator
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.route_utils import (
    insert_request_user,
    check_db_exists,
    init_db_routine,
    set_admin_user,
    retrive_user,
    check_user_in_service_portal,
    verify_api_access,
)
from cmdb.interface.rest_api.responses import DefaultResponse, LoginResponse

from cmdb.errors.manager.users_manager import UsersManagerInsertError, UsersManagerGetError
from cmdb.errors.provider import AuthenticationProviderNotActivated, AuthenticationProviderNotFoundError
from cmdb.errors.security.security_errors import (
    InvalidCloudUserError,
    NoAccessTokenError,
    RequestTimeoutError,
    RequestError,
)
from cmdb.errors.database import DatabaseConnectionError
from cmdb.errors.models.cmdb_auth_settings import AuthSettingsInitError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER = logging.getLogger(__name__)

auth_blueprint = APIBlueprint('auth', __name__)

# --------------------------------------------------- CRUD - CREATE -------------------------------------------------- #
#TODO: REFACTOR-FIX (Reduce complexity)
@auth_blueprint.route('/login', methods=['POST'])
def post_login() -> Response:
    """
    Handles user login authentication

    This function processes login credentials, verifies the user, and returns
    an authentication token upon successful login. It supports both cloud mode
    (where users authenticate via a service portal) and non-cloud mode (where
    authentication is managed locally)

    Returns:
        Response: A response containing authentication tokens or subscription options
    """
    try:
        login_data: Any | None = request.json

        if not login_data:
            abort(400, 'No valid JSON data was provided')

        request_user_name: str = login_data['user_name']
        request_password: str = login_data['password']
        request_subscription = None

        if 'subscription' in login_data:
            request_subscription = login_data['subscription']

        try:
            if current_app.cloud_mode:
                request_user_name = request_user_name.lower()
                user_data = check_user_in_service_portal(request_user_name, request_password)

                if not user_data:
                    LOGGER.error("[post_login] Could not retrieve User from ServicePortal!")
                    abort(401, 'Invalid user data. Failed to login!')

                user_database = None

                # If only one subscription directly login the user
                if len(user_data['subscriptions']) == 1:
                    user_database = user_data['subscriptions'][0]['database']

                    if not check_db_exists(user_database):
                        init_db_routine(user_database)

                    set_admin_user(user_data, user_data['subscriptions'][0])

                # In this case the user selected a subscription in the frontend
                elif request_subscription:
                    user_database = request_subscription['database']

                    if not check_db_exists(user_database):
                        init_db_routine(user_database)

                    set_admin_user(user_data, request_subscription)
                # User have multiple subscriptions, send them to frontend to select
                elif len(user_data['subscriptions']) > 1:
                    return DefaultResponse(user_data['subscriptions']).make_response()
                # There are either no subscriptions or something went wrong => failed path
                else:
                    LOGGER.error("[post_login] Error: Invalid data. No subscriptions!")
                    abort(401, "The user has no assigned subscription!")

                user: dict[str, Any] | None = retrive_user(user_data, user_database)

                # User does not exist
                if not user:
                    LOGGER.error("[post_login] Could not retrieve User from database!")
                    abort(401, "Invalid user or password. Could not login!")

                token, token_issued_at, token_expire = generate_token_with_params(
                                                                            user,
                                                                            current_app.database_manager,
                                                                            True
                                                                        )

                return LoginResponse(user, token, token_issued_at, token_expire).make_response()
        except HTTPException as http_err:
            raise http_err
        except NoAccessTokenError as err:
            LOGGER.error("[post_login] NoAccessTokenError: %s", err)
            abort(500, "No access token found!")
        except InvalidCloudUserError as err:
            LOGGER.error("[post_login] InvalidCloudUserError: %s", err)
            abort(403, "Invalid credentials!")
        except RequestTimeoutError as err:
            LOGGER.error("[post_login] RequestTimeoutError: %s", err)
            abort(500, "Login request timed out!")
        except DatabaseConnectionError as err:
            LOGGER.error("[post_login] DatabaseConnectionError: %s", err, exc_info=True)
            abort(500, "Failed to establish a connection to the database!")
        except RequestError as err:
            LOGGER.error("[post_login] RequestError: %s", err)
            abort(500, "Login failed due a malformed request!")
        except UsersManagerGetError as err:
            LOGGER.error("[post_login] UsersManagerGetError: %s", err, exc_info=True)
            abort(500, "Could not login because user can't be retrieved from database!")
        except UsersManagerInsertError as err:
            LOGGER.error("[post_login] UsersManagerInsertError: %s", err, exc_info=True)
            abort(500, "Could not login because user can't be inserted in database!")
        except Exception as err:
            LOGGER.error("[post_login] Exception: %s, Type: %s", err, type(err), exc_info=True)
            abort(500, "An internal server error occured while trying to login!")

        # PATH when its not cloud mode
        users_manager = UsersManager(current_app.database_manager)
        security_manager = SecurityManager(current_app.database_manager)
        settings_manager = SettingsManager(current_app.database_manager)

        auth_module = AuthModule(
            settings_manager.get_all_values_from_section('auth', default=AuthModule.__DEFAULT_SETTINGS__),
            security_manager=security_manager,
            users_manager=users_manager
        )

        user_instance: CmdbUser | None = None

        try:
            user_instance = auth_module.login(request_user_name, request_password)

            if user_instance:
                token, token_issued_at, token_expire = generate_token_with_params(user_instance,
                                                                                current_app.database_manager)

                login_response = LoginResponse(user_instance, token, token_issued_at, token_expire)

                return login_response.make_response()

            abort(401, 'Could not login!')
        except AuthenticationProviderNotActivated:
            abort(400, "The Authentication provider is not active!")
        except AuthenticationProviderNotFoundError:
            abort(400, "The authentication provider was not found!")
        except Exception as err: #pylint: disable=broad-exception-caught
            LOGGER.error("[post_login] Exception: %s, Type: %s", err, type(err))
            abort(500, "Could not login")
    except HTTPException as http_err:
        raise http_err
    except Exception as err:
        LOGGER.error("[post_login] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while validating the login data!")

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

@auth_blueprint.route('/settings', methods=['GET'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@auth_blueprint.protect(auth=True, right='base.system.view')
def get_auth_settings(request_user: CmdbUser):
    """
    Retrieves the authentication settings for the given user.

    This function fetches all authentication-related settings from the system configuration 
    and returns them as a response.

    Args:
        request_user (CmdbUser): The user making the request

    Returns:
        DefaultResponse: A response object containing the authentication settings
    """
    try:
        settings_manager: SettingsManager = ManagerProvider.get_manager(ManagerType.SETTINGS, request_user)

        auth_settings = settings_manager.get_all_values_from_section('auth', default=AuthModule.__DEFAULT_SETTINGS__)
        auth_module = AuthModule(auth_settings)

        return DefaultResponse(auth_module.settings).make_response()
    except Exception as err:
        LOGGER.error("[get_auth_settings] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while retrieving auth settings!")


@auth_blueprint.route('/providers', methods=['GET'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@auth_blueprint.protect(auth=True, right='base.system.view')
def get_installed_providers(request_user: CmdbUser):
    """
    Retrieves a list of installed authentication providers

    This function fetches all available authentication providers from the system configuration 
    and returns their details, including their class name and whether they are external providers

    Args:
        request_user (CmdbUser): The user making the request, used for authorization

    Returns:
        DefaultResponse: A response object containing a list of installed authentication providers
        Each provider is represented as a dictionary with:
            - class_name (str): The name of the provider class
            - external (bool): Indicates whether the provider is external
    """
    try:
        provider_names: list[dict] = []

        settings_manager: SettingsManager = ManagerProvider.get_manager(ManagerType.SETTINGS, request_user)

        auth_module = AuthModule(
            settings_manager.get_all_values_from_section('auth', default=AuthModule.__DEFAULT_SETTINGS__)
        )

        for provider in auth_module.providers:
            provider_names.append({'class_name': provider.get_name(), 'external': provider.EXTERNAL_PROVIDER})

        return DefaultResponse(provider_names).make_response()
    except Exception as err:
        LOGGER.error("[get_installed_providers] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while retrieving installed providers!")


@auth_blueprint.route('/providers/<string:provider_class>', methods=['GET'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@auth_blueprint.protect(auth=True, right='base.system.view')
def get_provider_config(provider_class: str, request_user: CmdbUser):
    """
    Retrieves the configuration for a specified authentication provider

    This function fetches authentication provider settings from the system configuration
    based on the given provider class

    Args:
        provider_class (str): The name of the authentication provider to retrieve settings for
        request_user (CmdbUser): The user making the request

    Returns:
        DefaultResponse: A response object containing the provider's configuration if found
    """
    try:
        settings_manager: SettingsManager = ManagerProvider.get_manager(ManagerType.SETTINGS, request_user)

        auth_module = AuthModule(
            settings_manager.get_all_values_from_section('auth', default=AuthModule.__DEFAULT_SETTINGS__)
        )

        try:
            provider_class_config = auth_module.get_provider(provider_class).get_config()
        except StopIteration:
            abort(404, f"Provider: '{provider_class}' not found!")

        return DefaultResponse(provider_class_config).make_response()
    except HTTPException as http_err:
        raise http_err
    except Exception as err:
        LOGGER.error("[get_provider_config] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while retrieving the provider configuration!")

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

@auth_blueprint.route('/settings', methods=['POST', 'PUT'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@auth_blueprint.protect(auth=True, right='base.system.edit')
def update_auth_settings(request_user: CmdbUser):
    """
    Updates authentication settings for the given user

    This function retrieves new authentication settings from the request payload,
    validates the data, and updates the authentication settings in the system.

    Args:
        request_user (CmdbUser): The user performing the update

    Returns:
        DefaultResponse: A response object containing the updated authentication settings if successful
    """
    try:
        new_auth_settings_values = request.get_json()

        settings_manager: SettingsManager = ManagerProvider.get_manager(ManagerType.SETTINGS, request_user)

        if not new_auth_settings_values:
            abort(400, 'No new data was provided')

        try:
            new_auth_setting_instance = CmdbAuthSettings(**new_auth_settings_values)
        except AuthSettingsInitError as err:
            LOGGER.error("[update_auth_settings] Error: %s", err)
            abort(500, "Could not initialise auth settings!")

        update_result = settings_manager.write(_id='auth', data=new_auth_setting_instance.__dict__)

        if update_result.acknowledged:
            return DefaultResponse(settings_manager.get_section('auth')).make_response()

        abort(400, 'Could not update auth settings')
    except HTTPException as http_err:
        raise http_err
    except Exception as err:
        LOGGER.error("[update_auth_settings] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while updating auth settings!")

# ------------------------------------------------------ HELPERS ----------------------------------------------------- #

def generate_token_with_params(
        login_user: CmdbUser,
        database_manager: MongoDatabaseManager,
        cloud_mode: bool = False) -> Tuple[bytes, int, int]:
    """
    Generates an authentication token for the given user

    This function creates a token containing user-specific data, including a 
    public identifier and optionally the associated database (if cloud mode is enabled). 
    The token's issue and expiration times are also returned

    Args:
        login_user (CmdbUser): The user for whom the token is generated
        database_manager (MongoDatabaseManager): The database manager instance used for token generation
        cloud_mode (bool, optional): Whether the application is running in cloud mode. Defaults to False

    Returns:
        Tuple[bytes, int, int]: A tuple containing:
            - token (bytes): The generated authentication token
            - token_issued_at (int): The timestamp (UTC) when the token was issued
            - token_expire (int): The timestamp (UTC) when the token expires
    """
    tg = TokenGenerator(database_manager)

    user_data: dict[str, Any] = {'public_id': login_user.get_public_id()}

    if cloud_mode:
        user_data['database'] = login_user.get_database()

    token: bytes = tg.generate_token(payload={'user': user_data})

    token_issued_at = int(datetime.now(timezone.utc).timestamp())
    token_expire = int(tg.get_expire_time().timestamp())

    return token, token_issued_at, token_expire
