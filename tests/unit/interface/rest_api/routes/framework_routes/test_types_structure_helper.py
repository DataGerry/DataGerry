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
Unit tests for the CmdbType structure rules

Pure: no Mongo, no Flask app. The rules decide whether a Type payload can render itself - its
sections and its summary line carry only the NAMES of the fields the flat `fields` list declares - so
what is pinned here is the pairing on both sides, the two identifier-uniqueness rules, and the shapes
that are deliberately NOT refused. Schema dict keys come from the model key enums per the
no-magic-values rule
"""
from typing import Any

import pytest
from werkzeug.exceptions import HTTPException

from cmdb.models.type_model.field_key_enum import FieldKey
from cmdb.models.type_model.section_key_enum import SectionKey
from cmdb.models.type_model.type_schema_key_enum import TypeSchemaKey
from cmdb.interface.rest_api.routes.framework_routes.cmdb_types.types_structure_helper import (
    duplicated,
    guard_type_structure,
    summary_blocker,
    type_structure_blocker,
)
# -------------------------------------------------------------------------------------------------------------------- #

FIELD_A: str = 'text-a'
FIELD_B: str = 'text-b'
SECTION_A: str = 'section-a'


def _field(name: str, label: str = 'Label') -> dict[str, Any]:
    """Builds the minimal field definition the rules read."""
    return {FieldKey.TYPE.value: 'text', FieldKey.NAME.value: name, FieldKey.LABEL.value: label}


def _section(name: str, fields: list[str]) -> dict[str, Any]:
    """Builds the minimal section the rules read."""
    return {
        SectionKey.TYPE.value: 'section',
        SectionKey.NAME.value: name,
        SectionKey.LABEL.value: 'Section',
        SectionKey.FIELDS.value: fields,
    }


def _payload(
    fields: list[dict[str, Any]],
    sections: list[dict[str, Any]],
    summary: list[str] | None = None,
) -> dict[str, Any]:
    """Builds the part of a Type payload the rules look at, with a summary only when one is given."""
    render_meta: dict[str, Any] = {TypeSchemaKey.SECTIONS.value: sections}

    if summary is not None:
        render_meta[TypeSchemaKey.SUMMARY.value] = {TypeSchemaKey.FIELDS.value: summary}

    return {
        TypeSchemaKey.FIELDS.value: fields,
        TypeSchemaKey.RENDER_META.value: render_meta,
    }


# -------------------------------------------------------------------------------------------------------------------- #
#                                                    duplicated                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize('names, expected', [
    ([], []),
    (['a', 'b'], []),
    (['a', 'a'], ['a']),
    (['a', 'b', 'a', 'b', 'a'], ['a', 'b']),
])
def test_duplicated_reports_each_repeat_once(names: list[str], expected: list[str]) -> None:
    """A repeated name is reported once, in the order it was first repeated"""
    assert duplicated(names) == expected


# -------------------------------------------------------------------------------------------------------------------- #
#                                             what the rules refuse                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
def test_a_section_naming_an_undeclared_field_is_refused() -> None:
    """The reported bug: renaming the field definitions without rewriting the section references

    The Type would be stored holding fields and rendering none of them, while those names stay
    taken - so adding a field under the intended name is refused as a duplicate.
    """
    blocker = type_structure_blocker(_payload([_field(FIELD_A)], [_section(SECTION_A, ['text-old'])]))

    assert blocker is not None
    assert 'text-old' in blocker
    assert SECTION_A in blocker


def test_the_message_names_every_unknown_field_of_the_section() -> None:
    """A caller fixing the payload needs the whole list, not the first entry"""
    blocker = type_structure_blocker(
        _payload([_field(FIELD_A)], [_section(SECTION_A, ['text-old', FIELD_A, 'date-old'])])
    )

    assert 'text-old' in blocker and 'date-old' in blocker


def test_duplicate_field_identifiers_are_refused() -> None:
    """A field's name is its identity - an Object keys its stored values by the name alone"""
    blocker = type_structure_blocker(
        _payload([_field(FIELD_A, 'First'), _field(FIELD_A, 'Second')], [_section(SECTION_A, [FIELD_A])])
    )

    assert blocker is not None
    assert FIELD_A in blocker


