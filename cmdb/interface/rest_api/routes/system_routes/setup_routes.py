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

These routes let the DataGerry Service Portal tear down a tenant's resources: dropping a
subscription's database and evicting cloud users from the local user cache (collection
``cache.users``). Every route is gated at ``ApiLevel.SUPER_ADMIN`` via ``verify_api_access`` and is
only meaningful in cloud mode (``verify_api_access`` passes through untouched when not in cloud
mode). They are destructive and intended to be called by the portal, not end users.
"""
from logging import Logger, getLogger
from typing import Any
from flask import request, abort, current_app
from werkzeug import Response
from werkzeug.exceptions import HTTPException

from cmdb.manager import CachedUserManager

from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.rest_api.responses import DefaultResponse
from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.route_utils import (
    delete_database,
    verify_api_access,
)

from cmdb.errors.database import DatabaseNotFoundError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

setup_blueprint = APIBlueprint('setup', __name__)

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

#TODO: REFACTOR-FIX (create specific errors)
@setup_blueprint.route('/subscriptions', methods=['DELETE'])
@verify_api_access(required_api_level=ApiLevel.SUPER_ADMIN)
def delete_subscription() -> Response:
    """
    HTTP `DELETE` route to drop the database backing a subscription

    Reads the target database name from the ``database`` query parameter (e.g.
    ``DELETE /setup/subscriptions?database=<name>``) and deletes that database. Intended for the
    Service Portal to tear down a cancelled subscription's tenant database

    Returns:
        DefaultResponse: True after the database has been dropped

    Raises:
        HTTPException: 400 when no query arguments are given, the ``database`` argument is missing,
            the named database does not exist, or the drop otherwise fails; 500 on an unexpected error
    """
    try:
        if not request.args:
            abort(400, "No request arguments provided!")

        delete_data: dict[str, str] = request.args.to_dict()

        try:
            subscrption_database: str = delete_data['database']
        except KeyError:
            abort(400, "Database name was not provided!")

        try:
            delete_database(subscrption_database)
        except DatabaseNotFoundError:
            abort(400, f"The database with the name {subscrption_database} does not exist!")
        except Exception as err:
            LOGGER.error("[delete_subscription] Error: %s, Type: %s", err, type(err))
            abort(400, "An issue occured while deleting the subscription!")

        return DefaultResponse(True).make_response()
    except HTTPException as http_err:
        raise http_err
    except Exception as err:
        LOGGER.error("[delete_subscription] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while deleting the subscription!")


@setup_blueprint.route('/cache/user', methods=['DELETE'])
@verify_api_access(required_api_level=ApiLevel.SUPER_ADMIN)
def delete_cached_user() -> Response:
    """
    HTTP `DELETE` route to evict one or more cloud users from the local user cache

    Expects a JSON body ``{"email": <str | list[str]>}``: a single email deletes that cached user,
    a list of emails deletes each of them. Removing a user from ``cache.users`` forces the next
    request for that user to be re-validated against the Service Portal

    Returns:
        DefaultResponse: True after the cached user(s) have been removed

    Raises:
        HTTPException: 400 when the body is missing / not a JSON object, the ``email`` key is absent,
            or its value is neither a string nor a list; 500 on an unexpected error
    """
    try:
        user_emails: dict[str, Any] | None = request.get_json(silent=True)

        if not isinstance(user_emails, dict):
            abort(400, "No valid JSON object payload provided!")

        cached_user_manager: CachedUserManager = CachedUserManager(current_app.database_manager)

        try:
            if isinstance(user_emails['email'], str):
                cached_user_manager.delete_cached_user(user_emails['email'])
            elif isinstance(user_emails['email'], list):
                cached_user_manager.delete_multiple_cached_users(user_emails['email'])
            else:
                abort(400, "'email' must be a string or list of strings!")

        except KeyError:
            abort(400, "'email' key not provided in the request payload!")

        return DefaultResponse(True).make_response()
    except HTTPException as http_err:
        raise http_err
    except Exception as err:
        LOGGER.error("[delete_cached_user] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while deleting a cached User!")


@setup_blueprint.route('/cache/user/all', methods=['DELETE'])
@verify_api_access(required_api_level=ApiLevel.SUPER_ADMIN)
def delete_all_cached_users() -> Response:
    """
    HTTP `DELETE` route to clear the entire cloud user cache

    Empties the ``cache.users`` collection, forcing every cloud user to be re-validated against the
    Service Portal on their next request

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
        abort(500, "An internal server error occured while deleting all cached Users!")
