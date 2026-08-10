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
import re
import json
from logging import Logger, getLogger
from typing import Any
from urllib.parse import urlsplit

from cmdb.manager.system_manager.system_config_reader import SystemConfigReader

LOGGER: Logger = getLogger(__name__)

FRONTEND_CONFIG_FILENAME: str = 'app-config.json'

#: Section and key in cmdb.conf holding the address browsers use to reach DataGerry
FRONTEND_SECTION: str = 'Frontend'
FRONTEND_URL_OPTION: str = 'url'

#: Default ports, so a URL that omits the port still yields a complete config
DEFAULT_PORTS: dict[str, int] = {'http': 80, 'https': 443}

#: Characters a host may consist of - letters, digits, dots, hyphens, and IPv6 colons
HOSTNAME_PATTERN: re.Pattern = re.compile(r'[A-Za-z0-9.\-:]+')
# -------------------------------------------------------------------------------------------------------------------- #


def load_frontend_config() -> dict[str, Any]:
    """
    Loads the frontend runtime config, preferring cmdb.conf over the legacy JSON file.

    The frontend needs to know which address to call the API on, and that address is not
    necessarily the one the web server binds to: behind a reverse proxy, or under a subdomain,
    the two differ. It is therefore configured rather than derived.

    'cmdb.conf' is the one place an installation is configured, so the setting belongs there:

        [Frontend]
        url = https://cmdb.example.com

    'app-config.json' beside cmdb.conf keeps working for installations that already use it, but
    cmdb.conf wins when both are present. A missing or malformed source is not fatal - an empty
    dict is returned and the frontend falls back to the address it was built with.

    Returns:
        dict[str, Any]: Flat key-value pairs for the frontend, or {} when nothing is configured
    """
    from_conf: dict[str, Any] = _load_from_cmdb_conf()

    if from_conf:
        return from_conf

    return _load_from_json_file()


def _load_from_cmdb_conf() -> dict[str, Any]:
    """
    Reads '[Frontend] url' from cmdb.conf and splits it into the parts the frontend expects.

    Returns:
        dict[str, Any]: protocol, apiUrl and apiPort, or {} when the option is absent or unusable
    """
    try:
        raw: Any = SystemConfigReader().get_value(FRONTEND_URL_OPTION, FRONTEND_SECTION, default=None)
    except Exception as err:
        LOGGER.debug("[load_frontend_config] No '[%s]' section in cmdb.conf: %s", FRONTEND_SECTION, err)
        return {}

    if not raw or not str(raw).strip():
        return {}

    return _split_url(str(raw).strip())


def _split_url(url: str) -> dict[str, Any]:
    """
    Splits a configured address into protocol, host and port.

    The frontend only applies an override when all three are present, so a URL without an explicit
    port is completed from the scheme's default rather than left partial.

    Args:
        url (str): Address as configured, e.g. 'https://cmdb.example.com' or 'http://10.0.0.5:4000'

    Returns:
        dict[str, Any]: protocol, apiUrl and apiPort, or {} when the address cannot be read
    """
    # A bare host such as 'cmdb.example.com' has no scheme, and urlsplit would read it as a path.
    parts = urlsplit(url if '//' in url else f'//{url}', scheme='http')

    # urlsplit takes anything without a scheme as a host, so 'not a url' would arrive here as a
    # hostname. Only the characters a host may actually contain are accepted.
    if not parts.hostname or not HOSTNAME_PATTERN.fullmatch(parts.hostname):
        LOGGER.warning("[load_frontend_config] '[%s] %s' is not a usable address: '%s'",
                       FRONTEND_SECTION, FRONTEND_URL_OPTION, url)
        return {}

    protocol: str = parts.scheme or 'http'

    try:
        port: int | None = parts.port
    except ValueError:
        LOGGER.warning("[load_frontend_config] '[%s] %s' has an invalid port: '%s'",
                       FRONTEND_SECTION, FRONTEND_URL_OPTION, url)
        return {}

    return {
        'protocol': protocol,
        'apiUrl': parts.hostname,
        'apiPort': str(port if port is not None else DEFAULT_PORTS.get(protocol, 80)),
    }


def _load_from_json_file() -> dict[str, Any]:
    """
    Loads the frontend runtime config from '<config dir>/app-config.json'.

    The file is expected next to cmdb.conf, so its directory is derived from
    SystemConfigReader.RUNNING_CONFIG_LOCATION (which honours the CLI '-c' flag).

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
