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
Unit tests for cmdb.manager.gridfs_helper

delete_gridfs_files - pinned: the chunks of the batch go first, then the file documents, both by `_id` in one delete
each; the answer is the file documents' count; an empty batch deletes nothing; a failure on the file documents comes
after the chunks went

gridfs_failure / raise_gridfs_insert_failure - pinned: a lost server and a lock timeout become the transient errors
the app answers 503 / 423; GridFS's FileExists is read through to its DuplicateKeyError; the size limit and any other
refusal are the manager's error with the typed database error as its cause
"""
from unittest.mock import MagicMock, call

import pytest
from bson.errors import InvalidDocument
from gridfs.errors import FileExists
from pymongo.errors import (
    AutoReconnect,
    DocumentTooLarge,
    DuplicateKeyError,
    NetworkTimeout,
    OperationFailure,
    PyMongoError,
    ServerSelectionTimeoutError,
)

from cmdb.database.database_constants import MONGO_LOCK_TIMEOUT_ERROR_CODE
from cmdb.manager.gridfs_helper import (
    GRIDFS_DRIVER_ERRORS,
    GRIDFS_WRITE_ERRORS,
    delete_gridfs_files,
    gridfs_failure,
    raise_gridfs_insert_failure,
)
from cmdb.errors.database import (
    DocumentInsertDuplicateKeyError,
    DocumentInsertError,
    DocumentInsertTooLargeError,
    DocumentLockTimeoutError,
    DocumentNetworkError,
    DocumentTooLargeError,
)
from cmdb.errors.manager import BaseManagerDeleteError
# -------------------------------------------------------------------------------------------------------------------- #

BUCKET: str = 'test.bucket'
FILE_IDS: list[str] = ['oid-1', 'oid-2']
DELETED_DOCUMENTS: int = 2
DELETED_CHUNKS: int = 7


def _manager() -> MagicMock:
    """A manager whose chunk delete and document delete answer different counts"""
    manager = MagicMock()
    manager.delete_many_from_other_collection.side_effect = [
        MagicMock(deleted_count=DELETED_CHUNKS), MagicMock(deleted_count=DELETED_DOCUMENTS),
    ]

    return manager


def test_the_chunks_go_before_the_file_documents() -> None:
    """One delete each, by the file ids"""
    manager = _manager()

    delete_gridfs_files(manager, BUCKET, FILE_IDS)

    assert manager.delete_many_from_other_collection.call_args_list == [
        call(f'{BUCKET}.chunks', {'files_id': {'$in': FILE_IDS}}),
        call(f'{BUCKET}.files', {'_id': {'$in': FILE_IDS}}),
    ]


def test_the_answer_counts_the_file_documents() -> None:
    """Not the chunks"""
    assert delete_gridfs_files(_manager(), BUCKET, FILE_IDS) == DELETED_DOCUMENTS


def test_an_empty_batch_deletes_nothing() -> None:
    """No call at all"""
    manager = _manager()

    assert delete_gridfs_files(manager, BUCKET, []) == 0
    manager.delete_many_from_other_collection.assert_not_called()


def test_a_failed_document_delete_comes_after_the_chunks() -> None:
    """The documents stay to be found again by a repeated delete"""
    manager = MagicMock()
    failure = BaseManagerDeleteError('db')
    manager.delete_many_from_other_collection.side_effect = [MagicMock(deleted_count=DELETED_CHUNKS), failure]

    with pytest.raises(BaseManagerDeleteError) as caught:
        delete_gridfs_files(manager, BUCKET, FILE_IDS)

    assert caught.value is failure
    assert manager.delete_many_from_other_collection.call_count == len(FILE_IDS)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                    gridfs_failure                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
COLLECTION: str = 'test.bucket.files'


class _ManagerError(Exception):
    """A stand-in manager error"""


def _lock_timeout() -> OperationFailure:
    """The driver's lock timeout"""
    return OperationFailure('lock timeout', code=MONGO_LOCK_TIMEOUT_ERROR_CODE)


