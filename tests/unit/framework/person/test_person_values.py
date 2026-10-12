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
Unit tests for cmdb.framework.person.person_values

Pure tests. Pinned here is the stored shape of a person field and how a sent value is canonicalised
towards it:

  - the empty values become None (single) or [] (multiple); a lone pair and a one-entry list are
    converted to the field's cardinality; duplicate ids of a list are dropped, keeping the first
  - a selection is exactly {'ref_type', 'id'}; the kind must be one the field's 'person_ref_kind' allows;
    the id must be an int that is not a bool
  - the entries of a person field are found in the top-level fields AND in every multi-data-section row
"""
from typing import Any

import pytest

from cmdb.framework.person.person_values import (
    allowed_ref_types,
    get_person_field_definitions,
    is_public_id,
    iter_person_entries,
    normalize_person_value,
    person_value_errors,
    referenced_ids,
    selections_of,
)
from tests.utils.person_stubs import person_field, selection
# -------------------------------------------------------------------------------------------------------------------- #

PERSON: str = 'PERSON'
GROUP: str = 'PERSON_GROUP'

SINGLE: dict[str, Any] = person_field('owner', ref_kind='BOTH', multiple=False)
MULTIPLE: dict[str, Any] = person_field('team', ref_kind='BOTH', multiple=True)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                      is_public_id                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize('value, expected', [
    (1, True), (0, True), (-3, True),
    (True, False), (False, False), (1.0, False), ('1', False), (None, False), ([1], False),
])
def test_is_public_id(value: Any, expected: bool) -> None:
    """Only an int that is not a bool can name a stored document"""
    assert is_public_id(value) is expected


# -------------------------------------------------------------------------------------------------------------------- #
#                                                   allowed_ref_types                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize('ref_kind, expected', [
    ('PERSON', {PERSON}),
    ('PERSON_GROUP', {GROUP}),
    ('BOTH', {PERSON, GROUP}),
    (None, {PERSON, GROUP}),
    ('', {PERSON, GROUP}),
])
def test_allowed_ref_types(ref_kind: str | None, expected: set[str]) -> None:
    """A field without a kind - a hand-written type - allows both"""
    assert allowed_ref_types(person_field('f', ref_kind=ref_kind)) == frozenset(expected)


# -------------------------------------------------------------------------------------------------------------------- #
#                                             get_person_field_definitions                                             #
# -------------------------------------------------------------------------------------------------------------------- #
def test_get_person_field_definitions_keeps_only_person_fields() -> None:
    """Text fields, nameless fields and non-dicts are skipped"""
    owner = person_field('owner')
    fields: list[Any] = [
        {'type': 'text', 'name': 'name'},
        owner,
        {'type': 'person'},
        {'type': 'person', 'name': 7},
        'not-a-field',
    ]

    assert get_person_field_definitions(fields) == {'owner': owner}


@pytest.mark.parametrize('fields', [None, []])
def test_get_person_field_definitions_of_nothing(fields: Any) -> None:
    """A type without fields has no person field"""
    assert get_person_field_definitions(fields) == {}


# -------------------------------------------------------------------------------------------------------------------- #
#                                                 normalize_person_value                                               #
# -------------------------------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize('empty', [None, '', [], {}])
def test_the_empty_values_become_none_on_a_single_field(empty: Any) -> None:
    """None is the one stored 'nobody' of a single field"""
    assert normalize_person_value(empty, multiple=False) is None


@pytest.mark.parametrize('empty', [None, '', [], {}])
def test_the_empty_values_become_an_empty_list_on_a_multiple_field(empty: Any) -> None:
    """[] is the one stored 'nobody' of a multiple field"""
    assert normalize_person_value(empty, multiple=True) == []


def test_a_lone_pair_sent_to_a_multiple_field_becomes_a_list() -> None:
    """A client sending the single shape to a multiple field is canonicalised, not refused"""
    assert normalize_person_value(selection(PERSON, 4), multiple=True) == [selection(PERSON, 4)]


def test_a_one_entry_list_sent_to_a_single_field_becomes_the_pair() -> None:
    """The other direction"""
    assert normalize_person_value([selection(GROUP, 4)], multiple=False) == selection(GROUP, 4)


def test_a_longer_list_sent_to_a_single_field_is_left_for_the_shape_check() -> None:
    """Two selections cannot be reduced to one, so the value is returned as given"""
    value = [selection(PERSON, 1), selection(PERSON, 2)]

    assert normalize_person_value(value, multiple=False) == value


def test_a_pair_on_a_single_field_is_kept() -> None:
    """The canonical single shape is returned unchanged"""
    assert normalize_person_value(selection(PERSON, 1), multiple=False) == selection(PERSON, 1)


def test_duplicate_ids_are_dropped_keeping_the_first() -> None:
    """Ids are unique across objects, so a second selection of the same id is a duplicate whatever its kind"""
    value = [selection(PERSON, 1), selection(GROUP, 2), selection(GROUP, 1), selection(PERSON, 2), selection(PERSON, 3)]

    assert normalize_person_value(value, multiple=True) == [selection(PERSON, 1), selection(GROUP, 2), selection(PERSON, 3)]


def test_entries_without_a_public_id_are_kept_for_the_shape_check() -> None:
    """A malformed entry is not silently swallowed by the de-duplication"""
    value = [selection(PERSON, 'x'), 'junk', selection(PERSON, 'x')]

    assert normalize_person_value(value, multiple=True) == value


@pytest.mark.parametrize('value', ['someone', 7, 1.5])
def test_an_unrecognised_shape_is_returned_as_given(value: Any) -> None:
    """Neither a pair nor a list: nothing to canonicalise"""
    assert normalize_person_value(value, multiple=True) == value
    assert normalize_person_value(value, multiple=False) == value


# -------------------------------------------------------------------------------------------------------------------- #
#                                                    selections_of                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize('value, expected', [
    (None, []),
    (selection(PERSON, 1), [selection(PERSON, 1)]),
    ([selection(PERSON, 1), selection(GROUP, 2)], [selection(PERSON, 1), selection(GROUP, 2)]),
    ([], []),
])
def test_selections_of(value: Any, expected: list[Any]) -> None:
    """None, a pair or a list - always a list of the pairs"""
    assert selections_of(value) == expected


def test_selections_of_copies_the_list() -> None:
    """The caller may extend the result without touching the stored value"""
    value = [selection(PERSON, 1)]

    selections_of(value).append(selection(PERSON, 2))

    assert value == [selection(PERSON, 1)]


# -------------------------------------------------------------------------------------------------------------------- #
#                                                 person_value_errors                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize('definition, value', [
    (SINGLE, None),
    (SINGLE, selection(PERSON, 1)),
    (SINGLE, selection(GROUP, 1)),
    (MULTIPLE, []),
    (MULTIPLE, [selection(PERSON, 1), selection(GROUP, 2)]),
])
def test_a_valid_value_has_no_error(definition: dict[str, Any], value: Any) -> None:
    """The canonical shapes of both cardinalities"""
    assert person_value_errors(definition['name'], value, definition) == []


def test_a_multiple_field_needs_a_list() -> None:
    """A canonical multiple value is always a list"""
    errors = person_value_errors('team', 'someone', MULTIPLE)

    assert errors == ["The person field 'team' expects a list of selections"]


def test_a_single_field_needs_one_selection() -> None:
    """Two selections in a single field cannot be reduced and are refused"""
    errors = person_value_errors('owner', [selection(PERSON, 1), selection(PERSON, 2)], SINGLE)

    assert errors == ["The person field 'owner' expects a single selection"]


@pytest.mark.parametrize('bad_selection', [
    {'ref_type': PERSON},
    {'id': 1},
    {'ref_type': PERSON, 'id': 1, 'label': 'Ada'},
    'PERSON:1',
    7,
])
def test_a_selection_must_be_exactly_the_pair(bad_selection: Any) -> None:
    """A missing key, an extra key or a non-dict is refused - extra keys would be persisted otherwise"""
    errors = person_value_errors('team', [bad_selection], MULTIPLE)

    assert len(errors) == 1
    assert "must be an object with exactly 'ref_type' and 'id'" in errors[0]


@pytest.mark.parametrize('ref_kind, refused', [('PERSON', GROUP), ('PERSON_GROUP', PERSON)])
def test_a_kind_the_field_does_not_allow_is_refused(ref_kind: str, refused: str) -> None:
    """'person_ref_kind' restricts what the field may select"""
    definition = person_field('owner', ref_kind=ref_kind)

    errors = person_value_errors('owner', selection(refused, 1), definition)

    assert errors == [f"The person field 'owner' does not allow '{refused}' (allowed: ['{ref_kind}'])"]


def test_an_unknown_ref_type_is_refused() -> None:
    """A token that is no person SpecialType is never allowed"""
    errors = person_value_errors('owner', selection('RACK', 1), SINGLE)

    assert len(errors) == 1
    assert "does not allow 'RACK'" in errors[0]


@pytest.mark.parametrize('bad_id', ['1', True, 1.0, None])
def test_an_id_that_is_no_public_id_is_refused(bad_id: Any) -> None:
    """Strings, bools, floats and None never reach the existence lookup"""
    errors = person_value_errors('owner', selection(PERSON, bad_id), SINGLE)

    assert errors == ["The person field 'owner' holds an id that is not a public_id"]


def test_every_bad_selection_is_reported() -> None:
    """One message per problem, so the user sees all of them at once"""
    definition = person_field('team', ref_kind='PERSON', multiple=True)

    errors = person_value_errors('team', [selection(GROUP, 1), selection(PERSON, 'x'), 'junk'], definition)

    assert len(errors) == 3


# -------------------------------------------------------------------------------------------------------------------- #
#                                                    referenced_ids                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
def test_referenced_ids_of_a_list() -> None:
    """Every valid selection, in order, as (ref_type, id)"""
    value = [selection(PERSON, 1), selection(GROUP, 2)]

    assert referenced_ids(value) == [(PERSON, 1), (GROUP, 2)]


def test_referenced_ids_of_a_pair_and_of_none() -> None:
    """A single selection and the empty value"""
    assert referenced_ids(selection(GROUP, 9)) == [(GROUP, 9)]
    assert referenced_ids(None) == []


def test_referenced_ids_skips_what_names_no_document() -> None:
    """Junk entries and non-int ids reference nothing"""
    value = [selection(PERSON, 'x'), 'junk', selection(PERSON, True), selection(PERSON, 3)]

    assert referenced_ids(value) == [(PERSON, 3)]


# -------------------------------------------------------------------------------------------------------------------- #
#                                                 iter_person_entries                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
def test_iter_person_entries_covers_fields_and_every_mds_row() -> None:
    """A person field inside a multi-data-section is judged like any other"""
    top = {'name': 'owner', 'value': selection(PERSON, 1)}
    row_one = {'name': 'owner', 'value': selection(PERSON, 2)}
    row_two = {'name': 'owner', 'value': None}
    document: dict[str, Any] = {
        'fields': [{'name': 'hostname', 'value': 'srv'}, top],
        'multi_data_sections': [
            {'section_id': 'mds', 'values': [
                {'multi_data_id': 0, 'data': [row_one, {'name': 'note', 'value': 'x'}]},
                {'multi_data_id': 1, 'data': [row_two]},
            ]},
        ],
    }

    found = list(iter_person_entries(document, {'owner': SINGLE}))

    assert [entry for entry, _ in found] == [top, row_one, row_two]
    assert all(definition is SINGLE for _, definition in found)


def test_iter_person_entries_yields_the_stored_dict_for_in_place_edits() -> None:
    """The enforcement canonicalises through the yielded entry, so it must be the document's own dict"""
    entry = {'name': 'owner', 'value': [selection(PERSON, 1)]}
    document = {'fields': [entry]}

    for found, _ in iter_person_entries(document, {'owner': SINGLE}):
        found['value'] = 'changed'

    assert document['fields'][0]['value'] == 'changed'


def test_iter_person_entries_tolerates_malformed_documents() -> None:
    """Missing keys, None and non-dict sections, rows and entries are skipped"""
    document: dict[str, Any] = {
        'fields': None,
        'multi_data_sections': [None, 'junk', {'values': None}, {'values': ['junk', {'data': None}, {'data': ['junk']}]}],
    }

    assert not list(iter_person_entries(document, {'owner': SINGLE}))
    assert not list(iter_person_entries({}, {'owner': SINGLE}))


def test_iter_person_entries_ignores_fields_that_are_no_person_field() -> None:
    """Only the given definitions count, even for a field holding a pair"""
    document = {'fields': [{'name': 'other', 'value': selection(PERSON, 1)}]}

    assert not list(iter_person_entries(document, {'owner': SINGLE}))
