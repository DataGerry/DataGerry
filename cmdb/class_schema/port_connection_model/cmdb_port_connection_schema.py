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
Validation schema for CmdbPortConnection

A CmdbPortConnection joins two CmdbPorts (collection ``framework.portConnections``).

This module is the single source of the document's Cerberus validation schema, consumed as
CmdbPortConnection.SCHEMA. It describes the document's SHAPE only. Three rules it deliberately does
NOT express, because a per-field schema cannot:

  - that no port appears in two CABLE connections and in at most one INTERNAL one - that is the pair
    of partial unique indexes on ``endpoints``, and it is the feature's only hard guarantee
  - that the two endpoints differ, and that both name real ports - the connection validator's job
  - that an INTERNAL connection carries no cable info - the per-type field rule, also the validator's
"""
from typing import Any

from cmdb.models.port_connection_model.port_connection_constants import (
    ConnectionType,
    PortConnectionKey,
    ENDPOINT_COUNT,
)
# -------------------------------------------------------------------------------------------------------------------- #
# pylint: disable=R0801
def get_cmdb_port_connection_schema() -> dict[str, Any]:
    """
    Builds the Cerberus validation schema for a CmdbPortConnection document

    Returns:
        dict: Field name to Cerberus rule mapping, consumed as CmdbPortConnection.SCHEMA
    """
    return {
        PortConnectionKey.PUBLIC_ID.value: {  # public_id of the CmdbPortConnection
            'type': 'integer',
        },
        PortConnectionKey.ENDPOINTS.value: {  # The two connected CmdbPort public_ids, stored sorted
            'type': 'list',
            'required': True,
            'minlength': ENDPOINT_COUNT,
            'maxlength': ENDPOINT_COUNT,
            'schema': {'type': 'integer'},
        },
        PortConnectionKey.CONNECTION_TYPE.value: {  # Whether the link is a cable or a panel pairing
            'type': 'string',
            'required': True,
            'allowed': [connection_type.value for connection_type in ConnectionType],
        },
        PortConnectionKey.CABLE_NAME.value: {  # Free text naming the cable
            'type': 'string',
            'nullable': True,
            'required': False,
        },
        PortConnectionKey.CABLE_TYPE.value: {  # public_id of a CABLE_TYPE CmdbExtendableOption
            'type': 'integer',
            'nullable': True,
            'required': False,
        },
        PortConnectionKey.CABLE_LENGTH.value: {  # TEXT on purpose - '5 m', '2.5 m' (concept section 18)
            'type': 'string',
            'nullable': True,
            'required': False,
        },
        PortConnectionKey.CABLE_COLOR.value: {  # Free text for v1, not a '#RRGGBB' value
            'type': 'string',
            'nullable': True,
            'required': False,
        },
        PortConnectionKey.CABLE_DESCRIPTION.value: {  # Free text; the frontend renders it as a textarea
            'type': 'string',
            'nullable': True,
            'required': False,
        },
        PortConnectionKey.CABLE_CI_ID.value: {  # public_id of a CABLE SpecialType CmdbObject. ABSENT,
                                                # never null, when the connection names no cable CI -
                                                # its unique index is filtered on this key's presence,
                                                # so a stored null would make every CI-less connection
                                                # collide with the next one
            'type': 'integer',
            'required': False,
        },
        PortConnectionKey.AUTHOR_ID.value: {  # public_id of the CmdbUser who created the connection
            'type': 'integer',
            'nullable': True,
            'required': False,
        },
        PortConnectionKey.CREATION_TIME.value: {  # When the connection was created
            'type': 'dict',
            'nullable': True,
            'required': False,
        },
        PortConnectionKey.LAST_EDIT_TIME.value: {  # When the connection was last changed
            'type': 'dict',
            'nullable': True,
            'required': False,
        },
    }
