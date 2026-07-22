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
Unit tests for cmdb.models.special_type_model.schemas.vlan_schema

Pins the VLAN SpecialType blueprint: the special_type marker, the Subnet reference field (with an
empty ref_types populated post-insert), and the Type select (static / dynamic) and its placement
in the Vlan Details section.
"""
from typing import Any

from cmdb.models.type_model import FieldType, SectionType, FieldKey, SectionKey, TypeSchemaKey
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.special_type_model.ipam_constants import VlanField, IpamSection
from cmdb.models.special_type_model.schemas.vlan_schema import get_vlan_schema
# -------------------------------------------------------------------------------------------------------------------- #


def _fields_by_name(schema: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Indexes the schema's flat field definitions by their name"""
    return {field[FieldKey.NAME]: field for field in schema[TypeSchemaKey.FIELDS]}


def _section_by_name(schema: dict[str, Any], section_name: str) -> dict[str, Any]:
    """Returns the schema section with the given name"""
    return next(section for section in schema[TypeSchemaKey.SECTIONS] if section[SectionKey.NAME] == section_name)


def test_vlan_schema_carries_special_type_marker() -> None:
    """The blueprint is marked as the VLAN SpecialType"""
    assert get_vlan_schema()[TypeSchemaKey.SPECIAL_TYPE] == SpecialType.VLAN


def test_vlan_subnet_ref_is_a_reference_field_with_empty_ref_types() -> None:
    """dg-subnet-ref is a REFERENCE field whose ref_types start empty (wired post-insert)"""
    ref_field: dict[str, Any] = _fields_by_name(get_vlan_schema())[VlanField.SUBNET_REF]

    assert ref_field[FieldKey.TYPE] == FieldType.REFERENCE
    assert ref_field[FieldKey.REF_TYPES] == []


def test_vlan_type_field_is_a_select_offering_static_and_dynamic() -> None:
    """The Type field is a SELECT offering the static and dynamic options, in that order"""
    type_field: dict[str, Any] = _fields_by_name(get_vlan_schema())[VlanField.TYPE]

    assert type_field[FieldKey.TYPE] == FieldType.SELECT
    assert [opt[FieldKey.NAME] for opt in type_field[FieldKey.OPTIONS]] == ['static', 'dynamic']


def test_vlan_details_section_lists_subnet_ref_then_type() -> None:
    """The Vlan Details section renders the subnet reference ahead of the type select"""
    section: dict[str, Any] = _section_by_name(get_vlan_schema(), IpamSection.VLAN_DETAILS)
    section_fields: list[str] = section[SectionKey.FIELDS]

    assert section[SectionKey.TYPE] == SectionType.SECTION
    assert section_fields.index(VlanField.SUBNET_REF) < section_fields.index(VlanField.TYPE)


def test_vlan_name_is_the_first_flat_field() -> None:
    """The name field is the first flat field (the SpecialType summary field)"""
    assert get_vlan_schema()[TypeSchemaKey.FIELDS][0][FieldKey.NAME] == VlanField.NAME
