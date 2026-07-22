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
Unit tests for cmdb.models.special_type_model.schemas.subnet_schema

Focuses on the required 'Type' (IPv4/IPv6) select recently added to the SUBNET SpecialType: its
field definition, its placement in the Network Details section, and that only the IPv4 option is
offered for now. Includes a light regression check on the network-range field.
"""
from typing import Any

from cmdb.models.type_model import FieldType, SectionType, FieldKey, SectionKey
from cmdb.models.special_type_model.ipam_constants import SubnetField, IpamSection
from cmdb.models.special_type_model.schemas.subnet_schema import get_subnet_schema
# -------------------------------------------------------------------------------------------------------------------- #

TYPE_FIELD_LABEL: str = 'Type'
IPV4_OPTION: dict[str, str] = {FieldKey.NAME: 'ipv4', FieldKey.LABEL: 'IPv4'}
IPV6_OPTION: dict[str, str] = {FieldKey.NAME: 'ipv6', FieldKey.LABEL: 'IPv6'}


def _fields_by_name(schema: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Indexes the schema's flat field definitions by their name"""
    return {field[FieldKey.NAME]: field for field in schema['fields']}


def _section_by_name(schema: dict[str, Any], section_name: str) -> dict[str, Any]:
    """Returns the schema section with the given name"""
    return next(section for section in schema['sections'] if section[SectionKey.NAME] == section_name)

# -------------------------------------------------------------------------------------------------------------------- #
#                                              the new 'Type' select                                                 #
# -------------------------------------------------------------------------------------------------------------------- #

def test_subnet_type_field_is_a_required_select() -> None:
    """The subnet Type field is a required SELECT field"""
    type_field: dict[str, Any] = _fields_by_name(get_subnet_schema())[SubnetField.TYPE]

    assert type_field[FieldKey.TYPE] == FieldType.SELECT
    assert type_field[FieldKey.LABEL] == TYPE_FIELD_LABEL
    assert type_field[FieldKey.REQUIRED] is True


def test_subnet_type_field_offers_ipv4_and_ipv6() -> None:
    """The Type field offers the IPv4 and IPv6 options, in that order"""
    type_field: dict[str, Any] = _fields_by_name(get_subnet_schema())[SubnetField.TYPE]

    assert type_field[FieldKey.OPTIONS] == [IPV4_OPTION, IPV6_OPTION]


def test_subnet_type_field_sits_in_network_details_before_range() -> None:
    """The Type field is rendered in Network Details, ahead of the network range"""
    section: dict[str, Any] = _section_by_name(get_subnet_schema(), IpamSection.NETWORK_DETAILS)
    section_fields: list[str] = section[SectionKey.FIELDS]

    assert SubnetField.TYPE in section_fields
    assert section[SectionKey.TYPE] == SectionType.SECTION
    assert section_fields.index(SubnetField.TYPE) < section_fields.index(SubnetField.NETWORK_RANGE)

# -------------------------------------------------------------------------------------------------------------------- #
#                                          regression: existing fields                                               #
# -------------------------------------------------------------------------------------------------------------------- #

def test_network_range_remains_required() -> None:
    """The network-range field is still a required text field with a regex"""
    range_field: dict[str, Any] = _fields_by_name(get_subnet_schema())[SubnetField.NETWORK_RANGE]

    assert range_field[FieldKey.TYPE] == FieldType.TEXT
    assert range_field[FieldKey.REQUIRED] is True
    assert FieldKey.REGEX in range_field
