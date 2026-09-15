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
Unit tests for cmdb.framework.section_templates.predefined_section_guard

Pure tests (no database): the type is a real CmdbType built from a seed document, the section
template lookup is a MagicMock manager. Asserts which select fields a predefined template owns
(and which are correctly left alone: a non-predefined global template, a non-select field, a plain
section field), the inconsistent-type-document branch, and that the resolver skips the database
lookup for a type that uses no global template at all
"""
from typing import Any
from unittest.mock import MagicMock

import pytest

from cmdb.models.section_template_model import SectionTemplateKey
from cmdb.models.type_model import CmdbType, FieldType, SectionType
from cmdb.framework.section_templates import (
    PREDEFINED_SELECT_OPTION_REJECTED,
    get_predefined_template_names,
    predefined_select_fields,
    resolve_predefined_select_fields,
)
from tests.utils.ipam_doc_builders import make_type_doc
# -------------------------------------------------------------------------------------------------------------------- #

TYPE_ID: int = 1

PREDEFINED_TEMPLATE: str = 'dg-ipam-interface'      # a predefined template, its select field is protected
CUSTOM_TEMPLATE: str = 'custom-global-section'      # a user-created global template, not protected

PROTECTED_SELECT_FIELD: str = 'dg-interface-type'   # select field owned by PREDEFINED_TEMPLATE
CUSTOM_SELECT_FIELD: str = 'custom-select'          # select field owned by CUSTOM_TEMPLATE
LOCAL_SELECT_FIELD: str = 'local-select'            # select field of a plain, template-free section
TEXT_FIELD: str = 'dg-interface-host'               # non-select field owned by PREDEFINED_TEMPLATE

PLAIN_SECTION: str = 'information'


def _type_instance(global_template_ids: list[str], sections: list[dict[str, Any]] | None = None) -> CmdbType:
    """
    Builds a CmdbType carrying one select field per section: a predefined-template MDS section, a
    user-created global template section, and a plain section - plus one non-select template field
    """
    fields: list[dict[str, Any]] = [
        {'type': FieldType.SELECT.value, 'name': PROTECTED_SELECT_FIELD, 'label': 'Type'},
        {'type': FieldType.TEXT.value, 'name': TEXT_FIELD, 'label': 'Hostname'},
        {'type': FieldType.SELECT.value, 'name': CUSTOM_SELECT_FIELD, 'label': 'Custom'},
        {'type': FieldType.SELECT.value, 'name': LOCAL_SELECT_FIELD, 'label': 'Local'},
    ]

    if sections is None:
        sections = [
            {
                'type': SectionType.MDS_SECTION.value,
                'name': PREDEFINED_TEMPLATE,
                'label': 'Interfaces',
                'fields': [PROTECTED_SELECT_FIELD, TEXT_FIELD],
            },
            {
                'type': SectionType.SECTION.value,
                'name': CUSTOM_TEMPLATE,
                'label': 'Custom',
                'fields': [CUSTOM_SELECT_FIELD],
            },
            {
                'type': SectionType.SECTION.value,
                'name': PLAIN_SECTION,
                'label': 'Information',
                'fields': [LOCAL_SELECT_FIELD],
            },
        ]

    return CmdbType.from_data(
        make_type_doc(TYPE_ID, 'guard-demo', fields=fields, sections=sections,
                      global_template_ids=global_template_ids),
    )


@pytest.fixture(name='section_templates_manager')
def fixture_section_templates_manager() -> MagicMock:
    """A manager whose predefined-template lookup returns only PREDEFINED_TEMPLATE"""
    manager = MagicMock()
    manager.get_distinct.return_value = [PREDEFINED_TEMPLATE]

    return manager


# -------------------------------------------------------------------------------------------------------------------- #
#                                            get_predefined_template_names                                             #
# -------------------------------------------------------------------------------------------------------------------- #
class TestGetPredefinedTemplateNames:
    """The database lookup of the predefined template names."""

    def test_queries_the_predefined_flag(self, section_templates_manager: MagicMock) -> None:
        """It asks for the distinct names of the templates flagged predefined."""
        result = get_predefined_template_names(section_templates_manager)

        assert result == {PREDEFINED_TEMPLATE}
        section_templates_manager.get_distinct.assert_called_once_with(
            SectionTemplateKey.NAME.value,
            {SectionTemplateKey.PREDEFINED.value: True},
        )

    def test_no_predefined_templates_returns_empty(self, section_templates_manager: MagicMock) -> None:
        """An installation without predefined templates yields an empty set."""
        section_templates_manager.get_distinct.return_value = []

        assert get_predefined_template_names(section_templates_manager) == set()


# -------------------------------------------------------------------------------------------------------------------- #
#                                              predefined_select_fields                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class TestPredefinedSelectFields:
    """Classifying a type's select fields by the predefined template owning them."""

    def test_select_field_of_a_predefined_template_is_owned(self) -> None:
        """The select field of the predefined template's section maps to that template."""
        type_instance = _type_instance([PREDEFINED_TEMPLATE, CUSTOM_TEMPLATE])

        assert predefined_select_fields(type_instance, {PREDEFINED_TEMPLATE}) == {
            PROTECTED_SELECT_FIELD: PREDEFINED_TEMPLATE
        }

    def test_select_field_of_a_non_predefined_global_template_is_not_owned(self) -> None:
        """A user-created global template's select field stays extendable."""
        type_instance = _type_instance([PREDEFINED_TEMPLATE, CUSTOM_TEMPLATE])

        assert CUSTOM_SELECT_FIELD not in predefined_select_fields(type_instance, {PREDEFINED_TEMPLATE})

    def test_select_field_of_a_plain_section_is_not_owned(self) -> None:
        """A select field that belongs to no template at all stays extendable."""
        type_instance = _type_instance([PREDEFINED_TEMPLATE])

        assert LOCAL_SELECT_FIELD not in predefined_select_fields(type_instance, {PREDEFINED_TEMPLATE})

    def test_non_select_template_field_is_not_reported(self) -> None:
        """Only select fields are collected - the template's text field is irrelevant here."""
        type_instance = _type_instance([PREDEFINED_TEMPLATE])

        assert TEXT_FIELD not in predefined_select_fields(type_instance, {PREDEFINED_TEMPLATE})

    def test_no_predefined_template_names_returns_empty(self) -> None:
        """Without any predefined template nothing is protected."""
        type_instance = _type_instance([PREDEFINED_TEMPLATE])

        assert predefined_select_fields(type_instance, set()) == {}

    def test_type_without_select_fields_returns_empty(self) -> None:
        """A type whose predefined section has no select field yields nothing."""
        type_instance = CmdbType.from_data(
            make_type_doc(
                TYPE_ID,
                'guard-no-select',
                fields=[{'type': FieldType.TEXT.value, 'name': TEXT_FIELD, 'label': 'Hostname'}],
                sections=[{
                    'type': SectionType.MDS_SECTION.value,
                    'name': PREDEFINED_TEMPLATE,
                    'label': 'Interfaces',
                    'fields': [TEXT_FIELD],
                }],
                global_template_ids=[PREDEFINED_TEMPLATE],
            ),
        )

        assert predefined_select_fields(type_instance, {PREDEFINED_TEMPLATE}) == {}

    def test_referenced_template_without_a_section_is_skipped(self) -> None:
        """An inconsistent type document (template referenced, section missing) contributes nothing."""
        type_instance = _type_instance(
            [PREDEFINED_TEMPLATE],
            sections=[{
                'type': SectionType.SECTION.value,
                'name': PLAIN_SECTION,
                'label': 'Information',
                'fields': [PROTECTED_SELECT_FIELD, TEXT_FIELD, CUSTOM_SELECT_FIELD, LOCAL_SELECT_FIELD],
            }],
        )

        assert predefined_select_fields(type_instance, {PREDEFINED_TEMPLATE}) == {}


