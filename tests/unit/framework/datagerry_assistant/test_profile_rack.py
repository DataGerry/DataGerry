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
Unit tests for cmdb.framework.datagerry_assistant.profile_rack

RackProfile builds the single RACK SpecialType from the canonical SchemaProvider blueprint. What
matters for the Rack View to work is the persisted contract: the special_type marker, the Rack
field names and the selectable_as_parent flag (a Rack parents the location nodes of its mounts).
"""
from typing import Any

from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.special_type_model.rack_constants import RackField, RackSection
from cmdb.framework.datagerry_assistant.datagerry_assistant_constants import TypeSlotKey, RackTypeIdentity
from cmdb.framework.datagerry_assistant.profile_rack import RackProfile
# -------------------------------------------------------------------------------------------------------------------- #


def _create_rack(
    empty_slot_map: dict[str, int | None],
    fake_types_manager: Any,
    fake_section_templates_manager: Any,
    type_constructor: Any,
) -> dict[str, Any]:
    """Runs the RackProfile and returns the created Rack type document"""
    RackProfile(empty_slot_map, fake_types_manager, fake_section_templates_manager, type_constructor).create_profile()

    return fake_types_manager.by_name(RackTypeIdentity.NAME)


def test_rack_profile_creates_the_rack_special_type(
    empty_slot_map: dict[str, int | None],
    fake_types_manager: Any,
    fake_section_templates_manager: Any,
    type_constructor: Any,
) -> None:
    """Exactly one type is created, carrying the RACK marker and the assistant's Rack identity"""
    rack: dict[str, Any] = _create_rack(
        empty_slot_map, fake_types_manager, fake_section_templates_manager, type_constructor,
    )

    assert len(fake_types_manager.store) == 1
    assert rack['special_type'] == SpecialType.RACK
    assert rack['label'] == RackTypeIdentity.LABEL
    assert rack['render_meta']['icon'] == RackTypeIdentity.ICON


def test_rack_profile_records_the_rack_slot(
    empty_slot_map: dict[str, int | None],
    fake_types_manager: Any,
    fake_section_templates_manager: Any,
    type_constructor: Any,
) -> None:
    """The created public_id is stored under the rack slot, so it lands in the hardware category"""
    rack: dict[str, Any] = _create_rack(
        empty_slot_map, fake_types_manager, fake_section_templates_manager, type_constructor,
    )

    assert empty_slot_map[TypeSlotKey.RACK_ID] == rack['public_id']


def test_rack_profile_keeps_the_blueprint_fields_and_section(
    empty_slot_map: dict[str, int | None],
    fake_types_manager: Any,
    fake_section_templates_manager: Any,
    type_constructor: Any,
) -> None:
    """The Rack keeps the blueprint's field names in its single information section"""
    rack: dict[str, Any] = _create_rack(
        empty_slot_map, fake_types_manager, fake_section_templates_manager, type_constructor,
    )

    sections: list[dict[str, Any]] = rack['render_meta']['sections']

    assert [section['name'] for section in sections] == [RackSection.INFORMATION]
    assert [field['name'] for field in rack['fields']] == [
        RackField.NAME,
        RackField.NUMBER,
        RackField.HEIGHT,
        RackField.NOTES,
        RackField.LOCATION,
    ]
    assert rack['render_meta']['summary']['fields'] == [RackField.NAME]


def test_rack_profile_stays_selectable_as_parent(
    empty_slot_map: dict[str, int | None],
    fake_types_manager: Any,
    fake_section_templates_manager: Any,
    type_constructor: Any,
) -> None:
    """A Rack must stay selectable as a parent Location or nothing could ever be mounted in it"""
    rack: dict[str, Any] = _create_rack(
        empty_slot_map, fake_types_manager, fake_section_templates_manager, type_constructor,
    )

    assert rack['selectable_as_parent'] is True
