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
Unit tests for cmdb.framework.object_section_structure: the structure rule every object write shares

Pure tests on dict payloads. Pinned per rule: the reason and its wording (from the constants), the row id bounds (0
is an id, a bool and -1 are none), a section repeat versus an unknown section, a reason per row versus one per
section, the cap of the 400, the row-id counter (sent, rows, stored - the largest wins; never below a row id) and the
next PATCH row id. The module's public function set is pinned
"""
import inspect
from http import HTTPStatus
from typing import Any
from unittest.mock import MagicMock

import pytest
from werkzeug.exceptions import HTTPException

from cmdb.framework import object_section_structure
from cmdb.framework.object_section_structure import (
    align_highest_ids,
    aligned_highest_id,
    declared_sections_of,
    describe_reasons,
    field_name_reasons,
    guard_object_structure,
    is_row_id,
    next_row_id,
    object_structure_reasons,
    row_reasons,
    rows_reasons,
    section_reasons,
    stored_highest_ids,
)
from cmdb.framework.object_section_structure_constants import (
    ENTRY_INVALID,
    FIELDS_REPEATED,
    HIGHEST_ID_INVALID,
    MAX_LISTED_REASONS,
    MIN_ROW_ID,
    MORE_REASONS_PART,
    OBJECT_STRUCTURE_INVALID_MSG,
    REASON_SEPARATOR,
    ROW_DATA_NOT_A_LIST,
    ROW_FIELDS_REPEATED,
    ROW_FIELDS_UNDECLARED,
    ROW_ID_INVALID,
    ROW_IDS_REPEATED,
    ROW_NOT_AN_OBJECT,
    SECTION_NOT_AN_OBJECT,
    SECTION_REPEATED,
    SECTION_UNDECLARED,
    SECTION_WITHOUT_ID,
    SECTIONS_NOT_A_LIST,
    VALUES_NOT_A_LIST,
)
from cmdb.models.type_model.section_type_enum import SectionType
# -------------------------------------------------------------------------------------------------------------------- #

NICS: str = 'nics'
DISKS: str = 'disks'
NIC: str = 'nic'
MAC: str = 'mac'
SIZE: str = 'size'
HOST: str = 'host'
DECLARED: dict[str, set[str]] = {NICS: {NIC, MAC}, DISKS: {SIZE}}


def _row(row_id: Any, *names: str) -> dict[str, Any]:
    """One row naming the given fields"""
    return {'multi_data_id': row_id, 'data': [{'name': name, 'value': 'v'} for name in names]}


def _section(section_id: Any, *rows: Any, highest_id: Any = None) -> dict[str, Any]:
    """One section holding the given rows"""
    section: dict[str, Any] = {'section_id': section_id, 'values': list(rows)}

    if highest_id is not None:
        section['highest_id'] = highest_id

    return section


def _object(*sections: Any, fields: Any = None) -> dict[str, Any]:
    """An object holding the given sections"""
    return {'fields': fields if fields is not None else [{'name': HOST, 'value': 'h'}],
            'multi_data_sections': list(sections)}


class TestRowIds:
    """is_row_id"""

    @pytest.mark.parametrize('value, expected', [
        (MIN_ROW_ID, True), (1, True), (MIN_ROW_ID - 1, False), (True, False), (False, False), ('1', False),
        (None, False), (1.0, False),
    ])
    def test_a_whole_number_from_zero(self, value: Any, expected: bool) -> None:
        """0 is an id (stored rows hold it); a bool is none"""
        assert is_row_id(value) is expected


class TestFieldNames:
    """field_name_reasons"""

    def test_a_repeated_top_level_name_is_one_reason(self) -> None:
        """Each repeated name once, in order"""
        fields = [{'name': 'b'}, {'name': 'a'}, {'name': 'b'}, {'name': 'a'}, {'name': 'b'}]

        assert field_name_reasons(fields) == [FIELDS_REPEATED.format(names=['b', 'a'])]

    @pytest.mark.parametrize('fields', [[{'name': 'a'}, {'name': 'b'}], None, 'x', [{'name': ['a']}, 'x']])
    def test_unique_or_unreadable_fields_are_the_field_checks_concern(self, fields: Any) -> None:
        """Nothing here"""
        assert not field_name_reasons(fields)


class TestRow:
    """row_reasons"""

    def test_a_row_in_line(self) -> None:
        """Declared names, once, an id"""
        assert not row_reasons(NICS, 0, _row(1, NIC, MAC), DECLARED[NICS])

    def test_a_row_that_is_no_object(self) -> None:
        """Nothing else is read"""
        assert row_reasons(NICS, 3, 'x', DECLARED[NICS]) == [ROW_NOT_AN_OBJECT.format(section_id=NICS, position=3)]

    @pytest.mark.parametrize('row_id', [None, -1, True, '1'])
    def test_a_row_without_an_id(self, row_id: Any) -> None:
        """Absent or no whole number from 0"""
        row: dict[str, Any] = _row(row_id, NIC)

        if row_id is None:
            row.pop('multi_data_id')

        assert row_reasons(NICS, 2, row, DECLARED[NICS]) == [
            ROW_ID_INVALID.format(section_id=NICS, position=2, minimum=MIN_ROW_ID),
        ]

    def test_data_that_is_no_list(self) -> None:
        """Named; the entries are not read"""
        assert row_reasons(NICS, 0, {'multi_data_id': 1, 'data': 'x'}, DECLARED[NICS]) == [
            ROW_DATA_NOT_A_LIST.format(section_id=NICS, position=0),
        ]

    @pytest.mark.parametrize('entry', ['x', {'value': 1}, {'name': 5}])
    def test_an_entry_without_a_string_name(self, entry: Any) -> None:
        """The names are not judged further"""
        assert row_reasons(NICS, 0, {'multi_data_id': 1, 'data': [entry]}, DECLARED[NICS]) == [
            ENTRY_INVALID.format(section_id=NICS, position=0),
        ]

    def test_a_field_the_section_does_not_declare(self) -> None:
        """Another section's field and a top-level one, sorted"""
        assert row_reasons(NICS, 1, _row(1, NIC, SIZE, HOST), DECLARED[NICS]) == [
            ROW_FIELDS_UNDECLARED.format(section_id=NICS, position=1, names=[HOST, SIZE]),
        ]

    def test_no_declaration_judges_no_field(self) -> None:
        """The importer without its type"""
        assert not row_reasons(NICS, 1, _row(1, HOST), None)

    def test_a_name_twice_in_one_row(self) -> None:
        """Names repeating across rows are the rule, not a break"""
        assert row_reasons(NICS, 0, _row(1, NIC, NIC), DECLARED[NICS]) == [
            ROW_FIELDS_REPEATED.format(section_id=NICS, position=0, names=[NIC]),
        ]

    def test_every_break_of_one_row_is_named(self) -> None:
        """Id, foreign field and repeat together"""
        assert row_reasons(NICS, 0, _row(None, NIC, NIC, SIZE), DECLARED[NICS]) == [
            ROW_ID_INVALID.format(section_id=NICS, position=0, minimum=MIN_ROW_ID),
            ROW_FIELDS_UNDECLARED.format(section_id=NICS, position=0, names=[SIZE]),
            ROW_FIELDS_REPEATED.format(section_id=NICS, position=0, names=[NIC]),
        ]


