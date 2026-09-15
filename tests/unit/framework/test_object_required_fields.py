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
Unit tests for cmdb.framework.object_required_fields

Pure tests (no database): the type is a real CmdbType built from a seed document, the candidate is a
plain CmdbObject document. Covers what counts as "no value", which of a type's fields are required,
how that set splits between the top-level fields and the multi-data sections, which required fields a
candidate leaves empty, and the wording of the resulting errors
"""
from typing import Any

import pytest

from cmdb.framework.object_required_fields import (
    build_missing_required_errors,
    collect_missing_required_values,
    collect_required_field_names,
    find_missing_required_values,
    is_value_missing,
    mds_section_field_names,
    split_required_field_names,
)
from cmdb.models.type_model import CmdbType, FieldType, SectionType
from tests.utils.ipam_doc_builders import make_type_doc
# -------------------------------------------------------------------------------------------------------------------- #

TYPE_ID: int = 1

REQUIRED_FIELD: str = 'req-name'        # required, lives in the plain section
OPTIONAL_FIELD: str = 'opt-note'        # not required
REQUIRED_REFERENCE: str = 'req-ref'     # required reference - the importer exempts it, the REST path does not
REQUIRED_ROW_FIELD: str = 'req-row'     # required, lives in the MDS section
OPTIONAL_ROW_FIELD: str = 'opt-row'     # not required, lives in the MDS section

PLAIN_SECTION: str = 'information'
MDS_SECTION: str = 'rows'


def _type_instance() -> CmdbType:
    """Builds a CmdbType with a required + an optional field in a plain and in a multi-data section"""
    fields: list[dict[str, Any]] = [
        {'type': FieldType.TEXT.value, 'name': REQUIRED_FIELD, 'label': 'Name', 'required': True},
        {'type': FieldType.TEXT.value, 'name': OPTIONAL_FIELD, 'label': 'Note'},
        {'type': FieldType.REFERENCE.value, 'name': REQUIRED_REFERENCE, 'label': 'Ref', 'required': True},
        {'type': FieldType.TEXT.value, 'name': REQUIRED_ROW_FIELD, 'label': 'Row', 'required': True},
        {'type': FieldType.TEXT.value, 'name': OPTIONAL_ROW_FIELD, 'label': 'Row note'},
    ]
    sections: list[dict[str, Any]] = [
        {
            'type': SectionType.SECTION.value,
            'name': PLAIN_SECTION,
            'label': 'Information',
            'fields': [REQUIRED_FIELD, OPTIONAL_FIELD, REQUIRED_REFERENCE],
        },
        {
            'type': SectionType.MDS_SECTION.value,
            'name': MDS_SECTION,
            'label': 'Rows',
            'fields': [REQUIRED_ROW_FIELD, OPTIONAL_ROW_FIELD],
        },
    ]

    return CmdbType.from_data(make_type_doc(TYPE_ID, 'required-demo', fields=fields, sections=sections))


def _entry(name: str, value: Any) -> dict[str, Any]:
    """Builds one {'name', 'value'} entry of a 'fields' list or an MDS row's 'data' list"""
    return {'name': name, 'value': value}


# -------------------------------------------------------------------------------------------------------------------- #
#                                                   is_value_missing                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
class TestIsValueMissing:
    """Only None and the empty string count as "no value"."""

    @pytest.mark.parametrize('value', [None, ''])
    def test_no_value(self, value: Any) -> None:
        """None and the empty string are missing."""
        assert is_value_missing(value) is True

    @pytest.mark.parametrize('value', [0, 0.0, False, 'x', [], {}, '0'])
    def test_falsy_but_present_values_count_as_values(self, value: Any) -> None:
        """A falsy value the user actually chose (0, False, an unchecked box) is a value, not a gap."""
        assert is_value_missing(value) is False


# -------------------------------------------------------------------------------------------------------------------- #
#                                               mds_section_field_names                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class TestMdsSectionFieldNames:
    """Only multi-data sections are reported, keyed by the section_id an object stores."""

    def test_returns_only_multi_data_sections(self) -> None:
        """The plain section is left out; the MDS section maps to its ordered field names."""
        assert mds_section_field_names(_type_instance()) == {
            MDS_SECTION: [REQUIRED_ROW_FIELD, OPTIONAL_ROW_FIELD],
        }

    def test_type_without_multi_data_sections_returns_empty(self) -> None:
        """A type with no MDS section has no per-section required fields to check."""
        type_instance = CmdbType.from_data(make_type_doc(TYPE_ID, 'plain-demo'))

        assert mds_section_field_names(type_instance) == {}


