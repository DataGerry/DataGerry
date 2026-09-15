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
Helper functions for the OpenCelium template REST routes

An OpenCelium *business template* is a reusable blueprint of a connection between two connectors.
DataGerry does not store them - the routes proxy OpenCelium over HTTP - so everything here works on
payloads that come from another product: the keys are OpenCelium's (`OcResponseKey`) and any level of
them can be missing or null.

Two of the three helpers exist so the routes can be tested without a Flask request context:
`datagerry_invoker_name` decides which invoker a template must name to count as DataGerry's own, and
`filter_datagerry_templates` applies that decision to a list.
"""
from typing import Any

from flask import current_app

from cmdb.manager import OcTemplateManager

from cmdb.models.user_model import CmdbUser

from cmdb.interface.rest_api.routes.open_celium_routes.oc_routes_constants import OcResponseKey

from cmdb.open_celium.oc_constants import OC_DATAGERRY_CLOUD_INVOKER_NAME, OC_DATAGERRY_INVOKER_NAME
# -------------------------------------------------------------------------------------------------------------------- #


def build_template_manager(request_user: CmdbUser) -> OcTemplateManager:
    """
    Builds the OcTemplateManager for the requesting user

    Every template route needs the same two arguments - the process-wide database manager and the
    caller's database - so the construction lives here instead of four times in the route module

    Args:
        request_user (CmdbUser): The user making the request; its database scopes the manager

    Returns:
        OcTemplateManager: The manager to talk to OpenCelium with
    """
    return OcTemplateManager(current_app.database_manager, request_user.database)


def datagerry_invoker_name() -> str:
    """
    Answers the invoker name that marks a business template as DataGerry's own

    A cloud installation is registered in OpenCelium under its own invoker, so the name differs -
    and getting it wrong does not fail, it simply matches nothing and answers an empty template
    list. The mode is read from the app at request time (see the cloud/local flags, which are set at
    process start)

    Returns:
        str: OC_DATAGERRY_CLOUD_INVOKER_NAME on a hosted cloud installation, otherwise
            OC_DATAGERRY_INVOKER_NAME
    """
    if current_app.cloud_mode and not current_app.local_mode:
        return OC_DATAGERRY_CLOUD_INVOKER_NAME

    return OC_DATAGERRY_INVOKER_NAME


def _connector_invoker_name(template: dict[str, Any], connector_key: str) -> Any:
    """
    Reads one connector's invoker name out of a template, tolerating a missing or null level

    The payload is OpenCelium's: `connection`, the connector block and its `invoker` may each be
    absent OR explicitly null, and a bare `.get(key, {})` chain raises AttributeError on the null
    case - which used to surface as a 500 for the whole template list

    Args:
        template (dict[str, Any]): One business template as OpenCelium answered it
        connector_key (str): Which side to read - OcResponseKey.FROM_CONNECTOR / TO_CONNECTOR

    Returns:
        Any: The invoker's name, or None when any level of the path is missing or not a mapping
    """
    node: Any = template

    for key in (OcResponseKey.CONNECTION.value, connector_key, OcResponseKey.INVOKER.value):
        if not isinstance(node, dict):
            return None

        node = node.get(key)

    if not isinstance(node, dict):
        return None

    return node.get(OcResponseKey.NAME.value)


def filter_datagerry_templates(
        templates: list[dict[str, Any]] | None,
        invoker_name: str) -> list[dict[str, Any]]:
    """
    Keeps the business templates that name the given invoker on either side of their connection

    Answers a LIST in every case, including for the `None` the manager returns when OpenCelium
    replies with an empty body - the route used to hand that null straight to the frontend on one of
    the two list routes while the other answered `[]`

    Args:
        templates (list[dict[str, Any]] | None): The templates OpenCelium answered, if any
        invoker_name (str): The invoker a template has to name - see `datagerry_invoker_name`

    Returns:
        list[dict[str, Any]]: The matching templates, in the order OpenCelium listed them
    """
    if not templates:
        return []

    return [
        template for template in templates
        if isinstance(template, dict)
        and invoker_name in (
            _connector_invoker_name(template, OcResponseKey.FROM_CONNECTOR.value),
            _connector_invoker_name(template, OcResponseKey.TO_CONNECTOR.value),
        )
    ]