@pytest.mark.parametrize('failure', [
    AutoReconnect('gone'), NetworkTimeout('slow'), ServerSelectionTimeoutError('no server'),
])
def test_a_lost_server_is_the_network_error(failure: Exception) -> None:
    """Every ConnectionFailure becomes the error the app answers 503"""
    assert isinstance(gridfs_failure(failure, _ManagerError), DocumentNetworkError)


def test_a_lock_timeout_is_the_lock_error() -> None:
    """Code 24 becomes the error the app answers 423"""
    assert isinstance(gridfs_failure(_lock_timeout(), _ManagerError), DocumentLockTimeoutError)


@pytest.mark.parametrize('failure', [PyMongoError('refused'), OperationFailure('bad operator', code=2)])
def test_any_other_driver_error_is_the_managers(failure: Exception) -> None:
    """Wrapped in the caller's error, the driver's error as its argument"""
    result = gridfs_failure(failure, _ManagerError)

    assert isinstance(result, _ManagerError)
    assert result.args[0] is failure


def test_the_caught_tuples_hold_no_catch_all() -> None:
    """Only the driver's errors (and bson's for a write) - a programming error is never caught"""
    assert Exception not in GRIDFS_DRIVER_ERRORS + GRIDFS_WRITE_ERRORS
    assert set(GRIDFS_WRITE_ERRORS) == {PyMongoError, InvalidDocument}


# -------------------------------------------------------------------------------------------------------------------- #
#                                              raise_gridfs_insert_failure                                             #
# -------------------------------------------------------------------------------------------------------------------- #
def _file_exists() -> FileExists:
    """GridFS's FileExists, raised while handling the driver's DuplicateKeyError - as GridIn.close raises it"""
    try:
        try:
            raise DuplicateKeyError(
                'dup', code=11000, details={'keyPattern': {'filename': 1}, 'keyValue': {'filename': 'a'}},
            )
        except DuplicateKeyError as err:
            raise FileExists('file with _id x already exists') from err
    except FileExists as exists:
        return exists


def test_file_exists_is_read_as_the_duplicate_it_was_raised_for() -> None:
    """The violated index is named, and the typed duplicate is in the cause chain"""
    with pytest.raises(_ManagerError) as caught:
        raise_gridfs_insert_failure(_file_exists(), COLLECTION, _ManagerError)

    typed = caught.value.__cause__
    assert isinstance(typed, DocumentInsertDuplicateKeyError)
    assert typed.key_pattern == {'filename': 1}
    assert caught.value.args[0] is typed


def test_the_size_limit_is_the_typed_too_large() -> None:
    """A file document over 16 MB is DocumentTooLarge - the route's shared 400 looks for it in the chain"""
    with pytest.raises(_ManagerError) as caught:
        raise_gridfs_insert_failure(DocumentTooLarge('too big'), COLLECTION, _ManagerError)

    assert isinstance(caught.value.__cause__, DocumentInsertTooLargeError)
    assert isinstance(caught.value.__cause__, DocumentTooLargeError)


def test_any_other_write_failure_is_the_typed_insert_error() -> None:
    """The typed insert error is the cause, the driver's error beneath it"""
    failure = PyMongoError('refused')

    with pytest.raises(_ManagerError) as caught:
        raise_gridfs_insert_failure(failure, COLLECTION, _ManagerError)

    assert caught.value.__cause__.__class__ is DocumentInsertError
    assert caught.value.__cause__.__cause__ is failure


@pytest.mark.parametrize('failure, expected', [
    (AutoReconnect('gone'), DocumentNetworkError),
    (_lock_timeout(), DocumentLockTimeoutError),
])
def test_a_transient_write_failure_is_raised_unwrapped(failure: Exception, expected: type[Exception]) -> None:
    """Not the manager's error: the app's 503 / 423"""
    with pytest.raises(expected) as caught:
        raise_gridfs_insert_failure(failure, COLLECTION, _ManagerError)

    assert caught.value.__cause__ is failure
