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
Provides all constants for OpenCelium interaction
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #

OC_REQUEST_TIMEOUT: int = 10
UNIQUE_POSITIVE: str = "NOT_EXISTS"
UNIQUE_NEGATIVE: str = "EXISTS"
OC_INTERNAL_CONNECTOR_NAME: str = "DataGerryInternal"

# OpenCelium login endpoint + max token-refresh attempts before giving up on a 403 loop
OC_AUTH_URL: str = "/login"
MAX_AUTH_RETRIES: int = 6

# settings_manager section (and document _id) + key under which the OC JWT token is cached
OC_TOKEN_SECTION: str = "oc_token"
OC_TOKEN_KEY: str = "token"

# HTTP header names / content type used when talking to OpenCelium
OC_HEADER_AUTHORIZATION: str = "Authorization"
OC_HEADER_MASTER_PASSWORD: str = "X-Master-Password"
OC_HEADER_CONTENT_TYPE: str = "Content-Type"
OC_CONTENT_TYPE_JSON: str = "application/json"

# SystemConfigReader section holding the on-premise OpenCelium connection config
OC_CONFIG_SECTION: str = "OpenCelium"


class OcConfigKey(BaseStrEnum):
    """
    Key names of the on-premise `[OpenCelium]` config-file section

    The members mirror the keys documented in `etc/cmdb.conf`. They are read by
    `OcApiConnector._load_local_config` to build the connection config and by the
    `/config_file/status/opencelium` route to report which of them are configured

    Attributes:
        HOST: Hostname or IP address of the OpenCelium instance
        PORT: TCP port of the OpenCelium instance
        PROTOCOL: URL scheme used to reach OpenCelium (`http` / `https`)
        EMAIL: Email address of the OpenCelium account DataGerry logs in with
        USER: Username of that OpenCelium account
        PASSWORD: Password of that OpenCelium account
    """
    HOST = "host"
    PORT = "port"
    PROTOCOL = "protocol"
    EMAIL = "email"
    USER = "user"
    PASSWORD = "password"


# Key of the connection-config dict holding the URL derived from protocol/host/port. Not a config-file
# key - the connector composes it, so it is kept apart from `OC_CONFIG_KEYS`
OC_CONFIG_BASE_URL_KEY: str = "base_url"

# Every key of the `[OpenCelium]` section, in the order the config file documents them. Shared by the
# connector (which reads their values) and the config-status route (which reports their presence)
OC_CONFIG_KEYS: tuple[OcConfigKey, ...] = (
    OcConfigKey.HOST,
    OcConfigKey.PORT,
    OcConfigKey.PROTOCOL,
    OcConfigKey.EMAIL,
    OcConfigKey.USER,
    OcConfigKey.PASSWORD,
)
