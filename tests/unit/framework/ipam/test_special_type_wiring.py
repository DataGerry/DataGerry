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

Covers the pure mutators (ensure_ref_type / remove_ref_type), the shared read-mutate-persist
primitives (apply_type_ref_type, get_special_type_id, apply_interface_template_ref_change), the
handle_special_types cross-wiring orchestrator for each SpecialType branch, and both un-wiring
functions - the type-level sweep (one server-side $pull) and the template-only SpecialType cleanup,
including that it propagates the template change exactly like the wiring side does.

The managers are MagicMocks; types_manager.get_one_by uses a side_effect that dispatches on the
filter (by special_type or public_id), mirroring the real lookups. CmdbSectionTemplate.from_data is
patched wherever the snapshot step runs so no fully-valid template document is needed.
"""
from typing import Any, Callable

from unittest.mock import MagicMock, patch

import pytest

from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.special_type_model.ipam_constants import (
    SubnetField,
    VlanField,
    InterfaceField,
    IpamSection,
)
from cmdb.framework.ipam.special_type_wiring import (
    ALL_TYPE_FIELDS_REF_TYPES_PATH,
    TYPE_FIELD_REF_TYPES_PATH,
    apply_interface_template_ref_change,
    apply_type_ref_type,
    cleanup_special_type_template_references,
    cleanup_type_references_from_all_types,
    ensure_ref_type,
    get_special_type_id,
    handle_special_types,
    remove_ref_type,
)
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

# -------------------------------------------------------------------------------------------------------------------- #
#                                                  remove_ref_type                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
def test_remove_ref_type_drops_the_id_and_returns_true() -> None:
    """A present id is removed from the field's ref_types."""
    fields = [{'name': SubnetField.PARENT_SUPERNET, 'ref_types': [SUPERNET_TYPE_ID, VLAN_TYPE_ID]}]

    assert remove_ref_type(fields, SubnetField.PARENT_SUPERNET, SUPERNET_TYPE_ID) is True
    assert fields[0]['ref_types'] == [VLAN_TYPE_ID]


def test_remove_ref_type_is_idempotent_when_id_absent() -> None:
    """An id that is not referenced leaves the list untouched."""
    fields = [{'name': SubnetField.PARENT_SUPERNET, 'ref_types': [VLAN_TYPE_ID]}]

    assert remove_ref_type(fields, SubnetField.PARENT_SUPERNET, SUPERNET_TYPE_ID) is False
    assert fields[0]['ref_types'] == [VLAN_TYPE_ID]


def test_remove_ref_type_returns_false_when_field_absent() -> None:
    """A field list without the named field reports no change."""
    assert remove_ref_type([{'name': 'other', 'ref_types': [SUPERNET_TYPE_ID]}],
                           SubnetField.PARENT_SUPERNET, SUPERNET_TYPE_ID) is False


def test_remove_ref_type_returns_false_without_a_ref_types_list() -> None:
    """A field carrying no ref_types key is not a candidate."""
    assert remove_ref_type([{'name': SubnetField.PARENT_SUPERNET}],
                           SubnetField.PARENT_SUPERNET, SUPERNET_TYPE_ID) is False


def test_remove_ref_type_ignores_a_non_list_ref_types() -> None:
    """A malformed ref_types value is left alone instead of raising."""
    fields = [{'name': SubnetField.PARENT_SUPERNET, 'ref_types': 'not-a-list'}]

    assert remove_ref_type(fields, SubnetField.PARENT_SUPERNET, SUPERNET_TYPE_ID) is False


# -------------------------------------------------------------------------------------------------------------------- #
#                                                apply_type_ref_type                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
def test_apply_type_ref_type_persists_a_changed_type() -> None:
    """The matched type is mutated and written once."""
    subnet_doc = _type_doc(SUBNET_TYPE_ID, SubnetField.PARENT_SUPERNET)
    types_manager = MagicMock()
    types_manager.get_one_by.return_value = subnet_doc

    result = apply_type_ref_type(
        types_manager, {'public_id': SUBNET_TYPE_ID}, SubnetField.PARENT_SUPERNET, SUPERNET_TYPE_ID,
    )

    assert result is True
    assert _ref_types(subnet_doc, SubnetField.PARENT_SUPERNET) == [SUPERNET_TYPE_ID]
    types_manager.update_type.assert_called_once_with(SUBNET_TYPE_ID, subnet_doc)


def test_apply_type_ref_type_is_a_noop_without_a_matching_type() -> None:
    """No type, no write."""
    types_manager = MagicMock()
    types_manager.get_one_by.return_value = None

    assert apply_type_ref_type(types_manager, {'public_id': 1}, SubnetField.PARENT_SUPERNET, 2) is False
    types_manager.update_type.assert_not_called()


