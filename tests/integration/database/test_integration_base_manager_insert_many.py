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
Integration tests for BaseManager.insert_many and get_distinct against a real MongoDB

insert_many numbers the documents that carry no public_id from ONE reserved counter block, in list order, and keeps a
supplied id. Only the database layer's errors are wrapped: a duplicate key still arrives as the typed refusal one hop
down, which the routes look for. insert_many_reporting writes every document the server accepts and answers the
refused ones by their index, each with its typed error, touching no counter
"""
from typing import Any

import pytest
from pymongo import ASCENDING

from cmdb.database import MongoDatabaseManager
from cmdb.database.database_constants import PUBLIC_ID_COUNTER_COLLECTION
from cmdb.errors.database import DocumentInsertDuplicateKeyError, DocumentInsertError
from cmdb.errors.manager import BaseManagerInsertError
from cmdb.manager.base_manager import BaseManager
from cmdb.utils import find_cause
# -------------------------------------------------------------------------------------------------------------------- #

COLLECTION: str = 'test.insertManyScratch'
NAME_KEY: str = 'name'
SUPPLIED_ID: int = 900
BATCH_SIZE: int = 3
STARTING_COUNTER: int = 40


@pytest.fixture(name='manager')
def fixture_manager(database_manager: MongoDatabaseManager, database_name: str):
    """A BaseManager on a scratch collection whose counter starts at a known value; both removed afterwards"""
    counters = database_manager.get_collection(PUBLIC_ID_COUNTER_COLLECTION, database_name)
    counters.replace_one({'_id': COLLECTION}, {'_id': COLLECTION, 'counter': STARTING_COUNTER}, upsert=True)

    yield BaseManager(COLLECTION, database_manager, database_name)

    database_manager.get_collection(COLLECTION, database_name).drop()
    counters.delete_one({'_id': COLLECTION})


def _counter(database_manager: MongoDatabaseManager, database_name: str) -> int:
    """The scratch collection's counter as stored"""
    counters = database_manager.get_collection(PUBLIC_ID_COUNTER_COLLECTION, database_name)
    return counters.find_one({'_id': COLLECTION})['counter']


def _stored(database_manager: MongoDatabaseManager, database_name: str) -> dict[str, int]:
    """Each stored document's public_id, by name"""
    documents: list[dict[str, Any]] = list(database_manager.get_collection(COLLECTION, database_name).find())
    return {document[NAME_KEY]: document['public_id'] for document in documents}


def test_a_batch_takes_one_contiguous_block_in_list_order(
        manager: BaseManager, database_manager: MongoDatabaseManager, database_name: str,
        monkeypatch: pytest.MonkeyPatch) -> None:
    """N documents, one reservation of N; ids follow the counter and the list order"""
    reservations: list[int] = []
    reserve = database_manager.reserve_public_ids

    def _spy(collection: str, db_name: str, amount: int) -> list[int]:
        reservations.append(amount)
        return reserve(collection, db_name, amount)

    monkeypatch.setattr(database_manager, 'reserve_public_ids', _spy)

    returned: list[int] = manager.insert_many([{NAME_KEY: 'a'}, {NAME_KEY: 'b'}, {NAME_KEY: 'c'}])

    expected: list[int] = [STARTING_COUNTER + 1, STARTING_COUNTER + 2, STARTING_COUNTER + 3]
    assert reservations == [BATCH_SIZE]
    assert returned == expected
    assert _stored(database_manager, database_name) == dict(zip(['a', 'b', 'c'], expected))
    assert _counter(database_manager, database_name) == STARTING_COUNTER + BATCH_SIZE


def test_a_supplied_id_is_kept_and_takes_no_number(
        manager: BaseManager, database_manager: MongoDatabaseManager, database_name: str) -> None:
    """Only the documents without an id are counted"""
    manager.insert_many([{NAME_KEY: 'own', 'public_id': SUPPLIED_ID}, {NAME_KEY: 'new'}])

    assert _stored(database_manager, database_name) == {'own': SUPPLIED_ID, 'new': STARTING_COUNTER + 1}
    assert _counter(database_manager, database_name) == STARTING_COUNTER + 1


def test_a_batch_of_supplied_ids_leaves_the_counter_alone(
        manager: BaseManager, database_manager: MongoDatabaseManager, database_name: str) -> None:
    """No reservation at all"""
    manager.insert_many([{NAME_KEY: 'x', 'public_id': SUPPLIED_ID}])

    assert _counter(database_manager, database_name) == STARTING_COUNTER


def test_a_duplicate_key_arrives_as_the_typed_refusal(
        manager: BaseManager, database_manager: MongoDatabaseManager, database_name: str) -> None:
    """Wrapped as the insert error, with the typed duplicate-key refusal in its chain"""
    database_manager.get_collection(COLLECTION, database_name).create_index([(NAME_KEY, ASCENDING)], unique=True)
    manager.insert_many([{NAME_KEY: 'same'}])

    with pytest.raises(BaseManagerInsertError) as caught:
        manager.insert_many([{NAME_KEY: 'same'}])

    assert find_cause(caught.value, DocumentInsertDuplicateKeyError) is not None


def test_get_distinct_reads_the_stored_values(manager: BaseManager) -> None:
    """The narrowed read still answers the distinct values"""
    manager.insert_many([{NAME_KEY: 'a'}, {NAME_KEY: 'a'}, {NAME_KEY: 'b'}])

    assert sorted(manager.get_distinct(NAME_KEY, {})) == ['a', 'b']


def test_a_reporting_insert_writes_around_a_refused_document(
        manager: BaseManager, database_manager: MongoDatabaseManager, database_name: str) -> None:
    """Unordered: the documents after a duplicate are written too, and the duplicate is named by its index"""
    database_manager.get_collection(COLLECTION, database_name).create_index(
        [('public_id', ASCENDING)], unique=True,
    )
    manager.insert_many([{NAME_KEY: 'taken', 'public_id': SUPPLIED_ID}])

    failures = manager.insert_many_reporting([
        {NAME_KEY: 'first', 'public_id': SUPPLIED_ID + 1},
        {NAME_KEY: 'clash', 'public_id': SUPPLIED_ID},
        {NAME_KEY: 'last', 'public_id': SUPPLIED_ID + 2},
    ])

    assert list(failures) == [1]
    assert isinstance(failures[1], DocumentInsertDuplicateKeyError)
    assert failures[1].key_pattern == {'public_id': 1}
    assert _stored(database_manager, database_name) == {
        'taken': SUPPLIED_ID, 'first': SUPPLIED_ID + 1, 'last': SUPPLIED_ID + 2,
    }
    assert _counter(database_manager, database_name) == STARTING_COUNTER


def test_a_reporting_insert_names_another_refusal_as_an_insert_error(
        manager: BaseManager, database_manager: MongoDatabaseManager, database_name: str) -> None:
    """A clash on another unique index is the document's own duplicate, not a public_id clash"""
    database_manager.get_collection(COLLECTION, database_name).create_index([(NAME_KEY, ASCENDING)], unique=True)
    manager.insert_many([{NAME_KEY: 'same'}])

    failures = manager.insert_many_reporting([{NAME_KEY: 'same', 'public_id': SUPPLIED_ID}])

    assert isinstance(failures[0], DocumentInsertError)
    assert failures[0].key_pattern == {NAME_KEY: 1}
