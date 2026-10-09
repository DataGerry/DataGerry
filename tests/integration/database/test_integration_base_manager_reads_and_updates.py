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
Integration tests for BaseManager's many-document reads and updates against a real MongoDB

The reads take their filter as one criteria dict, so a stored field named like an option (`sort`, `limit`) or like
the other-collection parameter (`collection`) is a filter field. The updates: `update_many` wraps field values in
`$set` / `$addToSet`; a `$pull`, an `$unset` or a pipeline is a raw update
"""
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.base_manager import BaseManager
# -------------------------------------------------------------------------------------------------------------------- #

COLLECTION: str = 'test.readsAndUpdatesScratch'
OTHER_COLLECTION: str = 'test.readsAndUpdatesOther'
SORT_KEY: str = 'sort'
TAGS_KEY: str = 'tags'
STALE_KEY: str = 'stale'
SEEDED: list[dict[str, Any]] = [
    {'public_id': 1, SORT_KEY: 2, TAGS_KEY: ['a', 'b'], STALE_KEY: 'x'},
    {'public_id': 2, SORT_KEY: 1, TAGS_KEY: ['b'], STALE_KEY: 'y'},
    {'public_id': 3, SORT_KEY: 2, TAGS_KEY: [], STALE_KEY: 'z'},
]


@pytest.fixture(name='manager')
def fixture_manager(database_manager: MongoDatabaseManager, database_name: str):
    """A BaseManager over a seeded scratch collection; both scratch collections dropped afterwards"""
    database_manager.get_collection(COLLECTION, database_name).insert_many([dict(doc) for doc in SEEDED])
    database_manager.get_collection(OTHER_COLLECTION, database_name).insert_many([
        {'public_id': 10, 'collection': 'framework.objects'},
        {'public_id': 11, 'collection': 'framework.types'},
    ])

    yield BaseManager(COLLECTION, database_manager, database_name)

    database_manager.get_collection(COLLECTION, database_name).drop()
    database_manager.get_collection(OTHER_COLLECTION, database_name).drop()


def _stored(database_manager: MongoDatabaseManager, database_name: str) -> dict[int, dict[str, Any]]:
    """Every stored document by public_id"""
    collection = database_manager.get_collection(COLLECTION, database_name)
    return {document['public_id']: document for document in collection.find({}, {'_id': 0})}


def test_get_many_filters_on_a_stored_sort_field(manager: BaseManager) -> None:
    """`sort` in the criteria selects documents by that field; the sort option stays an option"""
    found: list[dict[str, Any]] = manager.get_many(sort='public_id', direction=1, criteria={SORT_KEY: 2})

    assert [document['public_id'] for document in found] == [1, 3]


def test_get_many_from_other_collection_filters_on_a_field_named_collection(manager: BaseManager) -> None:
    """The collection to read and a `collection` field to match are two different things now"""
    found = manager.get_many_from_other_collection(OTHER_COLLECTION, criteria={'collection': 'framework.types'})

    assert [document['public_id'] for document in found] == [11]


def test_update_many_pull_removes_the_member_everywhere(
        manager: BaseManager, database_manager: MongoDatabaseManager, database_name: str) -> None:
    """The $pull built by BaseManager and sent raw"""
    manager.update_many_pull({TAGS_KEY: 'b'}, {TAGS_KEY: 'b'})

    assert {public_id: doc[TAGS_KEY] for public_id, doc in _stored(database_manager, database_name).items()} == {
        1: ['a'], 2: [], 3: [],
    }


def test_update_many_adds_a_member_once(
        manager: BaseManager, database_manager: MongoDatabaseManager, database_name: str) -> None:
    """$addToSet: an array that already holds the value is left as it is"""
    manager.update_many({}, {TAGS_KEY: 'a'}, add_to_set=True)

    assert {public_id: doc[TAGS_KEY] for public_id, doc in _stored(database_manager, database_name).items()} == {
        1: ['a', 'b'], 2: ['b', 'a'], 3: ['a'],
    }


def test_an_unset_is_a_raw_update(
        manager: BaseManager, database_manager: MongoDatabaseManager, database_name: str) -> None:
    """What the removed unset wrapper did, written as the raw update it always was"""
    manager.update_many_raw({SORT_KEY: 2}, {'$unset': {STALE_KEY: 1}})

    stored = _stored(database_manager, database_name)
    assert [STALE_KEY in stored[public_id] for public_id in (1, 2, 3)] == [False, True, False]


def test_a_pipeline_is_a_raw_update(
        manager: BaseManager, database_manager: MongoDatabaseManager, database_name: str) -> None:
    """A list of stages reaches MongoDB as an aggregation-pipeline update"""
    manager.update_many_raw({}, [{'$set': {SORT_KEY: {'$multiply': [f'${SORT_KEY}', 10]}}}])

    assert {public_id: doc[SORT_KEY] for public_id, doc in _stored(database_manager, database_name).items()} == {
        1: 20, 2: 10, 3: 20,
    }