def test_apply_type_ref_type_is_a_noop_when_nothing_changes() -> None:
    """An id already present writes nothing."""
    types_manager = MagicMock()
    types_manager.get_one_by.return_value = _type_doc(
        SUBNET_TYPE_ID, SubnetField.PARENT_SUPERNET, ref_types=[SUPERNET_TYPE_ID],
    )

    result = apply_type_ref_type(
        types_manager, {'public_id': SUBNET_TYPE_ID}, SubnetField.PARENT_SUPERNET, SUPERNET_TYPE_ID,
    )

    assert result is False
    types_manager.update_type.assert_not_called()


def test_apply_type_ref_type_is_a_noop_when_the_field_is_missing() -> None:
    """A type without the reference field is left untouched (no signal, by design)."""
    types_manager = MagicMock()
    types_manager.get_one_by.return_value = {'public_id': SUBNET_TYPE_ID, 'fields': []}

    assert apply_type_ref_type(
        types_manager, {'public_id': SUBNET_TYPE_ID}, SubnetField.PARENT_SUPERNET, SUPERNET_TYPE_ID,
    ) is False
    types_manager.update_type.assert_not_called()


# -------------------------------------------------------------------------------------------------------------------- #
#                                                get_special_type_id                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
def test_get_special_type_id_returns_the_public_id() -> None:
    """An existing SpecialType resolves to its public_id."""
    types_manager = MagicMock()
    types_manager.get_one_by.return_value = {'public_id': SUPERNET_TYPE_ID, 'fields': []}

    assert get_special_type_id(types_manager, SpecialType.SUPERNET) == SUPERNET_TYPE_ID


def test_get_special_type_id_returns_none_when_absent() -> None:
    """A SpecialType that does not exist yet resolves to None."""
    types_manager = MagicMock()
    types_manager.get_one_by.return_value = None

    assert get_special_type_id(types_manager, SpecialType.SUPERNET) is None


# -------------------------------------------------------------------------------------------------------------------- #
#                                        apply_interface_template_ref_change                                           #
# -------------------------------------------------------------------------------------------------------------------- #
def _interface_template(ref_types: list[int] | None = None) -> dict[str, Any]:
    """Builds a minimal dg-ipam-interface template document."""
    return {
        'public_id': INTERFACE_TEMPLATE_ID,
        'name': IpamSection.INTERFACE,
        'fields': [{'name': InterfaceField.SUBNET,
                    'ref_types': list(ref_types) if ref_types is not None else []}],
    }


def test_apply_interface_template_ref_change_persists_then_propagates() -> None:
    """A changed template is written first and propagated afterwards - in that order."""
    template = _interface_template()
    section_templates_manager = MagicMock()
    section_templates_manager.get_one_by.return_value = template
    calls: list[str] = []
    section_templates_manager.update_section_template.side_effect = lambda *a, **k: calls.append('update')
    section_templates_manager.handle_section_template_changes.side_effect = \
        lambda *a, **k: calls.append('propagate')

    with patch(f'{PATH}.CmdbSectionTemplate.from_data', return_value=MagicMock()):
        result = apply_interface_template_ref_change(
            section_templates_manager,
            lambda fields: ensure_ref_type(fields, InterfaceField.SUBNET, SUBNET_TYPE_ID),
        )

    assert result is True
    assert calls == ['update', 'propagate']
    assert _ref_types(template, InterfaceField.SUBNET) == [SUBNET_TYPE_ID]


def test_apply_interface_template_ref_change_is_a_noop_without_the_template() -> None:
    """An installation without the IPAM section template writes nothing."""
    section_templates_manager = MagicMock()
    section_templates_manager.get_one_by.return_value = None

    assert apply_interface_template_ref_change(section_templates_manager, lambda fields: True) is False
    section_templates_manager.update_section_template.assert_not_called()
    section_templates_manager.handle_section_template_changes.assert_not_called()


def test_apply_interface_template_ref_change_is_a_noop_when_the_mutation_changes_nothing() -> None:
    """When the mutator reports no change, neither the write nor the propagation runs."""
    section_templates_manager = MagicMock()
    section_templates_manager.get_one_by.return_value = _interface_template([SUBNET_TYPE_ID])

    with patch(f'{PATH}.CmdbSectionTemplate.from_data', return_value=MagicMock()):
        result = apply_interface_template_ref_change(
            section_templates_manager,
            lambda fields: ensure_ref_type(fields, InterfaceField.SUBNET, SUBNET_TYPE_ID),
        )

    assert result is False
    section_templates_manager.update_section_template.assert_not_called()
    section_templates_manager.handle_section_template_changes.assert_not_called()


# -------------------------------------------------------------------------------------------------------------------- #
#                                          handle_special_types - missing counterparts                                 #
# -------------------------------------------------------------------------------------------------------------------- #
def test_handle_subnet_skips_the_self_wiring_without_a_supernet() -> None:
    """No SUPERNET yet: the subnet's own parent ref is left for the SUPERNET's own wiring run."""
    types_manager = MagicMock()
    types_manager.get_one_by.side_effect = _type_router({
        ('special_type', SpecialType.VLAN): None,
        ('special_type', SpecialType.SUPERNET): None,
    })
    section_templates_manager = MagicMock()
    section_templates_manager.get_one_by.return_value = None

    handle_special_types(types_manager, SpecialType.SUBNET, section_templates_manager, SUBNET_TYPE_ID)

    types_manager.update_type.assert_not_called()


