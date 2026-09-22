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
Integration tests for the public_id counter against a real MongoDB

Two write paths choose their own public_id instead of drawing one: `POST /objects/` (a free id is
honoured, a taken one is a 400) and the object importer (an object is imported under the id its file
names). The counter has to learn about those ids, or the next drawn id is one that already exists.

Before the reconciliation the collision was survivable but real: the insert retry loop dropped the
drawn id and drew again, so a create silently burned a retry - and a block of MAX_DUPLICATE_KEY_RETRIES
consecutive supplied ids exhausted the loop and failed the insert outright. These tests use a real
counter document and a real unique index, because the interplay of the two is the thing being asserted.
"""
import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.database.database_constants import MAX_DUPLICATE_KEY_RETRIES, PUBLIC_ID_COUNTER_COLLECTION
# -------------------------------------------------------------------------------------------------------------------- #

COLLECTION: str = 'test.publicIdCounterScratch'


@pytest.fixture(autouse=True)
def _scratch(database_manager: MongoDatabaseManager, database_name: str):
    """Gives each test an empty collection with the unique public_id index, and its own counter."""
    collection = database_manager.get_collection(COLLECTION, database_name)
    counters = database_manager.get_collection(PUBLIC_ID_COUNTER_COLLECTION, database_name)

    collection.delete_many({})
    counters.delete_many({'_id': COLLECTION})
    collection.create_index('public_id', unique=True, name='public_id')

    yield

    collection.drop()
    counters.delete_many({'_id': COLLECTION})


def _counter(database_manager: MongoDatabaseManager, database_name: str) -> int:
    """Reads the stored counter value for the scratch collection."""
    counters = database_manager.get_collection(PUBLIC_ID_COUNTER_COLLECTION, database_name)
    document = counters.find_one({'_id': COLLECTION})

    return document['counter']


def test_a_supplied_id_raises_the_counter_above_itself(
    database_manager: MongoDatabaseManager, database_name: str,
) -> None:
    """An id the caller chose is stored as given, and the counter follows it."""
    assert database_manager.insert(COLLECTION, database_name, {'public_id': 500, 'name': 'supplied'}) == 500

    assert _counter(database_manager, database_name) == 500


def test_the_next_drawn_id_does_not_collide_with_a_supplied_one(
    database_manager: MongoDatabaseManager, database_name: str,
) -> None:
    """The point of the reconciliation: the id after an explicit one is free on the first attempt."""
    database_manager.insert(COLLECTION, database_name, {'public_id': 500, 'name': 'supplied'})

    assert database_manager.insert(COLLECTION, database_name, {'name': 'drawn'}) == 501


def test_a_block_of_supplied_ids_does_not_exhaust_the_retry_loop(
    database_manager: MongoDatabaseManager, database_name: str,
) -> None:
    """
    The failure this closes: more than MAX_DUPLICATE_KEY_RETRIES consecutive supplied ids

    With the counter left behind, the next create drew id 1, 2, 3 ... each already taken, and the loop
    gave up with 'Failed to insert document after N duplicate key attempts'.
    """
    for public_id in range(1, MAX_DUPLICATE_KEY_RETRIES + 3):
        database_manager.insert(COLLECTION, database_name, {'public_id': public_id, 'name': 'supplied'})

    drawn = database_manager.insert(COLLECTION, database_name, {'name': 'drawn'})

    assert drawn == MAX_DUPLICATE_KEY_RETRIES + 3


def test_a_lower_supplied_id_does_not_pull_the_counter_back(
    database_manager: MongoDatabaseManager, database_name: str,
) -> None:
    """The counter only ever moves forward, so filling an old gap cannot hand out a used id twice."""
    database_manager.insert(COLLECTION, database_name, {'public_id': 500, 'name': 'supplied'})
    database_manager.insert(COLLECTION, database_name, {'public_id': 7, 'name': 'gap-filler'})

    assert _counter(database_manager, database_name) == 500
    assert database_manager.insert(COLLECTION, database_name, {'name': 'drawn'}) == 501


def test_an_upsert_that_creates_a_document_raises_the_counter_to_it(
    database_manager: MongoDatabaseManager, database_name: str,
) -> None:
    """upsert_set used to bump the counter by one, which left it below the id it had just created."""
    database_manager.upsert_set(COLLECTION, database_name, {'public_id': 500, 'name': 'upserted'})

    assert _counter(database_manager, database_name) == 500
