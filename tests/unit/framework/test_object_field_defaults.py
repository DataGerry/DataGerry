# DataGerry - OpenSource Enterprise CMDB
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
Unit tests for cmdb.framework.object_field_defaults

Pure tests. Which declared defaults are usable (not an excluded kind, not breaking their own field's
rules), how one entry list is filled (absent / null / '' take the default; 0 and False are kept), and how
a whole object is filled - the top-level list and the rows its multi-data sections carry, never new rows
"""
import logging
from typing import Any

import pytest

from cmdb.framework.object_field_defaults import (
    DEFAULT_EXCLUDED_KINDS,
    fill_entries_from_defaults,
    fill_object_defaults,
    usable_default,
)
from cmdb.framework.object_field_value_rules import build_field_value_rules
from cmdb.models.type_model import CmdbType, FieldType, SectionType, TEXT_VALUE_MAX_LENGTH
from tests.utils.ipam_doc_builders import make_type_doc
# -------------------------------------------------------------------------------------------------------------------- #

TEXT_FIELD: str = 'df-text'
CODE_FIELD: str = 'df-code'
ROW_FIELD: str = 'df-row'
MDS_SECTION: str = 'df-rows'
TEXT_DEFAULT: str = 'fallback'
CODE_REGEX: str = '[A-Z]+'


def _usable(field: dict[str, Any]) -> Any:
    """The usable default of one field, judged by its own rules."""
    return usable_default(field, build_field_value_rules([field]).get(field.get('name')))


class TestUsableDefault:
    """Which declared defaults may be filled."""

    @pytest.mark.parametrize('default', ['x', 0, False, 5.5], ids=['text', 'zero', 'false', 'number'])
    def test_a_declared_value_is_usable(self, default: Any) -> None:
        """0 and False are values, like the required-field rule reads them"""
        assert _usable({'type': 'text', 'name': TEXT_FIELD, 'value': default}) == default

    @pytest.mark.parametrize('field', [
        {'type': 'text', 'name': TEXT_FIELD},
        {'type': 'text', 'name': TEXT_FIELD, 'value': None},
        {'type': 'text', 'name': TEXT_FIELD, 'value': ''},
    ], ids=['absent', 'null', 'empty'])
    def test_no_default_is_none(self, field: dict[str, Any]) -> None:
        """Nothing to fill"""
        assert _usable(field) is None

    @pytest.mark.parametrize('kind', sorted(DEFAULT_EXCLUDED_KINDS))
    def test_a_reference_like_kind_is_never_filled(self, kind: str) -> None:
        """Its default would be an object id"""
        assert _usable({'type': kind, 'name': TEXT_FIELD, 'value': 7}) is None

    @pytest.mark.parametrize('field', [
        {'type': 'text', 'name': CODE_FIELD, 'regex': CODE_REGEX, 'value': 'abc'},
        {'type': 'text', 'name': TEXT_FIELD, 'value': 'x' * (TEXT_VALUE_MAX_LENGTH + 1)},
    ], ids=['breaks-its-regex', 'over-the-cap'])
    def test_a_default_breaking_its_own_rules_is_skipped_with_a_warning(
        self, field: dict[str, Any], caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A create that leaves the field empty never fails over a value the client did not send"""
        with caplog.at_level(logging.WARNING):
            assert _usable(field) is None

        assert field['name'] in caplog.text

    def test_a_field_without_any_value_rule_keeps_its_default(self) -> None:
        """A checkbox has no cap and no pattern - nothing to judge the default by"""
        assert usable_default({'type': FieldType.CHECKBOX.value, 'name': TEXT_FIELD, 'value': True}, None) is True

    def test_a_default_matching_its_regex_is_usable(self) -> None:
        """The control"""
        assert _usable({'type': 'text', 'name': CODE_FIELD, 'regex': CODE_REGEX, 'value': 'ABC'}) == 'ABC'