# -------------------------------------------------------------------------------------------------------------------- #
#                                             collect_required_field_names                                             #
# -------------------------------------------------------------------------------------------------------------------- #
class TestCollectRequiredFieldNames:
    """The required flag selects the fields; the exempt field types drop out again."""

    def test_collects_every_flagged_field(self) -> None:
        """Without an exemption every field flagged required is collected, whatever its type."""
        result = collect_required_field_names(_type_instance().get_fields())

        assert result == {REQUIRED_FIELD, REQUIRED_REFERENCE, REQUIRED_ROW_FIELD}

    def test_exempt_field_types_are_dropped(self) -> None:
        """A required field of an exempt type is not required-checked (the importer clears its value)."""
        result = collect_required_field_names(
            _type_instance().get_fields(), frozenset({FieldType.REFERENCE.value}),
        )

        assert result == {REQUIRED_FIELD, REQUIRED_ROW_FIELD}

    def test_no_fields_returns_empty(self) -> None:
        """A type without fields requires nothing."""
        assert collect_required_field_names(None) == set()


# -------------------------------------------------------------------------------------------------------------------- #
#                                              split_required_field_names                                              #
# -------------------------------------------------------------------------------------------------------------------- #
class TestSplitRequiredFieldNames:
    """A required field of an MDS section is checked per row, never in the top-level field list."""

    def test_splits_top_level_from_section_fields(self) -> None:
        """The MDS field lands under its section id and is removed from the top-level set."""
        type_instance = _type_instance()

        top_level, by_section = split_required_field_names(
            collect_required_field_names(type_instance.get_fields()),
            mds_section_field_names(type_instance),
        )

        assert top_level == {REQUIRED_FIELD, REQUIRED_REFERENCE}
        assert by_section == {MDS_SECTION: {REQUIRED_ROW_FIELD}}

    def test_section_without_a_required_field_is_omitted(self) -> None:
        """A section none of whose fields are required contributes no per-row check."""
        top_level, by_section = split_required_field_names({REQUIRED_FIELD}, {MDS_SECTION: [OPTIONAL_ROW_FIELD]})

        assert top_level == {REQUIRED_FIELD}
        assert by_section == {}


# -------------------------------------------------------------------------------------------------------------------- #
#                                             find_missing_required_values                                             #
# -------------------------------------------------------------------------------------------------------------------- #
class TestFindMissingRequiredValues:
    """One entry list against one set of required names."""

    @pytest.mark.parametrize('entries', [
        [],
        None,
        [_entry(OPTIONAL_FIELD, 'x')],
        [_entry(REQUIRED_FIELD, '')],
        [_entry(REQUIRED_FIELD, None)],
    ])
    def test_absent_or_empty_counts_as_missing(self, entries: list[dict[str, Any]] | None) -> None:
        """A required name that is absent from the list is as missing as one carrying no value."""
        assert find_missing_required_values(entries, {REQUIRED_FIELD}) == {REQUIRED_FIELD}

    def test_a_carried_value_satisfies_the_check(self) -> None:
        """A required name present with a value is not reported."""
        assert find_missing_required_values([_entry(REQUIRED_FIELD, 'x')], {REQUIRED_FIELD}) == set()

    def test_nothing_required_reports_nothing(self) -> None:
        """An empty required set never reports a miss, whatever the entries hold."""
        assert find_missing_required_values([_entry(OPTIONAL_FIELD, '')], set()) == set()


