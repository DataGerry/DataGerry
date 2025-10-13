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
All API routes for OpenCelium Licenses
"""
from logging import Logger, getLogger
from typing import Any

from flask import abort
from werkzeug import Response

from cmdb.manager import OcLicenseManager

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

oc_licenses_blueprint = APIBlueprint('oc_licenses', __name__)

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

@oc_licenses_blueprint.route('/licenses/activation/generate', methods=['GET', 'HEAD'])
@handle_oc_errors("retrieving the OpenCelium License activation request!")
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
def get_oc_license_activation(request_user: CmdbUser) -> Response:
    """
    **GET**/**HEAD** route to retrive an OpenCelium license activation

    Args:
        request_user (CmdbUser): User requesting this data

    Returns:
        text file: The generated license activation
    """
    try:
        oc_license_manager: OcLicenseManager = OcLicenseManager()

        oc_license: Any = oc_license_manager.get_license_activation()

        return DefaultResponse(oc_license).make_response()
    except OcTemplateGetError as err:
        LOGGER.error("[get_oc_template] %s: %s.", type(err).__name__, err, exc_info=True)
        abort(500, "Failed to retrieve OpenCelium License activation!")
