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
Integration tests for the ``skip_public`` insert's failures, against a real MongoDB

The real server raises the duplicate: a second document under a unique index, and a second document under the
same ``_id``. Each is the typed duplicate refusal - never a network error, which every layer above would treat as
worth retrying - and the stored document is unchanged
"""
import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.errors.database import DocumentInsertDuplicateKeyError, DocumentNetworkError
# -------------------------------------------------------------------------------------------------------------------- #

COLLECTION: str = 'test.insert_failure_sorting'
UNIQUE_KEY: str = 'name'
STORED_NAME: str = 'first'


@pytest.fixture(name='collection', autouse=True)
def fixture_collection(database_manager: MongoDatabaseManager, database_name: str):
    """A scratch collection with a unique index and one stored document, dropped after"""
    collection = database_manager.get_collection(COLLECTION, database_name)
    collection.drop()
    collection.create_index(UNIQUE_KEY, unique=True)
    collection.insert_one({'_id': 'one', 'public_id': 1, UNIQUE_KEY: STORED_NAME})
    yield collection
    collection.drop()


def test_a_unique_index_clash_is_the_typed_refusal(database_manager, database_name, collection) -> None:
    """Naming the violated index and the value"""
    with pytest.raises(DocumentInsertDuplicateKeyError) as caught:
        database_manager.insert(COLLECTION, database_name, {'public_id': 2, UNIQUE_KEY: STORED_NAME}, skip_public=True)

    assert not isinstance(caught.value, DocumentNetworkError)
    assert caught.value.key_pattern == {UNIQUE_KEY: 1}
    assert collection.count_documents({}) == 1


def test_a_document_already_stored_under_its_id_is_the_typed_refusal(database_manager, database_name,
                                                                      collection) -> None:
    """What an undo re-insert would meet if the document were put back meanwhile"""
    with pytest.raises(DocumentInsertDuplicateKeyError):
        database_manager.insert(COLLECTION, database_name, {'_id': 'one', 'public_id': 1, UNIQUE_KEY: 'other'},
                                skip_public=True)

    assert collection.find_one({'_id': 'one'})[UNIQUE_KEY] == STORED_NAME


def test_a_free_document_is_stored(database_manager, database_name, collection) -> None:
    """The success path answers the document's own id"""
    assert database_manager.insert(COLLECTION, database_name, {'public_id': 3, UNIQUE_KEY: 'free'},
                                   skip_public=True) == 3
    assert collection.count_documents({}) == 2
