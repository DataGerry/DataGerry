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
Integration tests for the typed duplicate-key refusal against a real MongoDB

A route answers "that name is taken" only when the database layer raised a DocumentDuplicateKeyError,
so what the real server reports - on insert_one, on an unordered insert_many and on update_one - is
the thing asserted here: the refusal's type, the index it names and the value that collided. A mocked
collection cannot show that the server's 'keyPattern' / 'keyValue' and a bulk write's 'writeErrors'
really have the shape the reader expects.
"""
import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.database.database_constants import PUBLIC_ID_COUNTER_COLLECTION
from cmdb.errors.database import (
    DocumentDuplicateKeyError,
    DocumentInsertDuplicateKeyError,
    DocumentInsertError,
    DocumentUpdateDuplicateKeyError,
)
from cmdb.manager.base_manager import BaseManager
from cmdb.errors.manager import BaseManagerInsertError
from cmdb.utils import find_cause
# -------------------------------------------------------------------------------------------------------------------- #

COLLECTION: str = 'test.duplicateKeyScratch'
NAME_INDEX: str = 'owner_name'
OWNER_ID: int = 8802
TAKEN_NAME: str = 'Gi0/1'
FREE_NAME: str = 'Gi0/2'
EXPECTED_PATTERN: dict[str, int] = {'owner': 1, 'name': 1}


@pytest.fixture(autouse=True)
def _scratch(database_manager: MongoDatabaseManager, database_name: str):
    """An empty collection with a unique public_id index and a unique compound (owner, name) index."""
    collection = database_manager.get_collection(COLLECTION, database_name)
    counters = database_manager.get_collection(PUBLIC_ID_COUNTER_COLLECTION, database_name)

    collection.delete_many({})
    counters.delete_many({'_id': COLLECTION})
    collection.create_index('public_id', unique=True, name='public_id')
    collection.create_index([('owner', 1), ('name', 1)], unique=True, name=NAME_INDEX)

    yield collection

    collection.drop()
    counters.delete_many({'_id': COLLECTION})


def _store(database_manager: MongoDatabaseManager, database_name: str, name: str) -> int:
    """Stores one document through the real insert path."""
    return database_manager.insert(COLLECTION, database_name, {'owner': OWNER_ID, 'name': name})


def test_an_insert_that_duplicates_the_index_is_the_typed_refusal(
    database_manager: MongoDatabaseManager, database_name: str, _scratch,
) -> None:
    """insert_one: the refusal names the compound index and the colliding value - and is not retried."""
    _store(database_manager, database_name, TAKEN_NAME)

    with pytest.raises(DocumentInsertDuplicateKeyError) as raised:
        _store(database_manager, database_name, TAKEN_NAME)

    assert raised.value.key_pattern == EXPECTED_PATTERN
    assert raised.value.key_value == {'owner': OWNER_ID, 'name': TAKEN_NAME}
    assert _scratch.count_documents({}) == 1


def test_an_update_that_duplicates_the_index_is_the_typed_refusal(
    database_manager: MongoDatabaseManager, database_name: str, _scratch,
) -> None:
    """update_one: a rename onto a taken name, refused by the same index, and the document unchanged."""
    _store(database_manager, database_name, TAKEN_NAME)
    renamed: int = _store(database_manager, database_name, FREE_NAME)

    with pytest.raises(DocumentUpdateDuplicateKeyError) as raised:
        database_manager.update(COLLECTION, database_name, {'public_id': renamed}, {'name': TAKEN_NAME})

    assert raised.value.key_pattern == EXPECTED_PATTERN
    assert raised.value.key_value == {'owner': OWNER_ID, 'name': TAKEN_NAME}
    assert _scratch.find_one({'public_id': renamed})['name'] == FREE_NAME


def test_an_unordered_insert_many_reports_its_duplicate_typed(
    database_manager: MongoDatabaseManager, database_name: str,
) -> None:
    """
    The driver raises a BulkWriteError there, never a DuplicateKeyError

    Before the refusal was typed that branch was unreachable, and a duplicate in a batch came out as
    a plain "failed to insert many documents".
    """
    _store(database_manager, database_name, TAKEN_NAME)

    with pytest.raises(DocumentInsertDuplicateKeyError) as raised:
        database_manager.insert_many(COLLECTION, database_name, [{'owner': OWNER_ID, 'name': TAKEN_NAME}])

    assert isinstance(raised.value, DocumentInsertError)
    assert raised.value.key_pattern == EXPECTED_PATTERN


def test_the_refusal_is_found_through_the_manager_layer(
    database_manager: MongoDatabaseManager, database_name: str,
) -> None:
    """What a route catches is the manager's error; the refusal is still findable by type beneath it."""
    manager = BaseManager(COLLECTION, database_manager, database_name)
    manager.insert({'owner': OWNER_ID, 'name': TAKEN_NAME})

    with pytest.raises(BaseManagerInsertError) as raised:
        manager.insert({'owner': OWNER_ID, 'name': TAKEN_NAME})

    duplicate = find_cause(raised.value, DocumentDuplicateKeyError)

    assert isinstance(duplicate, DocumentInsertDuplicateKeyError)
    assert duplicate.key_pattern == EXPECTED_PATTERN
