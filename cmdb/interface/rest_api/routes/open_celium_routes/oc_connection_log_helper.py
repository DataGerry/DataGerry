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
Helper functions for the OpenCelium execution-log REST routes

The routes proxy OpenCelium's execution logs, so everything here works on another product's payload:
the shape is whatever that API answered, and a key may be absent or hold a null. Two jobs live here
so the routes can be tested without a Flask request context - reading the required query parameters,
and the cloud-mode rewrite of the connector names.

**The rewrite is why this module exists.** On a hosted installation every OpenCelium connector is
registered under a `<database>_<name>` prefix so tenants cannot see each other's, and the prefix has
to be stripped before a flowchart reaches a client. The rewrite used to sit inline in the route,
iterating the payload as a list of dicts while the manager annotated it as a dict, subscripting the
name unguarded, and unmapping in STRICT mode - so on a hosted installation it would have raised for a
payload of the annotated shape, for a flowchart without the key, and for a connector name carrying no
prefix. It had never been executed by a test, which is how all three survived.
"""
from logging import Logger, getLogger
from typing import Any

from flask import abort, current_app, request

from cmdb.manager import OcConnectionLogManager

from cmdb.models.user_model import CmdbUser

from cmdb.interface.rest_api.routes.open_celium_routes.oc_routes_constants import (
    OcLogQueryParam,
    OcResponseKey,
)

from cmdb.open_celium import unmap_oc_name
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# Answered when a required query parameter is absent, or present without a value
MISSING_QUERY_PARAM_MESSAGE: str = "The '{parameter}' was not provided!"


def build_connection_log_manager(request_user: CmdbUser) -> OcConnectionLogManager:
    """
    Builds the OcConnectionLogManager for the requesting user

    Every log route needs the same two arguments - the process-wide database manager and the caller's
    database, which is what selects the OpenCelium installation to talk to - so the construction lives
    here instead of six times in the route module

    Args:
        request_user (CmdbUser): The user making the request; its database scopes the manager

    Returns:
        OcConnectionLogManager: The manager to talk to OpenCelium with
    """
    return OcConnectionLogManager(current_app.database_manager, request_user.database)


def required_int_param_or_abort(parameter: OcLogQueryParam) -> int:
    """
    Reads a required integer query parameter, or answers 400

    Absence is what is refused, **not falsiness**: `?connectionId=0` used to be reported as "not
    provided", because the guard read the parsed value for truthiness. 0 is an id like any other as
    far as this proxy is concerned - OpenCelium decides whether it exists

    Args:
        parameter (OcLogQueryParam): The query parameter to read

    Raises:
        HTTPException: 400 when the parameter is absent or not a whole number

    Returns:
        int: The parameter's value
    """
    if parameter.value not in request.args:
        abort(400, MISSING_QUERY_PARAM_MESSAGE.format(parameter=parameter.value))

    value: int | None = request.args.get(parameter.value, type=int)

    if value is None:
        abort(400, f"The '{parameter.value}' has to be a whole number!")

    return value


def required_str_param_or_abort(parameter: OcLogQueryParam) -> str:
    """
    Reads a required non-empty string query parameter, or answers 400

    An empty value is refused with its own message: it was sent, so reporting it as "not provided"
    sends the caller looking for the wrong mistake

    Args:
        parameter (OcLogQueryParam): The query parameter to read

    Raises:
        HTTPException: 400 when the parameter is absent, or present but empty

    Returns:
        str: The parameter's value
    """
    if parameter.value not in request.args:
        abort(400, MISSING_QUERY_PARAM_MESSAGE.format(parameter=parameter.value))

    value: str = request.args.get(parameter.value, type=str) or ''

    if not value:
        abort(400, f"The '{parameter.value}' was empty!")

    return value


def _unmap_connector_name(flowchart: dict[str, Any]) -> None:
    """
    Strips the tenant prefix off one flowchart's connector name, in place

    Tolerant in both directions, because the payload is OpenCelium's: a flowchart without the key is
    left alone, and a name that carries no prefix is answered unchanged (`strict=False`) instead of
    raising - one unprefixed connector must not cost the whole log view

    Args:
        flowchart (dict[str, Any]): One flowchart of an execution log, edited in place
    """
    connector_name = flowchart.get(OcResponseKey.CONNECTOR_NAME.value)

    if not isinstance(connector_name, str):
        return

    unmapped = unmap_oc_name(connector_name, strict=False)

    if unmapped == connector_name and '_' not in connector_name:
        LOGGER.debug(
            "[unmap_flowchart_connector_names] Connector name '%s' carries no tenant prefix",
            connector_name,
        )

    flowchart[OcResponseKey.CONNECTOR_NAME.value] = unmapped


def unmap_flowchart_connector_names(flowcharts: Any) -> Any:
    """
    Rewrites the connector names of an execution log's flowcharts for a hosted installation

    The tenant prefix (`<database>_`) must not reach a client, and the payload is whatever OpenCelium
    answered: a LIST of flowcharts is what the endpoint returns in practice, a dict is what the
    manager's annotation claims, and both are handled - a dict is treated as one flowchart, or as a
    mapping of them when its values are dicts. Anything else is passed through untouched rather than
    raising, since a log view that cannot render is worse than one showing a prefixed name.

    Edits in place and answers the same payload, so a caller may use either

    Args:
        flowcharts (Any): The flowcharts as OpenCelium answered them

    Returns:
        Any: The same payload, with the connector names unprefixed where there were any
    """
    if isinstance(flowcharts, list):
        for flowchart in flowcharts:
            if isinstance(flowchart, dict):
                _unmap_connector_name(flowchart)

        return flowcharts

    if isinstance(flowcharts, dict):
        if OcResponseKey.CONNECTOR_NAME.value in flowcharts:
            _unmap_connector_name(flowcharts)

            return flowcharts

        for flowchart in flowcharts.values():
            if isinstance(flowchart, dict):
                _unmap_connector_name(flowchart)

        return flowcharts

    LOGGER.warning(
        "[unmap_flowchart_connector_names] Unexpected flowchart payload of type %s, left unchanged",
        type(flowcharts).__name__,
    )

    return flowcharts
