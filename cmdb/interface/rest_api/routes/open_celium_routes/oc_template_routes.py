# DataGerry - OpenSource Enterprise CMDB
# Copyright (C) 2025 becon GmbH
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
"""
from logging import Logger, getLogger
from typing import Any

from flask import abort
from werkzeug import Response

from cmdb.manager import OcTemplateManager

from cmdb.models.user_model import CmdbUser
from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.route_utils import insert_request_user, verify_api_access, handle_oc_errors
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.rest_api.responses import DefaultResponse

from cmdb.errors.open_celium.template import (
    OcTemplateGetError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

oc_templates_blueprint = APIBlueprint('oc_templates', __name__)

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

@oc_templates_blueprint.route('/templates/<int:template_id>', methods=['GET', 'HEAD'])
@handle_oc_errors("retrieving the OpenCelium Template!")
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
def get_oc_template(request_user: CmdbUser, template_id: int) -> Response:
    """
    **GET**/**HEAD** route to retrive a OcTemplate with the given template_id

    Args:
        request_user (CmdbUser): User requesting this data
        template_id (int): templateId of the OcTemplate

    Returns:
        dict[str, Any]: The OcTemplate from OpenCelium
    """
    try:
        oc_template_manager: OcTemplateManager = OcTemplateManager()

        template: dict[str, Any] = oc_template_manager.get_template_by_id(template_id)

        # LOGGER.debug(f"template: {template}")

        return DefaultResponse(template).make_response()
    except OcTemplateGetError as err:
        LOGGER.error("[get_oc_template] %s: %s.", type(err).__name__, err, exc_info=True)
        abort(500, f"Failed to retrieve OpenCelium Connector with ID:{template_id}!")


@oc_templates_blueprint.route('/templates', methods=['GET', 'HEAD'])
@handle_oc_errors("retrieving OpenCelium Business Templates!")
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
def get_all_oc_templates(request_user: CmdbUser) -> list[dict[str, Any]]:
    """
    **GET**/**HEAD** route for getting multiple OcBusinessTemplates

    Args:
        request_user (CmdbUser): User requesting this data

    Returns:
        list[dict[str, Any]]: All OcBusinessTemplates from OpenCelium
    """
    try:
        oc_template_manager: OcTemplateManager = OcTemplateManager()

        templates: list[dict[str, Any]] = oc_template_manager.get_all_templates()

        # LOGGER.debug(f"count templates: {len(templates)}")
        # LOGGER.debug(f"all templates: {templates}")

        return DefaultResponse(templates).make_response()
    except OcTemplateGetError as err:
        LOGGER.error("[get_all_oc_templates] %s: %s.", type(err).__name__, err, exc_info=True)
        abort(500, "Failed to retrieve OpenCelium Business Templates!")
