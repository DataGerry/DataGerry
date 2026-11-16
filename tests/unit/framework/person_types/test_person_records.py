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
Unit tests for cmdb.framework.person_types.person_records

The record of an object (old keys from the base fields, a group's ``group_members`` from ``members``), the field
entries a body sets, the reshaping stages and the groups each person is in
"""
from typing import Any
from unittest.mock import MagicMock

from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.framework.person_types.person_records import (
    field_entries,
    groups_of_persons,
    record_of,
    record_stages,
)
# -------------------------------------------------------------------------------------------------------------------- #

def _object(public_id: int, **values: Any) -> dict[str, Any]:
    """An object document with the given field values"""
    return {'public_id': public_id, 'fields': [{'name': name, 'value': value} for name, value in values.items()]}


def test_a_person_object_as_a_record() -> None:
    """Every record key; a missing field is None; user is no record key"""
    record = record_of(_object(4, display_name='Ada', first_name='A', email='a@x', user=None), SpecialType.PERSON)

    assert record == {'public_id': 4, 'display_name': 'Ada', 'first_name': 'A', 'last_name': None,
                      'phone_number': None, 'email': 'a@x'}


def test_a_group_object_as_a_record() -> None:
    """members read as group_members"""
    assert record_of(_object(5, name='Ops', email='', members=[4]), SpecialType.PERSON_GROUP) == {
        'public_id': 5, 'name': 'Ops', 'email': '', 'group_members': [4]}


def test_the_field_entries_are_the_keys_the_body_carries() -> None:
    """group_members becomes members; unknown keys and groups are not fields"""
    assert field_entries(SpecialType.PERSON_GROUP, {'name': 'Ops', 'group_members': [4], 'x': 1}) == [
        {'name': 'name', 'value': 'Ops'}, {'name': 'members', 'value': [4]}]
    assert field_entries(SpecialType.PERSON, {'groups': [1]}) == []


def test_the_stages_match_the_marker_and_the_readable_types_then_reshape() -> None:
    """A $match, then a $project of every record key"""
    match, project = record_stages(SpecialType.PERSON_GROUP, [7, 3, 7])

    assert match == {'$match': {'special_type': 'PERSON_GROUP', 'type_id': {'$nin': [3, 7]}}}
    assert set(project['$project']) == {'_id', 'public_id', 'name', 'email', 'group_members'}


def test_the_groups_of_persons_in_one_read() -> None:
    """Each person's groups, ascending; a person in none has an empty list; nothing read for none"""
    manager = MagicMock()
    manager.find.return_value = [_object(9, members=[1, 2]), _object(8, members=[1])]

    assert groups_of_persons(manager, [2, 1, 3], [5]) == {1: [8, 9], 2: [9], 3: []}
    criteria = manager.find.call_args.args[0]
    assert (criteria['special_type'], criteria['type_id'], criteria['fields']['$elemMatch']['value']) == (
        'PERSON_GROUP', {'$nin': [5]}, {'$in': [1, 2, 3]})

    manager.find.reset_mock()
    assert not groups_of_persons(manager, [], [])
    manager.find.assert_not_called()
