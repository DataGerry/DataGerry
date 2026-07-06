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
Implementation of all API routes for DateSettings
"""
from logging import Logger, getLogger

from flask import request, abort
from werkzeug import Response
from werkzeug.exceptions import HTTPException

from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.manager import SettingsManager
from cmdb.settings.date_settings import DateSettingsDAO
from cmdb.models.user_model import CmdbUser
from cmdb.interface.rest_api.responses import DefaultResponse
from cmdb.interface.rest_api.routes.settings_routes.date_helper import build_date_settings
from cmdb.interface.route_utils import insert_request_user, verify_api_access
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.blueprints import APIBlueprint
# -------------------------------------------------------------------------------------------------------------------- #

date_blueprint = APIBlueprint('date', __name__)

LOGGER: Logger = getLogger(__name__)

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

@date_blueprint.route('/', methods=['GET'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
def get_date_settings(request_user: CmdbUser) -> Response:
    """
    Retrieves the date-related settings for the current user

    Args:
        request_user (CmdbUser): The user making the request

    Returns:
        DefaultResponse: The HTTP response containing the date settings
    """
    try:
        settings_manager: SettingsManager = ManagerProvider.get_manager(ManagerType.SETTINGS, request_user)

        date_settings = settings_manager.get_all_values_from_section('date', DateSettingsDAO.__DEFAULT_SETTINGS__)

        date_settings = build_date_settings(date_settings)

        return DefaultResponse(date_settings).make_response()
    except HTTPException as http_err:
        raise http_err
    except Exception as err:
        LOGGER.error("[get_date_settings] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while retrieving the DateSettings!")

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

@date_blueprint.route('/', methods=['POST', 'PUT'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@date_blueprint.protect(auth=True, right='base.system.edit')
def update_date_settings(request_user: CmdbUser) -> Response:
    """
    Updates the date-related settings for the current user

    Args:
        request_user (CmdbUser): The user making the request

    Returns:
        DefaultResponse: The HTTP response containing the updated date settings, or an error message
    """
    try:
        new_date_settings_values = request.get_json()

        settings_manager: SettingsManager = ManagerProvider.get_manager(ManagerType.SETTINGS, request_user)

        if not new_date_settings_values:
            abort(400, 'No new data was provided')

        new_date_settings_instance = build_date_settings(new_date_settings_values)

        update_result = settings_manager.write(_id='date', data=new_date_settings_instance.__dict__)

        if update_result.acknowledged:
            return DefaultResponse(settings_manager.get_section('date')).make_response()

        abort(400, 'Could not update the DateSettings')
    except HTTPException as http_err:
        raise http_err
    except Exception as err:
        LOGGER.error("[update_date_settings] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while updating the DateSettings!")
