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

**The paths are the portal's contract, spelled exactly as above: no trailing slash.** The API's ``strict_slashes``
is on, so ``/setup/subscriptions/`` is a 404, not a redirect. No slash is also the API's own majority form (the
collection roots and a handful of deduplicated routes are the exceptions), so the setup routes follow it; a second
spelling would only be one no caller uses

All three are destructive and meant to be called by the portal, not by end users. They are decorated
with ``verify_api_access(required_api_level=ApiLevel.SUPER_ADMIN)``, which authenticates a cloud-mode
Basic request against the Service Portal (the ``x-api-key`` required) and holds the portal account to
that level - and passes every other request through untouched: on-premise every request, in cloud mode a
request carrying a Bearer token. No route here carries ``insert_request_user`` or ``.protect`` - on purpose,
since no tenant user's token may tear down a tenant - so ``verify_api_access`` is the only authentication
these routes have, and it must be the one that runs.

**Which is why this surface is cloud-only, guarded twice, and portal-only**: on-premise ``verify_api_access`` is
a pass-through, so publishing these routes there would let an unauthenticated
``DELETE /rest/setup/subscriptions?database=<name>`` drop any database on the cluster; and in cloud mode a
Bearer-carrying request would reach them with nothing looking at the token.

* ``init_rest_api`` registers the blueprint **only when ``cmdb.__CLOUD_MODE__`` is set**. That is the
  primary control: outside cloud mode the surface does not exist, so there is nothing to reach.
* ``refuse_outside_cloud_mode`` below is a ``before_request`` on the blueprint - a **backstop**, for
  the case where the blueprint is registered by some other path (a test, a second app factory, a
  future refactor), and so that this rule is visible to a reader of this file.
* ``refuse_anything_but_portal_credentials`` is the second ``before_request``: in cloud mode only HTTP Basic -
  the portal's channel - reaches a handler (**401** otherwise), so ``verify_api_access`` always runs its portal
  check and the ``SUPER_ADMIN`` level.

All three are blueprint-wide on purpose. A route added here inherits them; a per-handler check would have
to be remembered, and a per-route guard can be inert in one mode without anything showing it.

And the teardown may only name a DataGerry tenant database (``setup_helper.assert_tenant_database``): MongoDB's own
databases, the shared user cache and the process's own database are refused, and so is any database DataGerry did
not create - one bad request from the portal's channel can no longer wipe every tenant's cache or another
application's data

