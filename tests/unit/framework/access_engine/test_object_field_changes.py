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
Unit tests for cmdb.framework.access_engine.object_field_changes

Only changed fields count: equal values and two empty ones (None, '', []) are no change, 0 and False are values; a
field added or removed with a value is changed, with an empty value it is not; a multi-data-section field changes with
any row's value - a row added or removed with a value too; unreadable entries are passed over
"""
from typing import Any

import pytest

from cmdb.framework.access_engine import TOP_LEVEL, changed_field_names, field_values, same_value
# -------------------------------------------------------------------------------------------------------------------- #

SECTION: str = 'ports'
ROW: int = 1
OTHER_ROW: int = 2


def _field(name: str, value: Any) -> dict[str, Any]:
    """A stored field entry"""
    return {'name': name, 'value': value, 'type': 'text'}


def _object(fields: list[dict[str, Any]] | None = None, rows: dict[int, list[dict[str, Any]]] | None = None
            ) -> dict[str, Any]:
    """An object with top-level fields and one multi-data-section's rows"""
    sections: list[dict[str, Any]] = []

    if rows is not None:
        sections.append({'section_id': SECTION, 'highest_id': max(rows, default=0),
                         'values': [{'multi_data_id': row_id, 'data': data} for row_id, data in rows.items()]})

    return {'public_id': 1, 'type_id': 11, 'fields': fields or [], 'multi_data_sections': sections}


class TestFieldValues:
    """field_values"""

    def test_no_object_has_no_value(self) -> None:
        """Before a create"""
        assert not field_values(None)

    def test_top_level_and_row_values_by_place(self) -> None:
        """Each value under where it sits"""
        state: dict[str, Any] = _object([_field('hostname', 'srv-1')], {ROW: [_field('port', 'eth0')]})

        assert field_values(state) == {'hostname': {TOP_LEVEL: 'srv-1'}, 'port': {(SECTION, ROW): 'eth0'}}

    def test_unreadable_entries_are_passed_over(self) -> None:
        """No name, a non-dict entry, a fields value that is no list"""
        assert not field_values({'fields': [{'value': 'x'}, 'hostname', {'name': 7, 'value': 1}]})
        assert not field_values({'fields': {'hostname': 'x'}})

    def test_the_first_entry_of_a_name_counts(self) -> None:
        """A repeated name in one place"""
        assert field_values(_object([_field('hostname', 'a'), _field('hostname', 'b')])) == {
            'hostname': {TOP_LEVEL: 'a'}}


class TestSameValue:
    """same_value"""

    @pytest.mark.parametrize('old, new', [('a', 'a'), (None, ''), ('', []), ([], None), ([1, 2], [1, 2])],
                             ids=['equal', 'none-empty', 'empty-list', 'list-none', 'lists'])
    def test_the_same(self, old: Any, new: Any) -> None:
        """Equal, or both empty"""
        assert same_value(old, new)

    @pytest.mark.parametrize('old, new', [('a', 'b'), (0, None), (False, ''), ([1], [])],
                             ids=['strings', 'zero', 'false', 'list'])
    def test_different(self, old: Any, new: Any) -> None:
        """0 and False are values"""
        assert not same_value(old, new)


class TestChangedFieldNames:
    """changed_field_names"""

    def test_an_unchanged_object_changes_nothing(self) -> None:
        """A form sending everything back"""
        state: dict[str, Any] = _object([_field('hostname', 'srv-1')], {ROW: [_field('port', 'eth0')]})

        assert not changed_field_names(state, dict(state))

    def test_a_changed_value(self) -> None:
        """Only that field"""
        before: dict[str, Any] = _object([_field('hostname', 'srv-1'), _field('ip', '10.0.0.1')])
        after: dict[str, Any] = _object([_field('hostname', 'srv-2'), _field('ip', '10.0.0.1')])

        assert changed_field_names(before, after) == ['hostname']

    def test_a_field_added_or_removed(self) -> None:
        """With a value it changes, with an empty value it does not"""
        before: dict[str, Any] = _object([_field('gone', 'x'), _field('gone_empty', '')])
        after: dict[str, Any] = _object([_field('new', 'y'), _field('new_empty', None)])

        assert changed_field_names(before, after) == ['gone', 'new']

    def test_a_create_changes_every_field_with_a_value(self) -> None:
        """No stored object; ascending"""
        after: dict[str, Any] = _object([_field('zone', 'a'), _field('empty', ''), _field('asset', 0)])

        assert changed_field_names(None, after) == ['asset', 'zone']

    def test_a_row_value_changed(self) -> None:
        """The section field, not the top-level one of the same state"""
        before: dict[str, Any] = _object([_field('hostname', 'srv')], {ROW: [_field('port', 'eth0')]})
        after: dict[str, Any] = _object([_field('hostname', 'srv')], {ROW: [_field('port', 'eth1')]})

        assert changed_field_names(before, after) == ['port']

    def test_a_row_added_or_removed_with_a_value(self) -> None:
        """Both directions"""
        one_row: dict[str, Any] = _object(rows={ROW: [_field('port', 'eth0')]})
        two_rows: dict[str, Any] = _object(rows={ROW: [_field('port', 'eth0')], OTHER_ROW: [_field('port', 'eth1')]})

        assert changed_field_names(one_row, two_rows) == ['port']
        assert changed_field_names(two_rows, one_row) == ['port']

    def test_an_empty_row_added_changes_nothing(self) -> None:
        """Nothing written"""
        one_row: dict[str, Any] = _object(rows={ROW: [_field('port', 'eth0')]})
        empty_added: dict[str, Any] = _object(rows={ROW: [_field('port', 'eth0')], OTHER_ROW: [_field('port', '')]})

        assert not changed_field_names(one_row, empty_added)

    def test_a_delete_changes_every_field_with_a_value(self) -> None:
        """No state after"""
        assert changed_field_names(_object([_field('hostname', 'srv')]), None) == ['hostname']
