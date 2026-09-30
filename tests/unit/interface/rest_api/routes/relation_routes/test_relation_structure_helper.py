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
Unit tests for the CmdbRelation structure rules

Pure: no Mongo, no Flask app. A relation declares every field once in its flat ``fields`` list; its
sections carry only the NAMES. What is pinned here is the pairing, the two identifier-uniqueness
rules, and the shapes that are deliberately NOT refused.

The stakes differ from the CmdbType version of the same rules: a relation's sections are read by
``get_added_and_removed_fields``, whose result is written onto every dependent CmdbObjectRelation - so
a section naming a field the relation does not declare is propagated rather than merely unrendered.
"""
from typing import Any

import pytest
from werkzeug.exceptions import HTTPException

from cmdb.models.relation_model.relation_constants import RelationKey
from cmdb.models.type_model.field_key_enum import FieldKey
from cmdb.models.type_model.field_type_enum import FieldType
from cmdb.models.type_model.section_key_enum import SectionKey
from cmdb.models.type_model.section_type_enum import SectionType
from cmdb.interface.rest_api.routes.relation_routes.relation_structure_helper import (
    duplicated_names,
    guard_relation_structure,
    relation_structure_blocker,
)
# -------------------------------------------------------------------------------------------------------------------- #

HTTP_BAD_REQUEST: int = 400

FIELD_A: str = 'text-a'
FIELD_B: str = 'text-b'
SECTION_A: str = 'section-a'


def _field(name: str, label: str = 'Label') -> dict[str, Any]:
    """The minimal field definition the rules read."""
    return {
        FieldKey.TYPE.value: FieldType.TEXT.value,
        FieldKey.NAME.value: name,
        FieldKey.LABEL.value: label,
    }


def _section(name: str, fields: list[str]) -> dict[str, Any]:
    """A section referencing the given field names."""
    return {
        SectionKey.TYPE.value: SectionType.SECTION.value,
        SectionKey.NAME.value: name,
        SectionKey.LABEL.value: 'Section',
        SectionKey.FIELDS.value: fields,
    }


def _payload(fields: list[dict[str, Any]], sections: list[dict[str, Any]]) -> dict[str, Any]:
    """The part of a CmdbRelation payload the rules look at."""
    return {
        RelationKey.FIELDS.value: fields,
        RelationKey.SECTIONS.value: sections,
    }


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  duplicated_names                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize('names, expected', [
    ([], []),
    (['a', 'b'], []),
    (['a', 'a'], ['a']),
    (['a', 'b', 'a', 'b', 'a'], ['a', 'b']),
])
def test_duplicated_reports_each_repeat_once(names: list[str], expected: list[str]) -> None:
    """A repeated name is reported once, in the order it was first repeated"""
    assert duplicated_names(names) == expected


# -------------------------------------------------------------------------------------------------------------------- #
#                                                what the rules refuse                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
def test_a_section_naming_an_undeclared_field_is_refused() -> None:
    """The name reaches the update diff and is written onto every dependent CmdbObjectRelation"""
    blocker = relation_structure_blocker(_payload([_field(FIELD_A)], [_section(SECTION_A, ['nope'])]))

    assert blocker is not None
    assert 'nope' in blocker
    assert SECTION_A in blocker


def test_the_message_names_every_unknown_field_of_the_section() -> None:
    """A caller fixing the payload needs the whole list, not the first entry"""
    blocker = relation_structure_blocker(
        _payload([_field(FIELD_A)], [_section(SECTION_A, ['nope', FIELD_A, 'also-gone'])])
    )

    assert 'nope' in blocker and 'also-gone' in blocker


def test_duplicate_field_identifiers_are_refused() -> None:
    """A field's name is its identity - an ObjectRelation keys its stored values by the name alone"""
    blocker = relation_structure_blocker(
        _payload([_field(FIELD_A, 'First'), _field(FIELD_A, 'Second')], [_section(SECTION_A, [FIELD_A])])
    )

    assert blocker is not None
    assert FIELD_A in blocker


def test_duplicate_section_identifiers_are_refused() -> None:
    """The name is how a section is addressed"""
    blocker = relation_structure_blocker(
        _payload([_field(FIELD_A)], [_section(SECTION_A, [FIELD_A]), _section(SECTION_A, [])])
    )

    assert blocker is not None
    assert SECTION_A in blocker


def test_duplicate_fields_are_reported_before_the_reference_rule() -> None:
    """The identifier rules come first: an ambiguous name makes the pairing unanswerable"""
    blocker = relation_structure_blocker(
        _payload([_field(FIELD_A), _field(FIELD_A)], [_section(SECTION_A, ['nope'])])
    )

    assert FIELD_A in blocker
    assert 'nope' not in blocker


# -------------------------------------------------------------------------------------------------------------------- #
#                                           what the rules deliberately allow                                          #
# -------------------------------------------------------------------------------------------------------------------- #
def test_a_consistent_payload_passes() -> None:
    """The ordinary case"""
    assert relation_structure_blocker(
        _payload([_field(FIELD_A), _field(FIELD_B)], [_section(SECTION_A, [FIELD_A, FIELD_B])])
    ) is None


def test_a_field_no_section_shows_is_allowed() -> None:
    """A relation under construction has them, and they render nowhere without breaking anything"""
    assert relation_structure_blocker(_payload([_field(FIELD_A)], [_section(SECTION_A, [])])) is None


def test_a_section_with_no_fields_is_allowed() -> None:
    """An empty section is a relation being built, not a broken one"""
    assert relation_structure_blocker(_payload([], [_section(SECTION_A, [])])) is None


@pytest.mark.parametrize('payload', [
    {},
    {RelationKey.FIELDS.value: None, RelationKey.SECTIONS.value: None},
    {RelationKey.SECTIONS.value: []},
])
def test_an_absent_or_empty_structure_is_not_refused(payload: dict[str, Any]) -> None:
    """The rules judge what is there; the schema owns the required keys"""
    assert relation_structure_blocker(payload) is None


# -------------------------------------------------------------------------------------------------------------------- #
#                                              guard_relation_structure                                                #
# -------------------------------------------------------------------------------------------------------------------- #
def test_the_guard_aborts_400_with_the_reason() -> None:
    """The route wrapper hands the reason to the caller rather than a generic refusal"""
    with pytest.raises(HTTPException) as raised:
        guard_relation_structure(_payload([_field(FIELD_A)], [_section(SECTION_A, ['nope'])]))

    assert raised.value.code == HTTP_BAD_REQUEST
    assert 'nope' in raised.value.description


def test_the_guard_passes_a_consistent_payload() -> None:
    """Nothing is raised for a relation that can render itself"""
    guard_relation_structure(_payload([_field(FIELD_A)], [_section(SECTION_A, [FIELD_A])]))