**Every route answers a flat ``true`` on success, deliberately**: the Service Portal parses that body, and the
repository holds no description of what else it would read. What actually happened - the database dropped, how many
of the requested cache entries were evicted, how many the clear removed - is logged at INFO instead, so an operator
can tell "evicted 40" from "that address was not cached". An eviction request's addresses are normalised the way
every cloud entry point spells them (``setup_helper.read_target_emails``)
"""
from logging import Logger, getLogger
from flask import request, abort, current_app
from werkzeug import Response

from cmdb.manager import CachedUserManager

from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.rest_api.responses import DefaultResponse
from cmdb.interface.rest_api.routes.setup_routes.setup_constants import SetupMessage, SetupQueryParam
from cmdb.interface.rest_api.routes.setup_routes.setup_helper import assert_tenant_database, read_target_emails
from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.route_utils import (
    get_cached_user_manager,
    handle_route_errors,
    request_uses_basic_auth,
    verify_api_access,
)

from cmdb.errors.database import DatabaseNotFoundError, DatabaseConnectionError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

setup_blueprint = APIBlueprint('setup', __name__)

# Answered when the surface is reached outside cloud mode. 404 rather than 403: the routes serve the
# DataGerry Service Portal and do not exist for an on-premise installation, so "no such thing" is the
# honest answer and it matches what the unregistered blueprint already produces
NOT_IN_CLOUD_MODE_MESSAGE: str = "The setup routes are only available in the cloud version!"

# Answered to anything but the Service Portal's channel (HTTP Basic, checked by verify_api_access with the
# x-api-key). 401: the request did not authenticate the way this surface requires
PORTAL_CREDENTIALS_ONLY_MESSAGE: str = "The setup routes accept the Service Portal's credentials only!"


@setup_blueprint.before_request
def refuse_outside_cloud_mode() -> None:
    """
    Refuses every route on this blueprint when the process is not in cloud mode

    **A backstop, not the primary control.** `init_rest_api` does not register this blueprint outside
    cloud mode, so in normal operation this never runs: on-premise there is nothing to reach, and in
    cloud mode it passes. It exists for the case where the blueprint is registered by some other path
    and to keep the rule visible in the file it governs.

    Blueprint-wide rather than per-handler deliberately: a route added to this module inherits it,
    whereas a per-route guard has to be remembered and can be inert in one mode without anything
    showing it.

    Raises:
        HTTPException: 404 when the process does not run in cloud mode
    """
    if not current_app.cloud_mode:
        abort(404, NOT_IN_CLOUD_MODE_MESSAGE)


@setup_blueprint.before_request
def refuse_anything_but_portal_credentials() -> None:
    """
    Refuses every route on this blueprint unless it authenticates with HTTP Basic - the Service Portal's channel

    ``verify_api_access`` authenticates a Basic request against the portal (the ``x-api-key`` required) and holds the
    account to ``SUPER_ADMIN``; any other request it passes through untouched - a Bearer token is the frontend's
    channel, which every other route validates with ``insert_request_user`` and ``.protect``. The setup routes carry
    neither, on purpose: they belong to the portal, not to a tenant, so no tenant user's token - however privileged -
    may tear down a tenant. Without this guard a request carrying ``Authorization: Bearer <anything>`` reached the
    handlers with nothing looking at the token, and could drop any database on the cluster.

    Blueprint-wide like ``refuse_outside_cloud_mode``, and registered after it, so a route added to this module
    inherits it. The scheme is matched case-insensitively (``request_uses_basic_auth``); a lower-case ``basic``
    header passes here and is then refused by ``verify_api_access``, which reads the scheme as written

    Raises:
        HTTPException: 401 when the request carries no Basic credentials - no header, a Bearer token, or any other
            scheme
    """
    if not request_uses_basic_auth():
        abort(401, PORTAL_CREDENTIALS_ONLY_MESSAGE)

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

@setup_blueprint.route('/subscriptions', methods=['DELETE'])
@verify_api_access(required_api_level=ApiLevel.SUPER_ADMIN)
@handle_route_errors("while deleting the subscription")
def delete_subscription() -> Response:
    """
    HTTP `DELETE` route to drop the database backing a subscription

    Reads the target database name from the ``database`` query parameter (e.g.
    ``DELETE /setup/subscriptions?database=<name>``) and drops that database. Intended for the
    Service Portal to tear down a cancelled subscription's tenant database

    Only a DataGerry tenant database may be named (``setup_helper.assert_tenant_database``): never MongoDB's own
    databases, the shared user cache or the process's own database, and never a database without DataGerry's
    framework collections. The drop is logged (INFO); the answer stays the flat ``true`` the portal parses

    Returns:
        DefaultResponse: True after the database has been dropped

    Raises:
        HTTPException: 400 when the ``database`` query parameter is missing/empty, or names a reserved database,
            one which does not exist or one DataGerry did not create; 500 when the drop itself fails or on an
            unexpected error
    """
    subscription_database: str | None = request.args.get(SetupQueryParam.DATABASE)

    if not subscription_database:
        abort(400, SetupMessage.NO_DATABASE.value)

    assert_tenant_database(current_app.database_manager, subscription_database)

    try:
        current_app.database_manager.drop_database(subscription_database)
    except DatabaseNotFoundError:
        abort(400, SetupMessage.UNKNOWN_DATABASE.value.format(database=subscription_database))
    except DatabaseConnectionError as err:
        LOGGER.error("[delete_subscription] Error: %s, Type: %s", err, type(err))
        abort(500, "An issue occurred while deleting the subscription!")

    LOGGER.info("[delete_subscription] Dropped the database '%s'", subscription_database)

    return DefaultResponse(True).make_response()


@setup_blueprint.route('/cache/user', methods=['DELETE'])
@verify_api_access(required_api_level=ApiLevel.SUPER_ADMIN)
@handle_route_errors("while deleting a cached User")
def delete_cached_user() -> Response:
    """
    HTTP `DELETE` route to evict one or more cloud users from the local user cache

    Expects a JSON body ``{"email": <str | list[str]>}``: a non-empty string, or a non-empty list of non-empty
    strings. Each address is normalised the way every cloud entry point spells it before it reaches the cache
    (stripped, lower-cased) and evicted in one operation. Removing a user from ``cache.users`` forces the next
    request for that user to be re-validated against the Service Portal

    The answer is the flat ``true`` the Service Portal parses, also when an address was not cached; how many
    entries were actually removed is logged (INFO)

    Returns:
        DefaultResponse: True after the cached user(s) have been removed

    Raises:
        HTTPException: 400 when the body is missing / not a JSON object, the ``email`` key is absent, its value
            is neither a string nor a list, names no address, or holds an entry that is not a non-empty string;
            500 on an unexpected error
    """
    target_emails: list[str] = read_target_emails(request.get_json(silent=True))

    cached_user_manager: CachedUserManager = get_cached_user_manager()
    removed: int = cached_user_manager.delete_multiple_cached_users(target_emails)

    LOGGER.info("[delete_cached_user] Evicted %d of %d requested cached users", removed, len(target_emails))

    return DefaultResponse(True).make_response()


@setup_blueprint.route('/cache/user/all', methods=['DELETE'])
@verify_api_access(required_api_level=ApiLevel.SUPER_ADMIN)
@handle_route_errors("while deleting all cached Users")
def delete_all_cached_users() -> Response:
    """
    HTTP `DELETE` route to clear the entire cloud user cache

    Empties the ``cache.users`` collection, forcing every cloud user to be re-validated against the
    Service Portal on their next request. The answer is the flat ``true`` the portal parses; the number of
    removed entries is logged (INFO)

    Returns:
        DefaultResponse: True after the cache has been cleared

    Raises:
        HTTPException: 500 on an unexpected error while clearing the cache
    """
    cached_user_manager: CachedUserManager = get_cached_user_manager()

    removed: int = cached_user_manager.clear_cache()

    LOGGER.info("[delete_all_cached_users] Cleared %d cached users", removed)

    return DefaultResponse(True).make_response()
