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
Sides and document keys of a CmdbPort

``PORT_TEMPLATE_FIELD_KEYS`` below is the field list the virtual section template is derived from, so
this module - not the template builder - is the single source of truth for which fields a port has and
in which order they are shown
"""
from cmdb.utils import BaseStrEnum

from cmdb.models.extendable_option_model.option_type_enum import OptionType
# -------------------------------------------------------------------------------------------------------------------- #

class PortSide(BaseStrEnum):
    """
    Which face of its owner object a port sits on

    Always explicit, never absent: **panel-ness is derived from this field**. A device is a patch panel
    exactly when its ports carry FRONT/REAR, so nothing has to store "is a panel" and nothing may infer
    it from port names - the concept forbids deriving the front/rear pairing from names (§7-§17).

      - SINGLE - an ordinary device port, the default
      - FRONT / REAR - the two faces of a patch panel, paired by an INTERNAL connection
    """
    SINGLE = 'single'
    FRONT = 'front'
    REAR = 'rear'


    @classmethod
    def get_panel_sides(cls) -> frozenset["PortSide"]:
        """
        Returns the two sides that only a patch panel has

        Returns:
            frozenset[PortSide]: The front and rear sides
        """
        return frozenset({cls.FRONT, cls.REAR})


    @classmethod
    def is_panel_side(cls, side: str | None) -> bool:
        """
        Reports whether a stored side value belongs to a patch panel

        Tolerates an unknown or missing value by answering False, which reads it as an ordinary
        SINGLE port - the same leniency the stored default has

        Args:
            side (str | None): The port's stored side value

        Returns:
            bool: True when the side is one of the panel faces
        """
        return side in {member.value for member in cls.get_panel_sides()}


class PortKey(BaseStrEnum):
    """
    Document field names of a CmdbPort (collection ``framework.ports``)

    PUBLIC_ID, OBJECT_ID, SIDE and the three audit keys are server-owned. The rest is the user-facing
    field list, which is also exactly what the virtual section template offers - see
    PORT_TEMPLATE_FIELD_KEYS.

    There is deliberately no ``connected`` key: it is computed from a port's connections on read and
    never stored, so a stale value cannot exist
    """
    PUBLIC_ID = 'public_id'
    OBJECT_ID = 'object_id'
    SIDE = 'side'
    NAME = 'name'
    PORT_NUMBER = 'port_number'
    STATUS = 'status'
    PORT_TYPE = 'port_type'
    SPEED = 'speed'
    DESCRIPTION = 'description'
    AUTHOR_ID = 'author_id'
    CREATION_TIME = 'creation_time'
    LAST_EDIT_TIME = 'last_edit_time'


# The user-facing port fields, in the order they are presented. The virtual section template is
# derived from this tuple, so adding a port field here is what makes it appear in the UI - and the
# order is part of that contract
PORT_TEMPLATE_FIELD_KEYS: tuple[PortKey, ...] = (
    PortKey.NAME,
    PortKey.PORT_NUMBER,
    PortKey.STATUS,
    PortKey.PORT_TYPE,
    PortKey.SPEED,
    PortKey.DESCRIPTION,
)

# The three port fields whose value is a CmdbExtendableOption, mapped to the OptionType each draws
# from. Two consumers: the virtual section template, which passes the option_type to the frontend so it
# can extend a list, and cmdb.framework.extendable_options, whose reference map is DERIVED from this -
# so an option cannot be deleted while a port still holds it, and the two cannot drift apart
PORT_SELECT_FIELD_OPTION_TYPES: dict[PortKey, OptionType] = {
    PortKey.STATUS: OptionType.PORT_STATUS,
    PortKey.PORT_TYPE: OptionType.PORT_TYPE,
    PortKey.SPEED: OptionType.PORT_SPEED,
}
