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
This module manages the 'Rack View' - Profile for the DataGerry assistant
"""
from logging import Logger, getLogger
from typing import Any

from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.special_type_model.schemas.schema_provider import SchemaProvider

from .profile_base import ProfileBase
from .datagerry_assistant_constants import TypeSlotKey, RackTypeIdentity
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                 RackProfile - CLASS                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
class RackProfile(ProfileBase):
    """
    This class cointains all types and logics for the 'Rack View'-Profile

    The profile creates the RACK SpecialType from the canonical SchemaProvider blueprint, which is
    what makes the Rack View usable out-of-the-box: the view is rendered for objects of the type
    carrying the RACK marker. This is the assistant's only Rack type - the location profile stops at
    Room and no longer builds a plain one of its own, so nothing else fills the RACK_ID slot.
    """

    def create_profile(self) -> dict[str, int | None]:
        """
        Creates the RACK SpecialType of the 'Rack View'-Profile

        Returns:
            dict[str, int | None]: The shared slot map of created type ids
        """
        schema: dict[str, Any] = SchemaProvider().get_schema(SpecialType.RACK)

        type_dict: dict[str, Any] = self.type_constructor.create_special_type_config(
            schema,
            RackTypeIdentity.NAME,
            RackTypeIdentity.LABEL,
            RackTypeIdentity.ICON,
        )

        self.create_special_type(TypeSlotKey.RACK_ID, SpecialType.RACK, type_dict)

        return self.created_type_ids
