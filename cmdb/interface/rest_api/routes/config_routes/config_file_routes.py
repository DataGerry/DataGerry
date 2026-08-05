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
Implementation of all config file API routes
"""
from logging import Logger, getLogger

from flask import abort
from werkzeug import Response

from cmdb.manager.system_manager.system_config_reader import SystemConfigReader

from cmdb.models.user_model import CmdbUser
from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.route_utils import insert_request_user, verify_api_access
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.rest_api.responses import DefaultResponse

from cmdb.errors.system_config import SectionError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

config_file_blueprint = APIBlueprint('config_file', __name__)

# --------------------------------------------------- CRUD - CREATE -------------------------------------------------- #

@config_file_blueprint.route('/status/opencelium', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
def get_oc_config_status(request_user: CmdbUser) -> Response:
    """
    Checks if the status of OpenCelium in the config file cmdb.conf


    Returns:
        DefaultResponse: Status of the config file
    """
    try:
        config_state: dict[str, bool] = {
            "status": False,
            "section": True,
            "host": False,
            "port": False,
            "protocol": False,
            "email": False,
            "user": False,
            "password": False,
        }

        scr = SystemConfigReader()
        section = "OpenCelium"

        # String-based fields
        string_fields = ["host", "protocol", "email", "user", "password"]

        for field in string_fields:
            value = scr.get_value(field, section)
            config_state[field] = bool(value)

        # Port handling (numeric)
        port_value = scr.get_value("port", section)
        try:
            port = int(port_value)
            config_state["port"] = port > 0
        except (TypeError, ValueError):
            config_state["port"] = False

        # Overall status
        config_state["status"] = all(
            config_state[field]
            for field in ["host", "port", "protocol", "email", "user", "password"]
        )

        return DefaultResponse(config_state).make_response()
    except SectionError:
        config_state["section"] = False
        return DefaultResponse(config_state).make_response()
    except Exception as err:
        LOGGER.error("[get_oc_config_status] Exception: %s. Type: %s", err, type(err).__name__, exc_info=True)
        abort(500, "An internal server error occured while checking the config file status for OpenCelium!")
