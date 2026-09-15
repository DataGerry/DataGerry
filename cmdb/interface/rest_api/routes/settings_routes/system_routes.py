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

Exposes the two read-only system endpoints the frontend's System page uses: `GET /settings/system/`
(build / runtime information) and `GET /settings/system/config/` (the loaded configuration file). The
blueprint is mounted by init_rest_api at `/settings/system`, so this module is self-contained - it can
be imported without an application context and without a parent blueprint
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
from cmdb.interface.route_utils import insert_request_user, verify_api_access
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.rest_api.responses import DefaultResponse
from cmdb.models.user_model import CmdbUser
from cmdb.interface.rest_api.routes.settings_routes.system_constants import (
    SYSTEM_VIEW_RIGHT,
    UPDATER_SETTINGS_SECTION,
    UNKNOWN_DB_VERSION,
    SystemInfoKey,
    SystemConfigKey,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

system_blueprint = APIBlueprint('system', __name__)

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

@system_blueprint.route('/', methods=['GET'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
def get_datagerry_information(request_user: CmdbUser) -> Response:
    """
    Returns basic information about the DataGerry system

    Reports the build (title / version), the database schema version recorded by the updater, how long
    the process has been running and the parameters it was started with. An unreadable updater version
    is reported as UNKNOWN_DB_VERSION rather than failing the request, since the rest of the
    information is still valid

    Args:
        request_user (CmdbUser): The requesting user, used to resolve the tenant-scoped manager

    Raises:
        HTTPException: 500 if the information could not be gathered

    Returns:
        Response: A Flask Response object containing a dictionary of system information
    """
    try:
        settings_manager: SettingsManager = ManagerProvider.get_manager(ManagerType.SETTINGS, request_user)

        try:
            db_version = settings_manager.get_all_values_from_section(UPDATER_SETTINGS_SECTION)\
                .get(SystemInfoKey.VERSION.value)
        except Exception as err:
            LOGGER.error("[get_datagerry_information] Exception: %s. Type: %s", err, type(err), exc_info=True)
            db_version = UNKNOWN_DB_VERSION

        datagerry_infos: dict[str, Any] = {
            SystemInfoKey.TITLE.value: __title__,
            SystemInfoKey.VERSION.value: __version__,
            SystemInfoKey.DB_VERSION.value: db_version,
            SystemInfoKey.RUNTIME.value: (time.time() - __runtime__),
            SystemInfoKey.STARTING_PARAMETERS.value: sys.argv,
        }

        return DefaultResponse(datagerry_infos).make_response()
    except Exception as err:
        LOGGER.error("[get_datagerry_information] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while gathering DataGerry information!")


@system_blueprint.route('/config/', methods=['GET'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@system_blueprint.protect(auth=True, right=SYSTEM_VIEW_RIGHT)
def get_config_information(request_user: CmdbUser) -> Response:  # pylint: disable=unused-argument
    """
    Returns the loaded system configuration file: its path and every section it defines

    The sections are emitted as `[section name, [[key, value], ...]]` pairs, in the order the reader
    reports them. `path` is None when the process runs config-file-less (environment variables only)

    Args:
        request_user (CmdbUser): The requesting user; unused in the body - the right is enforced by
                                 the `protect` decorator, which needs the user injected above it

    Raises:
        HTTPException: 403 if the user lacks the system-view right, 500 if the configuration could
                       not be read

    Returns:
        Response: A Flask Response object containing the configuration details
    """
    try:
        ssc = SystemConfigReader()

        # 'config_file' is only set when a config file is loaded; in config-less mode it is absent
        config_dict: dict[str, Any] = {
            SystemConfigKey.PATH.value: getattr(ssc, 'config_file', None),
            SystemConfigKey.PROPERTIES.value: [],
        }

        for section in ssc.get_sections():
            section_values = [[key, value] for key, value in ssc.get_all_values_from_section(section).items()]
            config_dict[SystemConfigKey.PROPERTIES.value].append([section, section_values])

        return DefaultResponse(config_dict).make_response()
    except Exception as err:
        LOGGER.error("[get_config_information] Exception: %s. Type: %s", err, type(err), exc_info=True)
        abort(500, "An internal server error occured while gathering DataGerry config information!")
