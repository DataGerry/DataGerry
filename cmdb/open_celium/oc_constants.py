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

# Name of the INVOKER that marks a business template as DataGerry's own, as registered in
# OpenCelium. A cloud installation is registered under its own invoker, so the two are not
# interchangeable: the detailed template route filters on whichever applies, and picking the wrong
# one answers an empty template list rather than an error
OC_DATAGERRY_INVOKER_NAME: str = "DataGerry"
OC_DATAGERRY_CLOUD_INVOKER_NAME: str = "DataGerryCloud"

# Environment variable carrying the OpenCelium MASTER password on a hosted installation. Every
# connector read and write in cloud mode is authenticated with it, so a hosted process that does not
# have it cannot serve connectors at all - OcConnectorManager refuses to be constructed
OC_MASTER_PW_ENV_VAR: str = "OC_MASTER_PW"

# Key of the boolean OpenCelium answers its 'does this connector exist' endpoint with. Read by the
# connector AND the invoker manager, which answer the same question about two different entities
OC_EXISTS_RESULT_KEY: str = "result"

# Query parameter of OpenCelium's all-invokers endpoint. Named here because BOTH ends spell it: the
# DataGerry route reads it off its own query string and the manager forwards it to OpenCelium
OC_OPS_INCLUDED_PARAM: str = "opsIncluded"

# Query parameters of OpenCelium's license-usage endpoint, with the page size DataGerry asks for by
# default. Named here because both ends spell them: the route reads them off its own query string and
# the manager forwards them to OpenCelium
OC_PAGE_PARAM: str = "page"
OC_SIZE_PARAM: str = "size"
OC_DEFAULT_USAGE_PAGE: int = 0
OC_DEFAULT_USAGE_SIZE: int = 5

# The only value that turns the flag off. Deliberately not a truthiness test - `bool('false')` is
# True, which is the footgun `request.args.get(..., type=bool)` walks into - and deliberately not a
# list of spellings: whether '0' / 'no' / an EMPTY value should also disable operations is
# discussion-backlog #223
OC_FLAG_DISABLED_VALUE: str = "false"

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
