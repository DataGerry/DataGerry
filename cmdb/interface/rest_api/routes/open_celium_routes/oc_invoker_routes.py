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
All API routes for OpenCelium invokers
"""
from logging import Logger, getLogger
from typing import Any

from flask import abort#, request
from werkzeug import Response
# from werkzeug.exceptions import HTTPException

from cmdb.manager import OcInvokerManager

from cmdb.models.user_model import CmdbUser
from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.route_utils import insert_request_user, verify_api_access, handle_oc_errors
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.rest_api.responses import DefaultResponse

from cmdb.errors.open_celium.invoker import (
    OcInvokerGetError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

oc_invokers_blueprint = APIBlueprint('oc_invokers', __name__)

# --------------------------------------------------- CRUD - CREATE -------------------------------------------------- #

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

@oc_invokers_blueprint.route('/invokers', methods=['GET', 'HEAD'])
@handle_oc_errors("retrieving OpenCelium Invokers!")
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
def get_all_oc_invokers(request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route for getting multiple OcInvokers

    Args:
        request_user (CmdbUser): User requesting this data

    Returns:
        list[dict[str, Any]]: All OcInvokers from OpenCelium
    """
    try:
        oc_invoker_manager: OcInvokerManager = OcInvokerManager()

        invokers: list[dict[str, Any]] = oc_invoker_manager.get_all_invokers()

        # LOGGER.debug(f"count invokers: {len(invokers)}")
        # LOGGER.debug(f"all invokers: {invokers}")

        return DefaultResponse(invokers).make_response()
    except OcInvokerGetError as err:
        LOGGER.error("[get_all_oc_invokers] OcInvokerGetError: %s.", err, exc_info=True)
        abort(500, "Failed to retrieve OpenCelium Invokers!")
