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

The instance's regional date settings (per tenant in cloud mode): the moment.js date format and the
moment-timezone name the frontend formats every date with.

* ``GET /date/`` is open to every authenticated user. It carries no right on purpose: the frontend's app-wide
  date pipe reads it for every account, and a right would leave every user without it unable to see a date.
  A stored value that is missing or unusable is answered as its default, one key at a time
* ``POST|PUT /date/`` needs ``base.system.edit`` and a body matching ``DateSettingsDAO.SCHEMA``: both values
  required, non-empty strings. Their content is not interpreted - only the frontend does that
"""
from logging import Logger, getLogger
from typing import Any

from flask import abort
from werkzeug import Response

from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.manager import SettingsManager
from cmdb.settings.date_settings import DateSettingsDAO
from cmdb.settings.date_settings_constants import DATE_SETTINGS_SECTION
from cmdb.models.user_model import CmdbUser
from cmdb.class_schema.write_schema_helper import build_write_schema
from cmdb.interface.rest_api.responses import DefaultResponse
from cmdb.interface.rest_api.routes.settings_routes.date_helper import build_date_settings
from cmdb.interface.route_utils import handle_route_errors, insert_request_user, verify_api_access
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.blueprints import APIBlueprint
# -------------------------------------------------------------------------------------------------------------------- #

date_blueprint = APIBlueprint('date', __name__)

LOGGER: Logger = getLogger(__name__)

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

@date_blueprint.route('/', methods=['GET'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@handle_route_errors("while retrieving the DateSettings")
def get_date_settings(request_user: CmdbUser) -> Response:
    """
    Retrieves the instance's date settings (the tenant's, in cloud mode)

    Open to every authenticated user - the frontend's date pipe needs it on every page. The defaults are
    answered when nothing is stored, and per key for a stored value that is missing or unusable

    Status codes:
        200 OK: ``{_id, date_format, timezone}``
        500: An unexpected error

    Args:
        request_user (CmdbUser): The user making the request; selects the tenant in cloud mode

    Returns:
        DefaultResponse: The HTTP response containing the date settings
    """
    settings_manager: SettingsManager = ManagerProvider.get_manager(ManagerType.SETTINGS, request_user)

    date_settings = settings_manager.get_all_values_from_section(
        DATE_SETTINGS_SECTION, DateSettingsDAO.__DEFAULT_SETTINGS__
    )

    date_settings = build_date_settings(date_settings)

    return DefaultResponse(date_settings).make_response()

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

@date_blueprint.route('/', methods=['POST', 'PUT'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@date_blueprint.protect(auth=True, right='base.system.edit')
@date_blueprint.validate(build_write_schema(DateSettingsDAO.SCHEMA))
@handle_route_errors("while updating the DateSettings")
def update_date_settings(data: dict[str, Any], request_user: CmdbUser) -> Response:
    """
    Updates the instance's date settings (the tenant's, in cloud mode)

    The body must match ``DateSettingsDAO.SCHEMA``: ``date_format`` and ``timezone`` both required, non-empty
    strings within their length caps. Any other key - an echoed ``_id`` among them - is dropped by the
    validator. The whole section is written, so both values are always stored

    Status codes:
        200 OK: The stored section
        400 BAD_REQUEST: The body fails the schema (the message names each failing key), or the write was
            not acknowledged
        500: An unexpected error

    Args:
        data (dict[str, Any]): The validated body
        request_user (CmdbUser): The user making the request; selects the tenant in cloud mode

    Returns:
        DefaultResponse: The HTTP response containing the stored date settings
    """
    settings_manager: SettingsManager = ManagerProvider.get_manager(ManagerType.SETTINGS, request_user)

    new_date_settings_instance = build_date_settings(data)

    update_result = settings_manager.write(_id=DATE_SETTINGS_SECTION, data=new_date_settings_instance.to_json())

    if update_result.acknowledged:
        return DefaultResponse(settings_manager.get_section(DATE_SETTINGS_SECTION)).make_response()

    abort(400, 'Could not update the DateSettings')
