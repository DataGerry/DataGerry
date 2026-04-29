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
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                SchemaProvider - CLASS                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class SchemaProvider:
    """
    Provides required information of SpecialTypes for CmdbTypes
    """
    def get_schema(
        self,
        special_type: SpecialType,
        supernet_id: int | None = None,
        subnet_id: int | None = None,
    ) -> dict[str, Any]:
        """TODO: document"""
        if not SpecialType.is_valid(special_type):
            raise ValueError(f"Invalid 'special_type' provided: {special_type}")

        if special_type == SpecialType.SUPERNET:
            return get_supernet_schema()

        if special_type == SpecialType.SUBNET:
            if not supernet_id:
                raise ValueError("No Supernet ID provided for Subnet schema!")
            return get_subnet_schema(supernet_id)

        if special_type == SpecialType.VLAN:
            if not subnet_id:
                raise ValueError("No Subnet ID provided for Vlan schema!")
            return get_vlan_schema(subnet_id)

        raise ValueError(f"Unkown SpecialType: {special_type} provided to Schema!")
