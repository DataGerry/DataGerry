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
Unit tests for cmdb.framework.section_templates.section_template_creator

Pure tests (no database): assert the set and shape of the predefined templates returned by
get_predefined_templates, the per-template field layout (rack mounting, model specifications and the
dg-ipam-interface MDS section), that the removed 'dg-network' template no longer appears, and the
branching of the two private section/field builders (including the optional options/regex/helperText
keys that no live template currently exercises).
"""
from typing import Any

import pytest

from cmdb.models.type_model import FieldType, SectionType, SectionKey, FieldKey
from cmdb.models.special_type_model.ipam_constants import IpamSection, InterfaceField
from cmdb.framework.section_templates.section_template_creator import SectionTemplateCreator
# -------------------------------------------------------------------------------------------------------------------- #
# Several tests reach the creator's private section/field builders on purpose
# pylint: disable=protected-access

RACK_TEMPLATE: str = 'dg-rackmounting'
MODELSPEC_TEMPLATE: str = 'dg-modelspec'
REMOVED_NETWORK_TEMPLATE: str = 'dg-network'
EXPECTED_TEMPLATE_NAMES: set[str] = {RACK_TEMPLATE, MODELSPEC_TEMPLATE, IpamSection.INTERFACE}

GLOBAL_KEY: str = 'is_global'
PREDEFINED_KEY: str = 'predefined'
HELPER_TEXT_KEY: str = 'helperText'


@pytest.fixture(name='creator')
def fixture_creator() -> SectionTemplateCreator:
    """A fresh SectionTemplateCreator"""
    return SectionTemplateCreator()


def _templates_by_name(creator: SectionTemplateCreator) -> dict[str, dict[str, Any]]:
    """Indexes the predefined templates by their name"""
    return {template[SectionKey.NAME]: template for template in creator.get_predefined_templates()}


def _fields_by_name(template: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Indexes a template's fields by their name"""
    return {field[FieldKey.NAME]: field for field in template[SectionKey.FIELDS]}

# -------------------------------------------------------------------------------------------------------------------- #
#                                          get_predefined_templates                                                  #
# -------------------------------------------------------------------------------------------------------------------- #

def test_returns_expected_template_set(creator: SectionTemplateCreator) -> None:
    """Exactly the three predefined templates are produced"""
    templates: list[dict[str, Any]] = creator.get_predefined_templates()

    assert len(templates) == 3
    assert {template[SectionKey.NAME] for template in templates} == EXPECTED_TEMPLATE_NAMES


def test_removed_network_template_absent(creator: SectionTemplateCreator) -> None:
    """The retired 'dg-network' template is no longer produced"""
    names: set[str] = {template[SectionKey.NAME] for template in creator.get_predefined_templates()}

    assert REMOVED_NETWORK_TEMPLATE not in names


def test_all_templates_are_global_and_predefined(creator: SectionTemplateCreator) -> None:
    """Every predefined template is flagged global and predefined"""
    for template in creator.get_predefined_templates():
        assert template[GLOBAL_KEY] is True
        assert template[PREDEFINED_KEY] is True


def test_all_templates_have_required_keys_and_unique_nonempty_fields(creator: SectionTemplateCreator) -> None:
    """Every template carries name/label/type/fields and a unique, non-empty set of field names"""
    for template in creator.get_predefined_templates():
        for key in (SectionKey.NAME, SectionKey.LABEL, SectionKey.TYPE, SectionKey.FIELDS):
            assert key in template

        field_names: list[str] = [field[FieldKey.NAME] for field in template[SectionKey.FIELDS]]
        assert field_names
        assert len(field_names) == len(set(field_names))

# -------------------------------------------------------------------------------------------------------------------- #
#                                            per-template structure                                                  #
# -------------------------------------------------------------------------------------------------------------------- #

def test_rack_mounting_template_structure(creator: SectionTemplateCreator) -> None:
    """Rack mounting is a plain section with two regex-guarded numeric fields and an orientation select"""
    template: dict[str, Any] = _templates_by_name(creator)[RACK_TEMPLATE]
    assert template[SectionKey.TYPE] == SectionType.SECTION

    fields: dict[str, dict[str, Any]] = _fields_by_name(template)
    assert set(fields) == {'dg-rackmounting-ru', 'dg-rackmounting-position', 'dg-rackmounting-orientation'}

    assert FieldKey.REGEX in fields['dg-rackmounting-ru']
    assert FieldKey.REGEX in fields['dg-rackmounting-position']

    orientation: dict[str, Any] = fields['dg-rackmounting-orientation']
    assert orientation[FieldKey.TYPE] == FieldType.SELECT
    assert [option['name'] for option in orientation[FieldKey.OPTIONS]] == ['horizontal', 'vertical']


