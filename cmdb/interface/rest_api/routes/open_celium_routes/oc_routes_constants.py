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
Shared constants for the OpenCelium REST routes
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #


class OcResponseKey(BaseStrEnum):
    """Keys of an OpenCelium API response object consumed by the OpenCelium routes"""
    TITLE = 'title'
    CONNECTION = 'connection'
    CONNECTION_ID = 'connectionId'
    CONNECTOR_ID = 'connectorId'
    SCHEDULER = 'scheduler'
    SCHEDULER_ID = 'schedulerId'
    FROM_CONNECTOR = 'fromConnector'
    TO_CONNECTOR = 'toConnector'
    PASSWORD = 'password'


# HTTP request header carrying the OpenCelium master password
MASTER_PW_HEADER: str = 'X-Master-Password'