class TestRows:
    """rows_reasons"""

    def test_an_id_two_rows_share_is_one_reason_for_the_section(self) -> None:
        """After the rows' own reasons; 0 counts like any id"""
        rows = [_row(0, NIC), _row(0, NIC), _row(2, NIC), _row(2, NIC), 'x']

        assert rows_reasons(NICS, rows, DECLARED[NICS]) == [
            ROW_NOT_AN_OBJECT.format(section_id=NICS, position=4),
            ROW_IDS_REPEATED.format(section_id=NICS, row_ids=[0, 2]),
        ]

    def test_distinct_ids_pass(self) -> None:
        """Gaps are fine"""
        assert not rows_reasons(NICS, [_row(0, NIC), _row(7, NIC)], DECLARED[NICS])


class TestSection:
    """section_reasons"""

    def test_a_section_in_line_is_remembered(self) -> None:
        """Its id joins the seen ones"""
        seen: set[str] = set()

        assert not section_reasons(0, _section(NICS, _row(1, NIC), highest_id=1), DECLARED, seen)
        assert seen == {NICS}

    @pytest.mark.parametrize('section, expected', [
        ('x', SECTION_NOT_AN_OBJECT.format(position=1)),
        ({'values': []}, SECTION_WITHOUT_ID.format(position=1)),
        ({'section_id': '', 'values': []}, SECTION_WITHOUT_ID.format(position=1)),
        ({'section_id': 5, 'values': []}, SECTION_WITHOUT_ID.format(position=1)),
        (_section('ghosts', _row(1, NIC)), SECTION_UNDECLARED.format(section_id='ghosts')),
        ({'section_id': NICS, 'values': 'x'}, VALUES_NOT_A_LIST.format(section_id=NICS)),
        (_section(NICS, highest_id=-1), HIGHEST_ID_INVALID.format(section_id=NICS, minimum=MIN_ROW_ID)),
        (_section(NICS, highest_id=True), HIGHEST_ID_INVALID.format(section_id=NICS, minimum=MIN_ROW_ID)),
    ], ids=['no-object', 'no-id', 'empty-id', 'int-id', 'undeclared', 'values-no-list', 'highest-negative',
            'highest-bool'])
    def test_one_break(self, section: Any, expected: str) -> None:
        """Each named by the section's id once it has one, by its position before"""
        assert section_reasons(1, section, DECLARED, set()) == [expected]

    def test_a_repeat_is_the_repeat_even_of_an_unknown_section(self) -> None:
        """Not a second 'unknown'"""
        seen: set[str] = {'ghosts', NICS}

        assert section_reasons(2, _section('ghosts'), DECLARED, seen) == [SECTION_REPEATED.format(section_id='ghosts')]
        assert section_reasons(3, _section(NICS, _row(1, NIC)), DECLARED, seen) == [
            SECTION_REPEATED.format(section_id=NICS),
        ]

    def test_no_declaration_judges_no_section(self) -> None:
        """The importer without its type"""
        assert not section_reasons(0, _section('ghosts', _row(1, HOST)), None, set())

    def test_a_missing_values_list_is_an_empty_section(self) -> None:
        """Nothing to judge"""
        assert not section_reasons(0, {'section_id': NICS}, DECLARED, set())


