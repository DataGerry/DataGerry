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
Implementation of the config-file status API routes

Currently holds a single read-only route reporting whether the on-premise `[OpenCelium]` section of
`etc/cmdb.conf` is complete enough for DataGerry to talk to OpenCelium. Only booleans are reported -
the configured values themselves never leave the backend

The route is gated on the Automations licence on its own (``requires_feature``), not through the blueprint: the
blueprint is the home of every config-file status route, and a status route for another section must not inherit
the OpenCelium route's licence. It asks for ``base.openCelium.connection.view`` (``OcRight``), the right every
OpenCelium read asks for - the automations list, the one page that reads it, is guarded by the same right
"""
from logging import Logger, getLogger
from typing import Any

from flask import current_app
from werkzeug import Response

from cmdb.manager.system_manager.system_config_reader import SystemConfigReader

from cmdb.models.user_model import CmdbUser
from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.route_utils import handle_route_errors, insert_request_user, verify_api_access
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.rest_api.responses import DefaultResponse
from cmdb.interface.rest_api.routes.cmdb_license.license_guard import requires_feature
from cmdb.interface.rest_api.routes.open_celium_routes.oc_routes_constants import OcRight
from cmdb.interface.rest_api.routes.config_routes.config_file_constants import OcConfigStatusKey
from cmdb.open_celium.oc_config_rules import oc_setting_flags
from cmdb.open_celium.oc_constants import OC_CONFIG_KEYS, OC_CONFIG_SECTION
from cmdb.security.license.license_constants import LicenseFeature

from cmdb.errors.system_config import ConfigNotLoaded, SectionError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

config_file_blueprint = APIBlueprint('config_file', __name__)

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

@config_file_blueprint.route('/status/opencelium', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@config_file_blueprint.protect(auth=True, right=OcRight.CONNECTION_VIEW.value)
@requires_feature(LicenseFeature.AUTOMATIONS)
@handle_route_errors("while checking the config file status for OpenCelium")
def get_oc_config_status(request_user: CmdbUser) -> Response:
    """
    HTTP `GET` / `HEAD` route reporting which `[OpenCelium]` settings of the config file are usable

    Reads the section once and answers with one boolean per setting - never with the configured
    values. `section` is False when the section is missing entirely, when no config file is loaded
    at all, or in cloud mode (where the OpenCelium connection comes from the service portal instead
    of `etc/cmdb.conf`); an incomplete section still reports `section: True` plus a False flag for
    every setting it does not define. A setting is usable by the rule the connector reads it with
    (`cmdb.open_celium.oc_config_rules`): a port from 1 to 65535, `http` / `https`, a host that is a name or an
    address only, credentials that are not blank. `status` is True only when every setting is usable - then the
    connector can build its URL from the section - which is what the frontend gates the Automations view on. It
    asks for ``base.openCelium.connection.view``, and on-premise for the Automations licence; any unexpected failure
    answers 500

    Args:
        request_user (CmdbUser): The requesting user; unused in the body - the route only reads
                                 process-wide config, but the user is injected to authenticate it and to
                                 check its right

    Raises:
        HTTPException: 401 without a valid token, 403 without ``base.openCelium.connection.view`` or (on
                       premise) without the Automations licence, 500 on an unexpected failure

    Returns:
        Response: A Flask Response object holding `status` and `section` (see `OcConfigStatusKey`)
                  plus one boolean per `OcConfigKey` setting
    """
    config_state: dict[str, bool] = {
        OcConfigStatusKey.STATUS.value: False,
        OcConfigStatusKey.SECTION.value: True,
        **{key.value: False for key in OC_CONFIG_KEYS},
    }

    try:
        # Cloud mode never reads OpenCelium from the config file, so there is nothing to report on
        if current_app.cloud_mode:
            config_state[OcConfigStatusKey.SECTION.value] = False

            return DefaultResponse(config_state).make_response()

        # One read for the whole section: unlike get_value() it does not raise on a missing KEY, so
        # a partially filled section is reported instead of failing the request
        section_values: dict[str, Any] = SystemConfigReader().get_all_values_from_section(OC_CONFIG_SECTION)

        config_state.update(oc_setting_flags(section_values))
        config_state[OcConfigStatusKey.STATUS.value] = all(config_state[key.value] for key in OC_CONFIG_KEYS)

        return DefaultResponse(config_state).make_response()
    except (SectionError, ConfigNotLoaded):
        # No section (or no config file at all): every setting stays False and the frontend is told
        # that the section itself is what is missing
        config_state[OcConfigStatusKey.SECTION.value] = False

        return DefaultResponse(config_state).make_response()
