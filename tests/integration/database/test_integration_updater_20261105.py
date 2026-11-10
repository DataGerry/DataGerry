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
Integration tests for updater_20261105 against a real MongoDB

An object relation naming a field twice keeps the FIRST entry of each name (the value it held before the cascade
appended an empty one), in order; an instance naming every field once, one without field values and one whose
field_values is no list are left alone; a second run changes nothing
"""
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.database.updater.versions.updater_20261105 import Update20261105
from cmdb.models.object_relation_model import CmdbObjectRelation
# -------------------------------------------------------------------------------------------------------------------- #

REPEATED_ID: int = 96051
CLEAN_ID: int = 96052
NO_VALUES_ID: int = 96053
NOT_A_LIST_ID: int = 96054
ALL_IDS: list[int] = [REPEATED_ID, CLEAN_ID, NO_VALUES_ID, NOT_A_LIST_ID]

REPEATED_VALUES: list[dict[str, Any]] = [
    {'name': 'a', 'value': 'kept'}, {'name': 'b', 'value': 'b1'},
    {'name': 'a', 'value': None}, {'name': 'b', 'value': None}, {'name': 'c', 'value': 'c1'},
]
FIRST_OF_EACH: list[dict[str, Any]] = [
    {'name': 'a', 'value': 'kept'}, {'name': 'b', 'value': 'b1'}, {'name': 'c', 'value': 'c1'},
]
CLEAN_VALUES: list[dict[str, Any]] = [{'name': 'a', 'value': 'x'}, {'name': 'b', 'value': None}]


@pytest.fixture(name='instances')
def fixture_instances(database_manager: MongoDatabaseManager, database_name: str):
    """Four stored instances in the shapes above, removed again afterwards"""
    collection = database_manager.get_collection(CmdbObjectRelation.COLLECTION, database_name)
    collection.delete_many({'public_id': {'$in': ALL_IDS}})
    collection.insert_many([
        {'public_id': REPEATED_ID, 'relation_id': 1, 'field_values': REPEATED_VALUES},
        {'public_id': CLEAN_ID, 'relation_id': 1, 'field_values': CLEAN_VALUES},
        {'public_id': NO_VALUES_ID, 'relation_id': 1},
        {'public_id': NOT_A_LIST_ID, 'relation_id': 1, 'field_values': 'garbage'},
    ])
    yield collection
    collection.delete_many({'public_id': {'$in': ALL_IDS}})


def _run(database_manager: MongoDatabaseManager, database_name: str) -> None:
    """The real migration"""
    Update20261105(database_manager, database_name).start_update()


def _values(collection: Any, public_id: int) -> Any:
    """The stored field_values of one instance (None when absent)."""
    return collection.find_one({'public_id': public_id}).get('field_values')


def test_the_first_entry_of_each_name_is_kept_in_order(instances, database_manager, database_name) -> None:
    """The repeated null entries go; the held values and their order stay"""
    _run(database_manager, database_name)

    assert _values(instances, REPEATED_ID) == FIRST_OF_EACH


def test_other_shapes_are_left_alone(instances, database_manager, database_name) -> None:
    """Once per name, no list and a non-list are not matched"""
    _run(database_manager, database_name)

    assert _values(instances, CLEAN_ID) == CLEAN_VALUES
    assert _values(instances, NO_VALUES_ID) is None
    assert _values(instances, NOT_A_LIST_ID) == 'garbage'


def test_a_second_run_changes_nothing(instances, database_manager, database_name) -> None:
    """Re-run safe: the first run left every name once, so the second matches nothing"""
    _run(database_manager, database_name)
    _run(database_manager, database_name)

    assert _values(instances, REPEATED_ID) == FIRST_OF_EACH
    assert _values(instances, CLEAN_ID) == CLEAN_VALUES
