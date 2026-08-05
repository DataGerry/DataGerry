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
Unit tests for cmdb.framework.datagerry_assistant.profile_ipam

IPAMProfile builds the three IPAM SpecialTypes from the canonical SchemaProvider blueprints and
cross-wires them through the real handle_special_types (exercised here against the in-memory
FakeTypesManager; the dg-ipam-interface template is absent in the unit context, which is the
expected 'no inlined interface yet' path).
"""
from typing import Any

from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.special_type_model.ipam_constants import SubnetField, VlanField
from cmdb.framework.datagerry_assistant.datagerry_assistant_constants import TypeSlotKey
from cmdb.framework.datagerry_assistant.profile_ipam import IPAMProfile
# -------------------------------------------------------------------------------------------------------------------- #


def _ref_types(type_doc: dict[str, Any], field_name: str) -> list[int]:
    """Returns the ref_types of the named reference field on a type document"""
    return next(field['ref_types'] for field in type_doc['fields'] if field['name'] == field_name)


def test_ipam_profile_creates_the_three_special_types(
    empty_slot_map: dict[str, int | None],
    fake_types_manager: Any,
    fake_section_templates_manager: Any,
    type_constructor: Any,
) -> None:
    """Supernet, Subnet and VLAN are created, each carrying its special_type marker"""
    IPAMProfile(empty_slot_map, fake_types_manager, fake_section_templates_manager, type_constructor).create_profile()

    markers: dict[str, Any] = {doc['name']: doc['special_type'] for doc in fake_types_manager.store.values()}
    assert markers == {
        'supernet': SpecialType.SUPERNET,
        'subnet': SpecialType.SUBNET,
        'vlan': SpecialType.VLAN,
    }


def test_ipam_profile_records_each_slot(
    empty_slot_map: dict[str, int | None],
    fake_types_manager: Any,
    fake_section_templates_manager: Any,
    type_constructor: Any,
) -> None:
    """The created public_ids are stored under the supernet/subnet/vlan slots"""
    IPAMProfile(empty_slot_map, fake_types_manager, fake_section_templates_manager, type_constructor).create_profile()

    assert empty_slot_map[TypeSlotKey.SUPERNET_ID] == fake_types_manager.by_name('supernet')['public_id']
    assert empty_slot_map[TypeSlotKey.SUBNET_ID] == fake_types_manager.by_name('subnet')['public_id']
    assert empty_slot_map[TypeSlotKey.VLAN_ID] == fake_types_manager.by_name('vlan')['public_id']


def test_ipam_profile_cross_wires_references(
    empty_slot_map: dict[str, int | None],
    fake_types_manager: Any,
    fake_section_templates_manager: Any,
    type_constructor: Any,
) -> None:
    """Subnet references its Supernet and VLAN references its Subnet after creation"""
    IPAMProfile(empty_slot_map, fake_types_manager, fake_section_templates_manager, type_constructor).create_profile()

    supernet: dict[str, Any] = fake_types_manager.by_name('supernet')
    subnet: dict[str, Any] = fake_types_manager.by_name('subnet')
    vlan: dict[str, Any] = fake_types_manager.by_name('vlan')

    assert _ref_types(subnet, SubnetField.PARENT_SUPERNET) == [supernet['public_id']]
    assert _ref_types(vlan, VlanField.SUBNET_REF) == [subnet['public_id']]
