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
<<<<<<< HEAD
Implementation of all available SpecialTypes
"""
from typing import Any, Iterable
from enum import Enum
# -------------------------------------------------------------------------------------------------------------------- #

class SpecialType(str, Enum):
    """Types of Events"""
=======
The SpecialType enum: CmdbType flavours that carry framework-level IPAM behaviour

A CmdbType marks itself as a SpecialType via its schema's 'special_type' key. On creation
such a type receives its predefined schema (see cmdb.models.special_type_model.schemas) and
the IPAM cross-wiring (reference fields, dg-ipam-interface template; see
cmdb.framework.ipam.special_type_wiring). The enum extends BaseStrEnum so members are
interchangeable with their string values for dict lookup, equality and JSON serialization
"""
from typing import Iterable

from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #

class SpecialType(BaseStrEnum):
    """
    The available SpecialType tokens stored under a CmdbType schema's 'special_type' key

    At most one CmdbType per member may exist in an installation - the special-type creation
    route only offers members not yet claimed (see ``get_unused_types``). The string values
    are the wire-format tokens exchanged with the frontend
    """
>>>>>>> origin/version-3.2
    SUPERNET = 'SUPERNET'
    SUBNET = 'SUBNET'
    VLAN = 'VLAN'


    @classmethod
<<<<<<< HEAD
    def is_valid(cls, value: str) -> bool:
        """
        Checks if a given string is a valid SpecialType

        Args:
            value (str): The string to check

        Returns:
            bool: True if the string matches an existing SpecialType, False otherwise
        """
        return value in cls._value2member_map_


    @classmethod
    def get_special_types(cls) -> dict[str, Any]:
        """TODO: document"""
=======
    def get_special_types(cls) -> dict[str, str]:
        """
        Returns every SpecialType member mapped to its user-facing display label

        Backs the special-type listing route when existing special types are not filtered
        out; the labels are the fixed English strings the frontend shows in the creation
        dialog

        Returns:
            dict[str, str]: {member: display label} for every member of the enum
        """
>>>>>>> origin/version-3.2
        return {
            cls.SUPERNET: "IPAM - Supernet class",
            cls.SUBNET: "IPAM - Subnet class",
            cls.VLAN: "IPAM - VLAN class"
        }


    @classmethod
<<<<<<< HEAD
    def get_unused_types(cls, existing: Iterable[str]) -> dict[str, Any]:
        """TODO: dcoument"""
        existing_set: set[str] = set(existing)

        unused_types: dict[str, Any] = {
=======
    def get_unused_types(cls, existing: Iterable[str]) -> dict[str, str]:
        """
        Returns the SpecialTypes not yet claimed by an existing CmdbType, with display labels

        Drives the special-type creation dialog: each SpecialType may exist at most once, so
        members whose value appears in ``existing`` are omitted from the result

        Args:
            existing (Iterable[str]): SpecialType values already claimed by existing CmdbTypes

        Returns:
            dict[str, str]: {member: display label} for every member not in ``existing``
        """
        existing_set: set[str] = set(existing)

        unused_types: dict[str, str] = {
>>>>>>> origin/version-3.2
            key: value
            for key, value in cls.get_special_types().items()
            if key not in existing_set
        }

<<<<<<< HEAD
        # Subnet requires Supernet to exist
        if cls.SUPERNET not in existing_set:
            unused_types.pop(cls.SUBNET, None)

        # VLAN requires Subnet to exist
        if cls.SUBNET not in existing_set:
            unused_types.pop(cls.VLAN, None)

=======
>>>>>>> origin/version-3.2
        return unused_types
