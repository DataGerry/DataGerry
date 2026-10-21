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
Login helpers for the authentication REST routes

Holds the two login flows behind ``POST /auth/login`` (extracted from ``post_login`` to reduce its
complexity, behaviour unchanged): ``cloud_login`` (ServicePortal + subscription resolution) and
``local_login`` (the on-premise AuthModule flow), plus the shared ``generate_token_with_params`` token
builder. Each flow keeps its own error-to-HTTP mapping; the route's outer handler only wraps the
credential parsing. ``abort_if_external_provider_in_cloud`` is the auth-settings update's cloud rule:
external providers are on-premise only.
"""
from logging import Logger, getLogger
from typing import Any, Tuple

from flask import current_app, abort
from werkzeug import Response
from werkzeug.exceptions import HTTPException

from cmdb.database import MongoDatabaseManager
from cmdb.manager import (
    GroupsManager,
    SecurityManager,
    SettingsManager,
    UsersManager,
)

from cmdb.models.user_model import CmdbUser, CmdbUserKey
from cmdb.models.cached_user_model import CachedSubscriptionKey, CachedUserKey
from cmdb.security.auth.auth_module import AuthModule
from cmdb.models.security_models.auth_settings_constants import (
    CLOUD_EXTERNAL_PROVIDER_MSG,
    LDAP_GROUP_NOT_AN_ID_MSG,
    PROVIDER_CONFIG_UNUSABLE_MSG,
)
from cmdb.security.auth.providers.ldap_group_references import as_group_id, ldap_group_references
from cmdb.security.token.generator import TokenGenerator
from cmdb.security.token.token_constants import TokenPayloadKey
from cmdb.interface.route_utils import (
    abort_if_too_large,
    refuse_inactive_user,
)
from cmdb.interface.cloud_user_helper import (
    check_db_exists,
    init_db_routine,
    set_admin_user,
    retrieve_user,
    check_user_in_service_portal,
)
from cmdb.interface.rest_api.responses import DefaultResponse, LoginResponse
from cmdb.interface.tenant_availability import abort_if_tenant_unavailable
from cmdb.interface.rest_api.routes.auth_constants import CloudLoginMessage
from cmdb.interface.rest_api.routes.routes_helper import abort_on_unknown_references
from cmdb.interface.rest_api.routes.user_management_routes.cmdb_groups.groups_constants import USER_GROUP_LABEL

from cmdb.errors.manager.users_manager import UsersManagerInsertError, UsersManagerGetError
from cmdb.errors.provider import AuthenticationError
from cmdb.errors.security.security_errors import (
    InvalidCloudUserError,
    NoAccessTokenError,
    RequestTimeoutError,
    RequestError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)


def generate_token_with_params(
        login_user: CmdbUser,
        database_manager: MongoDatabaseManager,
        cloud_mode: bool = False) -> Tuple[bytes, int, int]:
    """
    Generates an authentication token for the given user

    This function creates a token containing user-specific data, including a
    public identifier and optionally the associated database (if cloud mode is enabled).
    The token's issue and expiration times are also returned - the very ones signed into it, so the
    `token_expire` the frontend's session timer runs on is the token's own `exp`. In cloud mode the
    token lifetime is the tenant's own `auth` setting

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
    tenant_database: str | None = login_user.get_database() if cloud_mode else None
    tg = TokenGenerator(database_manager, tenant_database)

    user_data: dict[str, Any] = {CmdbUserKey.PUBLIC_ID.value: login_user.get_public_id()}

    if cloud_mode:
        user_data[CmdbUserKey.DATABASE.value] = tenant_database

    return tg.generate_token_with_times(payload={TokenPayloadKey.USER.value: user_data})


