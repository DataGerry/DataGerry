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
Unit tests for the database layer's reading of MongoDB's 16 MB document limit

Pure tests: no Mongo, the collection is a stub. Pinned: ``is_document_too_large`` recognises all three shapes the
limit is reported in (the driver's ``DocumentTooLarge``, a server ``OperationFailure`` / ``WriteError`` with
code 10334 or 17419, a ``BulkWriteError`` listing that code) and nothing else, and every write method answers it
with the typed ``Document{Insert,Update}TooLargeError`` - still the method's own error class to every caller -
instead of its generic failure
"""
from typing import Any, Callable
from unittest.mock import MagicMock

import pytest
from pymongo.errors import BulkWriteError, DocumentTooLarge, OperationFailure, WriteError

import cmdb.database.mongo_database_manager as mdm
from cmdb.database.mongo_database_manager import MongoDatabaseManager, is_document_too_large
from cmdb.database.database_constants import DOCUMENT_TOO_LARGE_MESSAGE, MONGO_DOCUMENT_TOO_LARGE_ERROR_CODES
from cmdb.errors.database import (
    DocumentInsertError,
    DocumentInsertTooLargeError,
    DocumentTooLargeError,
    DocumentUpdateError,
    DocumentUpdateTooLargeError,
)
# -------------------------------------------------------------------------------------------------------------------- #

DB: str = 'testdb'
COLLECTION: str = 'framework.objects'
BSON_OBJECT_TOO_LARGE: int = 10334
LEGACY_UPDATE_TOO_LARGE: int = 17419
UNRELATED_CODE: int = 121
DUPLICATE_KEY_CODE: int = 11000

# The collection methods a write may call
COLLECTION_WRITES: tuple[str, ...] = (
    'insert_one', 'insert_many', 'bulk_write', 'update_one', 'update_many', 'replace_one', 'find_one_and_update',
)


@pytest.fixture(name='mgr')
def fixture_mgr() -> MongoDatabaseManager:
    """A MongoDatabaseManager without its real __init__ (no connector, no keepalive thread)"""
    manager = MongoDatabaseManager.__new__(MongoDatabaseManager)
    manager.db_name = DB
    manager.connector = MagicMock(name='connector')
    manager._keepalive_thread = None  # pylint: disable=protected-access

    return manager


def _failing_collection(mgr: MongoDatabaseManager, error: Exception) -> MagicMock:
    """Every write of the stub collection raises the given error"""
    collection = MagicMock(name='collection')

    for method in COLLECTION_WRITES:
        getattr(collection, method).side_effect = error

    mgr.get_collection = MagicMock(return_value=collection)

    return collection


class TestIsDocumentTooLarge:
    """The three shapes the limit is reported in, and nothing else"""

    def test_the_drivers_refusal(self) -> None:
        """Raised before anything is sent - and no PyMongoError, which is why it needs its own reading"""
        assert is_document_too_large(DocumentTooLarge('BSON document too large'))

    @pytest.mark.parametrize('code', sorted(MONGO_DOCUMENT_TOO_LARGE_ERROR_CODES))
    def test_the_servers_refusal(self, code: int) -> None:
        """An update whose result outgrew the limit, as OperationFailure and as its WriteError subclass"""
        assert is_document_too_large(OperationFailure('too large', code=code))
        assert is_document_too_large(WriteError('too large', code=code))

    def test_a_bulk_write_naming_the_code(self) -> None:
        """One failed operation is enough"""
        err = BulkWriteError({'writeErrors': [{'code': DUPLICATE_KEY_CODE}, {'code': BSON_OBJECT_TOO_LARGE}]})

        assert is_document_too_large(err)

    @pytest.mark.parametrize('err', [
        OperationFailure('validation', code=UNRELATED_CODE),
        BulkWriteError({'writeErrors': [{'code': DUPLICATE_KEY_CODE}]}),
        BulkWriteError({}),
        RuntimeError('boom'),
    ], ids=['other-code', 'bulk-duplicate', 'bulk-without-details', 'not-a-mongo-error'])
    def test_anything_else_is_not(self, err: Exception) -> None:
        """A failure that is not the size limit keeps its own answer"""
        assert not is_document_too_large(err)

    def test_both_codes_are_declared(self) -> None:
        """BSONObjectTooLarge, and the code older servers report"""
        assert MONGO_DOCUMENT_TOO_LARGE_ERROR_CODES == {BSON_OBJECT_TOO_LARGE, LEGACY_UPDATE_TOO_LARGE}


class TestTheTypedErrors:
    """Still the operation's own error to every caller, and findable by the shared marker"""

    @pytest.mark.parametrize('typed, base', [
        (DocumentInsertTooLargeError, DocumentInsertError),
        (DocumentUpdateTooLargeError, DocumentUpdateError),
    ])
    def test_each_is_its_operations_error_and_the_marker(self, typed: type, base: type) -> None:
        """An existing `except DocumentInsertError` keeps catching it"""
        assert issubclass(typed, base)
        assert issubclass(typed, DocumentTooLargeError)


