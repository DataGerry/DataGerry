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
This module contains the implementation of CmdbPort, one physical port of one CmdbObject
"""
from logging import Logger, getLogger
from datetime import datetime, timezone
from typing import Any

from dateutil.parser import parse

from cmdb.models.cmdb_dao import CmdbDAO
from cmdb.models.port_model.port_constants import PortKey, PortSide

from cmdb.class_schema.port_model.cmdb_port_schema import get_cmdb_port_schema

from cmdb.errors.models.cmdb_port import (
    CmdbPortInitError,
    CmdbPortInitFromDataError,
    CmdbPortToJsonError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                  CmdbPort - CLASS                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
class CmdbPort(CmdbDAO):
    """
    A CmdbPort is one physical port of one CmdbObject

    The port owns its own document and therefore a real public_id - the stable identifier connections
    and interface links reference. The relationship to its owner is one-way: the port stores
    'object_id', the CmdbObject stores nothing about its ports, exactly as CmdbRackMount relates to
    the object it mounts. A type declares that its objects have ports at all through
    CmdbType.uses_ports.

    'connected' is deliberately NOT a field. Whether a port is connected follows from its connections,
    so it is computed on read; storing it would create a second truth that can go stale.

    IP and MAC are equally absent: the IPAM interface an MDS row describes stays the single source for
    those, and a port links to one or more of them rather than copying their values

    `Extends`: CmdbDAO
    """
    COLLECTION = 'framework.ports'
    REQUIRED_INIT_KEYS: list[str] = [PortKey.OBJECT_ID.value, PortKey.NAME.value]

    INDEX_KEYS: list[dict[str, Any]] = [
        # A port name identifies a port within one face of one object, and this index is the actual
        # guarantee. The create route will pre-check it for a readable error, but that is a
        # read-then-write, so two concurrent requests can only be stopped here.
        #
        # 'side' is part of the key because a patch panel legitimately has a front 1 AND a rear 1 -
        # the same name on the two faces is not a duplicate, and a unique (object_id, name) index
        # would have made every panel unbuildable.
        #
        # Not partial: 'side' is always stored (the schema defaults it), so there is no missing-value
        # case to carve out
        {
            'keys': [
                (PortKey.OBJECT_ID.value, CmdbDAO.DAO_ASCENDING),
                (PortKey.SIDE.value, CmdbDAO.DAO_ASCENDING),
                (PortKey.NAME.value, CmdbDAO.DAO_ASCENDING),
            ],
            'name': 'object_side_name',
            'unique': True,
        },
        # Every port read is "the ports of this object", ordered by port number. Both this index and
        # the unique one above start with object_id, so an object_id-only query is served from either
        # prefix - which is why no standalone 'object_id' index is declared
        {
            'keys': [
                (PortKey.OBJECT_ID.value, CmdbDAO.DAO_ASCENDING),
                (PortKey.PORT_NUMBER.value, CmdbDAO.DAO_ASCENDING),
            ],
            'name': 'object_port_number',
            'unique': False,
        },
    ]

    SCHEMA: dict = get_cmdb_port_schema()


    #pylint: disable=R0913, R0917
    def __init__(
            self,
            public_id: int,
            object_id: int,
            name: str,
            side: str = PortSide.SINGLE.value,
            port_number: int | None = None,
            status: int | None = None,
            port_type: int | None = None,
            speed: int | None = None,
            description: str | None = None,
            author_id: int | None = None,
            creation_time: datetime = None,
            last_edit_time: datetime = None):
        """
        Initialises a CmdbPort

        Args:
            public_id (int): public_id of the CmdbPort
            object_id (int): public_id of the CmdbObject owning the port
            name (str): The port's label, unique within its (object_id, side)
            side (str): A PortSide value. Defaults to SINGLE, which is also what a document written
                        without the key reads as - panel-ness is derived from this field
            port_number (int | None): Optional number used for ordering
            status (int | None): public_id of a PORT_STATUS CmdbExtendableOption
            port_type (int | None): public_id of a PORT_TYPE CmdbExtendableOption
            speed (int | None): public_id of a PORT_SPEED CmdbExtendableOption
            description (str | None): Free text
            author_id (int | None): public_id of the CmdbUser who created the port
            creation_time (datetime, optional): When the port was created. Defaults to now
            last_edit_time (datetime, optional): When the port was last changed. Defaults to None

        Raises:
            CmdbPortInitError: If the CmdbPort could not be initialised
        """
        try:
            self.object_id: int = object_id
            self.name: str = name
            self.side: str = side
            self.port_number: int | None = port_number
            self.status: int | None = status
            self.port_type: int | None = port_type
            self.speed: int | None = speed
            self.description: str | None = description
            self.author_id: int | None = author_id
            self.creation_time: datetime = creation_time or datetime.now(timezone.utc)
            self.last_edit_time: datetime | None = last_edit_time

            super().__init__(public_id=public_id)
        except Exception as err:
            raise CmdbPortInitError(err) from err

# -------------------------------------------------- CLASS FUNCTIONS ------------------------------------------------- #

    @classmethod
    def from_data(cls, data: dict) -> "CmdbPort":
        """
        Initialises a CmdbPort from a dict

        Args:
            data (dict): Data with which the CmdbPort should be initialised

        Raises:
            CmdbPortInitFromDataError: If the initialisation with the given data fails

        Returns:
            CmdbPort: CmdbPort with the given data
        """
        try:
            creation_time = data.get(PortKey.CREATION_TIME.value, None)

            if creation_time and isinstance(creation_time, str):
                creation_time = parse(creation_time, fuzzy=True)

            last_edit_time = data.get(PortKey.LAST_EDIT_TIME.value, None)

            if last_edit_time and isinstance(last_edit_time, str):
                last_edit_time = parse(last_edit_time, fuzzy=True)

            return cls(
                public_id = data.get(PortKey.PUBLIC_ID.value),
                object_id = data.get(PortKey.OBJECT_ID.value),
                name = data.get(PortKey.NAME.value),
                # An absent side reads as SINGLE rather than as null: the unique index keys on it, and
                # a stored null would put an ordinary port in its own namespace
                side = data.get(PortKey.SIDE.value) or PortSide.SINGLE.value,
                port_number = data.get(PortKey.PORT_NUMBER.value),
                status = data.get(PortKey.STATUS.value),
                port_type = data.get(PortKey.PORT_TYPE.value),
                speed = data.get(PortKey.SPEED.value),
                description = data.get(PortKey.DESCRIPTION.value),
                author_id = data.get(PortKey.AUTHOR_ID.value),
                # The audit timestamps parse strictly: an unusable one surfaces as the model's own
                # error rather than silently becoming "now"
                creation_time = creation_time,
                last_edit_time = last_edit_time,
            )
        except Exception as err:
            raise CmdbPortInitFromDataError(err) from err


    @classmethod
    def to_json(cls, instance: "CmdbPort") -> dict:
        """
        Converts a CmdbPort into a json compatible dict

        Args:
            instance (CmdbPort): The CmdbPort which should be converted

        Raises:
            CmdbPortToJsonError: If the CmdbPort could not be converted

        Returns:
            dict: Json compatible dict of the CmdbPort values
        """
        try:
            return {
                PortKey.PUBLIC_ID.value: instance.get_public_id(),
                PortKey.OBJECT_ID.value: instance.object_id,
                PortKey.NAME.value: instance.name,
                PortKey.SIDE.value: instance.side,
                PortKey.PORT_NUMBER.value: instance.port_number,
                PortKey.STATUS.value: instance.status,
                PortKey.PORT_TYPE.value: instance.port_type,
                PortKey.SPEED.value: instance.speed,
                PortKey.DESCRIPTION.value: instance.description,
                PortKey.AUTHOR_ID.value: instance.author_id,
                PortKey.CREATION_TIME.value: instance.creation_time,
                PortKey.LAST_EDIT_TIME.value: instance.last_edit_time,
            }
        except Exception as err:
            raise CmdbPortToJsonError(err) from err

# ------------------------------------------------ GENERAL FUNCTIONS ------------------------------------------------- #

    def is_panel_port(self) -> bool:
        """
        Reports whether this port is one face of a patch panel

        Panel-ness is a property of the port's side and of nothing else - never of the object, and
        never derived from the port's name, which the concept explicitly forbids

        Returns:
            bool: True when the port sits on a front or rear face
        """
        return PortSide.is_panel_side(self.side)