def test_model_spec_template_structure(creator: SectionTemplateCreator) -> None:
    """Model specifications is a plain section of three bare text fields"""
    template: dict[str, Any] = _templates_by_name(creator)[MODELSPEC_TEMPLATE]
    assert template[SectionKey.TYPE] == SectionType.SECTION

    fields: dict[str, dict[str, Any]] = _fields_by_name(template)
    assert set(fields) == {'dg-modelspec-manufacturer', 'dg-modelspec-model', 'dg-modelspec-serial'}

    for field in fields.values():
        assert field[FieldKey.TYPE] == FieldType.TEXT
        assert FieldKey.OPTIONS not in field
        assert FieldKey.REGEX not in field


def test_ipam_interface_template_structure(creator: SectionTemplateCreator) -> None:
    """The IPAM interface template is an MDS section with an empty-ref Subnet reference and a MAC regex"""
    template: dict[str, Any] = _templates_by_name(creator)[IpamSection.INTERFACE]
    assert template[SectionKey.TYPE] == SectionType.MDS_SECTION

    fields: dict[str, dict[str, Any]] = _fields_by_name(template)
    assert set(fields) == {
        'dg-interface-active',
        InterfaceField.TYPE,
        InterfaceField.SUBNET,
        InterfaceField.IP,
        'dg-interface-host',
        'dg-interface-domain',
        InterfaceField.MAC,
    }

    subnet_field: dict[str, Any] = fields[InterfaceField.SUBNET]
    assert subnet_field[FieldKey.TYPE] == FieldType.REFERENCE
    assert subnet_field[FieldKey.REF_TYPES] == []

    # The address-family selector is required: it drives the subnet picker and the
    # save-time type-family enforcement
    assert fields[InterfaceField.TYPE][FieldKey.REQUIRED] is True

    assert FieldKey.REGEX in fields[InterfaceField.MAC]
    assert FieldKey.REGEX in fields[InterfaceField.IP]

# -------------------------------------------------------------------------------------------------------------------- #
#                                __get_template_section / __get_template_section_field                               #
# -------------------------------------------------------------------------------------------------------------------- #

def test_template_section_base_shape(creator: SectionTemplateCreator) -> None:
    """The base section builder produces a global, predefined, empty plain section"""
    section: dict[str, Any] = creator._SectionTemplateCreator__get_template_section('dg-x', 'X')

    assert section[GLOBAL_KEY] is True
    assert section[PREDEFINED_KEY] is True
    assert section[SectionKey.NAME] == 'dg-x'
    assert section[SectionKey.LABEL] == 'X'
    assert section[SectionKey.TYPE] == SectionType.SECTION
    assert section[SectionKey.FIELDS] == []


def test_template_section_field_minimal_has_only_core_keys(creator: SectionTemplateCreator) -> None:
    """Without optional arguments only type/name/label are set"""
    field: dict[str, Any] = creator._SectionTemplateCreator__get_template_section_field('text', 'n', 'l')

    assert field == {'type': 'text', 'name': 'n', 'label': 'l'}


def test_template_section_field_includes_all_optionals(creator: SectionTemplateCreator) -> None:
    """Options, regex and helper text are added when provided"""
    options: list[dict[str, str]] = [{'name': 'a', 'label': 'A'}]
    field: dict[str, Any] = creator._SectionTemplateCreator__get_template_section_field(
        'select', 'n', 'l', options, '^x$', 'hint',
    )

    assert field[FieldKey.OPTIONS] == options
    assert field[FieldKey.REGEX] == '^x$'
    assert field[HELPER_TEXT_KEY] == 'hint'


def test_template_section_field_omits_unset_optionals(creator: SectionTemplateCreator) -> None:
    """Optional keys are absent (not None) when their argument is not provided"""
    field: dict[str, Any] = creator._SectionTemplateCreator__get_template_section_field('text', 'n', 'l')

    assert FieldKey.OPTIONS not in field
    assert FieldKey.REGEX not in field
    assert HELPER_TEXT_KEY not in field
