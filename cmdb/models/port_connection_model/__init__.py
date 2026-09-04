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
The connection entity of the Port Connectivity feature

A CmdbPortConnection is its own document in framework.portConnections joining two CmdbPorts, kept
apart from cmdb/models/port_model/ because connectivity and inventory are separate concerns: a port
exists whether or not anything is plugged into it, and 'connected' is computed from this collection
rather than stored on the port.

The link is UNDIRECTED, and that is structural: the two port ids live in one 'endpoints' array stored
sorted ascending, which is also what lets the collection's two partial unique indexes hold the
feature's cardinality guarantee. port_connection_helpers is the single source of that canonical form
"""
from cmdb.models.port_connection_model.port_connection_constants import (
    ConnectionType,
    PortConnectionKey,
    CABLE_CI_INDEX_NAME,
    CABLE_FIELD_KEYS,
    ENDPOINT_COUNT,
    ENDPOINTS_CABLE_INDEX_NAME,
    ENDPOINTS_INDEX_NAME,
    ENDPOINTS_INTERNAL_INDEX_NAME,
)
from cmdb.models.port_connection_model.port_connection_helpers import (
    coerce_endpoints,
    is_self_connection,
    sort_endpoints,
)
from cmdb.models.port_connection_model.cmdb_port_connection import CmdbPortConnection
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'ConnectionType',
    'PortConnectionKey',
    'CABLE_CI_INDEX_NAME',
    'CABLE_FIELD_KEYS',
    'ENDPOINT_COUNT',
    'ENDPOINTS_CABLE_INDEX_NAME',
    'ENDPOINTS_INDEX_NAME',
    'ENDPOINTS_INTERNAL_INDEX_NAME',
    'coerce_endpoints',
    'is_self_connection',
    'sort_endpoints',
    'CmdbPortConnection',
]
