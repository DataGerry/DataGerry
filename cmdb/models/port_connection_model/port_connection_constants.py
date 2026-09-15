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


class CableSource(BaseStrEnum):
    """
    Where the cable information of a connection comes from

    A connection describes its cable in exactly ONE of these two ways, never both: the write routes
    refuse the inline fields alongside a cable CI, so the duplication can not exist in stored data.

      - INLINE - the connection carries the five cable_* values itself (no cable is inventoried)
      - CI - the connection names a CABLE SpecialType CmdbObject and that object owns the values
    """
    INLINE = 'inline'
    CI = 'ci'


class CableViewKey(BaseStrEnum):
    """
    Keys of the resolved ``cable`` block the READ routes return

    Not document keys: a connection is stored with the flat cable_* fields, and the read layer
    resolves them - from the cable CI when one is named, from the connection itself otherwise - into
    this one block, so a client renders both storage modes with the same code.

    TYPE is always a LABEL and TYPE_ID always the CABLE_TYPE CmdbExtendableOption public_id behind it.
    Inline connections fill both (the stored id is resolved to its label); a cable CI fills only TYPE,
    because an ordinary CmdbType select stores the label and knows no option id.

    RESOLVED is written only when it is False - a named cable CI that no longer exists. The reference
    is soft by design (it is reported, never cascaded), and its absence means the block is complete
    """
    SOURCE = 'source'
    CABLE_CI_ID = 'cable_ci_id'
    RESOLVED = 'resolved'
    NAME = 'name'
    TYPE = 'type'
    TYPE_ID = 'type_id'
    LENGTH = 'length'
    COLOR = 'color'
    DESCRIPTION = 'description'


class AssignableCableKey(BaseStrEnum):
    """
    Keys of one row of the unassigned-cable picker

    A read view like `CableViewKey`, not document keys: the row is assembled from a CABLE SpecialType
    CmdbObject, whose cable values live in its `fields` triples.

    NAME / CABLE_TYPE / LENGTH / COLOR / DESCRIPTION are the object's own `dg-cable-*` values, the
    same five a linked connection reports in its `cable` block - so the value a caller picked here is
    the value it will read back there. CABLE_TYPE is spelled out rather than shortened to `type`
    (which is what the cable block calls it) because TYPE_ID / TYPE_LABEL on this row are the
    **CmdbType** of the Cable CI, as on every other picker row in the API, and one row may not use
    "type" for two different things.

    PUBLIC_ID is what a caller sends as a connection's `cable_ci_id`
    """
    PUBLIC_ID = 'public_id'
    NAME = 'name'
    CABLE_TYPE = 'cable_type'
    LENGTH = 'length'
    COLOR = 'color'
    DESCRIPTION = 'description'
    TYPE_ID = 'type_id'
    TYPE_LABEL = 'type_label'
    ACTIVE = 'active'


# Key under which the READ routes carry the resolved cable block. It REPLACES the flat cable_* keys
# and cable_ci_id in a response - returning both would leave a client free to read the wrong one
CABLE_VIEW_KEY: str = 'cable'

# The five fields a connection can carry INLINE, in the order they are presented and reported. These
# are what an INTERNAL connection may not carry, and what a connection naming a cable CI may not carry
# either - the CI owns them then
INLINE_CABLE_FIELD_KEYS: tuple[PortConnectionKey, ...] = (
    PortConnectionKey.CABLE_NAME,
    PortConnectionKey.CABLE_TYPE,
    PortConnectionKey.CABLE_LENGTH,
    PortConnectionKey.CABLE_COLOR,
    PortConnectionKey.CABLE_DESCRIPTION,
)

# The cable-info fields, the reference included. An INTERNAL connection may carry none of them - a
# panel's internal pairing is a fact about the panel, not a piece of cabling - and the per-type field
# rule is derived from this tuple rather than restating it
CABLE_FIELD_KEYS: tuple[PortConnectionKey, ...] = (
    *INLINE_CABLE_FIELD_KEYS,
    PortConnectionKey.CABLE_CI_ID,
)

# The audit timestamps, in the order they are stamped. Declared as the model's DATE_FIELDS, which is
# what normalises the three shapes a date arrives in - the frontend's {'$date': ...} wrapper, an API
# client's timestamp string, and a real datetime read back from MongoDB - into one stored type
PORT_CONNECTION_DATE_KEYS: tuple[PortConnectionKey, ...] = (
    PortConnectionKey.CREATION_TIME,
    PortConnectionKey.LAST_EDIT_TIME,
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
