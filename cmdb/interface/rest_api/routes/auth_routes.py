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

from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.manager import SettingsManager

from cmdb.models.user_model import CmdbUser
from cmdb.models.security_models.auth_settings import CmdbAuthSettings
from cmdb.models.security_models.auth_settings_constants import AUTH_SETTINGS_ID
from cmdb.security.auth.auth_module import AuthModule
from cmdb.security.auth.auth_settings_masking import (
    mask_auth_settings,
    mask_provider_config,
    restore_masked_secrets,
)
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.route_utils import handle_route_errors, insert_request_user, verify_api_access
from cmdb.interface.rest_api.responses import DefaultResponse
from cmdb.interface.rest_api.routes.auth_constants import LOGIN_REQUEST_SCHEMA, LoginKey
from cmdb.interface.rest_api.routes.auth_helper import (
    abort_if_external_provider_in_cloud,
    cloud_login,
    local_login,
)

from cmdb.errors.models.cmdb_auth_settings import AuthSettingsInitError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

auth_blueprint = APIBlueprint('auth', __name__)

# --------------------------------------------------- CRUD - CREATE -------------------------------------------------- #

@auth_blueprint.route('/login', methods=['POST'])
@auth_blueprint.validate(LOGIN_REQUEST_SCHEMA)
@handle_route_errors("while validating the login data")
def post_login(data: dict[str, Any]) -> Response:
    """
    Handles user login authentication

    The body is held to ``LOGIN_REQUEST_SCHEMA`` before any credential is checked: ``user_name`` and ``password``
    are non-empty strings, and the optional ``subscription`` (cloud mode's second step) is an object carrying its
    ``id``. Anything else - no body, a body that is not an object, a missing or mistyped field - is a 400 naming
    the field, and reveals nothing about accounts. Holding both names to strings is also what keeps a JSON object
    from reaching the user lookup as a query.

    Then it dispatches to the matching login flow: the cloud (ServicePortal) flow when ``current_app.cloud_mode``
    is set, otherwise the on-premise AuthModule flow. Both flows (see ``auth_helper``) return an authentication
    token, and the cloud flow may instead return the list of subscriptions the user must choose from; each maps
    its own errors to HTTP statuses.

    Args:
        data (dict[str, Any]): The validated login body

    Raises:
        HTTPException: 400 when the body breaks the login contract; the flows' own answers otherwise

    Returns:
        Response: A response containing authentication tokens or subscription options
    """
    request_user_name: str = data[LoginKey.USER_NAME.value]
    request_password: str = data[LoginKey.PASSWORD.value]
    request_subscription: dict[str, Any] | None = data.get(LoginKey.SUBSCRIPTION.value)

    if current_app.cloud_mode:
        return cloud_login(request_user_name, request_password, request_subscription)

    return local_login(request_user_name, request_password)

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

        auth_settings = settings_manager.get_all_values_from_section(
            AUTH_SETTINGS_ID, default=AuthModule.__DEFAULT_SETTINGS__,
        )
        auth_module = AuthModule(auth_settings)

        # vars(): the section is answered as the model's attributes, which is the shape this route has
        # always had. mask_auth_settings copies it and blanks the credentials before it leaves
        return DefaultResponse(mask_auth_settings(vars(auth_module.settings))).make_response()
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
        provider_names: list[dict[str, Any]] = []

        settings_manager: SettingsManager = ManagerProvider.get_manager(ManagerType.SETTINGS, request_user)

        auth_module = AuthModule(
            settings_manager.get_all_values_from_section(AUTH_SETTINGS_ID, default=AuthModule.__DEFAULT_SETTINGS__)
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
@handle_route_errors("while retrieving the provider configuration")
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
    settings_manager: SettingsManager = ManagerProvider.get_manager(ManagerType.SETTINGS, request_user)

    auth_module = AuthModule(
        settings_manager.get_all_values_from_section(AUTH_SETTINGS_ID, default=AuthModule.__DEFAULT_SETTINGS__)
    )

    provider = auth_module.get_provider(provider_class)

    if provider is None:
        abort(404, f"Provider: '{provider_class}' not found!")

    return DefaultResponse(
        mask_provider_config(provider_class, vars(provider.get_config()))
    ).make_response()

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

@auth_blueprint.route('/settings', methods=['POST', 'PUT'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@auth_blueprint.protect(auth=True, right='base.system.edit')
@handle_route_errors("while updating auth settings")
def update_auth_settings(request_user: CmdbUser) -> Response:
    """
    Updates the authentication settings section (in cloud mode: the tenant's)

    Takes the WHOLE section (``require_complete``), puts back any credential the payload sends masked
    (``restore_masked_secrets``), validates it as ``CmdbAuthSettings`` and stores it. In cloud mode a section
    that activates an external provider (LDAP) is refused: external providers are on-premise only and a
    cloud login never runs one. Everything else - the token lifetime among it - stays writable in cloud mode

    Status codes:
        200 OK: Stored; body is the stored section, credentials masked
        400 BAD_REQUEST: No body, a section ``CmdbAuthSettings`` cannot be built from, in cloud mode an
            active external provider (``CLOUD_EXTERNAL_PROVIDER_MSG``), or the write was not acknowledged
        500: An unexpected error

    Args:
        request_user (CmdbUser): The user performing the update

    Returns:
        DefaultResponse: The stored section, credentials masked
    """
    new_auth_settings_values = request.get_json()

    settings_manager: SettingsManager = ManagerProvider.get_manager(ManagerType.SETTINGS, request_user)

    if not new_auth_settings_values:
        abort(400, 'No new data was provided')

    # The reads mask every credential, and this route takes the WHOLE section - so a client that
    # read the settings, changed one field and sent the object back posts the mask where the bind
    # password was. Resolving it against what is stored is what keeps that from becoming the new
    # password; a payload carrying a real value at that path is a deliberate change and is written
    stored_auth_settings = settings_manager.get_all_values_from_section(
        AUTH_SETTINGS_ID, default=AuthModule.__DEFAULT_SETTINGS__,
    )
    new_auth_settings_values = restore_masked_secrets(new_auth_settings_values, stored_auth_settings)

    try:
        # require_complete: the update carries the WHOLE section. A payload omitting 'providers'
        # would otherwise blank the configured LDAP provider, since an absent key and a reset to
        # the default are indistinguishable once the defaults have been applied
        new_auth_setting_instance = CmdbAuthSettings.from_data(new_auth_settings_values, require_complete=True)
    except AuthSettingsInitError as err:
        # A malformed auth-settings payload is a client error, not a server fault
        LOGGER.error("[update_auth_settings] Error: %s", err)
        abort(400, f"Could not initialise auth settings from the provided data: {err}")

    abort_if_external_provider_in_cloud(new_auth_settings_values)

    update_result = settings_manager.write(
        _id=AUTH_SETTINGS_ID,
        data=CmdbAuthSettings.to_json(new_auth_setting_instance),
    )

    if update_result.acknowledged:
        # Masked like every other read: the echo is the stored section, credentials included
        return DefaultResponse(
            mask_auth_settings(settings_manager.get_section(AUTH_SETTINGS_ID))
        ).make_response()

    abort(400, 'Could not update auth settings')