def test_duplicate_section_identifiers_are_refused() -> None:
    """Section names are the key MDS propagation matches on, so a collision loses rows"""
    blocker = type_structure_blocker(
        _payload([_field(FIELD_A)], [_section(SECTION_A, [FIELD_A]), _section(SECTION_A, [])])
    )

    assert blocker is not None
    assert SECTION_A in blocker


def test_a_summary_naming_an_undeclared_field_is_refused() -> None:
    """The summary line identifies an Object everywhere it is referenced rather than opened

    An unresolvable name is skipped by the renderer, so the entry disappears from the line and the
    Object reads as if it simply had no value there.
    """
    blocker = type_structure_blocker(
        _payload([_field(FIELD_A)], [_section(SECTION_A, [FIELD_A])], summary=['text-old'])
    )

    assert blocker is not None
    assert 'text-old' in blocker


def test_the_message_names_every_unknown_summary_field() -> None:
    """A caller fixing the payload needs the whole list, not the first entry"""
    blocker = type_structure_blocker(
        _payload([_field(FIELD_A)], [_section(SECTION_A, [FIELD_A])], summary=['text-old', FIELD_A, 'date-old'])
    )

    assert 'text-old' in blocker and 'date-old' in blocker
    assert FIELD_A not in blocker


def test_a_summary_naming_one_field_twice_is_refused() -> None:
    """The repeat renders the same value twice, joined by the ' | ' that separates two fields"""
    blocker = type_structure_blocker(
        _payload([_field(FIELD_A), _field(FIELD_B)], [_section(SECTION_A, [FIELD_A, FIELD_B])],
                 summary=[FIELD_A, FIELD_B, FIELD_A])
    )

    assert blocker is not None
    assert FIELD_A in blocker


def test_an_unknown_summary_field_is_reported_before_a_repeated_one() -> None:
    """A name that is not a field at all cannot be judged as a repeat of anything declared"""
    blocker = type_structure_blocker(
        _payload([_field(FIELD_A)], [_section(SECTION_A, [FIELD_A])], summary=[FIELD_A, FIELD_A, 'text-old'])
    )

    assert 'text-old' in blocker


def test_a_broken_section_is_reported_before_the_summary() -> None:
    """The section pairing is the one a caller has to fix first - the summary reads from the result"""
    blocker = type_structure_blocker(
        _payload([_field(FIELD_A)], [_section(SECTION_A, ['text-old'])], summary=['date-old'])
    )

    assert 'text-old' in blocker
    assert 'date-old' not in blocker


def test_duplicate_fields_are_reported_before_the_reference_rule() -> None:
    """The identifier rules come first: an ambiguous name makes the pairing unanswerable"""
    blocker = type_structure_blocker(
        _payload([_field(FIELD_A), _field(FIELD_A)], [_section(SECTION_A, ['text-old'])])
    )

    assert FIELD_A in blocker
    assert 'text-old' not in blocker


# -------------------------------------------------------------------------------------------------------------------- #
#                                        what the rules deliberately allow                                             #
# -------------------------------------------------------------------------------------------------------------------- #
def test_a_consistent_payload_passes() -> None:
    """The ordinary case"""
    assert type_structure_blocker(
        _payload([_field(FIELD_A), _field(FIELD_B)], [_section(SECTION_A, [FIELD_A, FIELD_B])])
    ) is None


def test_a_field_no_section_shows_is_allowed() -> None:
    """A Type under construction has them, and they render nowhere without breaking anything"""
    assert type_structure_blocker(_payload([_field(FIELD_A)], [_section(SECTION_A, [])])) is None


def test_a_section_with_no_fields_is_allowed() -> None:
    """An empty section is a Type being built, not a broken one"""
    assert type_structure_blocker(_payload([], [_section(SECTION_A, [])])) is None


def test_a_ref_sections_selected_fields_are_not_checked() -> None:
    """`reference.selected_fields` name the OTHER Type's fields - checking them here would refuse
    every reference section"""
    ref_field = f'{SECTION_A}-field'
    section = {
        SectionKey.TYPE.value: 'ref-section',
        SectionKey.NAME.value: SECTION_A,
        SectionKey.LABEL.value: 'Reference',
        SectionKey.FIELDS.value: [ref_field],
        SectionKey.REFERENCE.value: {
            'type_id': 1, 'section_name': 'section-other', 'selected_fields': ['text-of-other-type'],
        },
    }

    assert type_structure_blocker(_payload([_field(ref_field)], [section])) is None


