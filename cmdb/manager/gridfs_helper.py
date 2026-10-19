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
What every caller of GridFS shares: batch deletion, and the reading of a failed GridFS call

GridFS itself deletes one file per call. A batch is two deletes instead: the chunks of every file first, then the
file documents. The order decides what a failure between the two leaves behind: file documents whose content is
gone, which every caller finds again by reading the file documents and deletes on a repeated run - never chunks
without a file document, which nothing would ever find again

A GridFS call goes to the driver directly, not through the database manager, so its failure arrives as the
driver's own error. ``gridfs_failure`` and ``raise_gridfs_insert_failure`` sort it the way the database manager sorts
its own: a lost server or a lock timeout becomes the transient error the app answers 503 / 423, a refused write
the typed error a route can read, anything else the caller's manager error
"""
from typing import Any, NoReturn

from bson.errors import InvalidDocument
from gridfs.errors import FileExists
from pymongo.errors import ConnectionFailure, DuplicateKeyError, OperationFailure, PyMongoError

from cmdb.database.database_constants import MONGO_ID_FIELD, MONGO_LOCK_TIMEOUT_ERROR_CODE
from cmdb.database.mongo_error_helper import typed_insert_failure
from cmdb.manager.base_manager import BaseManager
from cmdb.framework.media_library.media_file_keys import (
    GRIDFS_CHUNK_FILE_KEY,
    GRIDFS_CHUNKS_SUFFIX,
    GRIDFS_FILES_SUFFIX,
)

from cmdb.errors.database import TRANSIENT_DATABASE_ERRORS, DocumentLockTimeoutError, DocumentNetworkError
# -------------------------------------------------------------------------------------------------------------------- #

#: What a GridFS read, delete or metadata write raises when it fails - ``NoFile``, ``FileExists`` and
#: ``CorruptGridFile`` are ``PyMongoError`` subclasses too. A caller that treats one of them as an answer
#: (``NoFile`` = absent) catches it first
GRIDFS_DRIVER_ERRORS: tuple[type[Exception], ...] = (PyMongoError,)

#: What writing a GridFS file raises when it fails: the driver's errors, and ``DocumentTooLarge`` - a file document
#: over the 16 MB limit, which is a ``bson`` ``InvalidDocument`` and no ``PyMongoError``
GRIDFS_WRITE_ERRORS: tuple[type[Exception], ...] = (PyMongoError, InvalidDocument)


def gridfs_failure(err: BaseException, manager_error: type[Exception]) -> Exception:
    """
    The error a manager raises for a failed GridFS call, sorted by what failed

    * a lock timeout (code 24) -> ``DocumentLockTimeoutError``
    * a lost connection - ``ConnectionFailure``, which ``AutoReconnect``, ``NetworkTimeout`` and
      ``ServerSelectionTimeoutError`` all are -> ``DocumentNetworkError``
    * anything else -> ``manager_error``

    The two transient ones are raised unwrapped, for the app's handlers to answer 423 / 503

    Args:
        err (BaseException): The driver error the GridFS call raised
        manager_error (type[Exception]): The manager's error for a failure of this operation

    Returns:
        Exception: A new error to raise, for the caller to raise ``from err``
    """
    if isinstance(err, OperationFailure) and err.code == MONGO_LOCK_TIMEOUT_ERROR_CODE:
        return DocumentLockTimeoutError(f"Lock timeout: {err}")

    if isinstance(err, ConnectionFailure):
        return DocumentNetworkError(f"Network/timeout error during a GridFS operation: {err}")

    return manager_error(err)


def raise_gridfs_insert_failure(err: BaseException, collection: str, manager_error: type[Exception]) -> NoReturn:
    """
    Raises the error a manager raises for a GridFS file that could not be written

    The write is sorted like any insert (``typed_insert_failure``), so a duplicate key or the document size limit
    reaches the route as the typed error it looks for in the cause chain. GridFS reports a duplicate key of the
    file document as its own ``FileExists``, raised while handling the driver's ``DuplicateKeyError`` - that one is
    what is sorted, so the violated index is still named. The transient errors are raised unwrapped, for the app's
    handlers to answer 423 / 503; every other one is wrapped in ``manager_error``, with the typed error as its cause

    Args:
        err (BaseException): The error writing the file raised
        collection (str): The GridFS files collection the write was for
        manager_error (type[Exception]): The manager's insert error

    Raises:
        DocumentLockTimeoutError: When the write ran into a lock timeout
        DocumentNetworkError: When the database server could not be reached
        Exception: ``manager_error`` around the typed insert error, for every other failure
    """
    driver_error: BaseException = err

    if isinstance(err, FileExists) and isinstance(err.__context__, DuplicateKeyError):
        driver_error = err.__context__

    typed: Exception = typed_insert_failure(driver_error, collection)

    if isinstance(typed, TRANSIENT_DATABASE_ERRORS):
        raise typed from err

    typed.__cause__ = err

    raise manager_error(typed) from typed


def delete_gridfs_files(manager: BaseManager, bucket: str, file_ids: list[Any]) -> int:
    """
    Deletes a batch of GridFS files of one bucket, their chunks first

    Args:
        manager (BaseManager): Any manager of the database holding the bucket
        bucket (str): The GridFS bucket name, without the '.files' / '.chunks' suffix
        file_ids (list[Any]): The `_id`s of the file documents to delete

    Raises:
        BaseManagerDeleteError: When the chunks or the file documents could not be deleted - after a failure on
            the file documents, the chunks are already gone

    Returns:
        int: How many file documents were deleted
    """
    if not file_ids:
        return 0

    manager.delete_many_from_other_collection(
        f'{bucket}{GRIDFS_CHUNKS_SUFFIX}', {GRIDFS_CHUNK_FILE_KEY: {'$in': file_ids}},
    )

    return manager.delete_many_from_other_collection(
        f'{bucket}{GRIDFS_FILES_SUFFIX}', {MONGO_ID_FIELD: {'$in': file_ids}},
    ).deleted_count
