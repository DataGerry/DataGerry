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
All API routes for OpenCelium Templates

An OpenCelium *business template* is a reusable blueprint of a connection between two connectors.
DataGerry stores none of them: every route here is a thin proxy to OpenCelium over HTTP, so the
payloads are another product's shapes (`OcResponseKey`) and the manager can answer `None` when
OpenCelium replies with an empty body - which is why the list routes normalise through
`filter_datagerry_templates` rather than answering what they were handed.

The blueprint is license-gated as part of the `AUTOMATIONS` feature (see `init_rest_api`), but it
carries no per-route ACL right - unlike the sibling connection and connector routes. That gap, and
the missing request-schema validation on the create route, are discussion-backlog #115 (the rights
it would need do not exist yet).

**Only one of the four routes has a frontend caller**: `GET /templates/all/<from>/<to>`, used by the
Automations view (`automations.service.ts`). The other three are API-only surface.
"""
from logging import Logger, getLogger
from typing import Any

from flask import abort, request
from werkzeug import Response
from werkzeug.exceptions import HTTPException

from cmdb.manager import OcTemplateManager

from cmdb.models.user_model import CmdbUser
from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.route_utils import insert_request_user, verify_api_access, handle_oc_errors
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.rest_api.responses import DefaultResponse
from cmdb.interface.rest_api.routes.routes_helper import request_wants_body
from cmdb.interface.rest_api.routes.open_celium_routes.oc_template_helper import (
    build_template_manager,
    datagerry_invoker_name,
    filter_datagerry_templates,
)

from cmdb.errors.open_celium.template import (
    OcTemplateCreateError,
    OcTemplateGetError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

oc_templates_blueprint = APIBlueprint('oc_templates', __name__)

# --------------------------------------------------- CRUD - CREATE -------------------------------------------------- #

@oc_templates_blueprint.route('/templates', methods=['POST'])
@handle_oc_errors("creating the OpenCelium Template!")
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
def create_oc_template(request_user: CmdbUser) -> Response:
    """
    **POST** route to create an OcTemplate

    The body is forwarded to OpenCelium unvalidated - it is an OpenCelium template shape, not a
    DataGerry document (see the module docstring and backlog #115). A body that is not JSON at all is
    refused by `request.json` with a 400, which is the one HTTPException this route can raise itself.

    Args:
        request_user (CmdbUser): User requesting this data

    Returns:
        Response: The created OcTemplate as OpenCelium answered it
    """
    try:
        oc_template_manager: OcTemplateManager = build_template_manager(request_user)

        template_data: dict[str, Any] = request.json

        created_template: dict[str, Any] = oc_template_manager.create_template(template_data)

        return DefaultResponse(created_template).make_response()
    except HTTPException as http_err:
        # request.json answers a malformed body with a 400; the outer handle_oc_errors would
        # re-raise it as well, but this route is the only one that can produce one at all
        raise http_err
    except OcTemplateCreateError as err:
        LOGGER.error("[create_oc_template] %s: %s.", type(err).__name__, err, exc_info=True)
        abort(500, "Failed to create the OpenCelium Template!")

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

@oc_templates_blueprint.route('/templates/<string:template_id>', methods=['GET', 'HEAD'])
@handle_oc_errors("retrieving the OpenCelium Template!")
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
def get_oc_template(request_user: CmdbUser, template_id: str) -> Response:
    """
    **GET**/**HEAD** route to retrive a OcTemplate with the given template_id

    Args:
        request_user (CmdbUser): User requesting this data
        template_id (str): templateId of the OcTemplate

    Returns:
        Response: The OcTemplate as OpenCelium answered it
    """
    try:
        oc_template_manager: OcTemplateManager = build_template_manager(request_user)

        template: dict[str, Any] = oc_template_manager.get_template_by_id(template_id)

        return DefaultResponse(template, body=request_wants_body()).make_response()
    except OcTemplateGetError as err:
        LOGGER.error("[get_oc_template] %s: %s.", type(err).__name__, err, exc_info=True)
        abort(500, f"Failed to retrieve OpenCelium Template with ID:{template_id}!")


@oc_templates_blueprint.route('/templates', methods=['GET', 'HEAD'])
@handle_oc_errors("retrieving OpenCelium Business Templates!")
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
def get_all_oc_templates(request_user: CmdbUser) -> Response:
    """
    **GET**/**HEAD** route for getting every OcBusinessTemplate OpenCelium knows

    Unfiltered, unlike `get_all_oc_templates_detailed`: this route answers what OpenCelium lists,
    including templates authored by other invokers. An empty list is the answer when OpenCelium has
    none - the manager reports that as `None`, which never reaches the response.

    Args:
        request_user (CmdbUser): User requesting this data

    Returns:
        Response: All OcBusinessTemplates from OpenCelium, or an empty list
    """
    try:
        oc_template_manager: OcTemplateManager = build_template_manager(request_user)

        templates: list[dict[str, Any]] | None = oc_template_manager.get_all_templates()

        return DefaultResponse(templates or [], body=request_wants_body()).make_response()
    except OcTemplateGetError as err:
        LOGGER.error("[get_all_oc_templates] %s: %s.", type(err).__name__, err, exc_info=True)
        abort(500, "Failed to retrieve OpenCelium Templates!")


@oc_templates_blueprint.route('/templates/all/<int:from_connector_id>/<int:to_connector_id>', methods=['GET', 'HEAD'])
@handle_oc_errors("retrieving detailed OpenCelium Business Templates!")
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
def get_all_oc_templates_detailed(
        request_user: CmdbUser,
        from_connector_id: int,
        to_connector_id: int
    ) -> Response:
    """
    **GET**/**HEAD** route for the OcBusinessTemplates of one connector pair, DataGerry's own only

    The Automations view offers these as starting points for a new connection, so a template
    authored by an unrelated invoker would be useless here: the result is filtered to the templates
    that name DataGerry's invoker on either side of their connection. **A hosted cloud installation
    is registered under a different invoker name** (`datagerry_invoker_name`), and picking the wrong
    one answers an empty list rather than an error.

    Args:
        request_user (CmdbUser): User requesting this data
        from_connector_id (int): fromConnectorId
        to_connector_id (int): toConnectorId

    Returns:
        Response: The DataGerry OcBusinessTemplates of that connector pair, or an empty list
    """
    try:
        oc_template_manager: OcTemplateManager = build_template_manager(request_user)

        templates: list[dict[str, Any]] | None = oc_template_manager.get_all_templates(
            from_connector_id,
            to_connector_id,
        )

        datagerry_templates: list[dict[str, Any]] = filter_datagerry_templates(
            templates,
            datagerry_invoker_name(),
        )

        return DefaultResponse(datagerry_templates, body=request_wants_body()).make_response()
    except OcTemplateGetError as err:
        LOGGER.error("[get_all_oc_templates_detailed] %s: %s.", type(err).__name__, err, exc_info=True)
        abort(500, "Failed to retrieve OpenCelium detailed Templates!")
