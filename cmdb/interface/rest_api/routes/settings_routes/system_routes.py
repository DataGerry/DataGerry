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
Implementation of DataGerry general system information API routes
"""
import sys
import time
from logging import Logger, getLogger
from typing import Any
from flask import abort
from werkzeug import Response

from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.manager import SettingsManager
from cmdb.manager.system_manager.system_config_reader import SystemConfigReader

from cmdb import __title__, __version__, __runtime__
from cmdb.interface.rest_api.routes.framework_routes.setting_routes import settings_blueprint
from cmdb.interface.route_utils import right_required, insert_request_user, verify_api_access
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.blueprints import NestedBlueprint
from cmdb.interface.rest_api.responses import DefaultResponse
from cmdb.models.user_model import CmdbUser
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

system_blueprint = NestedBlueprint(settings_blueprint, url_prefix='/system')

# -------------------------------------------------------------------------------------------------------------------- #

@system_blueprint.route('/', methods=['GET'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
def get_datagerry_information(request_user: CmdbUser) -> Response:
    """
    Gathers and returns basic information about the DataGerry system, including version,
    database version, runtime, and startup parameters

    Args:
        request_user (CmdbUser): The user making the request (used for permissions)

    Returns:
        Response: A Flask Response object containing a dictionary of system information
    """
    try:
        settings_manager: SettingsManager = ManagerProvider.get_manager(ManagerType.SETTINGS, request_user)

        try:
            db_version = settings_manager.get_all_values_from_section('updater').get('version')
        except Exception as err:
            LOGGER.error("[get_datagerry_information] Exception: %s. Type: %s", err, type(err), exc_info=True)
            db_version = 0

        datagerry_infos: dict[str, Any] = {
            'title': __title__,
            'version': __version__,
            'db_version': db_version,
            'runtime': (time.time() - __runtime__),
            'starting_parameters': sys.argv
        }

        return DefaultResponse(datagerry_infos).make_response()
    except Exception as err:
        LOGGER.error("[get_datagerry_information] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while gathering DataGerry information!")


@system_blueprint.route('/config/', methods=['GET'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
# request_user is injected for auth/permission checks; the body reads SystemConfigReader directly
@right_required('base.system.view')
def get_config_information(request_user: CmdbUser) -> Response:  # pylint: disable=unused-argument
    """
    Retrieves and returns the configuration information, including path and properties,
    of the system configuration file

    Args:
        request_user (CmdbUser): The user making the request (used for permissions)

    Returns:
        Response: A Flask Response object containing the configuration details
    """
    try:
        ssc = SystemConfigReader()

        # 'config_file' is only set when a config file is loaded; in config-less mode it is absent
        config_dict: dict[str, Any] = {
            'path': getattr(ssc, 'config_file', None),
            'properties': []
        }

        for section in ssc.get_sections():
            section_values = []

            for key, value in ssc.get_all_values_from_section(section).items():
                section_values.append([key, value])

            config_dict['properties'].append([section, section_values])

        return DefaultResponse(config_dict).make_response()
    except Exception as err:
        LOGGER.error("[get_config_information] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while gathering DataGerry config information!")
