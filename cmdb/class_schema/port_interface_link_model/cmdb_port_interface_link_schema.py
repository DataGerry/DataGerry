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
Validation schema for CmdbPortInterfaceLink

A CmdbPortInterfaceLink joins one CmdbPort to one IPAM interface MDS row (collection
``framework.portInterfaceLinks``).

This module is the single source of the document's Cerberus validation schema, consumed as
CmdbPortInterfaceLink.SCHEMA. It describes the document's SHAPE only. Three rules it deliberately does
NOT express:

  - that a port is linked to the same interface row at most once - that is the unique index on the
    identity tuple
  - that the port and the interface object exist, and that the addressed MDS row is really there -
    cross-collection rules the link validator checks on write
  - that the row keeps existing afterwards. The reference is SOFT by design: a link whose interface row
    was deleted is tolerated on read and reported, never cascaded
"""
from typing import Any

from cmdb.models.port_interface_link_model.port_interface_link_constants import (
    InterfaceRelationType,
    PortInterfaceLinkKey,
)
# -------------------------------------------------------------------------------------------------------------------- #
# pylint: disable=R0801
def get_cmdb_port_interface_link_schema() -> dict[str, Any]:
    """
    Builds the Cerberus validation schema for a CmdbPortInterfaceLink document

    Returns:
        dict: Field name to Cerberus rule mapping, consumed as CmdbPortInterfaceLink.SCHEMA
    """
    return {
        PortInterfaceLinkKey.PUBLIC_ID.value: {  # public_id of the CmdbPortInterfaceLink
            'type': 'integer',
        },
        PortInterfaceLinkKey.PORT_ID.value: {  # public_id of the linked CmdbPort
            'type': 'integer',
            'required': True,
        },
        PortInterfaceLinkKey.INTERFACE_OBJECT_ID.value: {  # CmdbObject holding the interface MDS row
            'type': 'integer',
            'required': True,
        },
        PortInterfaceLinkKey.INTERFACE_SECTION_ID.value: {  # 'dg-ipam-interface' - stored so the
                                                           # triple is self-describing
            'type': 'string',
            'required': True,
            'empty': False,
        },
        PortInterfaceLinkKey.INTERFACE_MULTI_DATA_ID.value: {  # The MDS row id - the non-durable part
            'type': 'integer',
            'required': True,
        },
        PortInterfaceLinkKey.RELATION_TYPE.value: {  # How the port relates to the interface
            'type': 'string',
            'required': True,
            'allowed': [relation_type.value for relation_type in InterfaceRelationType],
        },
        PortInterfaceLinkKey.AUTHOR_ID.value: {  # public_id of the CmdbUser who created the link
            'type': 'integer',
            'nullable': True,
            'required': False,
        },
        PortInterfaceLinkKey.CREATION_TIME.value: {  # When the link was created
            'type': 'dict',
            'nullable': True,
            'required': False,
        },
        PortInterfaceLinkKey.LAST_EDIT_TIME.value: {  # When the link was last changed
            'type': 'dict',
            'nullable': True,
            'required': False,
        },
    }
