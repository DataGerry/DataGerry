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
Integration tests for BaseManager primitives on string/_id-keyed collections against a real MongoDB

Covers the criteria-keyed upsert helper (insert when nothing matches carrying the criteria keys,
update in place when one matches, the upserted_id signal) and the skip_public insert path for a
document that legitimately carries no public_id. Unlike upsert_set / the default insert path these
are not tied to an integer public_id, so an _id-keyed singleton is exercised here
"""
import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.base_manager import BaseManager
# -------------------------------------------------------------------------------------------------------------------- #

COLLECTION: str = 'test.upsertScratch'


@pytest.fixture(name='manager')
def fixture_manager(database_manager: MongoDatabaseManager, database_name: str) -> BaseManager:
    """Provides a BaseManager bound to a scratch collection in the test database"""
    return BaseManager(COLLECTION, database_manager, database_name)


@pytest.fixture(autouse=True)
def _cleanup(database_manager: MongoDatabaseManager, database_name: str):
    """Clears the scratch collection after each test"""
    yield
    database_manager.get_collection(COLLECTION, database_name).delete_many({})


def test_upsert_inserts_when_no_match(
    manager: BaseManager,
    database_manager: MongoDatabaseManager,
    database_name: str,
) -> None:
    """With no matching document, a new one is inserted carrying both criteria keys and data"""
    result = manager.upsert({'_id': 'singleton'}, {'value': 1})

    assert result.upserted_id == 'singleton'

    stored = database_manager.get_collection(COLLECTION, database_name).find_one({})
    assert stored == {'_id': 'singleton', 'value': 1}


def test_upsert_updates_in_place_when_match(
    manager: BaseManager,
    database_manager: MongoDatabaseManager,
    database_name: str,
) -> None:
    """A second upsert on the same key updates the document in place and never appends"""
    manager.upsert({'_id': 'singleton'}, {'value': 1})
    result = manager.upsert({'_id': 'singleton'}, {'value': 2})

    assert result.upserted_id is None

    collection = database_manager.get_collection(COLLECTION, database_name)
    assert collection.count_documents({}) == 1
    assert collection.find_one({})['value'] == 2


def test_upsert_only_sets_named_fields(
    manager: BaseManager,
    database_manager: MongoDatabaseManager,
    database_name: str,
) -> None:
    """An update sets only the supplied fields, leaving other existing fields untouched"""
    manager.upsert({'_id': 'singleton'}, {'value': 1, 'keep': 'me'})
    manager.upsert({'_id': 'singleton'}, {'value': 2})

    stored = database_manager.get_collection(COLLECTION, database_name).find_one({})
    assert stored == {'_id': 'singleton', 'value': 2, 'keep': 'me'}


def test_insert_skip_public_without_public_id_persists_and_returns_none(
    manager: BaseManager,
    database_manager: MongoDatabaseManager,
    database_name: str,
) -> None:
    """skip_public inserts a document that carries no public_id as-is and returns None"""
    result = manager.insert({'_id': 'string-keyed', 'value': 1}, skip_public=True)

    assert result is None

    stored = database_manager.get_collection(COLLECTION, database_name).find_one({})
    assert stored == {'_id': 'string-keyed', 'value': 1}