# The branch/statement count is inherent to the subscription matrix + the per-error HTTP mapping; it is
# isolated here so the post_login route itself stays trivial.
def cloud_login(
        request_user_name: str,
        request_password: str,
        request_subscription: Any | None) -> Response:
    """
    Runs the cloud (ServicePortal) login flow behind ``POST /auth/login``

    Authenticates the user against the ServicePortal (``authenticate_cloud_login``), resolves which
    subscription/database to log into (auto for a single subscription, the selected one when provided, or the list
    of options when the user has several and none was chosen - ``select_login_subscription``), prepares the tenant
    and its user (``prepare_cloud_login_user``) and returns a login token. A tenant whose database failed its startup
    update is answered 503 before anything touches it. A user this tenant stored as deactivated gets no token, even
    though the ServicePortal accepted the credentials - the flag is the tenant's own decision about the account

    **Only the caller's credentials and account answer 4xx** (``CloudLoginMessage``). A portal or server fault is a
    500 with its own message, a database outage or lock timeout reaches the app's handlers (503 / 423), and a
    programming error is the app's 500 - nothing is caught wholesale

    Args:
        request_user_name (str): The submitted email (normalised by ``check_user_in_service_portal``)
        request_password (str): The submitted password
        request_subscription (Any | None): The subscription the user selected in the frontend, if any

    Returns:
        Response: A ``LoginResponse`` with the token, or a ``DefaultResponse`` listing the available
                  subscriptions when the user must choose one
    """
    user_data: dict[str, Any] = authenticate_cloud_login(request_user_name, request_password)
    subscriptions: list[dict[str, Any]] = login_subscriptions(user_data)

    # Several subscriptions and none chosen yet: the frontend lets the user pick one
    if len(subscriptions) > 1 and not request_subscription:
        return DefaultResponse(list_subscription_choices(subscriptions)).make_response()

    user: CmdbUser = prepare_cloud_login_user(
        user_data, select_login_subscription(subscriptions, request_subscription),
    )

    # Remove the user password
    user.password = ""

    token, token_issued_at, token_expire = generate_token_with_params(user, current_app.database_manager, True)

    return LoginResponse(user, token, token_issued_at, token_expire).make_response()


def authenticate_cloud_login(request_user_name: str, request_password: str) -> dict[str, Any]:
    """
    Checks the login's credentials with the Service Portal

    Args:
        request_user_name (str): The submitted email
        request_password (str): The submitted password

    Raises:
        HTTPException: 401 when the portal answers nothing; 403 for refused credentials; 500 when the portal is not
            configured, times out or fails the request
        DocumentNetworkError: When the database server was lost while the user cache was read - answered 503
        DocumentLockTimeoutError: When a lock timed out there - answered 423

    Returns:
        dict[str, Any]: The portal's user data - its subscriptions among it
    """
    try:
        user_data: dict[str, Any] | None = check_user_in_service_portal(request_user_name, request_password)
    except InvalidCloudUserError as err:
        LOGGER.error("[authenticate_cloud_login] InvalidCloudUserError: %s", err)
        abort(403, CloudLoginMessage.INVALID_CREDENTIALS.value)
    except NoAccessTokenError as err:
        LOGGER.error("[authenticate_cloud_login] NoAccessTokenError: %s", err)
        abort(500, CloudLoginMessage.PORTAL_NOT_CONFIGURED.value)
    except RequestTimeoutError as err:
        LOGGER.error("[authenticate_cloud_login] RequestTimeoutError: %s", err)
        abort(500, CloudLoginMessage.PORTAL_TIMEOUT.value)
    except RequestError as err:
        LOGGER.error("[authenticate_cloud_login] RequestError: %s", err)
        abort(500, CloudLoginMessage.PORTAL_REQUEST_FAILED.value)

    if not user_data:
        LOGGER.error("[authenticate_cloud_login] Could not retrieve User from ServicePortal!")
        abort(401, CloudLoginMessage.NO_PORTAL_ANSWER.value)

    return user_data


def login_subscriptions(user_data: dict[str, Any]) -> list[dict[str, Any]]:
    """
    The subscriptions a portal answer carries - none when the key is missing or holds no list

    Args:
        user_data (dict[str, Any]): The portal's user data

    Returns:
        list[dict[str, Any]]: The subscriptions, possibly empty
    """
    subscriptions: Any = user_data.get(CachedUserKey.SUBSCRIPTIONS.value)

    return subscriptions if isinstance(subscriptions, list) else []