INSERT_WRITES: list[Any] = [
    pytest.param(lambda mgr: mgr.insert(COLLECTION, DB, {'public_id': 1}, skip_public=True), id='insert'),
    pytest.param(lambda mgr: mgr.insert_many(COLLECTION, DB, [{'public_id': 1}], skip_public=True), id='insert_many'),
    pytest.param(lambda mgr: mgr.bulk_write(COLLECTION, DB, [MagicMock()]), id='bulk_write'),
]
UPDATE_WRITES: list[Any] = [
    pytest.param(lambda mgr: mgr.update(COLLECTION, DB, {'public_id': 1}, {'v': 1}), id='update'),
    pytest.param(lambda mgr: mgr.replace(COLLECTION, DB, {'public_id': 1}, {'v': 1}), id='replace'),
    pytest.param(lambda mgr: mgr.upsert_set(COLLECTION, DB, {'public_id': 1, 'v': 1}), id='upsert_set'),
    pytest.param(lambda mgr: mgr.upsert(COLLECTION, DB, {'public_id': 1}, {'v': 1}), id='upsert'),
    pytest.param(lambda mgr: mgr.update_many(COLLECTION, DB, {}, {'v': 1}), id='update_many'),
    pytest.param(lambda mgr: mgr.update_many_raw(COLLECTION, DB, {}, {'$set': {'v': 1}}), id='update_many_raw'),
]
SIZE_REFUSALS: list[Any] = [
    pytest.param(DocumentTooLarge('BSON document too large'), id='driver'),
    pytest.param(WriteError('BSONObj size is invalid', code=BSON_OBJECT_TOO_LARGE), id='server'),
]


class TestEveryWriteAnswersTheTypedError:
    """The generic failure of each write method, read for the size limit first"""

    @pytest.mark.parametrize('error', SIZE_REFUSALS)
    @pytest.mark.parametrize('write', INSERT_WRITES)
    def test_an_insert(self, mgr: MongoDatabaseManager, write: Callable, error: Exception) -> None:
        """The message names the collection, and the original error is the cause"""
        _failing_collection(mgr, error)

        with pytest.raises(DocumentInsertTooLargeError) as caught:
            write(mgr)

        assert str(caught.value) == DOCUMENT_TOO_LARGE_MESSAGE.format(collection=COLLECTION, err=error)
        assert caught.value.__cause__ is error

    @pytest.mark.parametrize('error', SIZE_REFUSALS)
    @pytest.mark.parametrize('write', UPDATE_WRITES)
    def test_an_update(self, mgr: MongoDatabaseManager, write: Callable, error: Exception) -> None:
        """Every update shape - $set, replace, upsert, many, raw"""
        _failing_collection(mgr, error)

        with pytest.raises(DocumentUpdateTooLargeError) as caught:
            write(mgr)

        assert caught.value.__cause__ is error

    def test_an_insert_with_an_assigned_public_id(self, mgr: MongoDatabaseManager) -> None:
        """The counter path reads the server's refusal inside its retry loop, before the generic operation failure"""
        error = WriteError('BSONObj size is invalid', code=BSON_OBJECT_TOO_LARGE)
        _failing_collection(mgr, error)
        mgr.get_next_public_id = MagicMock(return_value=1)

        with pytest.raises(DocumentInsertTooLargeError) as caught:
            mgr.insert(COLLECTION, DB, {'value': 1})

        assert caught.value.__cause__ is error

    def test_a_bulk_insert_naming_the_code(self, mgr: MongoDatabaseManager) -> None:
        """insert_many reads its BulkWriteError for the size limit before the duplicate rule"""
        _failing_collection(mgr, BulkWriteError({'writeErrors': [{'code': BSON_OBJECT_TOO_LARGE}]}))

        with pytest.raises(DocumentInsertTooLargeError):
            mgr.insert_many(COLLECTION, DB, [{'public_id': 1}], skip_public=True)

    @pytest.mark.parametrize('write', INSERT_WRITES + UPDATE_WRITES)
    def test_another_failure_keeps_its_generic_error(self, mgr: MongoDatabaseManager, write: Callable) -> None:
        """The size reading adds a case, it changes no other answer"""
        _failing_collection(mgr, RuntimeError('boom'))

        with pytest.raises((DocumentInsertError, DocumentUpdateError)) as caught:
            write(mgr)

        assert not isinstance(caught.value, DocumentTooLargeError)


def test_the_module_reads_the_drivers_class() -> None:
    """The one shape that is not a PyMongoError is imported where it is read"""
    assert mdm.DocumentTooLarge is DocumentTooLarge
