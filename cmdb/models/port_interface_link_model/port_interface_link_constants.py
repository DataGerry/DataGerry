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
Relation types, document keys and index names of a CmdbPortInterfaceLink

``INTERFACE_REFERENCE_KEYS`` below is the triple identifying the linked interface row, so this module -
not a route or a validator - is the single source of truth for what "the same interface row" means
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #

class InterfaceRelationType(BaseStrEnum):
    """
    How a CmdbPort relates to the IPAM interface it is linked to

    A FIXED list, deliberately NOT a CmdbExtendableOption: the concept names these five and calls them
    explicitly non-customizable, unlike the port's status / type / speed lists. A customer-added sixth
    would carry no meaning for anything reading the link, so there is nothing for it to configure.

      - PHYSICAL - the interface runs directly on this port
      - BOND     - the port is one member of a bonded/aggregated interface
      - VLAN     - the interface is a VLAN sub-interface carried over this port
      - VIRTUAL  - a virtual interface associated with the port
      - OTHER    - anything the four above do not describe
    """
    PHYSICAL = 'PHYSICAL'
    BOND = 'BOND'
    VLAN = 'VLAN'
    VIRTUAL = 'VIRTUAL'
    OTHER = 'OTHER'


class PortInterfaceLinkKey(BaseStrEnum):
    """
    Document field names of a CmdbPortInterfaceLink (collection ``framework.portInterfaceLinks``)

    The link is N:M *within one CmdbObject* - one port may carry several interfaces and one interface
    may be reached over several of that object's ports - so it is its own document rather than a field
    on either side. A port is never linked to another object's interface: the two describe the same
    physical device.

    The three INTERFACE_* keys address one MDS row. INTERFACE_OBJECT_ID is consequently always the
    port's owner; it is stored rather than derived because it is what addresses the row and what the
    dangling report groups by. INTERFACE_SECTION_ID is stored even though it is
    constant today (`dg-ipam-interface`), so the triple is self-describing: a reader does not have to
    know which section the id belongs to, and a second interface-bearing section later would not
    invalidate every stored row.

    IP and MAC are deliberately absent. The interface row remains the single source for those, which is
    the whole reason a port links to one instead of copying its values
    """
    PUBLIC_ID = 'public_id'
    PORT_ID = 'port_id'
    INTERFACE_OBJECT_ID = 'interface_object_id'
    INTERFACE_SECTION_ID = 'interface_section_id'
    INTERFACE_MULTI_DATA_ID = 'interface_multi_data_id'
    RELATION_TYPE = 'relation_type'
    AUTHOR_ID = 'author_id'
    CREATION_TIME = 'creation_time'
    LAST_EDIT_TIME = 'last_edit_time'


# The three keys that together address one interface MDS row. Every "is this the same interface" and
# "resolve this link" question is asked through this tuple rather than through the keys one at a time,
# so a fourth coordinate could be added in one place
INTERFACE_REFERENCE_KEYS: tuple[PortInterfaceLinkKey, ...] = (
    PortInterfaceLinkKey.INTERFACE_OBJECT_ID,
    PortInterfaceLinkKey.INTERFACE_SECTION_ID,
    PortInterfaceLinkKey.INTERFACE_MULTI_DATA_ID,
)

# The keys of the unique constraint: the port plus the interface triple, and deliberately NOT
# relation_type - there is ONE link per port/interface pair, and the relation type describes that pair
# rather than being part of its identity. Including it would let the same pair be linked five times
LINK_IDENTITY_KEYS: tuple[PortInterfaceLinkKey, ...] = (
    PortInterfaceLinkKey.PORT_ID,
    *INTERFACE_REFERENCE_KEYS,
)

# Names of the three declared indexes
PORT_ID_INDEX_NAME: str = 'port_id'
INTERFACE_ROW_INDEX_NAME: str = 'interface_object_multi_data'
LINK_IDENTITY_INDEX_NAME: str = 'port_interface_row'


class AssignableInterfaceKey(BaseStrEnum):
    """
    Keys of one row of the assignable-interfaces picker

    The row is a projection, not a stored document: the first three keys are exactly the triple a
    create needs (`PortInterfaceLinkKey.INTERFACE_*`), so selecting a row and posting it is a copy
    rather than a translation, and the rest is what the picker shows. The interface values are
    resolved out of the MDS row's {name, value, type} entries and the subnet reference into
    {public_id, name}, so a consumer renders the table without knowing a single
    `dg-interface-*` field name
    """
    INTERFACE_OBJECT_ID = 'interface_object_id'
    INTERFACE_SECTION_ID = 'interface_section_id'
    INTERFACE_MULTI_DATA_ID = 'interface_multi_data_id'
    ACTIVE = 'active'
    IP = 'ip'
    MAC = 'mac'
    HOSTNAME = 'hostname'
    DOMAIN = 'domain'
    ADDRESS_FAMILY = 'address_family'
    SUBNET = 'subnet'
    OBJECT_INFO = 'object_info'


class AssignableInterfaceObjectKey(BaseStrEnum):
    """
    Keys of a picker row's `object_info` sub-dict - the device the interface row lives on

    Present because an interface row means nothing on its own: two devices can hold the same IP in
    different subnets, and the caller is choosing between devices as much as between addresses
    """
    PUBLIC_ID = 'public_id'
    TYPE_ID = 'type_id'
    TYPE_LABEL = 'type_label'
    SUMMARY_LINE = 'summary_line'


class AssignableInterfaceSubnetKey(BaseStrEnum):
    """Keys of a picker row's resolved `subnet` sub-dict, absent when the row references none"""
    PUBLIC_ID = 'public_id'
    NAME = 'name'
