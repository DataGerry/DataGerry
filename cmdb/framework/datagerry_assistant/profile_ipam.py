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
This module manages the IPAM - Profile for the DataGerry assistant
"""
from logging import Logger, getLogger
from typing import Any

from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.special_type_model.schemas.schema_provider import SchemaProvider

from .profile_base import ProfileBase
from .datagerry_assistant_constants import IPAM_SPECIAL_TYPE_DEFINITIONS, IpamSpecialTypeKey
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                  IPAMProfile - CLASS                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
class IPAMProfile(ProfileBase):
    """
    This class cointains all types and logics for the 'IPAM'-Profile

    The profile creates the three IPAM SpecialTypes (Supernet, Subnet, VLAN) from the canonical
    SchemaProvider blueprints and wires their reference fields via handle_special_types.
    """

    def create_profile(self) -> dict[str, int | None]:
        """
        Creates all SpecialTypes from the 'IPAM'-Profile

        The SpecialTypes are created in the order declared in IPAM_SPECIAL_TYPE_DEFINITIONS
        (Supernet, then Subnet, then VLAN) so that each type's reference fields can be wired to the
        previously created ones.

        Returns:
            dict: The created type ids dict
        """
        schema_provider: SchemaProvider = SchemaProvider()

        definition: dict[str, Any]
        for definition in IPAM_SPECIAL_TYPE_DEFINITIONS:
            special_type: SpecialType = definition[IpamSpecialTypeKey.SPECIAL_TYPE]
            schema: dict[str, Any] = schema_provider.get_schema(special_type)

            type_dict: dict[str, Any] = self.type_constructor.create_special_type_config(
                schema,
                definition[IpamSpecialTypeKey.NAME],
                definition[IpamSpecialTypeKey.LABEL],
                definition[IpamSpecialTypeKey.ICON],
            )

            self.create_special_type(definition[IpamSpecialTypeKey.SLOT], special_type, type_dict)

        return self.created_type_ids
