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
Unit tests for cmdb.framework.ipam.special_type_wiring

Covers the pure ensure_ref_type mutator (add / create-list / idempotent / field-absent) and the
handle_special_types cross-wiring orchestrator for each SpecialType branch. The managers are
MagicMocks; types_manager.get_one_by uses a side_effect that dispatches on the filter (by
special_type or public_id), mirroring the real lookups. CmdbSectionTemplate.from_data is patched
in the SUBNET branch so the snapshot step needs no fully-valid template document.
"""
from typing import Any, Callable

from unittest.mock import MagicMock, patch

from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.special_type_model.ipam_constants import (
    SubnetField,
    VlanField,
    InterfaceField,
    IpamSection,
)
from cmdb.framework.ipam.special_type_wiring import ensure_ref_type, handle_special_types
# -------------------------------------------------------------------------------------------------------------------- #

PATH: str = 'cmdb.framework.ipam.special_type_wiring'

SUPERNET_TYPE_ID: int = 10
SUBNET_TYPE_ID: int = 11
VLAN_TYPE_ID: int = 12
INTERFACE_TEMPLATE_ID: int = 99


def _type_doc(public_id: int, field_name: str, ref_types: list[int] | None = None) -> dict[str, Any]:
    """Builds a minimal CmdbType doc carrying one reference field with the given ref_types."""
    return {
        'public_id': public_id,
        'fields': [{'name': field_name, 'ref_types': list(ref_types) if ref_types is not None else []}],
    }


def _type_router(mapping: dict[tuple[str, Any], dict[str, Any] | None]) -> Callable[[dict[str, Any]], Any]:
    """Returns a get_one_by side_effect dispatching on a {'special_type': ...} or {'public_id': ...} filter."""
    def router(filter_doc: dict[str, Any]) -> dict[str, Any] | None:
        if 'special_type' in filter_doc:
            return mapping.get(('special_type', filter_doc['special_type']))
        if 'public_id' in filter_doc:
            return mapping.get(('public_id', filter_doc['public_id']))
        return None

    return router


def _ref_types(type_doc: dict[str, Any], field_name: str) -> list[int]:
    """Returns the ref_types list of the named field on a type doc."""
    return next(f for f in type_doc['fields'] if f['name'] == field_name)['ref_types']


# -------------------------------------------------------------------------------------------------------------------- #
#                                                ensure_ref_type                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
def test_ensure_ref_type_appends_and_returns_true() -> None:
    """A new ref id is appended to the matching field's ref_types and True is returned"""
    fields = [{'name': SubnetField.PARENT_SUPERNET, 'ref_types': [7]}]

    changed = ensure_ref_type(fields, SubnetField.PARENT_SUPERNET, SUPERNET_TYPE_ID)

    assert changed is True
    assert fields[0]['ref_types'] == [7, SUPERNET_TYPE_ID]


def test_ensure_ref_type_creates_missing_ref_types_list() -> None:
    """A field without a ref_types key gets one created with the id"""
    fields: list[dict[str, Any]] = [{'name': SubnetField.PARENT_SUPERNET}]

    changed = ensure_ref_type(fields, SubnetField.PARENT_SUPERNET, SUPERNET_TYPE_ID)

    assert changed is True
    assert fields[0]['ref_types'] == [SUPERNET_TYPE_ID]


def test_ensure_ref_type_is_idempotent_when_id_present() -> None:
    """An already-present id is not duplicated and False is returned"""
    fields = [{'name': SubnetField.PARENT_SUPERNET, 'ref_types': [SUPERNET_TYPE_ID]}]

    changed = ensure_ref_type(fields, SubnetField.PARENT_SUPERNET, SUPERNET_TYPE_ID)

    assert changed is False
    assert fields[0]['ref_types'] == [SUPERNET_TYPE_ID]


def test_ensure_ref_type_returns_false_when_field_absent() -> None:
    """A field-name with no matching entry leaves the list untouched and returns False"""
    fields = [{'name': 'other-field', 'ref_types': []}]

    assert ensure_ref_type(fields, SubnetField.PARENT_SUPERNET, SUPERNET_TYPE_ID) is False


# -------------------------------------------------------------------------------------------------------------------- #
#                                        handle_special_types - SUPERNET                                              #
# -------------------------------------------------------------------------------------------------------------------- #
def test_handle_supernet_wires_new_supernet_into_subnet_ref() -> None:
    """Creating a SUPERNET adds its id to the SUBNET's dg-supernet-ref ref_types and persists"""
    subnet_doc = _type_doc(SUBNET_TYPE_ID, SubnetField.PARENT_SUPERNET)
    types_manager = MagicMock()
    types_manager.get_one_by.side_effect = _type_router({('special_type', SpecialType.SUBNET): subnet_doc})

    handle_special_types(types_manager, SpecialType.SUPERNET, MagicMock(), SUPERNET_TYPE_ID)

    assert SUPERNET_TYPE_ID in _ref_types(subnet_doc, SubnetField.PARENT_SUPERNET)
    types_manager.update_type.assert_called_once_with(SUBNET_TYPE_ID, subnet_doc)


def test_handle_supernet_is_noop_when_no_subnet_type_exists() -> None:
    """With no SUBNET type defined the SUPERNET wiring writes nothing"""
    types_manager = MagicMock()
    types_manager.get_one_by.side_effect = _type_router({})

    handle_special_types(types_manager, SpecialType.SUPERNET, MagicMock(), SUPERNET_TYPE_ID)

    types_manager.update_type.assert_not_called()


