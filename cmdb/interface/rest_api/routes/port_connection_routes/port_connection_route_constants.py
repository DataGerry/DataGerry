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
Rights, request keys and refusal messages of the port-connection REST routes
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #

class ConnectionRight(BaseStrEnum):
    """
    ACL right identifiers guarding the port-connection REST routes

    A connection spans TWO CmdbObjects, and these rights are what governs it - **the endpoint objects'
    own ACLs are deliberately NOT consulted** (decision Q13, 2026-09-03). The Rack precedent for a row
    that joins two things is the same: a feature right alone.

    That is a real trade-off and it is recorded rather than hidden. A caller holding the connection
    rights can cable together two objects they could not open individually, and a connection read
    tells them those two ports exist. The alternative - requiring access to both endpoints - was
    rejected because a connection is a fact about the CABLING rather than about either device, and
    because the "either endpoint" and "both endpoints" readings differ on exactly the patch panel this
    feature exists for: a panel is routinely administered by a team that owns neither of the devices
    it patches together
    """
    VIEW = 'base.framework.connection.view'
    ADD = 'base.framework.connection.add'
    EDIT = 'base.framework.connection.edit'
    DELETE = 'base.framework.connection.delete'


class ConnectionRequestKey(BaseStrEnum):
    """
    Body keys a port-connection request may carry

    ENDPOINTS and CONNECTION_TYPE belong to the CREATE alone: both are immutable afterwards, because a
    re-cable is a delete plus a create rather than an edit. Everything else is the cable information,
    which is what an update writes.

    The audit fields and PUBLIC_ID are absent on purpose: they are server-owned and stamped from the
    request, never read from the payload
    """
    ENDPOINTS = 'endpoints'
    CONNECTION_TYPE = 'connection_type'
    CABLE_NAME = 'cable_name'
    CABLE_TYPE = 'cable_type'
    CABLE_LENGTH = 'cable_length'
    CABLE_COLOR = 'cable_color'
    CABLE_DESCRIPTION = 'cable_description'
    CABLE_CI_ID = 'cable_ci_id'


# Refusal (HTTP 404) when the addressed connection does not exist
CONNECTION_NOT_FOUND_MESSAGE: str = 'The Port connection with ID:{public_id} was not found!'

# Refusal (HTTP 404) when the port whose connections were requested does not exist
CONNECTION_PORT_NOT_FOUND_MESSAGE: str = 'The Port with ID:{port_id} was not found!'

# Refusal (HTTP 400) when a port already holds a connection of the requested kind. The two partial
# unique indexes are what guarantee it; these messages are what make the common case readable
CONNECTION_PORT_ALREADY_CABLED_MESSAGE: str = (
    'Port ID:{port_id} already has a cable connection. Resolve it before connecting the Port again!'
)
CONNECTION_PORT_ALREADY_PAIRED_MESSAGE: str = (
    'Port ID:{port_id} already has an internal connection. A panel Port pairs with exactly one '
    'counterpart!'
)

# Refusal (HTTP 400) when the same two ports are already joined by a connection of this kind
CONNECTION_PAIR_EXISTS_MESSAGE: str = (
    'Port ID:{port_id} and Port ID:{peer_id} are already connected by a {connection_type} connection!'
)

# Refusal (HTTP 400) when another connection already claims the cable CI
CONNECTION_CABLE_CI_IN_USE_MESSAGE: str = (
    'The Cable with ID:{cable_ci_id} is already used by Port connection ID:{public_id}!'
)

# Refusal (HTTP 400) when a payload key that is server-owned or immutable carries a different value.
# Re-cabling is a delete plus a create: changing an endpoint would move a connection between ports
# whose cardinality slots were never checked for it
CONNECTION_FIELD_IMMUTABLE_MESSAGE: str = (
    "The '{field}' of a Port connection can not be changed - delete it and create the new one!"
)

# Refusal (HTTP 400) fallback when the database refuses a write as a duplicate but the reason cannot
# be attributed to one of the messages above. Better than reporting a raw driver error
CONNECTION_DUPLICATE_MESSAGE: str = (
    'This Port connection collides with an existing one - a Port holds at most one cable and one '
    'internal connection, and a Cable belongs to at most one connection!'
)

# Prefix of the aggregated 400 the write routes build from the validator's reasons
CONNECTION_ABORT_PREFIX: str = 'Port connection validation failed'

# Substrings identifying which unique index a duplicate-key error names. The database reports the key
# PATTERN, so the two endpoint indexes are indistinguishable from each other here - which is fine, the
# route knows the requested connection_type and picks the message from that
DUPLICATE_KEY_ENDPOINTS_MARKER: str = 'endpoints'
DUPLICATE_KEY_CABLE_CI_MARKER: str = 'cable_ci_id'
