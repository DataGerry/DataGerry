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
Implementation of all available SpecialTypes
"""
from typing import Any, Iterable

from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #

class SpecialType(BaseStrEnum):
    """Types of Events"""
    SUPERNET = 'SUPERNET'
    SUBNET = 'SUBNET'
    VLAN = 'VLAN'


    @classmethod
    def get_special_types(cls) -> dict[str, Any]:
        """TODO: document"""
        return {
            cls.SUPERNET: "IPAM - Supernet class",
            cls.SUBNET: "IPAM - Subnet class",
            cls.VLAN: "IPAM - VLAN class"
        }


    @classmethod
    def get_unused_types(cls, existing: Iterable[str]) -> dict[str, Any]:
        """TODO: dcoument"""
        existing_set: set[str] = set(existing)

        unused_types: dict[str, Any] = {
            key: value
            for key, value in cls.get_special_types().items()
            if key not in existing_set
        }

        return unused_types
