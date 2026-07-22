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
Unit tests for cmdb.framework.datagerry_assistant.predefined_template_provider

The DB load is exercised with a MagicMock SectionTemplatesManager; the serve path (get_template)
is exercised against the pre-loaded provider fixture. The deep-copy behaviour has its own regression
test because a shared-cache mutation (summary leaking between types) was a real bug.
"""
from typing import Any
from types import SimpleNamespace
from unittest.mock import MagicMock

from cmdb.models.type_model import FieldKey, SectionKey
from cmdb.models.type_model.section_type_enum import SectionType
from cmdb.framework.datagerry_assistant.datagerry_assistant_constants import (
    AssistantFieldKey,
    AssistantSectionKey,
)
from cmdb.framework.datagerry_assistant.predefined_template_provider import PredefinedTemplateProvider
# -------------------------------------------------------------------------------------------------------------------- #
#                                                  get_template                                                        #
# -------------------------------------------------------------------------------------------------------------------- #

def test_get_template_marks_only_requested_summary_fields(template_provider: PredefinedTemplateProvider) -> None:
    """Only the named fields get is_summary; the others are left untouched"""
    template: dict[str, Any] = template_provider.get_template('dg-modelspec', ['dg-modelspec-model'])

    by_name: dict[str, dict[str, Any]] = {field[FieldKey.NAME]: field for field in template[SectionKey.FIELDS]}
    assert by_name['dg-modelspec-model'].get(AssistantFieldKey.IS_SUMMARY) is True
    assert AssistantFieldKey.IS_SUMMARY not in by_name['dg-modelspec-manufacturer']


def test_get_template_without_summary_fields_marks_nothing(template_provider: PredefinedTemplateProvider) -> None:
    """With no summary_fields argument no field is flagged as summary"""
    template: dict[str, Any] = template_provider.get_template('dg-modelspec')

    for field in template[SectionKey.FIELDS]:
        assert AssistantFieldKey.IS_SUMMARY not in field


def test_get_template_does_not_leak_summary_between_calls(template_provider: PredefinedTemplateProvider) -> None:
    """Marking a field as summary for one type must not leak into a later call for the same template"""
    first: dict[str, Any] = template_provider.get_template('dg-modelspec', ['dg-modelspec-model'])
    first_model: dict[str, Any] = next(
        f for f in first[SectionKey.FIELDS] if f[FieldKey.NAME] == 'dg-modelspec-model'
    )
    assert first_model.get(AssistantFieldKey.IS_SUMMARY) is True

    second: dict[str, Any] = template_provider.get_template('dg-modelspec')
    second_model: dict[str, Any] = next(
        f for f in second[SectionKey.FIELDS] if f[FieldKey.NAME] == 'dg-modelspec-model'
    )
    assert AssistantFieldKey.IS_SUMMARY not in second_model


def test_get_template_returns_independent_copies(template_provider: PredefinedTemplateProvider) -> None:
    """Mutating a returned template does not affect the cache or subsequent calls"""
    first: dict[str, Any] = template_provider.get_template('dg-modelspec')
    original_field_count: int = len(first[SectionKey.FIELDS])

    first[SectionKey.FIELDS].append({FieldKey.NAME: 'injected'})

    second: dict[str, Any] = template_provider.get_template('dg-modelspec')
    assert len(second[SectionKey.FIELDS]) == original_field_count

# -------------------------------------------------------------------------------------------------------------------- #
#                                        __load_predefined_templates / __format                                        #
# -------------------------------------------------------------------------------------------------------------------- #

def _raw_template(name: str, label: str, fields: list[dict[str, Any]],
                  section_type: str = SectionType.SECTION) -> SimpleNamespace:
    """A stand-in for a CmdbSectionTemplate whose __dict__ mirrors the stored document"""
    return SimpleNamespace(name=name, label=label, type=section_type, fields=fields)


def test_load_keys_templates_by_name_and_sets_global_id() -> None:
    """The loader keys every template by its name and records that name as global_id_name"""
    manager = MagicMock()
    manager.iterate.return_value = SimpleNamespace(results=[
        _raw_template('dg-a', 'A', [{'type': 'text', 'name': 'a1', 'label': 'A1'}]),
        _raw_template('dg-b', 'B', [{'type': 'text', 'name': 'b1', 'label': 'B1'}]),
    ])

    provider = PredefinedTemplateProvider(manager)

    assert set(provider.predefined_templates) == {'dg-a', 'dg-b'}
    template_a: dict[str, Any] = provider.predefined_templates['dg-a']
    assert template_a[SectionKey.NAME] == 'dg-a'
    assert template_a[SectionKey.LABEL] == 'A'
    assert template_a[AssistantSectionKey.GLOBAL_ID_NAME] == 'dg-a'


def test_format_splits_default_keys_from_extras() -> None:
    """type/name/label stay top-level on a field; every other attribute is moved into 'extras'"""
    manager = MagicMock()
    manager.iterate.return_value = SimpleNamespace(results=[
        _raw_template('dg-x', 'X', [
            {'type': 'text', 'name': 'plain', 'label': 'Plain'},
            {'type': 'text', 'name': 'fancy', 'label': 'Fancy', 'regex': '^x$', 'helperText': 'hint'},
        ]),
    ])

    provider = PredefinedTemplateProvider(manager)
    fields: list[dict[str, Any]] = provider.predefined_templates['dg-x'][SectionKey.FIELDS]
    by_name: dict[str, dict[str, Any]] = {field[FieldKey.NAME]: field for field in fields}

    assert by_name['plain'][AssistantFieldKey.EXTRAS] == {}
    assert by_name['fancy'][AssistantFieldKey.EXTRAS] == {'regex': '^x$', 'helperText': 'hint'}
    assert by_name['fancy'][FieldKey.TYPE] == 'text'
    assert by_name['fancy'][FieldKey.LABEL] == 'Fancy'


def test_format_carries_section_type() -> None:
    """The section 'type' is preserved so a multi-data-section template keeps its kind"""
    manager = MagicMock()
    manager.iterate.return_value = SimpleNamespace(results=[
        _raw_template('dg-plain', 'Plain', [{'type': 'text', 'name': 'p1', 'label': 'P1'}]),
        _raw_template('dg-mds', 'MDS', [{'type': 'text', 'name': 'm1', 'label': 'M1'}],
                      SectionType.MDS_SECTION),
    ])

    provider = PredefinedTemplateProvider(manager)

    assert provider.predefined_templates['dg-plain'][SectionKey.TYPE] == SectionType.SECTION
    assert provider.predefined_templates['dg-mds'][SectionKey.TYPE] == SectionType.MDS_SECTION
