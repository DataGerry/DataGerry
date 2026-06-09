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
Shared fakes and fixtures for the DataGerry assistant unit tests

The assistant only ever touches its managers through a tiny surface (get_new_type_public_id /
insert_type / get_one_by / update_type), so an in-memory FakeTypesManager keeps the tests pure
(no Mongo) while still exercising the real cross-wiring logic. The predefined section templates
are pre-loaded into a PredefinedTemplateProvider built with __new__ so no DB load happens.
"""
from typing import Any
from copy import deepcopy

import pytest

from cmdb.models.type_model import FieldKey, SectionKey, FieldType
from cmdb.models.type_model.section_type_enum import SectionType
from cmdb.models.special_type_model.ipam_constants import IpamSection, InterfaceField
from cmdb.framework.datagerry_assistant.datagerry_assistant_constants import (
    TypeSlotKey,
    AssistantFieldKey,
    AssistantSectionKey,
)
from cmdb.framework.datagerry_assistant.predefined_template_provider import PredefinedTemplateProvider
from cmdb.framework.datagerry_assistant.profile_type_constructor import ProfileTypeConstructor
# -------------------------------------------------------------------------------------------------------------------- #


class FakeTypesManager:
    """In-memory stand-in for TypesManager covering only what the assistant calls"""

    def __init__(self) -> None:
        self.store: dict[int, dict[str, Any]] = {}
        self._counter: int = 0

    def get_new_type_public_id(self) -> int:
        """Returns a fresh, monotonically increasing public_id"""
        self._counter += 1
        return self._counter

    def insert_type(self, type_dict: dict[str, Any]) -> int:
        """Stores the type under its assigned public_id and returns that id"""
        public_id: int = type_dict['public_id']
        self.store[public_id] = type_dict
        return public_id

    def get_one_by(self, query: dict[str, Any]) -> dict[str, Any] | None:
        """Resolves a stored type by 'public_id' or by 'special_type' marker"""
        if 'public_id' in query:
            return self.store.get(query['public_id'])

        if 'special_type' in query:
            return next((t for t in self.store.values() if t.get('special_type') == query['special_type']), None)

        return None

    def update_type(self, public_id: int, type_dict: dict[str, Any]) -> None:
        """Replaces the stored type for 'public_id'"""
        self.store[public_id] = type_dict

    def by_name(self, name: str) -> dict[str, Any] | None:
        """Test helper: returns the stored type whose 'name' matches"""
        return next((t for t in self.store.values() if t.get('name') == name), None)


class FakeSectionTemplatesManager:
    """SectionTemplatesManager stand-in: no dg-ipam-interface template present in the unit context"""

    def get_one_by(self, query: dict[str, Any]) -> dict[str, Any] | None:  # pylint: disable=unused-argument
        """Always returns None (no section template stored)"""
        return None


def _fmt_template(name: str, label: str, fields: list[tuple[str, str, str]],
                  section_type: str = SectionType.SECTION) -> dict[str, Any]:
    """Builds a template in the shape PredefinedTemplateProvider.__format_template produces"""
    return {
        SectionKey.NAME: name,
        SectionKey.LABEL: label,
        SectionKey.TYPE: section_type,
        AssistantSectionKey.GLOBAL_ID_NAME: name,
        SectionKey.FIELDS: [
            {FieldKey.TYPE: ftype, FieldKey.NAME: fname, FieldKey.LABEL: flabel, AssistantFieldKey.EXTRAS: {}}
            for (ftype, fname, flabel) in fields
        ],
    }


def _ipam_interface_template() -> dict[str, Any]:
    """Builds the dg-ipam-interface MDS template in the formatted shape, with an empty Subnet ref"""
    template: dict[str, Any] = _fmt_template(IpamSection.INTERFACE, 'Interfaces', [
        (FieldType.TEXT, InterfaceField.IP, 'IP-Address'),
        (FieldType.TEXT, InterfaceField.MAC, 'Mac-Address'),
    ], SectionType.MDS_SECTION)

    # The Subnet reference field the assistant wires to the created Subnet type
    template[SectionKey.FIELDS].insert(0, {
        FieldKey.TYPE: FieldType.REFERENCE,
        FieldKey.NAME: InterfaceField.SUBNET,
        FieldKey.LABEL: 'Network',
        AssistantFieldKey.EXTRAS: {FieldKey.REF_TYPES: []},
    })

    return template


# The predefined templates the profiles reference, using the real dg-* field names so that
# summary_fields look-ups in the profiles resolve
FAKE_PREDEFINED_TEMPLATES: dict[str, dict[str, Any]] = {
    'dg-modelspec': _fmt_template('dg-modelspec', 'Model specifications', [
        ('text', 'dg-modelspec-manufacturer', 'Manufacturer'),
        ('text', 'dg-modelspec-model', 'Model name'),
        ('text', 'dg-modelspec-serial', 'Serial number'),
    ]),
    'dg-rackmounting': _fmt_template('dg-rackmounting', 'Rack mounting', [
        ('text', 'dg-rackmounting-ru', 'Rack units'),
        ('text', 'dg-rackmounting-position', 'Mounting position'),
        ('select', 'dg-rackmounting-orientation', 'Mounting orientation'),
    ]),
    IpamSection.INTERFACE: _ipam_interface_template(),
}


@pytest.fixture(name='fake_types_manager')
def fixture_fake_types_manager() -> FakeTypesManager:
    """A fresh in-memory FakeTypesManager"""
    return FakeTypesManager()


@pytest.fixture(name='fake_section_templates_manager')
def fixture_fake_section_templates_manager() -> FakeSectionTemplatesManager:
    """A fresh FakeSectionTemplatesManager"""
    return FakeSectionTemplatesManager()


@pytest.fixture(name='template_provider')
def fixture_template_provider() -> PredefinedTemplateProvider:
    """A PredefinedTemplateProvider pre-loaded with FAKE_PREDEFINED_TEMPLATES (no DB load)"""
    provider: PredefinedTemplateProvider = PredefinedTemplateProvider.__new__(PredefinedTemplateProvider)
    provider.predefined_templates = deepcopy(FAKE_PREDEFINED_TEMPLATES)
    return provider


@pytest.fixture(name='type_constructor')
def fixture_type_constructor(template_provider: PredefinedTemplateProvider) -> ProfileTypeConstructor:
    """A ProfileTypeConstructor backed by the pre-loaded template provider"""
    return ProfileTypeConstructor(template_provider)


@pytest.fixture(name='empty_slot_map')
def fixture_empty_slot_map() -> dict[str, int | None]:
    """A fresh created_type_ids slot map with every TypeSlotKey set to None"""
    return {slot: None for slot in TypeSlotKey}
