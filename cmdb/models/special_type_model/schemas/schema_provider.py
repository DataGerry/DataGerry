# DATAGERRY - OpenSource Enterprise CMDB
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
Provides the available SpecialType schemas with required CmdbType information
"""
from logging import Logger, getLogger
from typing import Any

from cmdb.models.special_type_model.special_type_enum import SpecialType

from cmdb.models.special_type_model.schemas.supernet_schema import get_supernet_schema
from cmdb.models.special_type_model.schemas.subnet_schema import get_subnet_schema
from cmdb.models.special_type_model.schemas.vlan_schema import get_vlan_schema
from cmdb.models.special_type_model.schemas.rack_schema import get_rack_schema
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                SchemaProvider - CLASS                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class SchemaProvider:
    """
    Provides required information of SpecialTypes for CmdbTypes
    """
    def get_schema(self, special_type: SpecialType) -> dict[str, Any]:
        """
        Returns the static section/field blueprint for the given SpecialType

        Reference fields are returned with empty 'ref_types'; cross-wiring of those lists is
        performed post-insert by handle_special_types

        Args:
            special_type (SpecialType): The SpecialType to build the schema for

        Raises:
            ValueError: If 'special_type' is not a valid SpecialType

        Returns:
            dict[str, Any]: Blueprint with sections, fields and the 'special_type' marker
        """
        if not SpecialType.is_valid(special_type):
            raise ValueError(f"Invalid 'special_type' provided: {special_type}")

        if special_type == SpecialType.SUPERNET:
            return get_supernet_schema()

        if special_type == SpecialType.SUBNET:
            return get_subnet_schema()

        if special_type == SpecialType.VLAN:
            return get_vlan_schema()

        if special_type == SpecialType.RACK:
            return get_rack_schema()

        raise ValueError(f"Unkown SpecialType: {special_type} provided to Schema!")