def list_subscription_choices(subscriptions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    The subscriptions a user with several may choose from - id, name and short id of each

    Args:
        subscriptions (list[dict[str, Any]]): The portal's subscriptions

    Returns:
        list[dict[str, Any]]: One choice per subscription
    """
    return [
        {
            CachedSubscriptionKey.ID.value: subscription.get(CachedSubscriptionKey.ID.value),
            CachedSubscriptionKey.NAME.value: subscription.get(CachedSubscriptionKey.NAME.value),
            CachedSubscriptionKey.SHORT_ID.value: subscription.get(CachedSubscriptionKey.SHORT_ID.value),
        }
        for subscription in subscriptions
    ]


def select_login_subscription(subscriptions: list[dict[str, Any]],
                              request_subscription: Any | None) -> dict[str, Any]:
    """
    The subscription to log into: the only one, or the one the user chose by its id

    Args:
        subscriptions (list[dict[str, Any]]): The portal's subscriptions
        request_subscription (Any | None): The chosen subscription (checked by ``LOGIN_REQUEST_SCHEMA``), if any

    Raises:
        HTTPException: 401 without any subscription; 400 when the chosen one is not the user's

    Returns:
        dict[str, Any]: The subscription
    """
    if len(subscriptions) == 1:
        return subscriptions[0]

    if not subscriptions:
        LOGGER.error("[select_login_subscription] Error: Invalid data. No subscriptions!")
        abort(401, CloudLoginMessage.NO_SUBSCRIPTION.value)

    requested_id: Any = request_subscription[CachedSubscriptionKey.ID.value]
    selected: dict[str, Any] | None = next(
        (subscription for subscription in subscriptions
         if subscription.get(CachedSubscriptionKey.ID.value) == requested_id),
        None,
    )

    if not selected:
        abort(400, CloudLoginMessage.SUBSCRIPTION_NOT_FOUND.value)

    return selected


def prepare_cloud_login_user(user_data: dict[str, Any], subscription: dict[str, Any]) -> CmdbUser:
    """
    Prepares the subscription's tenant and answers the user logging into it

    The tenant is checked first (503 when it failed its startup update), its database initialised on first use, the
    tenant's copy of the user created or brought up to date (``set_admin_user``) and read (``retrieve_user``). A
    tenant user that cannot be read or stored is a 500; a tenant without the user a 401, a deactivated one a 401
    (``refuse_inactive_user``). A database outage or lock timeout passes through as itself (503 / 423), as does the
    connector's ``DatabaseConnectionError`` (the app's handler decides 503 or 500)

    Args:
        user_data (dict[str, Any]): The portal's user data
        subscription (dict[str, Any]): The subscription to log into

    Raises:
        HTTPException: 401 for a subscription naming no database, an unknown or a deactivated user; 503 for an
            unavailable tenant; 413 / 500 when the tenant user cannot be stored or read

    Returns:
        CmdbUser: The user, as the tenant stores it
    """
    user_database: Any = subscription.get(CachedSubscriptionKey.DATABASE.value)

    if not user_database:
        abort(401, CloudLoginMessage.NO_SUBSCRIPTION.value)

    abort_if_tenant_unavailable(user_database)

    if not check_db_exists(user_database):
        init_db_routine(user_database)

    try:
        set_admin_user(user_data, subscription)
        user: CmdbUser | None = retrieve_user(user_data, user_database)
    except UsersManagerGetError as err:
        LOGGER.error("[prepare_cloud_login_user] UsersManagerGetError: %s", err, exc_info=True)
        abort(500, CloudLoginMessage.USER_UNREADABLE.value)
    except UsersManagerInsertError as err:
        abort_if_too_large(err)
        LOGGER.error("[prepare_cloud_login_user] UsersManagerInsertError: %s", err, exc_info=True)
        abort(500, CloudLoginMessage.USER_NOT_STORED.value)

    if not user:
        LOGGER.error("[prepare_cloud_login_user] Could not retrieve User from database!")
        abort(401, CloudLoginMessage.UNKNOWN_USER.value)

    # The portal accepted the credentials; this tenant's own flag still decides
    refuse_inactive_user(user)

    return user


def local_login(request_user_name: str, request_password: str) -> Response:
    """
    Runs the on-premise (non-cloud) login flow behind ``POST /auth/login``

    Builds the AuthModule from the stored auth settings and delegates the credential check to it, then
    returns a login token. Every failed login is one 401 - ``AuthModule.login`` hands a missing user, an
    unknown or deactivated provider and wrong credentials alike to its fallback sweep, which ends in an
    ``AuthenticationError``, so the response never says which of them it was. A user that authenticated
    but whose account is deactivated is refused with 401 before any token is issued. The AuthModule
    construction is intentionally outside the try, so a construction error propagates to the route's
    outer handler rather than being mapped to a login error.

    Args:
        request_user_name (str): The submitted user name
        request_password (str): The submitted password

    Returns:
        Response: A ``LoginResponse`` with the token on success
    """
    users_manager = UsersManager(current_app.database_manager)
    security_manager = SecurityManager(current_app.database_manager)
    settings_manager = SettingsManager(current_app.database_manager)

    auth_module = AuthModule(
        settings_manager.get_all_values_from_section('auth', default=AuthModule.__DEFAULT_SETTINGS__),
        security_manager=security_manager,
        users_manager=users_manager
    )

    try:
        user_instance: CmdbUser | None = auth_module.login(request_user_name, request_password)

        if user_instance:
            # Checked here, after `login` returned, rather than inside it: a refusal raised within
            # `login` would be caught and handed to the fallback sweep over every other provider
            refuse_inactive_user(user_instance)

            token, token_issued_at, token_expire = generate_token_with_params(user_instance,
                                                                              current_app.database_manager)

            login_response = LoginResponse(user_instance, token, token_issued_at, token_expire)

            return login_response.make_response()

        abort(401, 'Could not login!')
    except HTTPException as http_err:
        raise http_err
    except AuthenticationError as err:
        LOGGER.error("[local_login] AuthenticationError: %s", err)
        abort(401, "Invalid user credentials!")
    except Exception as err:  # pylint: disable=broad-exception-caught
        LOGGER.error("[local_login] Exception: %s, Type: %s", err, type(err))
        abort(500, "Could not login")


def abort_if_provider_config_unusable(settings_values: dict[str, Any]) -> None:
    """
    Refuses an auth-settings section holding a provider config its provider's config class cannot build

    The read falls back to a provider's defaults on such a config, so storing it would switch the provider off
    behind a 200

    Args:
        settings_values (dict[str, Any]): The whole auth section the update is about to store

    Raises:
        HTTPException: 400 naming every refused provider and why
    """
    problems: list[str] = AuthModule.provider_config_problems(settings_values)

    if problems:
        abort(400, PROVIDER_CONFIG_UNUSABLE_MSG.format(problems='; '.join(problems)))


def abort_if_external_provider_in_cloud(settings_values: dict[str, Any]) -> None:
    """
    Refuses, in cloud mode, an auth-settings section that activates an external provider

    External providers are on-premise only: a cloud login never runs one
    (``AuthModule.external_providers_allowed``), so storing one as active would only look like it worked.
    The rest of the section - the token lifetime among it, which the tenant's tokens are issued with - stays
    writable in cloud mode. On premise this does nothing

    Args:
        settings_values (dict[str, Any]): The whole auth section the update is about to store

    Raises:
        HTTPException: 400 naming every external provider the section activates, in cloud mode only
    """
    if not current_app.cloud_mode:
        return

    active_names: list[str] = AuthModule(settings_values).active_external_provider_names()

    if active_names:
        abort(400, CLOUD_EXTERNAL_PROVIDER_MSG.format(names=', '.join(active_names)))


def abort_if_ldap_groups_unusable(settings_values: dict[str, Any], groups_manager: GroupsManager) -> None:
    """
    Refuses an auth-settings section whose LDAP default group or group mapping names no existing CmdbUserGroup

    A directory user is provisioned into the default group and moved into a mapped group on every login; a group
    that does not exist leaves them authenticated and refused every right, without a word why. Checked whether the
    provider is active or not - the settings are what an activation later uses

    Args:
        settings_values (dict[str, Any]): The section as it will be stored
        groups_manager (GroupsManager): Answers which groups exist, in one read

    Raises:
        HTTPException: 400 naming the values that are no group id, or the ids no group carries
    """
    references = ldap_group_references(settings_values)
    not_ids: list[Any] = [reference.value for reference in references if as_group_id(reference.value) is None]

    if not_ids:
        abort(400, LDAP_GROUP_NOT_AN_ID_MSG.format(values=not_ids))

    abort_on_unknown_references(
        groups_manager, sorted({as_group_id(reference.value) for reference in references}), USER_GROUP_LABEL,
    )
