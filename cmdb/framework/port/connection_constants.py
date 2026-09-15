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
Validation messages of a CmdbPortConnection

Every message here names a rule the DATABASE can not hold. The cardinality rules - no port in two
cable connections, one internal connection per port, no duplicate pair, one cable CI per connection -
are held by the collection's partial unique indexes instead, and surface as a duplicate-key error the
route layer turns into its own message
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #

class PortConnectionError(BaseStrEnum):
    """
    Messages reported when a CmdbPortConnection fails validation

    Members with a `{...}` placeholder are filled via `format()`. Every one of these is a business-rule
    rejection, surfaced as an HTTP 400 by the connection routes
    """
    UNKNOWN_CONNECTION_TYPE = "'{connection_type}' is not a valid connection type. Allowed: {allowed}"
    INVALID_ENDPOINTS = 'A connection needs exactly {count} port ids as its endpoints!'
    SELF_CONNECTION = 'A Port can not be connected to itself!'
    ENDPOINT_NOT_FOUND = 'No Port with ID {port_id} exists!'
    CABLE_FIELD_ON_INTERNAL = "'{field}' describes a cable and can not be set on an {connection_type} " \
                              'connection!'
    CABLE_FIELD_WITH_CABLE_CI = "'{field}' is owned by the linked Cable CI (ID {cable_ci_id}) and can " \
                                'not be set on the connection - edit the Cable CI instead!'
    CABLE_CI_NOT_FOUND = 'No CmdbObject with ID {cable_ci_id} exists!'
    CABLE_CI_NOT_A_CABLE = 'The CmdbObject with ID {cable_ci_id} is not a Cable!'


# Prefix of the aggregated abort message the connection routes build from the reasons above
CONNECTION_ABORT_PREFIX: str = 'Port connection validation failed'


# Refusal (HTTP 400) when a CABLE SpecialType CmdbObject is deleted while a connection still names it
# as its cable. The connection is a fact about the two ports and survives its cable record, so the
# deletion is refused rather than cascaded - resolving or re-describing the connection is the user's
# decision. One line per blocked cable, joined by CABLE_IN_USE_SEPARATOR
CABLE_IN_USE_MESSAGE: str = (
    'The Cable with ID:{cable_ci_id} is used by Port connection ID:{connection_id} '
    '(Ports {port_ids})'
)

# Prefix of the aggregated refusal, so a bulk delete says what it refused and what to do about it
CABLE_IN_USE_ABORT_PREFIX: str = (
    'Deletion refused - resolve the Port connection(s) first, or edit them to describe their cable '
    'without the Cable CI'
)

# Separator between the blocked cables of one refusal
CABLE_IN_USE_SEPARATOR: str = ' | '
