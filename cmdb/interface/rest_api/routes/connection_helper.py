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
Helper functions for the connection routes
"""
import os
import json
from logging import Logger, getLogger
from typing import Any

from cmdb.manager.system_manager.system_config_reader import SystemConfigReader
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# Filename of the frontend runtime config, located alongside cmdb.conf in the config directory
FRONTEND_CONFIG_FILENAME: str = 'app-config.json'

# -------------------------------------------------------------------------------------------------------------------- #

def load_frontend_config() -> dict[str, Any]:
    """
    Loads the frontend runtime config from '<config dir>/app-config.json'.

    The file is expected next to cmdb.conf, so its directory is derived from
    SystemConfigReader.RUNNING_CONFIG_LOCATION (which honours the CLI '-c' flag). A missing
    or malformed file is not treated as fatal: it is logged and an empty dict is returned so
    the frontend init endpoint keeps responding.

    Returns:
        dict[str, Any]: The parsed key-value pairs of the frontend config, or {} on failure
    """
    config_path: str = os.path.join(SystemConfigReader.RUNNING_CONFIG_LOCATION, FRONTEND_CONFIG_FILENAME)

    try:
        with open(config_path, 'r', encoding='utf-8') as config_file:
            return json.load(config_file)
    except (OSError, ValueError) as err:
        LOGGER.warning("[load_frontend_config] Could not load frontend config from '%s': %s", config_path, err)
        return {}
