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
Unit tests for cmdb.framework.person_selector.selector_values

Pure tests. Pinned: which definitions are selectors; every selector entry of an object, flat and per multi-data row,
with its place; the ids a value names; the canonical empty forms, the dropped render key and the shape refusals
(each selector named once); the stored values by place
"""
from typing import Any

import pytest

from cmdb.framework.person_selector.person_selector_constants import (
    PERSON_SELECTOR_CELL_ERROR,
    PersonSelectorWriteError,
)
from cmdb.framework.person_selector.selector_values import (
    SelectorPlace,
    canonicalize_and_check_shapes,
    ids_of,
    parse_selector_value,
    selector_entries,
    selector_fields,
    stored_values_by_place,
)
# -------------------------------------------------------------------------------------------------------------------- #

ONE: str = 'owner'
SEVERAL: str = 'members'
SELECTORS: dict[str, dict[str, Any]] = {
    ONE: {'type': 'person', 'name': ONE, 'selectable': ['PERSON'], 'multiple': False},
    SEVERAL: {'type': 'person', 'name': SEVERAL, 'selectable': ['PERSON'], 'multiple': True},
}
SECTION: str = 'contacts'


def _object(one: Any = None, several: Any = None, rows: list[Any] | None = None) -> dict[str, Any]:
    """An object holding both selectors flat, and the multiple one in each row"""
    return {
        'fields': [{'name': ONE, 'value': one}, {'name': SEVERAL, 'value': several}, {'name': 'note', 'value': 'x'}],
        'multi_data_sections': [{'section_id': SECTION, 'values': [
            {'multi_data_id': index, 'data': [{'name': SEVERAL, 'value': row}]} for index, row in enumerate(rows or [])
        ]}],
    }


def test_selector_fields_keeps_only_person_selectors() -> None:
    """By name"""
    fields = [*SELECTORS.values(), {'type': 'text', 'name': 'note'}]

    assert selector_fields(fields) == SELECTORS
    assert not selector_fields(None)


def test_selector_entries_flat_and_per_row() -> None:
    """Each with its place; other fields are not entries"""
    places = [place for place, _ in selector_entries(_object(1, [2], rows=[[3], []]), SELECTORS)]

    assert places == [
        SelectorPlace(None, None, ONE), SelectorPlace(None, None, SEVERAL),
        SelectorPlace(SECTION, 0, SEVERAL), SelectorPlace(SECTION, 1, SEVERAL),
    ]


def test_selector_entries_are_the_objects_own_dicts() -> None:
    """A caller may change them in place"""
    document = _object(1)
    (_, entry), *_ = selector_entries(document, SELECTORS)
    entry['value'] = 9

    assert document['fields'][0]['value'] == 9


@pytest.mark.parametrize('document', [None, {}, {'fields': 'junk', 'multi_data_sections': ['junk', {'values': 'x'}]}],
                         ids=['none', 'empty', 'junk'])
def test_selector_entries_tolerates_a_broken_document(document: Any) -> None:
    """No entry, no error"""
    assert not selector_entries(document, SELECTORS)


@pytest.mark.parametrize('value, expected', [
    (7, [7]), ([7, 8], [7, 8]), (None, []), ([], []), (True, []), ('7', []), ([7, 'x', False], [7]),
], ids=['id', 'ids', 'none', 'empty', 'bool', 'text', 'mixed'])
def test_ids_of(value: Any, expected: list[int]) -> None:
    """Whole numbers only, in order"""
    assert ids_of(value) == expected


@pytest.mark.parametrize('one, several, expected_one, expected_several', [
    ('', None, None, []), (None, '', None, []), (5, [5, 6], 5, [5, 6]),
], ids=['empty-text-one', 'empty-text-several', 'values'])
def test_the_empty_forms_are_canonical(one: Any, several: Any, expected_one: Any, expected_several: Any) -> None:
    """None for one, [] for several"""
    document = _object(one, several)

    assert canonicalize_and_check_shapes(selector_entries(document, SELECTORS), SELECTORS) == []
    assert (document['fields'][0]['value'], document['fields'][1]['value']) == (expected_one, expected_several)


def test_the_render_expansion_is_dropped() -> None:
    """A client may send it back; it is never stored"""
    document = _object(5)
    document['fields'][0]['persons'] = [{'object_id': 5}]

    canonicalize_and_check_shapes(selector_entries(document, SELECTORS), SELECTORS)

    assert 'persons' not in document['fields'][0]


@pytest.mark.parametrize('one', [[5], 'five', True, 5.5], ids=['list', 'text', 'bool', 'fraction'])
def test_a_wrong_single_shape_is_refused(one: Any) -> None:
    """One id or nothing"""
    assert canonicalize_and_check_shapes(selector_entries(_object(one, []), SELECTORS), SELECTORS) == [
        PersonSelectorWriteError.SHAPE_SINGLE.format(name=ONE),
    ]


@pytest.mark.parametrize('several', [5, [5, 5], [5, 'x'], [True]], ids=['id', 'repeated', 'text-item', 'bool-item'])
def test_a_wrong_multiple_shape_is_refused(several: Any) -> None:
    """A list of ids, each once"""
    assert canonicalize_and_check_shapes(selector_entries(_object(None, several), SELECTORS), SELECTORS) == [
        PersonSelectorWriteError.SHAPE_MULTIPLE.format(name=SEVERAL),
    ]


def test_a_selector_wrong_in_several_places_is_named_once() -> None:
    """Flat and in a row"""
    document = _object(None, 5, rows=['x'])

    assert canonicalize_and_check_shapes(selector_entries(document, SELECTORS), SELECTORS) == [
        PersonSelectorWriteError.SHAPE_MULTIPLE.format(name=SEVERAL),
    ]


def test_stored_values_by_place() -> None:
    """Empty on a create"""
    assert stored_values_by_place(_object(1, [2], rows=[[3]]), SELECTORS) == {
        SelectorPlace(None, None, ONE): 1,
        SelectorPlace(None, None, SEVERAL): [2],
        SelectorPlace(SECTION, 0, SEVERAL): [3],
    }
    assert not stored_values_by_place(None, SELECTORS)


@pytest.mark.parametrize('value, multiple, expected', [
    ('12', False, 12), (12, False, 12), (12.0, False, 12), ('12, 15', True, [12, 15]), ([12, 15], True, [12, 15]),
    ('12,', True, [12]), (12, True, [12]),
], ids=['cell', 'id', 'spreadsheet-float', 'cell-list', 'native-list', 'trailing-separator', 'one-into-several'])
def test_parse_selector_value(value: Any, multiple: bool, expected: Any) -> None:
    """One id, or ids separated by the cell separator"""
    assert parse_selector_value(value, multiple) == (expected, None)


@pytest.mark.parametrize('value, multiple', [('12,15', False), ('x', True), ('12,x', True), (True, False),
                                             ([12, 15], False), (',', True)],
                         ids=['several-into-one', 'text', 'text-item', 'bool', 'list-into-one', 'only-separators'])
def test_parse_selector_value_refuses(value: Any, multiple: bool) -> None:
    """The value is left as it is, with the reason"""
    assert parse_selector_value(value, multiple) == (value, PERSON_SELECTOR_CELL_ERROR.format(value=value))
