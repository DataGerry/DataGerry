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
credential parsing.
"""
from logging import Logger, getLogger
from typing import Any, Tuple
from datetime import datetime, timezone

from flask import current_app, abort
from werkzeug import Response
from werkzeug.exceptions import HTTPException

from cmdb.database import MongoDatabaseManager
from cmdb.manager import (
    SecurityManager,
    SettingsManager,
    UsersManager,
)

from cmdb.models.user_model import CmdbUser
from cmdb.security.auth.auth_module import AuthModule
from cmdb.security.token.generator import TokenGenerator
from cmdb.interface.route_utils import (
    check_db_exists,
    init_db_routine,
    set_admin_user,
    retrive_user,
    check_user_in_service_portal,
)
from cmdb.interface.rest_api.responses import DefaultResponse, LoginResponse

from cmdb.errors.manager.users_manager import UsersManagerInsertError, UsersManagerGetError
from cmdb.errors.provider import (
    AuthenticationProviderNotActivated,
    AuthenticationProviderNotFoundError,
    AuthenticationError,
)
from cmdb.errors.security.security_errors import (
    InvalidCloudUserError,
    NoAccessTokenError,
    RequestTimeoutError,
    RequestError,
)
from cmdb.errors.database import DatabaseConnectionError
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


# The branch/statement count is inherent to the subscription matrix + the per-error HTTP mapping; it is
# isolated here so the post_login route itself stays trivial.
def cloud_login(  # pylint: disable=too-many-branches, too-many-statements
        request_user_name: str,
        request_password: str,
        request_subscription: Any | None) -> Response:
    """
    Runs the cloud (ServicePortal) login flow behind ``POST /auth/login``

    Authenticates the user against the ServicePortal, resolves which subscription/database to log into
    (auto for a single subscription, the selected one when provided, or the list of options when the
    user has several and none was chosen), initialises the target database on first use, retrieves the
    user and returns a login token. Behaviour is unchanged from the original inline cloud branch.

    Args:
        request_user_name (str): The submitted user name (lower-cased for the ServicePortal lookup)
        request_password (str): The submitted password
        request_subscription (Any | None): The subscription the user selected in the frontend, if any

    Returns:
        Response: A ``LoginResponse`` with the token, or a ``DefaultResponse`` listing the available
                  subscriptions when the user must choose one
    """
    try:
        request_user_name = request_user_name.lower()
        user_data = check_user_in_service_portal(request_user_name, request_password)

        if not user_data:
            LOGGER.error("[cloud_login] Could not retrieve User from ServicePortal!")
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
            selected_subscription = next(
                (s for s in user_data.get("subscriptions", []) if s["id"] == request_subscription['id']),
                None
            )

            if not selected_subscription:
                abort(400, "Target subscription not found!")

            user_database = selected_subscription['database']

            if not check_db_exists(user_database):
                init_db_routine(user_database)

            set_admin_user(user_data, selected_subscription)
        # User have multiple subscriptions, send them to frontend to select
        elif len(user_data['subscriptions']) > 1:
            filtered_subs: list[dict[str, Any]] = [
                {"id": sub["id"], "name": sub["name"], "short_id": sub.get("short_id")}
                for sub in user_data.get("subscriptions", [])
            ]

            return DefaultResponse(filtered_subs).make_response()
        # There are either no subscriptions or something went wrong => failed path
        else:
            LOGGER.error("[cloud_login] Error: Invalid data. No subscriptions!")
            abort(401, "The user has no assigned subscription!")

        user: CmdbUser | None = retrive_user(user_data, user_database)

        # User does not exist
        if not user:
            LOGGER.error("[cloud_login] Could not retrieve User from database!")
            abort(401, "Invalid user or password. Could not login!")

        # Remove the user password
        user.password = ""

        token, token_issued_at, token_expire = generate_token_with_params(
            user,
            current_app.database_manager,
            True
        )

        return LoginResponse(user, token, token_issued_at, token_expire).make_response()
    except HTTPException as http_err:
        raise http_err
    except NoAccessTokenError as err:
        LOGGER.error("[cloud_login] NoAccessTokenError: %s", err)
        abort(500, "No access token found!")
    except InvalidCloudUserError as err:
        LOGGER.error("[cloud_login] InvalidCloudUserError: %s", err)
        abort(403, "Invalid credentials!")
    except RequestTimeoutError as err:
        LOGGER.error("[cloud_login] RequestTimeoutError: %s", err)
        abort(500, "Login request timed out!")
    except DatabaseConnectionError as err:
        LOGGER.error("[cloud_login] DatabaseConnectionError: %s", err, exc_info=True)
        abort(500, "Failed to establish a connection to the database!")
    except RequestError as err:
        LOGGER.error("[cloud_login] RequestError: %s", err)
        abort(500, "Login failed due a malformed request!")
    except UsersManagerGetError as err:
        LOGGER.error("[cloud_login] UsersManagerGetError: %s", err, exc_info=True)
        abort(500, "Could not login because user can't be retrieved from database!")
    except UsersManagerInsertError as err:
        LOGGER.error("[cloud_login] UsersManagerInsertError: %s", err, exc_info=True)
        abort(500, "Could not login because user can't be inserted in database!")
    except Exception as err:  # pylint: disable=broad-exception-caught
        LOGGER.error("[cloud_login] Exception: %s, Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while trying to login!")


def local_login(request_user_name: str, request_password: str) -> Response:
    """
    Runs the on-premise (non-cloud) login flow behind ``POST /auth/login``

    Builds the AuthModule from the stored auth settings and delegates the credential check to it, then
    returns a login token. Failed credentials (a provider ``AuthenticationError``) and the no-user path
    map to 401; a provider that is not active / not found maps to 400. The AuthModule construction is
    intentionally outside the try, so a construction error propagates to the route's outer handler
    rather than being mapped to a login error.

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
            token, token_issued_at, token_expire = generate_token_with_params(user_instance,
                                                                              current_app.database_manager)

            login_response = LoginResponse(user_instance, token, token_issued_at, token_expire)

            return login_response.make_response()

        abort(401, 'Could not login!')
    except HTTPException as http_err:
        raise http_err
    except AuthenticationProviderNotActivated:
        abort(400, "The Authentication provider is not active!")
    except AuthenticationProviderNotFoundError:
        abort(400, "The authentication provider was not found!")
    except AuthenticationError as err:
        LOGGER.error("[local_login] AuthenticationError: %s", err)
        abort(401, "Invalid user credentials!")
    except Exception as err:  # pylint: disable=broad-exception-caught
        LOGGER.error("[local_login] Exception: %s, Type: %s", err, type(err))
        abort(500, "Could not login")
