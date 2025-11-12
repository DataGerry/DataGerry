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

from flask import abort, request
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
@verify_api_access(required_api_level=ApiLevel.LOCKED)
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
        LOGGER.error("[get_oc_license_activation] %s: %s.", type(err).__name__, err, exc_info=True)
        abort(500, "Failed to retrieve OpenCelium License activation!")


@oc_licenses_blueprint.route('/licenses/info', methods=['GET', 'HEAD'])
@handle_oc_errors("retrieving the OpenCelium License info!")
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
def get_oc_license_info(request_user: CmdbUser) -> Response:
    """
    **GET**/**HEAD** route to retrive an OpenCelium license info

    Args:
        request_user (CmdbUser): User requesting this data

    Returns:
        dict[str, Any]: The license info
    """
    try:
        params: dict[str, str] = request.args.to_dict()

        page = int(params.get('page', 0))
        size = int(params.get('size', 5))

        oc_license_manager: OcLicenseManager = OcLicenseManager()

        license_data: dict[str, Any] = {
            'license': oc_license_manager.get_active_license(),
            'usage': oc_license_manager.get_license_usage(page, size),
        }

        return DefaultResponse(license_data).make_response()
    except OcTemplateGetError as err:
        LOGGER.error("[get_oc_license_info] %s: %s.", type(err).__name__, err, exc_info=True)
        abort(500, "Failed to retrieve OpenCelium License info!")