def test_handle_special_types_ignores_an_unknown_special_type() -> None:
    """A value that is none of the three IPAM SpecialTypes writes nothing (defensive no-op)."""
    types_manager = MagicMock()
    section_templates_manager = MagicMock()

    handle_special_types(types_manager, 'NOT_AN_IPAM_TYPE', section_templates_manager, SUBNET_TYPE_ID)

    types_manager.get_one_by.assert_not_called()
    types_manager.update_type.assert_not_called()
    section_templates_manager.get_one_by.assert_not_called()


def test_handle_vlan_is_a_noop_without_a_subnet_type() -> None:
    """A VLAN created before any SUBNET exists writes nothing."""
    types_manager = MagicMock()
    types_manager.get_one_by.side_effect = _type_router({('special_type', SpecialType.SUBNET): None})

    handle_special_types(types_manager, SpecialType.VLAN, MagicMock(), VLAN_TYPE_ID)

    types_manager.update_type.assert_not_called()


# -------------------------------------------------------------------------------------------------------------------- #
#                                      cleanup_type_references_from_all_types                                          #
# -------------------------------------------------------------------------------------------------------------------- #
def test_cleanup_type_references_is_one_server_side_pull() -> None:
    """The whole sweep is a single filtered $pull; no type is read or rewritten in full."""
    types_manager = MagicMock()
    types_manager.update_many_raw.return_value = MagicMock(modified_count=3)

    assert cleanup_type_references_from_all_types(types_manager, SUBNET_TYPE_ID) == 3

    types_manager.update_many_raw.assert_called_once_with(
        filter_query={TYPE_FIELD_REF_TYPES_PATH: SUBNET_TYPE_ID},
        update={'$pull': {ALL_TYPE_FIELDS_REF_TYPES_PATH: SUBNET_TYPE_ID}},
    )
    types_manager.find.assert_not_called()
    types_manager.update_type.assert_not_called()


def test_cleanup_type_references_reports_zero_when_nothing_referenced_it() -> None:
    """A type nobody referenced yields 0."""
    types_manager = MagicMock()
    types_manager.update_many_raw.return_value = MagicMock(modified_count=0)

    assert cleanup_type_references_from_all_types(types_manager, SUBNET_TYPE_ID) == 0


def test_cleanup_type_references_targets_both_paths_correctly() -> None:
    """The filter selects on 'fields.ref_types' and the update pulls via the all-positional operator."""
    assert TYPE_FIELD_REF_TYPES_PATH == 'fields.ref_types'
    assert ALL_TYPE_FIELDS_REF_TYPES_PATH == 'fields.$[].ref_types'


# -------------------------------------------------------------------------------------------------------------------- #
#                                    cleanup_special_type_template_references                                          #
# -------------------------------------------------------------------------------------------------------------------- #
def test_cleanup_template_references_unwires_a_deleted_subnet_and_propagates() -> None:
    """A deleted SUBNET is removed from the template, which is then propagated (symmetry with wiring)."""
    template = _interface_template([SUBNET_TYPE_ID])
    section_templates_manager = MagicMock()
    section_templates_manager.get_one_by.return_value = template

    with patch(f'{PATH}.CmdbSectionTemplate.from_data', return_value=MagicMock()):
        cleanup_special_type_template_references(
            section_templates_manager, SpecialType.SUBNET, SUBNET_TYPE_ID,
        )

    assert _ref_types(template, InterfaceField.SUBNET) == []
    section_templates_manager.update_section_template.assert_called_once()
    section_templates_manager.handle_section_template_changes.assert_called_once()


@pytest.mark.parametrize('special_type', [SpecialType.SUPERNET, SpecialType.VLAN])
def test_cleanup_template_references_only_applies_to_subnet(special_type: SpecialType) -> None:
    """Nothing in the template points at a SUPERNET or a VLAN, so neither is read."""
    section_templates_manager = MagicMock()

    cleanup_special_type_template_references(section_templates_manager, special_type, SUPERNET_TYPE_ID)

    section_templates_manager.get_one_by.assert_not_called()
    section_templates_manager.update_section_template.assert_not_called()


def test_cleanup_template_references_is_a_noop_when_the_id_is_not_referenced() -> None:
    """A template that never referenced the deleted subnet is not rewritten."""
    section_templates_manager = MagicMock()
    section_templates_manager.get_one_by.return_value = _interface_template([])

    with patch(f'{PATH}.CmdbSectionTemplate.from_data', return_value=MagicMock()):
        cleanup_special_type_template_references(
            section_templates_manager, SpecialType.SUBNET, SUBNET_TYPE_ID,
        )

    section_templates_manager.update_section_template.assert_not_called()
    section_templates_manager.handle_section_template_changes.assert_not_called()
