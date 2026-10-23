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

Four read-only endpoints. Two behind ``base.system.view``:

    - ``GET /settings/system/``: the build (title, version), the tenant's database schema version, and on
      premise the process uptime and the command line it was started with (``system_helper``). In cloud mode the
      last two are left out - they belong to the host process every tenant shares. The frontend's System page
      shows all of it; the version alone is public through the unauthenticated ``GET /rest/``
    - ``GET /settings/system/config/``: the loaded configuration file

and two for every authenticated user, without a right:

    - ``GET /settings/system/deployment/``: on premise or cloud, the build version, whether the database answered,
      and the machine's name (on premise only). It answers nothing a logged-in user may not know: the version is
      public through ``GET /rest/`` anyway, and in cloud mode the shared machine stays unnamed
    - ``GET /settings/system/limits/``: the largest request body and the largest upload the REST API accepts, in
      bytes - so an upload form can refuse a file that is too large before sending it

The blueprint is mounted by init_rest_api at ``/settings/system``, so this module is self-contained - it can be
imported without an application context and without a parent blueprint
"""
from logging import Logger, getLogger
from typing import Any
from flask import current_app
from werkzeug import Response

from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.manager import SettingsManager
from cmdb.manager.system_manager.system_config_reader import SystemConfigReader

from cmdb.interface.route_utils import handle_route_errors, insert_request_user, verify_api_access
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.rest_api.responses import DefaultResponse
from cmdb.models.user_model import CmdbUser
from cmdb.interface.rest_api.routes.settings_routes.system_constants import SYSTEM_VIEW_RIGHT, SystemConfigKey
from cmdb.interface.rest_api.routes.settings_routes.system_helper import (
    build_deployment_information,
    build_request_limits,
    build_system_information,
    read_db_version,
    read_host_name,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

system_blueprint = APIBlueprint('system', __name__)

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

@system_blueprint.route('/', methods=['GET'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@system_blueprint.protect(auth=True, right=SYSTEM_VIEW_RIGHT)
@handle_route_errors("while gathering the DataGerry system information")
def get_datagerry_information(request_user: CmdbUser) -> Response:
    """
    Returns basic information about the DataGerry system

    Reports the build (title / version) and the database schema version recorded by the updater; on premise also
    how long the process has been running (seconds) and the parameters it was started with (``sys.argv``: the
    mode flags and the config path). In cloud mode those two are left out, as they describe the host process.
    An unreadable updater version is reported as UNKNOWN_DB_VERSION rather than failing the request

    Args:
        request_user (CmdbUser): The requesting user, used to resolve the tenant-scoped manager

    Raises:
        HTTPException: 403 without ``base.system.view``, 500 if the information could not be gathered

    Returns:
        Response: A Flask Response object containing a dictionary of system information
    """
    settings_manager: SettingsManager = ManagerProvider.get_manager(ManagerType.SETTINGS, request_user)

    information: dict[str, Any] = build_system_information(read_db_version(settings_manager),
                                                           current_app.cloud_mode)

    return DefaultResponse(information).make_response()


@system_blueprint.route('/config/', methods=['GET'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@system_blueprint.protect(auth=True, right=SYSTEM_VIEW_RIGHT)
@handle_route_errors("while gathering the DataGerry config information")
def get_config_information(request_user: CmdbUser) -> Response:
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


@system_blueprint.route('/deployment/', methods=['GET'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@handle_route_errors("while gathering the DataGerry deployment information")
def get_deployment_information(request_user: CmdbUser) -> Response:
    """
    Returns how and where this DataGerry runs: the deployment, the version, the database and the machine

    Any authenticated user may read it - ``insert_request_user`` is the gate, there is no right. ``database_reachable``
    is the live probe of ``GET /rest/``; on this route it is in practice always true, because the request user is
    read from the database before the route runs, so an unreachable database fails the request first.
    ``host_name`` is null in cloud mode, where the machine is shared by every tenant

    Args:
        request_user (CmdbUser): The authenticated user; the route reads nothing of it

    Raises:
        HTTPException: 500 if the information could not be gathered

    Returns:
        Response: ``deployment``, ``version``, ``database_reachable`` and ``host_name``
    """
    cloud_mode: bool = current_app.cloud_mode
    information: dict[str, Any] = build_deployment_information(
        cloud_mode, current_app.database_manager.status(), read_host_name(cloud_mode),
    )

    return DefaultResponse(information).make_response()


@system_blueprint.route('/limits/', methods=['GET'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@handle_route_errors("while reading the request size limits")
def get_request_limits(request_user: CmdbUser) -> Response:
    """
    Returns the request size limits of the REST API, in bytes

    Any authenticated user may read it - ``insert_request_user`` is the gate, there is no right: every upload form
    needs it, whichever feature it belongs to. A reverse proxy in front of DataGerry may refuse smaller bodies; that
    limit is not seen here

    Args:
        request_user (CmdbUser): The authenticated user; the route reads nothing of it

    Raises:
        HTTPException: 500 on an unexpected error

    Returns:
        Response: ``max_request_size`` and ``max_upload_size``
    """
    return DefaultResponse(build_request_limits()).make_response()