# -------------------------------------------------------------------------------------------------------------------- #
#                                          resolve_predefined_select_fields                                            #
# -------------------------------------------------------------------------------------------------------------------- #
class TestResolvePredefinedSelectFields:
    """The database-backed resolver used by the object write paths."""

    def test_resolves_via_the_manager(self, section_templates_manager: MagicMock) -> None:
        """With a global template on the type, the templates are looked up and the field classified."""
        type_instance = _type_instance([PREDEFINED_TEMPLATE])

        result = resolve_predefined_select_fields(type_instance, section_templates_manager)

        assert result == {PROTECTED_SELECT_FIELD: PREDEFINED_TEMPLATE}
        section_templates_manager.get_distinct.assert_called_once()

    def test_type_without_global_templates_skips_the_lookup(self, section_templates_manager: MagicMock) -> None:
        """A type using no global template cannot own such a field - no database read is paid."""
        type_instance = _type_instance([])

        assert resolve_predefined_select_fields(type_instance, section_templates_manager) == {}
        section_templates_manager.get_distinct.assert_not_called()


# -------------------------------------------------------------------------------------------------------------------- #
#                                        PREDEFINED_SELECT_OPTION_REJECTED                                             #
# -------------------------------------------------------------------------------------------------------------------- #
class TestRejectionMessage:
    """The shared rejection reason names both the value and the owning template."""

    def test_names_the_value_and_the_template(self) -> None:
        """Formatting yields a message a user can act on."""
        message = PREDEFINED_SELECT_OPTION_REJECTED.format(value='IPv4', template=PREDEFINED_TEMPLATE)

        assert 'IPv4' in message
        assert PREDEFINED_TEMPLATE in message
