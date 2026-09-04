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
This module contains the implementation of CmdbPortConnection, one link between two CmdbPorts
"""
from logging import Logger, getLogger
from datetime import datetime, timezone
from typing import Any

from dateutil.parser import parse

from cmdb.models.cmdb_dao import CmdbDAO
from cmdb.models.port_connection_model.port_connection_constants import (
    ConnectionType,
    PortConnectionKey,
    CABLE_CI_INDEX_NAME,
    ENDPOINTS_CABLE_INDEX_NAME,
    ENDPOINTS_INDEX_NAME,
    ENDPOINTS_INTERNAL_INDEX_NAME,
)
from cmdb.models.port_connection_model.port_connection_helpers import sort_endpoints

from cmdb.class_schema.port_connection_model.cmdb_port_connection_schema import (
    get_cmdb_port_connection_schema,
)

from cmdb.errors.models.cmdb_port_connection import (
    CmdbPortConnectionInitError,
    CmdbPortConnectionInitFromDataError,
    CmdbPortConnectionToJsonError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                             CmdbPortConnection - CLASS                                               #
# -------------------------------------------------------------------------------------------------------------------- #
class CmdbPortConnection(CmdbDAO):
    """
    A CmdbPortConnection is one link between two CmdbPorts

    It is UNDIRECTED: the concept is explicit that a connection is 'port A to port B' and never
    'port A into port B', so there is no source end and no target end to leak into a UI as an arrow.
    That is expressed structurally rather than by convention - the two port ids live in one
    'endpoints' array stored SORTED ASCENDING, so the two spellings of one link are one document.

    A full physical path through a patch panel is three of these: server to front, front to rear (the
    INTERNAL pairing, created automatically) and rear to switch. The pairing IS the connection - it is
    never derived from the ports' names, which the concept forbids.

    Cable information lives here, flat, and a cable CI is optional: a connection works with cable info
    alone and with both. An INTERNAL connection carries neither, which is a per-type field rule the
    connection validator holds - a document schema can only describe one field at a time

    `Extends`: CmdbDAO
    """
    COLLECTION = 'framework.portConnections'
    REQUIRED_INIT_KEYS: list[str] = [
        PortConnectionKey.ENDPOINTS.value,
        PortConnectionKey.CONNECTION_TYPE.value,
    ]

    INDEX_KEYS: list[dict[str, Any]] = [
        # No port may appear in two CABLE connections. This is the feature's hard cardinality
        # refusal, and it is enforced HERE rather than by a read-then-write check, which two
        # concurrent requests would walk straight through.
        #
        # It works because a unique index over an ARRAY is multikey-unique: no two documents may
        # share any single element. Applied to the whole collection that property would be a bug - no
        # port could appear in two connections at all, which makes every patch-panel port
        # unbuildable - so each of the two indexes is PARTIAL, scoped to one connection_type. Within
        # the cable scope 'no port twice' is exactly what is wanted.
        #
        # A duplicate pair falls out of this for free, thanks to the stored sort. A SELF-connection
        # does not: [5, 5] dedupes to one key inside a single document and slips past, so it stays a
        # validator rule
        {
            'keys': [(PortConnectionKey.ENDPOINTS.value, CmdbDAO.DAO_ASCENDING)],
            'name': ENDPOINTS_CABLE_INDEX_NAME,
            'unique': True,
            'partialFilterExpression': {
                PortConnectionKey.CONNECTION_TYPE.value: ConnectionType.CABLE.value,
            },
        },
        # The same guarantee in the internal scope: a patch panel's front port pairs with exactly one
        # rear port. A port may therefore hold one cable AND one internal connection - the two
        # indexes never see each other's documents
        {
            'keys': [(PortConnectionKey.ENDPOINTS.value, CmdbDAO.DAO_ASCENDING)],
            'name': ENDPOINTS_INTERNAL_INDEX_NAME,
            'unique': True,
            'partialFilterExpression': {
                PortConnectionKey.CONNECTION_TYPE.value: ConnectionType.INTERNAL.value,
            },
        },
        # 'all connections of port X', and the batched {endpoints: {$in: [...]}} the computed
        # 'connected' flag runs once per page of ports. Neither partial index can serve those: a
        # partial index is only used for queries the planner can prove fall inside its filter
        {
            'keys': [(PortConnectionKey.ENDPOINTS.value, CmdbDAO.DAO_ASCENDING)],
            'name': ENDPOINTS_INDEX_NAME,
            'unique': False,
        },
        # One inventoried cable belongs to at most one connection - reusing a cable CI on two links is
        # a data-entry error, not a use case. Partial on the key's PRESENCE (the rack-reservation
        # shape), because the many connections that name no CI omit the key entirely and would
        # otherwise all collide with each other as the same missing value
        {
            'keys': [(PortConnectionKey.CABLE_CI_ID.value, CmdbDAO.DAO_ASCENDING)],
            'name': CABLE_CI_INDEX_NAME,
            'unique': True,
            'partialFilterExpression': {PortConnectionKey.CABLE_CI_ID.value: {'$exists': True}},
        },
    ]

    SCHEMA: dict = get_cmdb_port_connection_schema()


    #pylint: disable=R0913, R0917
    def __init__(
            self,
            public_id: int,
            endpoints: list[int],
            connection_type: str,
            cable_name: str | None = None,
            cable_type: int | None = None,
            cable_length: str | None = None,
            cable_color: str | None = None,
            cable_description: str | None = None,
            cable_ci_id: int | None = None,
            author_id: int | None = None,
            creation_time: datetime = None,
            last_edit_time: datetime = None):
        """
        Initialises a CmdbPortConnection

        Args:
            public_id (int): public_id of the CmdbPortConnection
            endpoints (list[int]): The two connected CmdbPort public_ids. Canonicalised to ascending
                                   order here, so an instance can not carry an unsorted pair; an
                                   unusable value is kept as given for the validator to refuse
            connection_type (str): A ConnectionType value - CABLE or INTERNAL
            cable_name (str | None): Free text naming the cable
            cable_type (int | None): public_id of a CABLE_TYPE CmdbExtendableOption
            cable_length (str | None): Length as text - '5 m', '2.5 m'
            cable_color (str | None): The cable's colour as free text
            cable_description (str | None): Free text
            cable_ci_id (int | None): public_id of a CABLE SpecialType CmdbObject, None when the
                                      connection inventories no cable. to_json OMITS the key then
            author_id (int | None): public_id of the CmdbUser who created the connection
            creation_time (datetime, optional): When the connection was created. Defaults to now
            last_edit_time (datetime, optional): When the connection was last changed. Defaults to None

        Raises:
            CmdbPortConnectionInitError: If the CmdbPortConnection could not be initialised
        """
        try:
            # An unusable value is passed through rather than replaced: the validator refuses it with
            # a readable message, and a historical row stays readable instead of raising on load
            self.endpoints: list[int] = sort_endpoints(endpoints) or endpoints
            self.connection_type: str = connection_type
            self.cable_name: str | None = cable_name
            self.cable_type: int | None = cable_type
            self.cable_length: str | None = cable_length
            self.cable_color: str | None = cable_color
            self.cable_description: str | None = cable_description
            self.cable_ci_id: int | None = cable_ci_id
            self.author_id: int | None = author_id
            self.creation_time: datetime = creation_time or datetime.now(timezone.utc)
            self.last_edit_time: datetime | None = last_edit_time

            super().__init__(public_id=public_id)
        except Exception as err:
            raise CmdbPortConnectionInitError(err) from err

# -------------------------------------------------- CLASS FUNCTIONS ------------------------------------------------- #

    @classmethod
    def from_data(cls, data: dict) -> "CmdbPortConnection":
        """
        Initialises a CmdbPortConnection from a dict

        Args:
            data (dict): Data with which the CmdbPortConnection should be initialised

        Raises:
            CmdbPortConnectionInitFromDataError: If the initialisation with the given data fails

        Returns:
            CmdbPortConnection: CmdbPortConnection with the given data
        """
        try:
            creation_time = data.get(PortConnectionKey.CREATION_TIME.value, None)

            if creation_time and isinstance(creation_time, str):
                creation_time = parse(creation_time, fuzzy=True)

            last_edit_time = data.get(PortConnectionKey.LAST_EDIT_TIME.value, None)

            if last_edit_time and isinstance(last_edit_time, str):
                last_edit_time = parse(last_edit_time, fuzzy=True)

            return cls(
                public_id = data.get(PortConnectionKey.PUBLIC_ID.value),
                endpoints = data.get(PortConnectionKey.ENDPOINTS.value),
                connection_type = data.get(PortConnectionKey.CONNECTION_TYPE.value),
                cable_name = data.get(PortConnectionKey.CABLE_NAME.value),
                cable_type = data.get(PortConnectionKey.CABLE_TYPE.value),
                cable_length = data.get(PortConnectionKey.CABLE_LENGTH.value),
                cable_color = data.get(PortConnectionKey.CABLE_COLOR.value),
                cable_description = data.get(PortConnectionKey.CABLE_DESCRIPTION.value),
                cable_ci_id = data.get(PortConnectionKey.CABLE_CI_ID.value),
                author_id = data.get(PortConnectionKey.AUTHOR_ID.value),
                # The audit timestamps parse strictly: an unusable one surfaces as the model's own
                # error rather than silently becoming "now"
                creation_time = creation_time,
                last_edit_time = last_edit_time,
            )
        except Exception as err:
            raise CmdbPortConnectionInitFromDataError(err) from err


    @classmethod
    def to_json(cls, instance: "CmdbPortConnection") -> dict:
        """
        Converts a CmdbPortConnection into a json compatible dict

        'cable_ci_id' is the one key that can be MISSING from the result rather than null. The unique
        index on it is filtered on its presence, so writing null for the many connections that name no
        cable CI would place every one of them in that index and the second insert would be refused as
        a duplicate

        Args:
            instance (CmdbPortConnection): The CmdbPortConnection which should be converted

        Raises:
            CmdbPortConnectionToJsonError: If the CmdbPortConnection could not be converted

        Returns:
            dict: Json compatible dict of the CmdbPortConnection values
        """
        try:
            document: dict[str, Any] = {
                PortConnectionKey.PUBLIC_ID.value: instance.get_public_id(),
                PortConnectionKey.ENDPOINTS.value: instance.endpoints,
                PortConnectionKey.CONNECTION_TYPE.value: instance.connection_type,
                PortConnectionKey.CABLE_NAME.value: instance.cable_name,
                PortConnectionKey.CABLE_TYPE.value: instance.cable_type,
                PortConnectionKey.CABLE_LENGTH.value: instance.cable_length,
                PortConnectionKey.CABLE_COLOR.value: instance.cable_color,
                PortConnectionKey.CABLE_DESCRIPTION.value: instance.cable_description,
                PortConnectionKey.AUTHOR_ID.value: instance.author_id,
                PortConnectionKey.CREATION_TIME.value: instance.creation_time,
                PortConnectionKey.LAST_EDIT_TIME.value: instance.last_edit_time,
            }

            if instance.cable_ci_id is not None:
                document[PortConnectionKey.CABLE_CI_ID.value] = instance.cable_ci_id

            return document
        except Exception as err:
            raise CmdbPortConnectionToJsonError(err) from err

# ------------------------------------------------ GENERAL FUNCTIONS ------------------------------------------------- #

    def is_internal(self) -> bool:
        """
        Reports whether this connection is a patch panel's front-to-rear pairing

        The internal pairing is what a panel row's 'Pair' column shows, and it is the one connection
        type that carries no cable information at all

        Returns:
            bool: True when the connection type is INTERNAL
        """
        return self.connection_type == ConnectionType.INTERNAL


    def get_peer_of(self, port_id: int) -> int | None:
        """
        Returns the other end of the connection, seen from one of its ports

        The read every 'what is this port connected to' question makes. Written against the sorted
        pair rather than a fixed 'a' and 'b' end, because the connection is undirected and neither
        position means anything

        Args:
            port_id (int): public_id of the CmdbPort to look from

        Returns:
            int | None: public_id of the port at the other end, or None when the given port is not an
                endpoint of this connection
        """
        endpoints: list[int] = list(self.endpoints or [])

        if port_id not in endpoints:
            return None

        endpoints.remove(port_id)

        # A self-connection is refused on write, but a historical row must still answer something
        return endpoints[0] if endpoints else port_id
