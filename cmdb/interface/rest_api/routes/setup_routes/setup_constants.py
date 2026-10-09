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
Request keys, query parameters and messages of the setup REST routes
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #

class SetupQueryParam(BaseStrEnum):
    """
    Query parameters read by the setup routes
    """
    DATABASE = 'database'


class SetupRequestKey(BaseStrEnum):
    """
    Body keys a setup request may carry

    EMAIL accepts either a single email or a list of them; the route branches on the value type
    """
    EMAIL = 'email'


class SetupMessage(BaseStrEnum):
    """
    The 400s the setup routes answer; the Service Portal reads them when a teardown request is malformed

    The two `{...}` members are formatted with the database name / the offending list positions
    """
    NO_DATABASE = "No database name was provided in the 'database' query parameter!"
    UNKNOWN_DATABASE = "The database with the name {database} does not exist!"
    NO_PAYLOAD = "No valid JSON object payload provided!"
    NO_EMAIL = "'email' key not provided in the request payload!"
    EMAIL_TYPE = "'email' must be a string or list of strings!"
    EMPTY_EMAIL = "'email' must name at least one non-empty email address!"
    EMAIL_ITEMS = "'email' entries must be non-empty strings - not at position(s) {positions}!"
    RESERVED_DATABASE = "The database {database} is not a subscription database and cannot be dropped!"
    NOT_A_TENANT_DATABASE = "The database {database} is not a DataGerry tenant database and cannot be dropped!"


# MongoDB's own databases. A teardown may never name one, whatever else the cluster holds
MONGODB_SYSTEM_DATABASES: tuple[str, ...] = ('admin', 'config', 'local')
