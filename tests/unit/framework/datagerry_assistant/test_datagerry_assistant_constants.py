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
Unit tests for cmdb.framework.datagerry_assistant.datagerry_assistant_constants

Pure structural-invariant tests over the category and IPAM SpecialType definition tables. They
encode the wiring guarantees the assistant relies on (every type slot is categorised exactly once,
the IPAM SpecialTypes are created in dependency order, ...) so a careless edit to the tables fails
loudly. The string-value contracts of the key enums are pinned separately in
tests/unit/test_str_enum_value_contracts.py.
"""
from typing import Any

from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.framework.datagerry_assistant.datagerry_assistant_constants import (
    TypeSlotKey,
    CategoryDefinitionKey,
    CATEGORY_DEFINITIONS,
    IpamSpecialTypeKey,
    IPAM_SPECIAL_TYPE_DEFINITIONS,
)
# -------------------------------------------------------------------------------------------------------------------- #
# CATEGORY_DEFINITIONS - invariants
# -------------------------------------------------------------------------------------------------------------------- #

def test_every_category_definition_has_all_keys() -> None:
    """Each category entry carries name, label, icon and a non-empty type_slots list"""
    for definition in CATEGORY_DEFINITIONS:
        assert set(definition.keys()) == set(CategoryDefinitionKey)
        assert isinstance(definition[CategoryDefinitionKey.NAME], str) and definition[CategoryDefinitionKey.NAME]
        assert isinstance(definition[CategoryDefinitionKey.LABEL], str) and definition[CategoryDefinitionKey.LABEL]
        assert isinstance(definition[CategoryDefinitionKey.ICON], str) and definition[CategoryDefinitionKey.ICON]
        assert len(definition[CategoryDefinitionKey.TYPE_SLOTS]) > 0


def test_category_type_slots_are_valid_type_slot_keys() -> None:
    """Every slot referenced by a category is a real TypeSlotKey member"""
    for definition in CATEGORY_DEFINITIONS:
        for slot in definition[CategoryDefinitionKey.TYPE_SLOTS]:
            assert isinstance(slot, TypeSlotKey)


def test_category_names_are_unique() -> None:
    """No two categories share a name"""
    names: list[str] = [definition[CategoryDefinitionKey.NAME] for definition in CATEGORY_DEFINITIONS]
    assert len(names) == len(set(names))


def test_every_type_slot_is_categorised_exactly_once() -> None:
    """Each TypeSlotKey belongs to exactly one category (no orphan, no duplicate)"""
    occurrences: list[TypeSlotKey] = [
        slot
        for definition in CATEGORY_DEFINITIONS
        for slot in definition[CategoryDefinitionKey.TYPE_SLOTS]
    ]

    assert sorted(occurrences, key=lambda s: s.value) == sorted(TypeSlotKey, key=lambda s: s.value)
    assert len(occurrences) == len(set(occurrences))


def test_ipam_slots_live_in_the_network_category() -> None:
    """Supernet, Subnet and VLAN slots are all assigned to the 'network' category"""
    network_category: dict[str, Any] = next(
        definition for definition in CATEGORY_DEFINITIONS if definition[CategoryDefinitionKey.NAME] == 'network'
    )

    assert {
        TypeSlotKey.SUPERNET_ID,
        TypeSlotKey.SUBNET_ID,
        TypeSlotKey.VLAN_ID,
    }.issubset(set(network_category[CategoryDefinitionKey.TYPE_SLOTS]))


def test_no_ipam_category_exists() -> None:
    """The dedicated 'ipam' category was removed; its slots moved into 'network'"""
    names: list[str] = [definition[CategoryDefinitionKey.NAME] for definition in CATEGORY_DEFINITIONS]
    assert 'ipam' not in names

# -------------------------------------------------------------------------------------------------------------------- #
# IPAM_SPECIAL_TYPE_DEFINITIONS - invariants
# -------------------------------------------------------------------------------------------------------------------- #

def test_ipam_definitions_have_all_keys_and_valid_members() -> None:
    """Each IPAM definition carries every key, a SpecialType, a TypeSlotKey and non-empty identity"""
    for definition in IPAM_SPECIAL_TYPE_DEFINITIONS:
        assert set(definition.keys()) == set(IpamSpecialTypeKey)
        assert isinstance(definition[IpamSpecialTypeKey.SPECIAL_TYPE], SpecialType)
        assert isinstance(definition[IpamSpecialTypeKey.SLOT], TypeSlotKey)
        assert definition[IpamSpecialTypeKey.NAME]
        assert definition[IpamSpecialTypeKey.LABEL]
        assert definition[IpamSpecialTypeKey.ICON]


def test_ipam_definitions_are_in_dependency_order() -> None:
    """SpecialTypes are declared Supernet -> Subnet -> VLAN so cross-wiring targets exist in turn"""
    order: list[SpecialType] = [
        definition[IpamSpecialTypeKey.SPECIAL_TYPE] for definition in IPAM_SPECIAL_TYPE_DEFINITIONS
    ]
    assert order == [SpecialType.SUPERNET, SpecialType.SUBNET, SpecialType.VLAN]


def test_ipam_definition_slots_match_their_special_types() -> None:
    """Each IPAM definition maps its SpecialType to the matching slot"""
    slot_by_type: dict[SpecialType, TypeSlotKey] = {
        definition[IpamSpecialTypeKey.SPECIAL_TYPE]: definition[IpamSpecialTypeKey.SLOT]
        for definition in IPAM_SPECIAL_TYPE_DEFINITIONS
    }
    assert slot_by_type == {
        SpecialType.SUPERNET: TypeSlotKey.SUPERNET_ID,
        SpecialType.SUBNET: TypeSlotKey.SUBNET_ID,
        SpecialType.VLAN: TypeSlotKey.VLAN_ID,
    }