def test_a_summary_naming_only_declared_fields_passes() -> None:
    """The ordinary case: every configured name resolves to a field the Type declares"""
    assert type_structure_blocker(
        _payload([_field(FIELD_A), _field(FIELD_B)], [_section(SECTION_A, [FIELD_A, FIELD_B])],
                 summary=[FIELD_A, FIELD_B])
    ) is None


def test_a_summary_naming_each_field_once_passes() -> None:
    """Two different fields in the line are the point of it - only a repeat is refused"""
    assert type_structure_blocker(
        _payload([_field(FIELD_A), _field(FIELD_B)], [_section(SECTION_A, [FIELD_A, FIELD_B])],
                 summary=[FIELD_B, FIELD_A])
    ) is None


def test_a_summary_may_name_a_field_no_section_shows() -> None:
    """Declared is the rule, not rendered - the summary line is composed from `fields`, not sections"""
    assert type_structure_blocker(
        _payload([_field(FIELD_A)], [_section(SECTION_A, [])], summary=[FIELD_A])
    ) is None


@pytest.mark.parametrize('summary', [None, {}, {TypeSchemaKey.FIELDS.value: None}, 'not-a-dict'])
def test_an_absent_or_unusable_summary_is_not_refused(summary: Any) -> None:
    """A Type without a summary line renders the bare `Type label #public_id`, which is legal"""
    payload = {
        TypeSchemaKey.FIELDS.value: [_field(FIELD_A)],
        TypeSchemaKey.RENDER_META.value: {
            TypeSchemaKey.SECTIONS.value: [_section(SECTION_A, [FIELD_A])],
            TypeSchemaKey.SUMMARY.value: summary,
        },
    }

    assert type_structure_blocker(payload) is None


@pytest.mark.parametrize('payload', [
    {},
    {TypeSchemaKey.FIELDS.value: None, TypeSchemaKey.RENDER_META.value: None},
    {TypeSchemaKey.RENDER_META.value: {TypeSchemaKey.SECTIONS.value: None}},
])
def test_an_absent_or_empty_structure_is_not_refused(payload: dict[str, Any]) -> None:
    """The rules judge what is there; other rules own the required keys"""
    assert type_structure_blocker(payload) is None


# -------------------------------------------------------------------------------------------------------------------- #
#                                                 guard_type_structure                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
def test_the_guard_aborts_400_with_the_reason() -> None:
    """The route wrapper hands the reason to the caller rather than a generic refusal"""
    with pytest.raises(HTTPException) as raised:
        guard_type_structure(_payload([_field(FIELD_A)], [_section(SECTION_A, ['text-old'])]))

    assert raised.value.code == 400
    assert 'text-old' in raised.value.description


def test_the_guard_aborts_400_when_only_the_summary_is_broken() -> None:
    """A sound section layout does not excuse a summary line naming a field that is not there"""
    with pytest.raises(HTTPException) as raised:
        guard_type_structure(
            _payload([_field(FIELD_A)], [_section(SECTION_A, [FIELD_A])], summary=['text-old'])
        )

    assert raised.value.code == 400
    assert 'text-old' in raised.value.description


def test_the_guard_passes_a_consistent_payload() -> None:
    """Nothing is raised for a Type that can render itself"""
    guard_type_structure(_payload([_field(FIELD_A)], [_section(SECTION_A, [FIELD_A])], summary=[FIELD_A]))


# -------------------------------------------------------------------------------------------------------------------- #
#                                                   summary_blocker                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
def test_summary_blocker_judges_against_the_names_it_is_given() -> None:
    """It reads the payload's summary but takes the declared names from its caller, which resolved
    them once for every rule"""
    payload = _payload([], [], summary=[FIELD_A, FIELD_B])

    assert summary_blocker(payload, {FIELD_A, FIELD_B}) is None
    assert FIELD_B in summary_blocker(payload, {FIELD_A})


def test_summary_blocker_reports_a_repeat_of_a_declared_name() -> None:
    """The second rule reads the same list, once every name on it is known"""
    payload = _payload([], [], summary=[FIELD_A, FIELD_A])

    assert FIELD_A in summary_blocker(payload, {FIELD_A})
