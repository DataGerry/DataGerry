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
Integration tests for MongoDatabaseManager's reading of the 16 MB document limit, against a real MongoDB

The unit tier stubs the errors; this one makes the server and the driver raise them for real, in each of the
three shapes: the driver refusing a document it would send whole, the server refusing the RESULT of an update
that grew a document past the limit, and an unordered insert_many reporting it. Every one arrives as the typed
error, and the document is left as it was
"""
from typing import Any

import pytest
from pymongo import UpdateOne

from cmdb.database import MongoDatabaseManager
from cmdb.errors.database import DocumentInsertTooLargeError, DocumentUpdateTooLargeError
from cmdb.interface.request_limits_constants import MEBIBYTE
# -------------------------------------------------------------------------------------------------------------------- #

COLLECTION: str = 'test.document_too_large'
DOCUMENT_ID: int = 1
OVERSIZE: str = 'x' * (17 * MEBIBYTE)
# Two of these fit in one document; three do not - so an update can grow a stored document past the limit
NINE_MB: str = 'y' * (9 * MEBIBYTE)


@pytest.fixture(name='collection', autouse=True)
def fixture_collection(database_manager: MongoDatabaseManager, database_name: str):
    """A scratch collection holding one 9 MB document, dropped after"""
    collection = database_manager.get_collection(COLLECTION, database_name)
    collection.delete_many({})
    collection.insert_one({'public_id': DOCUMENT_ID, 'first': NINE_MB})
    yield collection
    collection.drop()


def _stored(collection: Any) -> set[str]:
    """The keys the stored document carries"""
    return set(collection.find_one({'public_id': DOCUMENT_ID})) - {'_id'}


def test_an_insert_refused_by_the_driver(database_manager, database_name, collection) -> None:
    """Nothing is stored"""
    with pytest.raises(DocumentInsertTooLargeError):
        database_manager.insert(COLLECTION, database_name, {'public_id': 2, 'value': OVERSIZE}, skip_public=True)

    assert collection.count_documents({'public_id': 2}) == 0


def test_an_insert_many_refused(database_manager, database_name, collection) -> None:
    """The unordered batch's refusal"""
    with pytest.raises(DocumentInsertTooLargeError):
        database_manager.insert_many(COLLECTION, database_name, [{'public_id': 3, 'value': OVERSIZE}], skip_public=True)


def test_an_update_whose_result_outgrows_the_limit(database_manager, database_name, collection) -> None:
    """Refused by the server, and the document keeps what it had"""
    with pytest.raises(DocumentUpdateTooLargeError):
        database_manager.update(COLLECTION, database_name, {'public_id': DOCUMENT_ID}, {'second': NINE_MB})

    assert _stored(collection) == {'public_id', 'first'}


def test_an_update_many_whose_result_outgrows_the_limit(database_manager, database_name, collection) -> None:
    """The same refusal on the bulk update path"""
    with pytest.raises(DocumentUpdateTooLargeError):
        database_manager.update_many(COLLECTION, database_name, {'public_id': DOCUMENT_ID}, {'second': NINE_MB})

    assert _stored(collection) == {'public_id', 'first'}


def test_a_replace_refused_by_the_driver(database_manager, database_name, collection) -> None:
    """A replacement is sent whole"""
    with pytest.raises(DocumentUpdateTooLargeError):
        database_manager.replace(COLLECTION, database_name, {'public_id': DOCUMENT_ID}, {'value': OVERSIZE})

    assert _stored(collection) == {'public_id', 'first'}


def test_a_bulk_write_whose_result_outgrows_the_limit(database_manager, database_name, collection) -> None:
    """Reported per failed operation"""
    with pytest.raises(DocumentInsertTooLargeError):
        database_manager.bulk_write(
            COLLECTION, database_name, [UpdateOne({'public_id': DOCUMENT_ID}, {'$set': {'second': NINE_MB}})],
        )

    assert _stored(collection) == {'public_id', 'first'}
