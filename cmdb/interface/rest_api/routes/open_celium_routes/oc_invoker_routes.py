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
All API routes for OpenCelium Invokers

An **invoker** is the OpenCelium plugin that knows how to talk to a given system - its endpoints, its
authentication, the operations it offers. A connector is one configured instance of an invoker, which
is why the connector form has to list them. DataGerry itself is registered as an invoker in
OpenCelium, and that registration is what a business template is filtered by (see
`oc_template_helper.datagerry_invoker_name`).

All three routes are **read-only proxies**: DataGerry stores no invokers, and OpenCelium answers
whatever it answers. The blueprint is license-gated as part of the `AUTOMATIONS` feature (see
`init_rest_api`) and carries no per-route ACL right, unlike the sibling connection and connector
routes - discussion-backlog #115 lists this file by name and records that the rights it would need do
not exist yet.

**Only the list route has a frontend caller**: `GET /invokers`, read once per connector form through
the connectors resolver (`connectors.service.ts`), which sends no query parameters at all. The
name-lookup and exists routes are API-only surface, and nothing in the backend calls their manager
methods either.
"""
from logging import Logger, getLogger
from typing import Any

from flask import abort
from werkzeug import Response

from cmdb.manager import OcInvokerManager

from cmdb.models.user_model import CmdbUser
from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.route_utils import insert_request_user, verify_api_access, handle_oc_errors
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.rest_api.responses import DefaultResponse
from cmdb.interface.rest_api.routes.open_celium_routes.oc_invoker_helper import (
    build_invoker_manager,
    read_ops_included_flag,
)

from cmdb.errors.open_celium.invoker import (
    OcInvokerGetError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

oc_invokers_blueprint = APIBlueprint('oc_invokers', __name__)

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

@oc_invokers_blueprint.route('/invokers', methods=['GET', 'HEAD'])
@handle_oc_errors("retrieving OpenCelium Invokers!")
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
def get_all_oc_invokers(request_user: CmdbUser) -> Response:
    """
    **GET**/**HEAD** route for getting every OcInvoker OpenCelium offers

    Accepts **`?opsIncluded=false`** to ask for the invokers without their operations - a smaller
    answer for a caller that only needs the names. Operations are included by default, and only that
    literal value turns them off; see `read_ops_included_flag` for the rule and the open question
    about other spellings

    Args:
        request_user (CmdbUser): User requesting this data

    Returns:
        Response: All OcInvokers as OpenCelium answered them
    """
    try:
        with_operations: bool = read_ops_included_flag()

        oc_invoker_manager: OcInvokerManager = build_invoker_manager(request_user)

        invokers: list[dict[str, Any]] = oc_invoker_manager.get_all_invokers(with_operations)

        return DefaultResponse(invokers).make_response()
    except OcInvokerGetError as err:
        LOGGER.error("[get_all_oc_invokers] OcInvokerGetError: %s.", err, exc_info=True)
        abort(500, "Failed to retrieve OpenCelium Invokers!")


@oc_invokers_blueprint.route('/invokers/<string:name>', methods=['GET', 'HEAD'])
@handle_oc_errors("retrieving OpenCelium Invokers!")
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
def get_oc_invoker_by_name(request_user: CmdbUser, name: str) -> Response:
    """
    **GET**/**HEAD** route to retrieve one Invoker by name

    The name is URL-encoded on the way to OpenCelium. An empty one cannot reach this route - the
    `<string:name>` converter does not match an empty segment - so the manager's own "no name"
    guard is reachable only from other Python callers

    Args:
        request_user (CmdbUser): User requesting this data
        name (str): name of the Invoker

    Returns:
        Response: The Invoker as OpenCelium answered it
    """
    try:
        oc_invoker_manager: OcInvokerManager = build_invoker_manager(request_user)

        invoker: dict[str, Any] = oc_invoker_manager.get_invoker_by_name(name)

        return DefaultResponse(invoker).make_response()
    except OcInvokerGetError as err:
        LOGGER.error("[get_oc_invoker_by_name] OcInvokerGetError: %s.", err, exc_info=True)
        abort(500, f"Failed to retrieve OpenCelium Invoker with name: {name}!")


@oc_invokers_blueprint.route('/invokers/exists/<string:name>', methods=['GET', 'HEAD'])
@handle_oc_errors("checking OpenCelium Invoker exists!")
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
def check_oc_invoker_exists(request_user: CmdbUser, name: str) -> Response:
    """
    **GET**/**HEAD** route to check whether an Invoker with the given name exists

    Answers a **bare `true` / `false`**, not an object - the same shape as the connector-exists route
    beside it, and a frontend-visible contract

    Args:
        request_user (CmdbUser): User requesting this data
        name (str): name of the Invoker

    Returns:
        Response: True if the Invoker exists, else False
    """
    try:
        oc_invoker_manager: OcInvokerManager = build_invoker_manager(request_user)

        invoker_exists: bool = oc_invoker_manager.check_invoker_exists(name)

        return DefaultResponse(invoker_exists).make_response()
    except OcInvokerGetError as err:
        LOGGER.error("[check_oc_invoker_exists] OcInvokerGetError: %s.", err, exc_info=True)
        abort(500, f"Failed to check if the OpenCelium Invoker with name: '{name}' exists!")
