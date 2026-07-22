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
Unit tests for cmdb.framework.datagerry_assistant.profile_assistant

The category-derivation helpers are pure and tested directly. create_profiles is tested as an
orchestrator: the profile builder table, the PredefinedTemplateProvider and the ProfileTypeConstructor
are patched at the module path so the selection / fixed-order / error-wrapping logic is verified in
isolation from the real type building.
"""
from typing import Any, Callable
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from cmdb.errors.dg_assistant.dg_assistant_errors import ProfileCreationError
from cmdb.framework.datagerry_assistant import profile_assistant as profile_assistant_module
from cmdb.framework.datagerry_assistant.profile_assistant import ProfileAssistant
from cmdb.framework.datagerry_assistant.profile_name import ProfileName
from cmdb.framework.datagerry_assistant.datagerry_assistant_constants import TypeSlotKey
# -------------------------------------------------------------------------------------------------------------------- #


def _make_assistant() -> ProfileAssistant:
    """A ProfileAssistant with MagicMock managers (no DB)"""
    return ProfileAssistant(MagicMock(), MagicMock(), MagicMock())


def _fake_profile(name: str, slot: TypeSlotKey | None, run_order: list[str], fail: bool = False) -> Callable:
    """Builds a fake profile class that records its run, optionally fails, and fills one slot"""
    class _FakeProfile:
        def __init__(self, created_type_ids: dict[str, int | None], *_args: Any) -> None:
            self.created_type_ids = created_type_ids

        def create_profile(self) -> dict[str, int | None]:
            """Records the run, optionally raises, fills the assigned slot, returns the slot map"""
            run_order.append(name)

            if fail:
                raise RuntimeError("boom")

            if slot is not None:
                self.created_type_ids[slot] = 999

            return self.created_type_ids

    return _FakeProfile

# -------------------------------------------------------------------------------------------------------------------- #
#                                      category derivation (pure helpers)                                              #
# -------------------------------------------------------------------------------------------------------------------- #

def test_get_category_type_ids_keeps_created_slots_in_order(empty_slot_map: dict[str, int | None]) -> None:
    """Only created slots are returned, in the requested order, skipping uncreated ones"""
    empty_slot_map[TypeSlotKey.COMPANY_ID] = 10
    empty_slot_map[TypeSlotKey.USER_ID] = 12

    requested: list[TypeSlotKey] = [TypeSlotKey.COMPANY_ID, TypeSlotKey.CUSTOMER_USER_ID, TypeSlotKey.USER_ID]
    result: list[int] = _make_assistant().get_category_type_ids(empty_slot_map, requested)

    assert result == [10, 12]


def test_get_all_categories_only_builds_categories_with_a_created_type(
    empty_slot_map: dict[str, int | None],
) -> None:
    """A category is emitted only when at least one of its member types was created"""
    empty_slot_map[TypeSlotKey.COMPANY_ID] = 10

    categories: list[dict[str, Any]] = _make_assistant().get_all_categories(empty_slot_map)

    assert [category['name'] for category in categories] == ['contact']
    assert categories[0]['types'] == [10]


def test_get_all_categories_places_special_type_slots_in_network_category(
    empty_slot_map: dict[str, int | None],
) -> None:
    """The supernet/subnet/vlan slots are emitted under the 'network' category"""
    empty_slot_map[TypeSlotKey.SUPERNET_ID] = 1
    empty_slot_map[TypeSlotKey.SUBNET_ID] = 2
    empty_slot_map[TypeSlotKey.VLAN_ID] = 3

    categories: list[dict[str, Any]] = _make_assistant().get_all_categories(empty_slot_map)
    network: dict[str, Any] = next(category for category in categories if category['name'] == 'network')

    assert network['types'] == [1, 2, 3]
    assert all(category['name'] != 'ipam' for category in categories)


def test_get_category_body_shape() -> None:
    """The category body carries name/label/meta(icon,order)/parent/types and a creation_time"""
    body: dict[str, Any] = _make_assistant().get_category_body('hardware', 'Hardware', 'fas fa-hdd', [1, 2])

    assert body['name'] == 'hardware'
    assert body['label'] == 'Hardware'
    assert body['meta']['icon'] == 'fas fa-hdd'
    assert body['meta']['order'] is None
    assert body['parent'] is None
    assert body['types'] == [1, 2]
    assert isinstance(body['creation_time'], datetime)


def test_create_all_categories_inserts_each_built_category(empty_slot_map: dict[str, int | None]) -> None:
    """Every derived category is handed to categories_manager.insert_category exactly once"""
    empty_slot_map[TypeSlotKey.COMPANY_ID] = 10
    assistant: ProfileAssistant = _make_assistant()

    assistant.create_all_categories(empty_slot_map)

    assert assistant.categories_manager.insert_category.call_count == 1

# -------------------------------------------------------------------------------------------------------------------- #
#                                        create_profiles orchestration                                                #
# -------------------------------------------------------------------------------------------------------------------- #

def test_create_profiles_runs_selected_profiles_in_fixed_order() -> None:
    """Selected profiles run in PROFILE_BUILDERS order regardless of the order in profile_list"""
    run_order: list[str] = []
    fake_builders: list[tuple[ProfileName, Callable]] = [
        (ProfileName.USER_MANAGEMENT, _fake_profile('user', TypeSlotKey.COMPANY_ID, run_order)),
        (ProfileName.LOCATION, _fake_profile('location', TypeSlotKey.COUNTRY_ID, run_order)),
    ]
    assistant: ProfileAssistant = _make_assistant()

    with patch.object(profile_assistant_module, 'PROFILE_BUILDERS', fake_builders), \
         patch.object(profile_assistant_module, 'PredefinedTemplateProvider'), \
         patch.object(profile_assistant_module, 'ProfileTypeConstructor'):
        result: list[int] = assistant.create_profiles([ProfileName.LOCATION.value, ProfileName.USER_MANAGEMENT.value])

    assert run_order == ['user', 'location']
    assert result == [999, 999]


def test_create_profiles_skips_unselected_profiles() -> None:
    """A profile whose token is absent from profile_list is not run"""
    run_order: list[str] = []
    fake_builders: list[tuple[ProfileName, Callable]] = [
        (ProfileName.USER_MANAGEMENT, _fake_profile('user', TypeSlotKey.COMPANY_ID, run_order)),
        (ProfileName.LOCATION, _fake_profile('location', TypeSlotKey.COUNTRY_ID, run_order)),
    ]
    assistant: ProfileAssistant = _make_assistant()

    with patch.object(profile_assistant_module, 'PROFILE_BUILDERS', fake_builders), \
         patch.object(profile_assistant_module, 'PredefinedTemplateProvider'), \
         patch.object(profile_assistant_module, 'ProfileTypeConstructor'):
        assistant.create_profiles([ProfileName.USER_MANAGEMENT.value])

    assert run_order == ['user']


def test_create_profiles_wraps_failures_in_profile_creation_error() -> None:
    """Any error during creation is re-raised as ProfileCreationError"""
    run_order: list[str] = []
    fake_builders: list[tuple[ProfileName, Callable]] = [
        (ProfileName.USER_MANAGEMENT, _fake_profile('user', None, run_order, fail=True)),
    ]
    assistant: ProfileAssistant = _make_assistant()

    with patch.object(profile_assistant_module, 'PROFILE_BUILDERS', fake_builders), \
         patch.object(profile_assistant_module, 'PredefinedTemplateProvider'), \
         patch.object(profile_assistant_module, 'ProfileTypeConstructor'):
        with pytest.raises(ProfileCreationError):
            assistant.create_profiles([ProfileName.USER_MANAGEMENT.value])
