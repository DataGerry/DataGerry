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
Unit tests for cmdb.framework.datagerry_assistant.profile_base

Covers the two creation helpers. create_special_type's wiring call is verified by patching
handle_special_types at the profile_base module path. The one-line getters (get_created_id,
get_created_type_ids) are intentionally not tested - they are trivial dict accessors.
"""
from typing import Any
from unittest.mock import patch

import pytest

from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.special_type_model.ipam_constants import IpamSection, InterfaceField
from cmdb.framework.datagerry_assistant.datagerry_assistant_constants import TypeSlotKey
from cmdb.framework.datagerry_assistant.profile_base import ProfileBase
# -------------------------------------------------------------------------------------------------------------------- #

WIRING_PATH = 'cmdb.framework.datagerry_assistant.profile_base.handle_special_types'
# -------------------------------------------------------------------------------------------------------------------- #


def test_create_basic_type_assigns_public_id_and_records_slot(
    empty_slot_map: dict[str, int | None],
    fake_types_manager: Any,
    fake_section_templates_manager: Any,
    type_constructor: Any,
) -> None:
    """create_basic_type stamps the public_id, inserts the type and records it under its slot"""
    base = ProfileBase(empty_slot_map, fake_types_manager, fake_section_templates_manager, type_constructor)
    type_dict: dict[str, Any] = {'name': 'company', 'label': 'Company'}

    new_id: int = base.create_basic_type('company_id', type_dict)

    assert new_id == 1
    assert type_dict['public_id'] == 1
    assert base.created_type_ids['company_id'] == 1
    assert fake_types_manager.store[1] is type_dict


def test_create_special_type_inserts_then_cross_wires(
    empty_slot_map: dict[str, int | None],
    fake_types_manager: Any,
    fake_section_templates_manager: Any,
    type_constructor: Any,
) -> None:
    """create_special_type inserts the type, records the slot, then calls handle_special_types"""
    base = ProfileBase(empty_slot_map, fake_types_manager, fake_section_templates_manager, type_constructor)
    type_dict: dict[str, Any] = {'name': 'supernet', 'label': 'Supernet', 'special_type': 'SUPERNET'}

    with patch(WIRING_PATH) as mock_wire:
        new_id: int = base.create_special_type('supernet_id', SpecialType.SUPERNET, type_dict)

    assert new_id == 1
    assert base.created_type_ids['supernet_id'] == 1
    mock_wire.assert_called_once_with(
        fake_types_manager, SpecialType.SUPERNET, fake_section_templates_manager, 1,
    )


def test_get_ipam_interface_section_wires_subnet_from_slot(
    empty_slot_map: dict[str, int | None],
    fake_types_manager: Any,
    fake_section_templates_manager: Any,
    type_constructor: Any,
) -> None:
    """get_ipam_interface_section reads the SUBNET_ID slot and wires it onto the interface template"""
    empty_slot_map[TypeSlotKey.SUBNET_ID] = 77
    base = ProfileBase(empty_slot_map, fake_types_manager, fake_section_templates_manager, type_constructor)

    section: dict[str, Any] = base.get_ipam_interface_section()

    assert section['global_id_name'] == IpamSection.INTERFACE
    subnet_field: dict[str, Any] = next(f for f in section['fields'] if f['name'] == InterfaceField.SUBNET)
    assert subnet_field['extras']['ref_types'] == [77]


def test_base_create_profile_is_abstract(
    empty_slot_map: dict[str, int | None],
    fake_types_manager: Any,
    fake_section_templates_manager: Any,
    type_constructor: Any,
) -> None:
    """The base create_profile is a contract that subclasses must override"""
    base = ProfileBase(empty_slot_map, fake_types_manager, fake_section_templates_manager, type_constructor)

    with pytest.raises(NotImplementedError):
        base.create_profile()
