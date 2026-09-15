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
  - that a connection describes its cable inline OR by reference and never both - the validator's too

``get_cmdb_port_connection_write_schema`` derives the REQUEST body's schema from the document's. It
exists because the two are not the same thing: a request may not carry the server-owned keys at all,
and the two identity keys are deliberately left UNTYPED there, so the connection validator keeps
answering for them with a message a caller can act on
"""
from typing import Any

# The three shapes a date arrives in: the Mongo extended-JSON wrapper {'$date': ...} the frontend
# sends, a timestamp string from an API client, and a real datetime (an already-normalised payload)
_DATE_TYPES: list[str] = ['dict', 'string', 'datetime']
# -------------------------------------------------------------------------------------------------------------------- #
# pylint: disable=R0801
def get_cmdb_port_connection_schema() -> dict[str, Any]:
    """
    Builds the Cerberus validation schema for a CmdbPortConnection document

    Returns:
        dict: Field name to Cerberus rule mapping, consumed as CmdbPortConnection.SCHEMA
    """
    # pylint: disable=import-outside-toplevel
    # Resolved at call time, not at module import time: the model imports this builder while its own
    # package __init__ is still running, so a module-level import back into cmdb.models would close that
    # cycle and leave every class_schema module unimportable on its own (see class_schema/__init__.py)
    from cmdb.models.port_connection_model.port_connection_constants import (
        ConnectionType,
        PortConnectionKey,
        ENDPOINT_COUNT,
    )

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
            'anyof_type': _DATE_TYPES,
            'nullable': True,
            'required': False,
        },
        PortConnectionKey.LAST_EDIT_TIME.value: {  # When the connection was last changed
            'anyof_type': _DATE_TYPES,
            'nullable': True,
            'required': False,
        },
    }


def get_cmdb_port_connection_write_schema() -> dict[str, Any]:
    """
    Builds the Cerberus validation schema for a CmdbPortConnection REQUEST body

    Derived from the document schema so a field's type is declared once, with two deliberate
    differences:

      - the SERVER-OWNED keys are absent (public_id and the three audit fields). The validator runs
        with ``purge_unknown=True``, so leaving them out does more than ignore them - a payload
        carrying an author_id or a creation_time never reaches the route at all
      - ``endpoints`` and ``connection_type`` are accepted UNTYPED. Both are judged by
        cmdb.framework.port.connection_validator, which answers 'a connection needs exactly 2 port
        ids' or names the allowed types; letting a type rule refuse them first would replace those
        messages with the decorator's generic one

    What this schema is really for is the cable half: five text fields and two ids that nothing else
    type-checks, so before it a CSV-shaped number reached the database as the value of a field the
    document schema declares a string

    Returns:
        dict: Field name to Cerberus rule mapping for a create or update body
    """
    # pylint: disable=import-outside-toplevel
    # Same cycle as above: resolved at call time, not at module import time
    from cmdb.models.port_connection_model.port_connection_constants import PortConnectionKey

    document_schema: dict[str, Any] = get_cmdb_port_connection_schema()
    server_owned: set[str] = {
        PortConnectionKey.PUBLIC_ID.value,
        PortConnectionKey.AUTHOR_ID.value,
        PortConnectionKey.CREATION_TIME.value,
        PortConnectionKey.LAST_EDIT_TIME.value,
    }
    untyped: set[str] = {
        PortConnectionKey.ENDPOINTS.value,
        PortConnectionKey.CONNECTION_TYPE.value,
    }

    return {
        key: ({'required': False} if key in untyped else {**rules, 'required': False})
        for key, rules in document_schema.items()
        if key not in server_owned
    }
