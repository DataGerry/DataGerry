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
from logging import Logger, getLogger
from typing import Any

from flask import request, current_app, abort
from werkzeug import Response
from werkzeug.exceptions import HTTPException

from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.manager import SettingsManager

from cmdb.models.user_model import CmdbUser
from cmdb.models.security_models.auth_settings import CmdbAuthSettings
from cmdb.security.auth.auth_module import AuthModule
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.route_utils import insert_request_user, verify_api_access
from cmdb.interface.rest_api.responses import DefaultResponse
from cmdb.interface.rest_api.routes.auth_helper import cloud_login, local_login

from cmdb.errors.models.cmdb_auth_settings import AuthSettingsInitError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

auth_blueprint = APIBlueprint('auth', __name__)

# --------------------------------------------------- CRUD - CREATE -------------------------------------------------- #

@auth_blueprint.route('/login', methods=['POST'])
def post_login() -> Response:
    """
    Handles user login authentication

    Parses the credentials from the request body and dispatches to the matching login flow: the
    cloud (ServicePortal) flow when ``current_app.cloud_mode`` is set, otherwise the on-premise
    AuthModule flow. Both flows (see ``auth_helper``) return an authentication token, and the cloud
    flow may instead return the list of subscriptions the user must choose from. This outer handler
    only guards the credential parsing; each flow maps its own errors to HTTP statuses.

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

        if current_app.cloud_mode:
            return cloud_login(request_user_name, request_password, request_subscription)

        return local_login(request_user_name, request_password)
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
def get_auth_settings(request_user: CmdbUser) -> Response:
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
def get_installed_providers(request_user: CmdbUser) -> Response:
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
def get_provider_config(provider_class: str, request_user: CmdbUser) -> Response:
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

        provider = auth_module.get_provider(provider_class)

        if provider is None:
            abort(404, f"Provider: '{provider_class}' not found!")

        return DefaultResponse(provider.get_config()).make_response()
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
def update_auth_settings(request_user: CmdbUser) -> Response:
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
            # A malformed auth-settings payload is a client error, not a server fault
            LOGGER.error("[update_auth_settings] Error: %s", err)
            abort(400, "Could not initialise auth settings from the provided data!")

        update_result = settings_manager.write(_id='auth', data=new_auth_setting_instance.__dict__)

        if update_result.acknowledged:
            return DefaultResponse(settings_manager.get_section('auth')).make_response()

        abort(400, 'Could not update auth settings')
    except HTTPException as http_err:
        raise http_err
    except Exception as err:
        LOGGER.error("[update_auth_settings] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while updating auth settings!")