class TestObject:
    """object_structure_reasons and describe_reasons"""

    def test_an_object_in_line(self) -> None:
        """Both sections, rows identified"""
        assert not object_structure_reasons(_object(_section(NICS, _row(0, NIC)), _section(DISKS, _row(1, SIZE))),
                                            DECLARED)

    def test_an_object_without_sections(self) -> None:
        """Only the field names are judged"""
        assert not object_structure_reasons({'fields': []}, DECLARED)
        assert not object_structure_reasons({'fields': [], 'multi_data_sections': None}, DECLARED)

    def test_sections_that_are_no_list(self) -> None:
        """One reason"""
        assert object_structure_reasons({'multi_data_sections': 'x'}, DECLARED) == [SECTIONS_NOT_A_LIST]

    def test_every_reason_in_document_order(self) -> None:
        """Field names first, then section by section"""
        data: dict[str, Any] = _object(
            _section(NICS, _row(1, NIC)), _section(NICS, _row(1, NIC)), _section('ghosts'),
            fields=[{'name': HOST}, {'name': HOST}],
        )

        assert object_structure_reasons(data, DECLARED) == [
            FIELDS_REPEATED.format(names=[HOST]), SECTION_REPEATED.format(section_id=NICS),
            SECTION_UNDECLARED.format(section_id='ghosts'),
        ]

    def test_the_description_is_capped(self) -> None:
        """The first MAX_LISTED_REASONS, then the count"""
        reasons: list[str] = [f'r{index}' for index in range(MAX_LISTED_REASONS + 3)]

        assert describe_reasons(reasons) == MORE_REASONS_PART.format(
            listed=REASON_SEPARATOR.join(reasons[:MAX_LISTED_REASONS]), more=3,
        )
        assert describe_reasons(reasons[:MAX_LISTED_REASONS]) == REASON_SEPARATOR.join(reasons[:MAX_LISTED_REASONS])