class TestFillEntriesFromDefaults:
    """One entry list - an object's fields or one MDS row."""

    @pytest.mark.parametrize('empty', [None, '', []], ids=['null', 'empty-string', 'empty-list'])
    def test_a_present_empty_entry_takes_the_default(self, empty: Any) -> None:
        """Empty is absent, null, '' (and [] for a multi-value kind)"""
        entries: list[dict[str, Any]] = [{'name': TEXT_FIELD, 'value': empty}]

        fill_entries_from_defaults(entries, {TEXT_FIELD: TEXT_DEFAULT})

        assert entries == [{'name': TEXT_FIELD, 'value': TEXT_DEFAULT}]

    @pytest.mark.parametrize('value', [0, False, 'chosen'], ids=['zero', 'false', 'text'])
    def test_a_value_the_client_chose_is_kept(self, value: Any) -> None:
        """0 and False are values"""
        entries: list[dict[str, Any]] = [{'name': TEXT_FIELD, 'value': value}]

        fill_entries_from_defaults(entries, {TEXT_FIELD: TEXT_DEFAULT})

        assert entries[0]['value'] == value

    def test_an_absent_field_is_appended_with_its_type(self) -> None:
        """Stamped with the field's kind, as the object write expects"""
        entries: list[dict[str, Any]] = []

        fill_entries_from_defaults(entries, {TEXT_FIELD: TEXT_DEFAULT}, {TEXT_FIELD: FieldType.TEXT.value})

        assert entries == [{'name': TEXT_FIELD, 'value': TEXT_DEFAULT, 'type': FieldType.TEXT.value}]

    def test_an_absent_field_without_a_default_is_not_appended(self) -> None:
        """The REST create does not change the payload's shape for nothing"""
        entries: list[dict[str, Any]] = []

        fill_entries_from_defaults(entries, {TEXT_FIELD: None})

        assert not entries

    def test_complete_entries_append_none_for_a_field_without_a_default(self) -> None:
        """The importer asks for every field of the type"""
        entries: list[dict[str, Any]] = []

        fill_entries_from_defaults(entries, {TEXT_FIELD: None}, append_without_default=True)

        assert entries == [{'name': TEXT_FIELD, 'value': None}]

    def test_an_empty_entry_without_a_default_stays_empty(self) -> None:
        """Nothing to fill it with"""
        entries: list[dict[str, Any]] = [{'name': TEXT_FIELD, 'value': ''}]

        fill_entries_from_defaults(entries, {TEXT_FIELD: None}, append_without_default=True)

        assert entries == [{'name': TEXT_FIELD, 'value': ''}]


def _type(text_default: Any = TEXT_DEFAULT, row_default: Any = 'row-fallback') -> CmdbType:
    """A type with a defaulted plain field and a defaulted multi-data-section field."""
    fields: list[dict[str, Any]] = [
        {'type': 'text', 'name': TEXT_FIELD, 'label': 'Text', 'value': text_default},
        {'type': 'text', 'name': ROW_FIELD, 'label': 'Row', 'value': row_default},
    ]
    sections: list[dict[str, Any]] = [
        {'type': SectionType.SECTION.value, 'name': 'main', 'label': 'Main', 'fields': [TEXT_FIELD]},
        {'type': SectionType.MDS_SECTION.value, 'name': MDS_SECTION, 'label': 'Rows', 'fields': [ROW_FIELD]},
    ]

    return CmdbType.from_data(make_type_doc(5, 'defaults-demo', fields=fields, sections=sections))


class TestFillObjectDefaults:
    """A whole candidate object."""

    def test_the_top_level_list_gets_the_plain_defaults_only(self) -> None:
        """An MDS field's default belongs in its rows, not in the flat list"""
        document: dict[str, Any] = {'fields': []}

        fill_object_defaults(document, _type())

        assert document['fields'] == [{'name': TEXT_FIELD, 'value': TEXT_DEFAULT, 'type': 'text'}]

    def test_every_carried_row_is_filled(self) -> None:
        """Absent and empty entries of each row"""
        document: dict[str, Any] = {'fields': [], 'multi_data_sections': [{
            'section_id': MDS_SECTION,
            'values': [{'multi_data_id': 1, 'data': []},
                       {'multi_data_id': 2, 'data': [{'name': ROW_FIELD, 'value': ''}]}],
        }]}

        fill_object_defaults(document, _type())

        rows = document['multi_data_sections'][0]['values']
        assert rows[0]['data'] == [{'name': ROW_FIELD, 'value': 'row-fallback', 'type': 'text'}]
        assert rows[1]['data'] == [{'name': ROW_FIELD, 'value': 'row-fallback'}]

    def test_no_row_is_created(self) -> None:
        """A section with no rows stays empty - no interfaces is a legal state"""
        document: dict[str, Any] = {'fields': [], 'multi_data_sections': [{'section_id': MDS_SECTION, 'values': []}]}

        fill_object_defaults(document, _type())

        assert document['multi_data_sections'][0]['values'] == []

    def test_a_section_the_type_does_not_declare_is_left_alone(self) -> None:
        """Its rows name no field of this type, so there is nothing to fill"""
        document: dict[str, Any] = {'fields': [], 'multi_data_sections': [
            {'section_id': 'not-a-section-of-this-type', 'values': [{'multi_data_id': 1, 'data': []}]},
        ]}

        fill_object_defaults(document, _type())

        assert document['multi_data_sections'][0]['values'][0]['data'] == []

    def test_a_type_without_defaults_changes_nothing(self) -> None:
        """No default, no fill"""
        document: dict[str, Any] = {'fields': [{'name': TEXT_FIELD, 'value': None}]}

        fill_object_defaults(document, _type(text_default=None, row_default=None))

        assert document == {'fields': [{'name': TEXT_FIELD, 'value': None}]}