# -------------------------------------------------------------------------------------------------------------------- #
#                                            collect_missing_required_values                                           #
# -------------------------------------------------------------------------------------------------------------------- #
class TestCollectMissingRequiredValues:
    """The whole candidate: the top-level fields once, the MDS fields in every row of every section."""

    @staticmethod
    def _sets() -> tuple[set[str], dict[str, set[str]]]:
        """The required sets of the demo type"""
        type_instance = _type_instance()

        return split_required_field_names(
            collect_required_field_names(type_instance.get_fields()),
            mds_section_field_names(type_instance),
        )

    def test_a_complete_object_reports_nothing(self) -> None:
        """Every required field carrying a value leaves nothing to report."""
        required_top_level, required_by_section = self._sets()
        candidate = {
            'fields': [_entry(REQUIRED_FIELD, 'x'), _entry(REQUIRED_REFERENCE, 3)],
            'multi_data_sections': [{
                'section_id': MDS_SECTION,
                'values': [{'multi_data_id': 1, 'data': [_entry(REQUIRED_ROW_FIELD, 'y')]}],
            }],
        }

        assert collect_missing_required_values(candidate, required_top_level, required_by_section) == (set(), {})

    def test_reports_the_empty_top_level_fields(self) -> None:
        """A required top-level field left empty is reported, the optional one is not."""
        required_top_level, required_by_section = self._sets()
        candidate = {'fields': [_entry(REQUIRED_FIELD, ''), _entry(OPTIONAL_FIELD, '')]}

        missing_top_level, missing_by_section = collect_missing_required_values(
            candidate, required_top_level, required_by_section,
        )

        assert missing_top_level == {REQUIRED_FIELD, REQUIRED_REFERENCE}
        assert missing_by_section == {}

    def test_reports_a_row_leaving_a_required_field_empty(self) -> None:
        """One bad row among good ones rejects the section, reported under its section id."""
        required_top_level, required_by_section = self._sets()
        candidate = {
            'fields': [_entry(REQUIRED_FIELD, 'x'), _entry(REQUIRED_REFERENCE, 3)],
            'multi_data_sections': [{
                'section_id': MDS_SECTION,
                'values': [
                    {'multi_data_id': 1, 'data': [_entry(REQUIRED_ROW_FIELD, 'y')]},
                    {'multi_data_id': 2, 'data': [_entry(OPTIONAL_ROW_FIELD, 'z')]},
                ],
            }],
        }

        missing_top_level, missing_by_section = collect_missing_required_values(
            candidate, required_top_level, required_by_section,
        )

        assert missing_top_level == set()
        assert missing_by_section == {MDS_SECTION: {REQUIRED_ROW_FIELD}}

    def test_a_section_without_rows_requires_nothing(self) -> None:
        """An empty multi-data section is an empty section, not a missing value."""
        required_top_level, required_by_section = self._sets()
        candidate = {
            'fields': [_entry(REQUIRED_FIELD, 'x'), _entry(REQUIRED_REFERENCE, 3)],
            'multi_data_sections': [{'section_id': MDS_SECTION, 'values': []}],
        }

        assert collect_missing_required_values(candidate, required_top_level, required_by_section) == (set(), {})

    def test_a_section_the_type_does_not_require_is_skipped(self) -> None:
        """A section id with no required field is not walked at all."""
        required_top_level, required_by_section = self._sets()
        candidate = {
            'fields': [_entry(REQUIRED_FIELD, 'x'), _entry(REQUIRED_REFERENCE, 3)],
            'multi_data_sections': [{'section_id': 'other-section', 'values': [{'data': []}]}],
        }

        assert collect_missing_required_values(candidate, required_top_level, required_by_section) == (set(), {})


# -------------------------------------------------------------------------------------------------------------------- #
#                                             build_missing_required_errors                                            #
# -------------------------------------------------------------------------------------------------------------------- #
class TestBuildMissingRequiredErrors:
    """One message for the top-level fields, one per multi-data section."""

    def test_nothing_missing_yields_no_message(self) -> None:
        """A valid candidate produces an empty message list."""
        assert build_missing_required_errors(set(), {}) == []

    def test_names_the_missing_top_level_fields_sorted(self) -> None:
        """The names are sorted so the message does not depend on set ordering."""
        assert build_missing_required_errors({'b-field', 'a-field'}, {}) == [
            "Missing value for required field(s): ['a-field', 'b-field']",
        ]

    def test_names_the_section_of_a_missing_row_field(self) -> None:
        """A per-section message names both the fields and the section they belong to."""
        assert build_missing_required_errors(set(), {MDS_SECTION: {REQUIRED_ROW_FIELD}}) == [
            f"Missing value for required field(s) ['{REQUIRED_ROW_FIELD}'] in multi-data section '{MDS_SECTION}'",
        ]

    def test_both_scopes_are_reported(self) -> None:
        """A candidate failing on both scopes produces one message per scope."""
        messages = build_missing_required_errors({REQUIRED_FIELD}, {MDS_SECTION: {REQUIRED_ROW_FIELD}})

        assert len(messages) == 2
        assert REQUIRED_FIELD in messages[0]
        assert MDS_SECTION in messages[1]
