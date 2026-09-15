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
"""
from logging import Logger, getLogger
from typing import Any

from flask import abort, current_app
from werkzeug import Response

from cmdb.manager.system_manager.system_config_reader import SystemConfigReader

from cmdb.models.user_model import CmdbUser
from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.route_utils import insert_request_user, verify_api_access
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.rest_api.responses import DefaultResponse
from cmdb.interface.rest_api.routes.config_routes.config_file_constants import (
    MIN_VALID_PORT,
    OcConfigStatusKey,
)
from cmdb.open_celium.oc_constants import OC_CONFIG_KEYS, OC_CONFIG_SECTION, OcConfigKey
from cmdb.utils import coerce_whole_number

from cmdb.errors.system_config import ConfigNotLoaded, SectionError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

config_file_blueprint = APIBlueprint('config_file', __name__)

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

@config_file_blueprint.route('/status/opencelium', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
def get_oc_config_status(request_user: CmdbUser) -> Response:
    """
    HTTP `GET` route reporting which `[OpenCelium]` settings of the config file are configured

    Reads the section once and answers with one boolean per setting - never with the configured
    values. `section` is False when the section is missing entirely, when no config file is loaded
    at all, or in cloud mode (where the OpenCelium connection comes from the service portal instead
    of `etc/cmdb.conf`); an incomplete section still reports `section: True` plus a False flag for
    every setting it does not define. `status` is True only when every setting is usable, which is
    what the frontend gates the Automations view on

    Args:
        request_user (CmdbUser): The requesting user; unused in the body - the route only reads
                                 process-wide config, but the user is injected to authenticate

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

        for key in OC_CONFIG_KEYS:
            config_state[key.value] = _is_configured(section_values.get(key.value))

        config_state[OcConfigKey.PORT.value] = _is_valid_port(section_values.get(OcConfigKey.PORT.value))
        config_state[OcConfigStatusKey.STATUS.value] = all(config_state[key.value] for key in OC_CONFIG_KEYS)

        return DefaultResponse(config_state).make_response()
    except (SectionError, ConfigNotLoaded):
        # No section (or no config file at all): every setting stays False and the frontend is told
        # that the section itself is what is missing
        config_state[OcConfigStatusKey.SECTION.value] = False

        return DefaultResponse(config_state).make_response()
    except Exception as err:
        LOGGER.error("[get_oc_config_status] Exception: %s. Type: %s", err, type(err).__name__, exc_info=True)
        abort(500, "An internal server error occured while checking the config file status for OpenCelium!")

# --------------------------------------------------- HELPER METHODS ------------------------------------------------- #

def _is_configured(value: Any) -> bool:
    """
    Checks whether a config value counts as configured

    Values arrive already cast by the reader's `auto_cast`, so a literal `false` / `0` setting is a
    bool / int rather than a string here. Only absence and an empty (or whitespace-only) value mean
    "not configured" - a password of `false` is a configured password

    Args:
        value (Any): The value the config section holds for a setting, or None when it holds none

    Returns:
        bool: True when the setting carries a non-empty value
    """
    if value is None:
        return False

    return str(value).strip() != ''


def _is_valid_port(value: Any) -> bool:
    """
    Checks whether a config value is usable as an OpenCelium TCP port

    Booleans and fractional numbers are rejected by `coerce_whole_number`, so a `port = true` or
    `port = 80.5` setting counts as unusable rather than silently becoming 1 or 80

    Args:
        value (Any): The value the config section holds for the port setting, or None when unset

    Returns:
        bool: True when the value is a whole number of at least `MIN_VALID_PORT`
    """
    port: int | None = coerce_whole_number(value)

    return port is not None and port >= MIN_VALID_PORT