class TestCounter:
    """stored_highest_ids, aligned_highest_id, align_highest_ids, next_row_id"""

    def test_the_stored_counters(self) -> None:
        """Only readable ones"""
        stored = [_section(NICS, highest_id=4), _section(DISKS, highest_id=True), 'x', {'highest_id': 3}]

        assert stored_highest_ids(stored) == {NICS: 4}
        assert stored_highest_ids(None) == {}

    @pytest.mark.parametrize('sent, rows, stored, expected', [
        (None, [], None, MIN_ROW_ID),
        (2, [1, 5], None, 5),
        (9, [1], None, 9),
        (1, [1, 2], 7, 7),
        (None, [0], None, 0),
    ], ids=['nothing', 'row-above-sent', 'sent-above-rows', 'stored-above-both', 'only-row-zero'])
    def test_the_largest_wins(self, sent: Any, rows: list[int], stored: int | None, expected: int) -> None:
        """Never below a row id, never back below the stored counter"""
        section: dict[str, Any] = _section(NICS, *[_row(row_id, NIC) for row_id in rows], highest_id=sent)

        assert aligned_highest_id(section, stored) == expected

    def test_every_section_is_aligned_in_place(self) -> None:
        """Against its own stored counter"""
        data: dict[str, Any] = _object(_section(NICS, _row(3, NIC), highest_id=1), _section(DISKS, _row(1, SIZE)))

        align_highest_ids(data, [_section(DISKS, highest_id=6)])

        assert [section['highest_id'] for section in data['multi_data_sections']] == [3, 6]

    @pytest.mark.parametrize('section, expected', [
        (_section(NICS, _row(1, NIC), _row(2, NIC), highest_id=1), 3),
        (_section(NICS, _row(0, NIC), _row(1, NIC), highest_id=0), 2),
        (_section(NICS, highest_id=4), 5),
        ({'section_id': NICS}, MIN_ROW_ID + 1),
        (_section(NICS, 'x', _row(True, NIC)), MIN_ROW_ID + 1),
    ], ids=['stale-counter', 'row-zero', 'counter-only', 'empty', 'unreadable-rows'])
    def test_the_next_row_id_goes_above_every_id(self, section: dict[str, Any], expected: int) -> None:
        """A stale counter never hands out an id a row holds"""
        assert next_row_id(section) == expected


class TestGuard:
    """guard_object_structure and declared_sections_of"""

    def test_a_break_is_one_400_naming_every_reason(self) -> None:
        """Nothing is aligned"""
        data: dict[str, Any] = _object(_section(NICS, _row(1, NIC), _row(1, NIC), highest_id=0), _section('ghosts'))

        with pytest.raises(HTTPException) as raised:
            guard_object_structure(data, DECLARED, None)

        assert (raised.value.code, raised.value.description) == (
            HTTPStatus.BAD_REQUEST, OBJECT_STRUCTURE_INVALID_MSG.format(reasons=REASON_SEPARATOR.join([
                ROW_IDS_REPEATED.format(section_id=NICS, row_ids=[1]), SECTION_UNDECLARED.format(section_id='ghosts'),
            ])),
        )
        assert data['multi_data_sections'][0]['highest_id'] == 0

    def test_an_object_in_line_is_aligned(self) -> None:
        """Against the stored counter"""
        data: dict[str, Any] = _object(_section(NICS, _row(2, NIC), highest_id=1))

        guard_object_structure(data, DECLARED, [_section(NICS, highest_id=5)])

        assert data['multi_data_sections'][0]['highest_id'] == 5

    def test_the_declared_sections_of_a_type(self) -> None:
        """Each multi-data section with its fields; other sections are not"""
        a_type = MagicMock()
        a_type.get_sections.return_value = [
            MagicMock(type=SectionType.MDS_SECTION.value, get_fields=MagicMock(return_value=[NIC, MAC])),
            MagicMock(type=SectionType.SECTION.value, get_fields=MagicMock(return_value=[HOST])),
        ]
        a_type.get_sections.return_value[0].name = NICS
        a_type.get_sections.return_value[1].name = 'main'

        assert declared_sections_of(a_type) == {NICS: {NIC, MAC}}


def test_the_module_function_set_is_pinned() -> None:
    """A new public function is a deliberate change"""
    functions: set[str] = {
        name for name, member in inspect.getmembers(object_section_structure, inspect.isfunction)
        if member.__module__ == object_section_structure.__name__
    }

    assert functions == {
        'align_highest_ids', 'aligned_highest_id', 'declared_sections_of', 'describe_reasons', 'field_name_reasons',
        'guard_object_structure', 'is_row_id', 'next_row_id', 'object_structure_reasons', 'row_reasons',
        'rows_reasons', 'section_reasons', 'stored_highest_ids',
    }
