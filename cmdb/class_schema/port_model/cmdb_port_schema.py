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
Validation schema for CmdbPort

A CmdbPort is one physical port of one CmdbObject (collection ``framework.ports``). The port owns its
own document and its own public_id; the CmdbObject stores nothing about its ports.

This module is the single source of the document's Cerberus validation schema, consumed as
CmdbPort.SCHEMA. It describes the document's SHAPE only: that a port name is unique within
(object_id, side) is enforced by the collection's unique index, and that a select value is one the
matching CmdbExtendableOption list actually offers is a cross-collection rule neither a schema nor an
index can express
"""
from typing import Any

from cmdb.models.port_model.port_constants import PortKey, PortSide
# -------------------------------------------------------------------------------------------------------------------- #
# pylint: disable=R0801
def get_cmdb_port_schema() -> dict[str, Any]:
    """
    Builds the Cerberus validation schema for a CmdbPort document

    Returns:
        dict: Field name to Cerberus rule mapping, consumed as CmdbPort.SCHEMA
    """
    return {
        PortKey.PUBLIC_ID.value: {  # public_id of the CmdbPort - the id every other collection uses
            'type': 'integer',
        },
        PortKey.OBJECT_ID.value: {  # public_id of the CmdbObject owning the port
            'type': 'integer',
            'required': True,
        },
        PortKey.SIDE.value: {  # Which face of the object the port sits on; panel-ness derives from it
            'type': 'string',
            'required': False,
            'allowed': [side.value for side in PortSide],
            'default': PortSide.SINGLE.value,
        },
        PortKey.NAME.value: {  # The port's label, unique within (object_id, side)
            'type': 'string',
            'required': True,
            'empty': False,
        },
        PortKey.PORT_NUMBER.value: {  # Optional number used for ordering (concept §4)
            'type': 'integer',
            'nullable': True,
            'required': False,
        },
        PortKey.STATUS.value: {  # public_id of a PORT_STATUS CmdbExtendableOption
            'type': 'integer',
            'nullable': True,
            'required': False,
        },
        PortKey.PORT_TYPE.value: {  # public_id of a PORT_TYPE CmdbExtendableOption
            'type': 'integer',
            'nullable': True,
            'required': False,
        },
        PortKey.SPEED.value: {  # public_id of a PORT_SPEED CmdbExtendableOption
            'type': 'integer',
            'nullable': True,
            'required': False,
        },
        PortKey.DESCRIPTION.value: {  # Free text
            'type': 'string',
            'nullable': True,
            'required': False,
        },
        PortKey.AUTHOR_ID.value: {  # public_id of the CmdbUser who created the port
            'type': 'integer',
            'nullable': True,
            'required': False,
        },
        PortKey.CREATION_TIME.value: {  # When the port was created
            'type': 'dict',
            'nullable': True,
            'required': False,
        },
        PortKey.LAST_EDIT_TIME.value: {  # When the port was last changed
            'type': 'dict',
            'nullable': True,
            'required': False,
        },
    }
