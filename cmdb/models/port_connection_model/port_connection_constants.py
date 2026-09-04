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
Types, document keys and index names of a CmdbPortConnection

``CABLE_FIELD_KEYS`` below is the cable-info field list, so this module - not a validator - is the
single source of truth for which fields describe a cable and therefore for which fields an INTERNAL
connection may not carry. The index-name constants are here for the same reason: the model declares
them and the tests assert against them, and a name is what index reconciliation matches on
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #

class ConnectionType(BaseStrEnum):
    """
    What a connection between two ports physically is

    A FIXED list of exactly two, deliberately NOT a CmdbExtendableOption: the concept names these two
    and nothing else, and the collection's two partial unique indexes are filtered on these very
    values - a third, customer-added type would silently fall outside both and get no cardinality
    guarantee at all.

      - CABLE - the ordinary case, an external link carrying cable information
      - INTERNAL - a patch panel's front-to-rear pairing, created automatically and carrying no cable
    """
    CABLE = 'CABLE'
    INTERNAL = 'INTERNAL'


class PortConnectionKey(BaseStrEnum):
    """
    Document field names of a CmdbPortConnection (collection ``framework.portConnections``)

    ENDPOINTS holds exactly two CmdbPort public_ids, STORED SORTED ASCENDING. The sort is not
    cosmetic: it is what makes 'A to B' and 'B to A' the same document, which is how the undirected
    relation the concept demands becomes structural rather than a convention every reader has to
    remember - and it is what lets a single index refuse a duplicate pair.

    The five CABLE_* keys plus CABLE_CI_ID are the cable info, listed in CABLE_FIELD_KEYS and rejected
    outright on an INTERNAL connection. CABLE_CI_ID is ABSENT rather than null when a connection names
    no cable CI: its unique index is filtered on the key's PRESENCE, so a stored null would put every
    CI-less connection into that index and the second one would collide
    """
    PUBLIC_ID = 'public_id'
    ENDPOINTS = 'endpoints'
    CONNECTION_TYPE = 'connection_type'
    CABLE_NAME = 'cable_name'
    CABLE_TYPE = 'cable_type'
    CABLE_LENGTH = 'cable_length'
    CABLE_COLOR = 'cable_color'
    CABLE_DESCRIPTION = 'cable_description'
    CABLE_CI_ID = 'cable_ci_id'
    AUTHOR_ID = 'author_id'
    CREATION_TIME = 'creation_time'
    LAST_EDIT_TIME = 'last_edit_time'


# The cable-info fields, in the order they are presented and reported. An INTERNAL connection may
# carry none of them - a panel's internal pairing is a fact about the panel, not a piece of cabling -
# and the per-type field rule is derived from this tuple rather than restating it
CABLE_FIELD_KEYS: tuple[PortConnectionKey, ...] = (
    PortConnectionKey.CABLE_NAME,
    PortConnectionKey.CABLE_TYPE,
    PortConnectionKey.CABLE_LENGTH,
    PortConnectionKey.CABLE_COLOR,
    PortConnectionKey.CABLE_DESCRIPTION,
    PortConnectionKey.CABLE_CI_ID,
)

# A connection joins exactly two ports - never one, never three. The count is named because both the
# model and the endpoint validator assert it
ENDPOINT_COUNT: int = 2

# Names of the four declared indexes. The two partial unique ones on 'endpoints' are the feature's
# only hard guarantee, so their names are referenced from the tests that prove they exist
ENDPOINTS_CABLE_INDEX_NAME: str = 'endpoints-cable'
ENDPOINTS_INTERNAL_INDEX_NAME: str = 'endpoints-internal'
ENDPOINTS_INDEX_NAME: str = 'endpoints'
CABLE_CI_INDEX_NAME: str = 'cable_ci_id'
