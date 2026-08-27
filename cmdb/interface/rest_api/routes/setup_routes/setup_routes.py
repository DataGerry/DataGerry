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
Service-Portal-driven setup/teardown routes for the cloud deployment

These routes let the DataGerry Service Portal tear down a tenant's resources:

- ``DELETE /setup/subscriptions?database=<name>``  drops a subscription's tenant database
- ``DELETE /setup/cache/user``                     evicts one or more cloud users from the user cache
- ``DELETE /setup/cache/user/all``                 clears the whole cloud user cache

The cache lives in the ``cache.users`` collection of the shared cache database; removing an entry
forces the next request for that user to be re-validated against the Service Portal

All three are destructive and meant to be called by the portal, not by end users. They are decorated
with ``verify_api_access(required_api_level=ApiLevel.SUPER_ADMIN)``, which enforces that level only
for a cloud-mode request that authenticates with Basic auth - it passes every request through
untouched when the instance does not run in cloud mode, and it evaluates no API level for a request
carrying a Bearer token. Neither route carries ``.protect``, so nothing else gates them; the routes
are registered unconditionally (see ``init_rest_api``). Both gaps are filed for decision rather than
narrowed here, because tightening them changes the contract the Service Portal calls against
"""
from logging import Logger, getLogger
from typing import Any
from flask import request, abort, current_app
from werkzeug import Response
from werkzeug.exceptions import HTTPException

from cmdb.manager import CachedUserManager

from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.rest_api.responses import DefaultResponse
from cmdb.interface.rest_api.routes.setup_routes.setup_constants import SetupQueryParam, SetupRequestKey
from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.route_utils import verify_api_access

from cmdb.errors.database import DatabaseNotFoundError, DatabaseConnectionError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

setup_blueprint = APIBlueprint('setup', __name__)

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

@setup_blueprint.route('/subscriptions', methods=['DELETE'])
@verify_api_access(required_api_level=ApiLevel.SUPER_ADMIN)
def delete_subscription() -> Response:
    """
    HTTP `DELETE` route to drop the database backing a subscription

    Reads the target database name from the ``database`` query parameter (e.g.
    ``DELETE /setup/subscriptions?database=<name>``) and drops that database. Intended for the
    Service Portal to tear down a cancelled subscription's tenant database

    The name is used as given: nothing checks that it belongs to a subscription, so any database on
    the cluster is a valid target

    Returns:
        DefaultResponse: True after the database has been dropped

    Raises:
        HTTPException: 400 when the ``database`` query parameter is missing/empty or names a database
            which does not exist; 500 when the drop itself fails or on an unexpected error
    """
    try:
        subscription_database: str | None = request.args.get(SetupQueryParam.DATABASE)

        if not subscription_database:
            abort(400, "No database name was provided in the 'database' query parameter!")

        try:
            current_app.database_manager.drop_database(subscription_database)
        except DatabaseNotFoundError:
            abort(400, f"The database with the name {subscription_database} does not exist!")
        except DatabaseConnectionError as err:
            LOGGER.error("[delete_subscription] Error: %s, Type: %s", err, type(err))
            abort(500, "An issue occurred while deleting the subscription!")

        return DefaultResponse(True).make_response()
    except HTTPException as http_err:
        raise http_err
    except Exception as err:
        LOGGER.error("[delete_subscription] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occurred while deleting the subscription!")


@setup_blueprint.route('/cache/user', methods=['DELETE'])
@verify_api_access(required_api_level=ApiLevel.SUPER_ADMIN)
def delete_cached_user() -> Response:
    """
    HTTP `DELETE` route to evict one or more cloud users from the local user cache

    Expects a JSON body ``{"email": <str | list[str]>}``: a single email deletes that cached user,
    a list of emails deletes each of them in one operation. Removing a user from ``cache.users``
    forces the next request for that user to be re-validated against the Service Portal

    The response does not say whether anything was actually cached: an unknown email is a no-op
    answered with True

    Returns:
        DefaultResponse: True after the cached user(s) have been removed

    Raises:
        HTTPException: 400 when the body is missing / not a JSON object, the ``email`` key is absent,
            or its value is neither a string nor a list; 500 on an unexpected error
    """
    try:
        payload: dict[str, Any] | None = request.get_json(silent=True)

        if not isinstance(payload, dict):
            abort(400, "No valid JSON object payload provided!")

        if SetupRequestKey.EMAIL not in payload:
            abort(400, "'email' key not provided in the request payload!")

        target_emails: Any = payload[SetupRequestKey.EMAIL]
        cached_user_manager: CachedUserManager = CachedUserManager(current_app.database_manager)

        if isinstance(target_emails, str):
            cached_user_manager.delete_cached_user(target_emails)
        elif isinstance(target_emails, list):
            cached_user_manager.delete_multiple_cached_users(target_emails)
        else:
            abort(400, "'email' must be a string or list of strings!")

        return DefaultResponse(True).make_response()
    except HTTPException as http_err:
        raise http_err
    except Exception as err:
        LOGGER.error("[delete_cached_user] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occurred while deleting a cached User!")


@setup_blueprint.route('/cache/user/all', methods=['DELETE'])
@verify_api_access(required_api_level=ApiLevel.SUPER_ADMIN)
def delete_all_cached_users() -> Response:
    """
    HTTP `DELETE` route to clear the entire cloud user cache

    Empties the ``cache.users`` collection, forcing every cloud user to be re-validated against the
    Service Portal on their next request. The number of removed entries is not reported

    Returns:
        DefaultResponse: True after the cache has been cleared

    Raises:
        HTTPException: 500 on an unexpected error while clearing the cache
    """
    try:
        cached_user_manager: CachedUserManager = CachedUserManager(current_app.database_manager)

        cached_user_manager.clear_cache()

        return DefaultResponse(True).make_response()
    except HTTPException as http_err:
        raise http_err
    except Exception as err:
        LOGGER.error("[delete_all_cached_users] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occurred while deleting all cached Users!")
