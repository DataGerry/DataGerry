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
Field-name and section-name constants for the IPAM SpecialTypes (SUPERNET, SUBNET, VLAN) and
the dg-ipam-interface section template

Each enum is scoped to a single owner (one SpecialType, or the interface template) so a
member name documents which schema the string belongs to. All enums extend (str, Enum) so
members are interchangeable with their string values for dict lookup, equality and JSON
serialization. Use these members instead of bare 'dg-*' string literals when reading or
writing IPAM-related schemas, CmdbObject fields or MDS rows
"""
from enum import Enum
# -------------------------------------------------------------------------------------------------------------------- #


class SupernetField(str, Enum):
    """
    Field names of the SUPERNET SpecialType
    """
    NAME = 'dg-name'
    NETWORK_RANGE = 'dg-network-range'

    @classmethod
    def is_valid(cls, value: str) -> bool:
        """
        Checks if a given string is a known SupernetField

        Args:
            value (str): The string to check

        Returns:
            bool: True if the string matches an existing SupernetField, False otherwise
        """
        return value in cls._value2member_map_


class SubnetField(str, Enum):
    """
    Field names of the SUBNET SpecialType
    """
    NAME = 'dg-name'
    NETWORK_RANGE = 'dg-network-range'
    PARENT_SUPERNET = 'dg-supernet-ref'
    PARENT_SUBNET = 'dg-parent-subnet-ref'

    @classmethod
    def is_valid(cls, value: str) -> bool:
        """
        Checks if a given string is a known SubnetField

        Args:
            value (str): The string to check

        Returns:
            bool: True if the string matches an existing SubnetField, False otherwise
        """
        return value in cls._value2member_map_


class VlanField(str, Enum):
    """
    Field names of the VLAN SpecialType
    """
    NAME = 'dg-name'
    SUBNET_REF = 'dg-subnet-ref'
    TYPE = 'dg-vlan-type'

    @classmethod
    def is_valid(cls, value: str) -> bool:
        """
        Checks if a given string is a known VlanField

        Args:
            value (str): The string to check

        Returns:
            bool: True if the string matches an existing VlanField, False otherwise
        """
        return value in cls._value2member_map_


class InterfaceField(str, Enum):
    """
    Field names of one row in the dg-ipam-interface MDS section template
    """
    SUBNET = 'dg-interface-subnet'
    IP = 'dg-interface-ip-address'

    @classmethod
    def is_valid(cls, value: str) -> bool:
        """
        Checks if a given string is a known InterfaceField

        Args:
            value (str): The string to check

        Returns:
            bool: True if the string matches an existing InterfaceField, False otherwise
        """
        return value in cls._value2member_map_


class IpamSection(str, Enum):
    """
    Section names used in IPAM SpecialType schemas and the dg-ipam-interface MDS section template

    INTERFACE is the MDS section template name itself (not a section inside a SpecialType
    schema). The other members are section names that appear inside the SUPERNET / SUBNET / VLAN
    schemas
    """
    INTERFACE = 'dg-ipam-interface'
    INFORMATION = 'dg-information'
    NETWORK_DETAILS = 'dg-network-details'
    VLAN_DETAILS = 'dg-vlan-details'

    @classmethod
    def is_valid(cls, value: str) -> bool:
        """
        Checks if a given string is a known IpamSection

        Args:
            value (str): The string to check

        Returns:
            bool: True if the string matches an existing IpamSection, False otherwise
        """
        return value in cls._value2member_map_
