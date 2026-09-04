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
This module contains the implementation of CmdbPortInterfaceLink, one port-to-interface association
"""
from logging import Logger, getLogger
from datetime import datetime, timezone
from typing import Any

from dateutil.parser import parse

from cmdb.models.cmdb_dao import CmdbDAO
from cmdb.models.port_interface_link_model.port_interface_link_constants import (
    PortInterfaceLinkKey,
    INTERFACE_ROW_INDEX_NAME,
    LINK_IDENTITY_INDEX_NAME,
    LINK_IDENTITY_KEYS,
    PORT_ID_INDEX_NAME,
)

from cmdb.class_schema.port_interface_link_model.cmdb_port_interface_link_schema import (
    get_cmdb_port_interface_link_schema,
)

from cmdb.errors.models.cmdb_port_interface_link import (
    CmdbPortInterfaceLinkInitError,
    CmdbPortInterfaceLinkInitFromDataError,
    CmdbPortInterfaceLinkToJsonError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                          CmdbPortInterfaceLink - CLASS                                               #
# -------------------------------------------------------------------------------------------------------------------- #
class CmdbPortInterfaceLink(CmdbDAO):
    """
    A CmdbPortInterfaceLink associates one CmdbPort with one IPAM interface row

    The relationship is N:M - one port may carry several interfaces (a bond member, a stack of VLAN
    sub-interfaces) and one interface may be reachable over several ports - so it is its own document
    rather than a field on either side.

    **The reference to the interface row is SOFT, by decision.** It addresses an MDS row by
    (object, section, multi_data_id), and that row id is the non-durable part: the full object PUT does
    not preserve MDS row ids and the CSV import overwrite renumbers them, so a hard reference would
    break on writes that have nothing to do with ports. A link whose row has gone is therefore
    tolerated on read and REPORTED, never cascaded - the repair is the customer's to make, and silently
    deleting their link would destroy the only record of what they meant.

    Creating a link that is already dangling is a different matter and is refused: that is a mistake
    the write path can see.

    No IP and no MAC live here. The interface row stays the single source for those, which is the whole
    reason a port links to one instead of copying its values

    `Extends`: CmdbDAO
    """
    COLLECTION = 'framework.portInterfaceLinks'
    REQUIRED_INIT_KEYS: list[str] = [
        PortInterfaceLinkKey.PORT_ID.value,
        PortInterfaceLinkKey.INTERFACE_OBJECT_ID.value,
        PortInterfaceLinkKey.INTERFACE_SECTION_ID.value,
        PortInterfaceLinkKey.INTERFACE_MULTI_DATA_ID.value,
        PortInterfaceLinkKey.RELATION_TYPE.value,
    ]

    INDEX_KEYS: list[dict[str, Any]] = [
        # One link per port/interface pair. relation_type is deliberately NOT part of the key: it
        # DESCRIBES the pair rather than identifying it, so including it would let the same port and
        # the same interface row be linked once per relation type
        {
            'keys': [(key.value, CmdbDAO.DAO_ASCENDING) for key in LINK_IDENTITY_KEYS],
            'name': LINK_IDENTITY_INDEX_NAME,
            'unique': True,
        },
        # 'the interfaces of this port' - the read the ports panel makes for every port it shows
        {
            'keys': [(PortInterfaceLinkKey.PORT_ID.value, CmdbDAO.DAO_ASCENDING)],
            'name': PORT_ID_INDEX_NAME,
            'unique': False,
        },
        # The reverse lookup ('which ports reach this interface') and, more importantly, the
        # dangling-link report, which walks links grouped by the object holding their row
        {
            'keys': [
                (PortInterfaceLinkKey.INTERFACE_OBJECT_ID.value, CmdbDAO.DAO_ASCENDING),
                (PortInterfaceLinkKey.INTERFACE_MULTI_DATA_ID.value, CmdbDAO.DAO_ASCENDING),
            ],
            'name': INTERFACE_ROW_INDEX_NAME,
            'unique': False,
        },
    ]

    SCHEMA: dict = get_cmdb_port_interface_link_schema()


    #pylint: disable=R0913, R0917
    def __init__(
            self,
            public_id: int,
            port_id: int,
            interface_object_id: int,
            interface_section_id: str,
            interface_multi_data_id: int,
            relation_type: str,
            author_id: int | None = None,
            creation_time: datetime = None,
            last_edit_time: datetime = None):
        """
        Initialises a CmdbPortInterfaceLink

        Args:
            public_id (int): public_id of the CmdbPortInterfaceLink
            port_id (int): public_id of the linked CmdbPort
            interface_object_id (int): public_id of the CmdbObject holding the interface MDS row
            interface_section_id (str): Name of the MDS section the row lives in, 'dg-ipam-interface'
                                        today. Stored so the triple is self-describing
            interface_multi_data_id (int): The MDS row's multi_data_id - the non-durable part of the
                                           reference
            relation_type (str): An InterfaceRelationType value
            author_id (int | None): public_id of the CmdbUser who created the link
            creation_time (datetime, optional): When the link was created. Defaults to now
            last_edit_time (datetime, optional): When the link was last changed. Defaults to None

        Raises:
            CmdbPortInterfaceLinkInitError: If the CmdbPortInterfaceLink could not be initialised
        """
        try:
            self.port_id: int = port_id
            self.interface_object_id: int = interface_object_id
            self.interface_section_id: str = interface_section_id
            self.interface_multi_data_id: int = interface_multi_data_id
            self.relation_type: str = relation_type
            self.author_id: int | None = author_id
            self.creation_time: datetime = creation_time or datetime.now(timezone.utc)
            self.last_edit_time: datetime | None = last_edit_time

            super().__init__(public_id=public_id)
        except Exception as err:
            raise CmdbPortInterfaceLinkInitError(err) from err

# -------------------------------------------------- CLASS FUNCTIONS ------------------------------------------------- #

    @classmethod
    def from_data(cls, data: dict) -> "CmdbPortInterfaceLink":
        """
        Initialises a CmdbPortInterfaceLink from a dict

        Args:
            data (dict): Data with which the CmdbPortInterfaceLink should be initialised

        Raises:
            CmdbPortInterfaceLinkInitFromDataError: If the initialisation with the given data fails

        Returns:
            CmdbPortInterfaceLink: CmdbPortInterfaceLink with the given data
        """
        try:
            creation_time = data.get(PortInterfaceLinkKey.CREATION_TIME.value, None)

            if creation_time and isinstance(creation_time, str):
                creation_time = parse(creation_time, fuzzy=True)

            last_edit_time = data.get(PortInterfaceLinkKey.LAST_EDIT_TIME.value, None)

            if last_edit_time and isinstance(last_edit_time, str):
                last_edit_time = parse(last_edit_time, fuzzy=True)

            return cls(
                public_id = data.get(PortInterfaceLinkKey.PUBLIC_ID.value),
                port_id = data.get(PortInterfaceLinkKey.PORT_ID.value),
                interface_object_id = data.get(PortInterfaceLinkKey.INTERFACE_OBJECT_ID.value),
                interface_section_id = data.get(PortInterfaceLinkKey.INTERFACE_SECTION_ID.value),
                interface_multi_data_id = data.get(PortInterfaceLinkKey.INTERFACE_MULTI_DATA_ID.value),
                relation_type = data.get(PortInterfaceLinkKey.RELATION_TYPE.value),
                author_id = data.get(PortInterfaceLinkKey.AUTHOR_ID.value),
                # The audit timestamps parse strictly: an unusable one surfaces as the model's own
                # error rather than silently becoming "now"
                creation_time = creation_time,
                last_edit_time = last_edit_time,
            )
        except Exception as err:
            raise CmdbPortInterfaceLinkInitFromDataError(err) from err


    @classmethod
    def to_json(cls, instance: "CmdbPortInterfaceLink") -> dict:
        """
        Converts a CmdbPortInterfaceLink into a json compatible dict

        Args:
            instance (CmdbPortInterfaceLink): The CmdbPortInterfaceLink which should be converted

        Raises:
            CmdbPortInterfaceLinkToJsonError: If the CmdbPortInterfaceLink could not be converted

        Returns:
            dict: Json compatible dict of the CmdbPortInterfaceLink values
        """
        try:
            return {
                PortInterfaceLinkKey.PUBLIC_ID.value: instance.get_public_id(),
                PortInterfaceLinkKey.PORT_ID.value: instance.port_id,
                PortInterfaceLinkKey.INTERFACE_OBJECT_ID.value: instance.interface_object_id,
                PortInterfaceLinkKey.INTERFACE_SECTION_ID.value: instance.interface_section_id,
                PortInterfaceLinkKey.INTERFACE_MULTI_DATA_ID.value: instance.interface_multi_data_id,
                PortInterfaceLinkKey.RELATION_TYPE.value: instance.relation_type,
                PortInterfaceLinkKey.AUTHOR_ID.value: instance.author_id,
                PortInterfaceLinkKey.CREATION_TIME.value: instance.creation_time,
                PortInterfaceLinkKey.LAST_EDIT_TIME.value: instance.last_edit_time,
            }
        except Exception as err:
            raise CmdbPortInterfaceLinkToJsonError(err) from err

# ------------------------------------------------ GENERAL FUNCTIONS ------------------------------------------------- #

    def get_interface_reference(self) -> tuple[int, str, int]:
        """
        Returns the triple addressing the linked interface row

        The one way "which row is this" is asked, so a reader never has to assemble the three keys
        itself and a fourth coordinate could be added in one place

        Returns:
            tuple[int, str, int]: The object public_id, the section name and the MDS row id
        """
        return (self.interface_object_id, self.interface_section_id, self.interface_multi_data_id)
