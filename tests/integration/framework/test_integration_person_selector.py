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
Integration tests for the person selector's server-side statements against a real MongoDB

Seeds a person, a person group (each an object of a type with its marker) and three objects of an owning type that
hold a person selector - flat and in multi-data rows - and asserts:

  - the usage aggregation finds the objects holding several (flat or in a row) and the types of every selected
    object, ignoring an id that resolves to nothing; an object of another type is not read
  - the shape update turns one id into a one-item list and None into an empty list for a selector holding several,
    a list into its only item (or None) for one holding one - flat and in every row; other fields and other types'
    objects are untouched; a second run changes nothing
"""
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.objects_propagation_helper import build_person_value_shape_update
from cmdb.models.object_model import CmdbObject
from cmdb.interface.rest_api.routes.framework_routes.cmdb_types.types_person_selector_helper import (
    build_person_field_usage_pipeline,
)
# -------------------------------------------------------------------------------------------------------------------- #

OWNING_TYPE_ID: int = 48101
OTHER_TYPE_ID: int = 48102
PERSON_TYPE_ID: int = 48103
GROUP_TYPE_ID: int = 48104

PERSON_ID: int = 48111
GROUP_ID: int = 48112
GONE_ID: int = 48119
FLAT_SEVERAL_ID: int = 48121
ROW_SEVERAL_ID: int = 48122
SINGLE_ID: int = 48123
OTHER_TYPE_OBJECT_ID: int = 48124
ALL_OBJECT_IDS: list[int] = [PERSON_ID, GROUP_ID, FLAT_SEVERAL_ID, ROW_SEVERAL_ID, SINGLE_ID, OTHER_TYPE_OBJECT_ID]

FIELD: str = 'owner'
NOTE: str = 'note'
SECTION: str = 'contacts'


def _entry(value: Any, name: str = FIELD) -> dict[str, Any]:
    """One field entry"""
    return {'name': name, 'type': 'person', 'value': value}


def _object(public_id: int, type_id: int, value: Any = None, rows: list[Any] | None = None) -> dict[str, Any]:
    """An object holding the selector flat and, per row value, in one multi-data section"""
    return {
        'public_id': public_id, 'type_id': type_id,
        'fields': [_entry(value), {'name': NOTE, 'type': 'text', 'value': 'kept'}],
        'multi_data_sections': [{'section_id': SECTION, 'highest_id': len(rows or []), 'values': [
            {'multi_data_id': index, 'data': [_entry(row)]} for index, row in enumerate(rows or [])
        ]}],
    }


@pytest.fixture(name='objects')
def fixture_objects(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[Any]:
    """The seeded objects, purged before and after"""
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    objects.delete_many({'public_id': {'$in': ALL_OBJECT_IDS}})
    objects.insert_many([
        {'public_id': PERSON_ID, 'type_id': PERSON_TYPE_ID, 'fields': []},
        {'public_id': GROUP_ID, 'type_id': GROUP_TYPE_ID, 'fields': []},
        _object(FLAT_SEVERAL_ID, OWNING_TYPE_ID, [PERSON_ID, GROUP_ID]),
        _object(ROW_SEVERAL_ID, OWNING_TYPE_ID, None, rows=[[PERSON_ID, GONE_ID], [GROUP_ID]]),
        _object(SINGLE_ID, OWNING_TYPE_ID, PERSON_ID, rows=[[]]),
        _object(OTHER_TYPE_OBJECT_ID, OTHER_TYPE_ID, [PERSON_ID, GROUP_ID]),
    ])

    yield objects

    objects.delete_many({'public_id': {'$in': ALL_OBJECT_IDS}})


def _usage(database_manager: MongoDatabaseManager, database_name: str) -> dict[str, Any]:
    """The usage aggregation's one answer"""
    result = database_manager.aggregate_all(CmdbObject.COLLECTION, database_name,
                                            build_person_field_usage_pipeline(OWNING_TYPE_ID, FIELD))

    return result[0]


def _values(objects: Any, public_id: int) -> tuple[Any, list[Any], Any]:
    """The flat selector value, the selector value of each row, and the untouched note"""
    document: dict[str, Any] = objects.find_one({'public_id': public_id})
    flat: dict[str, Any] = {entry['name']: entry['value'] for entry in document['fields']}
    rows: list[Any] = [row['data'][0]['value'] for row in document['multi_data_sections'][0]['values']]

    return flat[FIELD], rows, flat[NOTE]


@pytest.mark.usefixtures('objects')
def test_the_usage_names_the_objects_holding_several(database_manager: MongoDatabaseManager,
                                                     database_name: str) -> None:
    """Flat or in a row, in public_id order; the object of another type is not read"""
    assert _usage(database_manager, database_name)['several'] == [
        {'public_id': FLAT_SEVERAL_ID}, {'public_id': ROW_SEVERAL_ID},
    ]


@pytest.mark.usefixtures('objects')
def test_the_usage_answers_the_types_of_the_selected_objects(database_manager: MongoDatabaseManager,
                                                             database_name: str) -> None:
    """Each type once; an id resolving to nothing joins nothing"""
    selected: list[int] = sorted(entry['_id'] for entry in _usage(database_manager, database_name)['selected_types'])

    assert selected == [PERSON_TYPE_ID, GROUP_TYPE_ID]


def _reshape(objects: Any, single: list[str], several: list[str]) -> None:
    """Runs the shape update the way ObjectsManager.apply_raw_updates does"""
    update = build_person_value_shape_update(OWNING_TYPE_ID, single, several)
    objects.update_many(update.filter_query, update.update)


def test_to_several_wraps_ids_and_turns_none_into_an_empty_list(objects: Any) -> None:
    """Flat and in every row; a list stays as it is"""
    _reshape(objects, [], [FIELD])

    assert _values(objects, SINGLE_ID) == ([PERSON_ID], [[]], 'kept')
    assert _values(objects, ROW_SEVERAL_ID) == ([], [[PERSON_ID, GONE_ID], [GROUP_ID]], 'kept')
    assert _values(objects, FLAT_SEVERAL_ID) == ([PERSON_ID, GROUP_ID], [], 'kept')


def test_to_one_takes_the_only_item_or_none(objects: Any) -> None:
    """An empty list becomes None; a one-item list its item"""
    _reshape(objects, [FIELD], [])

    assert _values(objects, SINGLE_ID) == (PERSON_ID, [None], 'kept')


def test_another_types_objects_are_untouched(objects: Any) -> None:
    """Only the owning type's objects"""
    before: dict[str, Any] = objects.find_one({'public_id': OTHER_TYPE_OBJECT_ID}, {'_id': 0})

    _reshape(objects, [FIELD], [])

    assert objects.find_one({'public_id': OTHER_TYPE_OBJECT_ID}, {'_id': 0}) == before


def test_a_second_run_changes_nothing(objects: Any) -> None:
    """State-based"""
    _reshape(objects, [], [FIELD])
    first: list[dict[str, Any]] = list(objects.find({'type_id': OWNING_TYPE_ID}, {'_id': 0}).sort('public_id', 1))

    _reshape(objects, [], [FIELD])

    assert list(objects.find({'type_id': OWNING_TYPE_ID}, {'_id': 0}).sort('public_id', 1)) == first