def test_handle_supernet_is_idempotent_when_ref_already_present() -> None:
    """When the SUBNET ref already includes the supernet id, no persist happens"""
    subnet_doc = _type_doc(SUBNET_TYPE_ID, SubnetField.PARENT_SUPERNET, ref_types=[SUPERNET_TYPE_ID])
    types_manager = MagicMock()
    types_manager.get_one_by.side_effect = _type_router({('special_type', SpecialType.SUBNET): subnet_doc})

    handle_special_types(types_manager, SpecialType.SUPERNET, MagicMock(), SUPERNET_TYPE_ID)

    types_manager.update_type.assert_not_called()


# -------------------------------------------------------------------------------------------------------------------- #
#                                          handle_special_types - VLAN                                                #
# -------------------------------------------------------------------------------------------------------------------- #
def test_handle_vlan_wires_subnet_id_into_vlan_ref() -> None:
    """Creating a VLAN adds the SUBNET's id to the VLAN's dg-subnet-ref ref_types and persists"""
    subnet_doc = _type_doc(SUBNET_TYPE_ID, SubnetField.PARENT_SUPERNET)
    vlan_doc = _type_doc(VLAN_TYPE_ID, VlanField.SUBNET_REF)
    types_manager = MagicMock()
    types_manager.get_one_by.side_effect = _type_router({
        ('special_type', SpecialType.SUBNET): subnet_doc,
        ('public_id', VLAN_TYPE_ID): vlan_doc,
    })

    handle_special_types(types_manager, SpecialType.VLAN, MagicMock(), VLAN_TYPE_ID)

    assert SUBNET_TYPE_ID in _ref_types(vlan_doc, VlanField.SUBNET_REF)
    types_manager.update_type.assert_called_once_with(VLAN_TYPE_ID, vlan_doc)


# -------------------------------------------------------------------------------------------------------------------- #
#                                          handle_special_types - SUBNET                                              #
# -------------------------------------------------------------------------------------------------------------------- #
def test_handle_subnet_wires_interface_template_vlan_and_self() -> None:
    """Creating a SUBNET wires the interface template, the VLAN ref and its own parent-supernet ref"""
    subnet_self = _type_doc(SUBNET_TYPE_ID, SubnetField.PARENT_SUPERNET)
    vlan_doc = _type_doc(VLAN_TYPE_ID, VlanField.SUBNET_REF)
    supernet_doc = {'public_id': SUPERNET_TYPE_ID, 'fields': []}
    interface_template: dict[str, Any] = {
        'public_id': INTERFACE_TEMPLATE_ID,
        'name': IpamSection.INTERFACE,
        'fields': [{'name': InterfaceField.SUBNET, 'ref_types': []}],
    }

    types_manager = MagicMock()
    types_manager.get_one_by.side_effect = _type_router({
        ('special_type', SpecialType.VLAN): vlan_doc,
        ('special_type', SpecialType.SUPERNET): supernet_doc,
        ('public_id', SUBNET_TYPE_ID): subnet_self,
    })
    section_templates_manager = MagicMock()
    section_templates_manager.get_one_by.return_value = interface_template

    with patch(f'{PATH}.CmdbSectionTemplate.from_data', return_value=MagicMock()):
        handle_special_types(types_manager, SpecialType.SUBNET, section_templates_manager, SUBNET_TYPE_ID)

    # interface section template gets the new subnet id and is persisted + propagated
    assert SUBNET_TYPE_ID in _ref_types(interface_template, InterfaceField.SUBNET)
    section_templates_manager.update_section_template.assert_called_once()
    section_templates_manager.handle_section_template_changes.assert_called_once()

    # the VLAN ref and the subnet's own parent-supernet ref are both wired + persisted
    assert SUBNET_TYPE_ID in _ref_types(vlan_doc, VlanField.SUBNET_REF)
    assert SUPERNET_TYPE_ID in _ref_types(subnet_self, SubnetField.PARENT_SUPERNET)
    updated_ids = {call.args[0] for call in types_manager.update_type.call_args_list}
    assert updated_ids == {VLAN_TYPE_ID, SUBNET_TYPE_ID}


def test_handle_subnet_skips_template_propagation_when_ref_already_present() -> None:
    """An interface template already carrying the subnet id is not re-persisted or re-propagated"""
    subnet_self = _type_doc(SUBNET_TYPE_ID, SubnetField.PARENT_SUPERNET, ref_types=[SUPERNET_TYPE_ID])
    supernet_doc = {'public_id': SUPERNET_TYPE_ID, 'fields': []}
    interface_template: dict[str, Any] = {
        'public_id': INTERFACE_TEMPLATE_ID,
        'name': IpamSection.INTERFACE,
        'fields': [{'name': InterfaceField.SUBNET, 'ref_types': [SUBNET_TYPE_ID]}],
    }

    types_manager = MagicMock()
    types_manager.get_one_by.side_effect = _type_router({
        ('special_type', SpecialType.VLAN): None,
        ('special_type', SpecialType.SUPERNET): supernet_doc,
        ('public_id', SUBNET_TYPE_ID): subnet_self,
    })
    section_templates_manager = MagicMock()
    section_templates_manager.get_one_by.return_value = interface_template

    with patch(f'{PATH}.CmdbSectionTemplate.from_data', return_value=MagicMock()):
        handle_special_types(types_manager, SpecialType.SUBNET, section_templates_manager, SUBNET_TYPE_ID)

    section_templates_manager.update_section_template.assert_not_called()
    section_templates_manager.handle_section_template_changes.assert_not_called()
    # subnet self ref already present -> no type persist either
    types_manager.update_type.assert_not_called()
