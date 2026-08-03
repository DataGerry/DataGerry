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
