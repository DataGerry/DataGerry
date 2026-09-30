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
Unit tests for cmdb.manager.objects_propagation_helper

Pure: no Mongo. Each builder is one `update_many`, and what is pinned here is the statement itself -
which documents it matches, what it changes, and the array filters that scope an MDS change to one
section and to the rows that need it. Two properties matter more than the exact shape and each has a
test of its own: an added entry is only pushed where it is MISSING (which is what makes a re-run
change nothing), and nothing but the named entries is addressed (which is what keeps a concurrent
edit of the same object).
"""
from typing import Any

import pytest

from cmdb.manager.objects_propagation_helper import (
    RawUpdate,
    build_add_field_update,
    build_add_mds_field_update,
    build_field_entry,
    build_remove_fields_update,
    build_remove_mds_fields_update,
    build_remove_mds_section_update,
    build_remove_undeclared_fields_update,
)
from cmdb.models.type_model.field_key_enum import FieldKey
from cmdb.models.type_model.field_type_enum import FieldType
# -------------------------------------------------------------------------------------------------------------------- #

TYPE_ID: int = 42
SECTION_ID: str = 'dg-ipam-interface'
ENTRY: dict[str, Any] = {'name': 'b', 'type': 'date', 'value': None}


class TestBuildFieldEntry:
    """The `{name, value, type}` triple a new field starts as."""

    def test_takes_type_and_default_from_the_definition(self) -> None:
        """The declared default is the starting value"""
        definition: dict[str, Any] = {
            FieldKey.NAME.value: 'b', FieldKey.TYPE.value: FieldType.DATE.value, FieldKey.VALUE.value: 'preset',
        }

        assert build_field_entry(definition) == {'name': 'b', 'type': 'date', 'value': 'preset'}

    def test_without_a_default_the_value_is_none(self) -> None:
        """A field declaring no default starts empty"""
        definition: dict[str, Any] = {FieldKey.NAME.value: 'b', FieldKey.TYPE.value: FieldType.TEXT.value}

        assert build_field_entry(definition)['value'] is None

    def test_a_falsy_default_is_kept(self) -> None:
        """A checkbox defaulting to False starts False, not None"""
        definition: dict[str, Any] = {
            FieldKey.NAME.value: 'c', FieldKey.TYPE.value: FieldType.CHECKBOX.value, FieldKey.VALUE.value: False,
        }

        assert build_field_entry(definition)['value'] is False

    def test_a_definition_without_a_type_is_text(self) -> None:
        """A drifted declaration still yields a usable entry"""
        assert build_field_entry({FieldKey.NAME.value: 'b'})['type'] == FieldType.TEXT.value


class TestFlatFieldUpdates:
    """The statements on an object's flat `fields` list."""

    def test_an_added_field_is_pushed_only_where_it_is_missing(self) -> None:
        """The `$ne` on the name is what makes a second run match nothing"""
        assert build_add_field_update(TYPE_ID, ENTRY) == RawUpdate(
            filter_query={'type_id': TYPE_ID, 'fields.name': {'$ne': 'b'}},
            update={'$push': {'fields': ENTRY}},
        )

    def test_removed_fields_are_pulled_by_name(self) -> None:
        """Every object of the type loses exactly the named entries"""
        assert build_remove_fields_update(TYPE_ID, ['b', 'c']) == RawUpdate(
            filter_query={'type_id': TYPE_ID},
            update={'$pull': {'fields': {'name': {'$in': ['b', 'c']}}}},
        )

    def test_undeclared_fields_are_pulled_by_what_is_declared(self) -> None:
        """`$nin` removes stale names without having to know which they are"""
        assert build_remove_undeclared_fields_update(TYPE_ID, ['a']) == RawUpdate(
            filter_query={'type_id': TYPE_ID},
            update={'$pull': {'fields': {'name': {'$nin': ['a']}}}},
        )


class TestMdsUpdates:
    """The statements on the rows of one multi-data section."""

    def test_an_added_field_is_pushed_into_the_rows_that_lack_it(self) -> None:
        """`$[s]` picks the section, `$[v]` only the rows without the name"""
        assert build_add_mds_field_update(TYPE_ID, SECTION_ID, ENTRY) == RawUpdate(
            filter_query={'type_id': TYPE_ID, 'multi_data_sections.section_id': SECTION_ID},
            update={'$push': {'multi_data_sections.$[s].values.$[v].data': ENTRY}},
            array_filters=[
                {'s.section_id': SECTION_ID},
                {'v.data.name': {'$ne': 'b'}},
            ],
        )

    def test_removed_fields_are_pulled_from_every_row_of_the_section(self) -> None:
        """`$[]` addresses all rows of the matched section"""
        assert build_remove_mds_fields_update(TYPE_ID, SECTION_ID, ['b']) == RawUpdate(
            filter_query={'type_id': TYPE_ID, 'multi_data_sections.section_id': SECTION_ID},
            update={'$pull': {'multi_data_sections.$[s].values.$[].data': {'name': {'$in': ['b']}}}},
            array_filters=[{'s.section_id': SECTION_ID}],
        )

    def test_a_removed_section_is_pulled_whole(self) -> None:
        """All rows go with it"""
        assert build_remove_mds_section_update(TYPE_ID, SECTION_ID) == RawUpdate(
            filter_query={'type_id': TYPE_ID},
            update={'$pull': {'multi_data_sections': {'section_id': SECTION_ID}}},
        )


@pytest.mark.parametrize('raw_update', [
    build_add_field_update(TYPE_ID, ENTRY),
    build_remove_fields_update(TYPE_ID, ['b']),
    build_remove_undeclared_fields_update(TYPE_ID, ['a']),
    build_add_mds_field_update(TYPE_ID, SECTION_ID, ENTRY),
    build_remove_mds_fields_update(TYPE_ID, SECTION_ID, ['b']),
    build_remove_mds_section_update(TYPE_ID, SECTION_ID),
], ids=['add', 'remove', 'remove-undeclared', 'mds-add', 'mds-remove', 'mds-section'])
def test_no_statement_overwrites_a_whole_array(raw_update: RawUpdate) -> None:
    """
    Every statement pushes or pulls single entries - none `$set`s an array

    A `$set` of a list written from a copy read earlier is what would lose an edit saved in between;
    `$push` / `$pull` change the stored document in place.
    """
    assert set(raw_update.update) <= {'$push', '$pull'}
    assert raw_update.filter_query['type_id'] == TYPE_ID
