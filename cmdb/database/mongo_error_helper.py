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
Reads what a failed MongoDB write means - the size limit, a duplicate key, and the typed error an insert raises

Pure functions over the driver's errors: no database access, so each is testable on a constructed error. The
database manager and its counter half sort every write failure through them
"""
from typing import Any

from pymongo.errors import BulkWriteError, ConnectionFailure, DocumentTooLarge, DuplicateKeyError, OperationFailure

from cmdb.database.database_constants import (
    DOCUMENT_TOO_LARGE_MESSAGE,
    MONGO_DOCUMENT_TOO_LARGE_ERROR_CODES,
    MONGO_DUPLICATE_KEY_ERROR_CODE,
    MONGO_ERROR_CODE_KEY,
    MONGO_ERROR_KEY_PATTERN,
    MONGO_ERROR_KEY_VALUE,
    MONGO_LOCK_TIMEOUT_ERROR_CODE,
    MONGO_WRITE_ERRORS_KEY,
    PUBLIC_ID_FIELD,
)

from cmdb.errors.database import (
    DocumentInsertDuplicateKeyError,
    DocumentInsertError,
    DocumentInsertTooLargeError,
    DocumentLockTimeoutError,
    DocumentNetworkError,
)
# -------------------------------------------------------------------------------------------------------------------- #

def is_document_too_large(err: BaseException) -> bool:
    """
    Decides whether a write failed because a document would exceed MongoDB's 16 MB document limit

    The limit is reported three ways, depending on who notices: the driver refuses a document it would have to
    send whole (``DocumentTooLarge`` - an insert, a replace, an ``$set`` carrying the oversize value), the server
    refuses the RESULT of an update that grew the document (an ``OperationFailure`` / ``WriteError`` with code
    10334, or 17419 on older servers), and a bulk write reports the same code per failed operation. Only the
    first is not a ``PyMongoError`` - it subclasses ``bson.errors.InvalidDocument``

    Args:
        err (BaseException): The error the write raised

    Returns:
        bool: True when the write failed on the document size limit
    """
    if isinstance(err, DocumentTooLarge):
        return True

    if isinstance(err, BulkWriteError):
        write_errors: list[dict[str, Any]] = (err.details or {}).get(MONGO_WRITE_ERRORS_KEY) or []

        return any(entry.get(MONGO_ERROR_CODE_KEY) in MONGO_DOCUMENT_TOO_LARGE_ERROR_CODES for entry in write_errors)

    return isinstance(err, OperationFailure) and err.code in MONGO_DOCUMENT_TOO_LARGE_ERROR_CODES


def typed_insert_failure(err: BaseException, collection: str) -> Exception:
    """
    The error an insert raises for one failed ``insert_one``, sorted by what failed

    The one sorting both insert paths share - the retry loop and ``skip_public`` - so a failure means the same on
    either. Checked in this order:

    * a duplicate key -> the typed ``DocumentInsertDuplicateKeyError``, naming the violated index and value (the
      retry loop has already handled a public_id clash it could retry)
    * a lock timeout (code 24) -> ``DocumentLockTimeoutError``
    * the 16 MB document limit -> ``DocumentInsertTooLargeError`` (see ``is_document_too_large``)
    * a lost connection - ``ConnectionFailure``, which ``AutoReconnect``, ``NetworkTimeout`` and
      ``ServerSelectionTimeoutError`` all are -> ``DocumentNetworkError``
    * anything else, every other ``PyMongoError`` included -> ``DocumentInsertError``

    The two transient ones are what every wrapping layer lets through to the app's error handlers (423 / 503); a
    refusal no retry can fix must never be one of them

    Args:
        err (BaseException): The error ``insert_one`` raised
        collection (str): Name of the collection the insert was for

    Returns:
        Exception: The error to raise, for the caller to raise ``from err``
    """
    if isinstance(err, DuplicateKeyError):
        key_pattern, key_value = duplicate_key_details(err)

        return DocumentInsertDuplicateKeyError(
            duplicate_key_message(collection, key_pattern, key_value), key_pattern=key_pattern, key_value=key_value,
        )

    if isinstance(err, OperationFailure) and err.code == MONGO_LOCK_TIMEOUT_ERROR_CODE:
        return DocumentLockTimeoutError(f"Lock timeout: {err}")

    if is_document_too_large(err):
        return DocumentInsertTooLargeError(DOCUMENT_TOO_LARGE_MESSAGE.format(collection=collection, err=err))

    if isinstance(err, ConnectionFailure):
        return DocumentNetworkError(f"Network/timeout error while inserting document: {err}")

    return DocumentInsertError(f"Failed to insert document into collection '{collection}': {err}")


def is_public_id_conflict(err: DuplicateKeyError) -> bool:
    """
    Decides whether a duplicate-key error can be resolved by taking a new public_id

    Only a violation of the public_id index can: retrying any other unique constraint just burns
    public_ids from the collection's counter and ends in a misleading "duplicate key attempts" error,
    when the truthful answer is that the document itself duplicates one already stored.

    A compound index that merely happens to contain public_id does not count either - a fresh id
    would not make the rest of the key unique. When MongoDB reports no key pattern at all (pre-4.2
    servers, or an error raised by something other than the server) the violated index cannot be
    identified, and the historical behaviour - retry - is kept

    Args:
        err (DuplicateKeyError): The error raised by the insert

    Returns:
        bool: True if a fresh public_id may resolve the conflict, False if the document is a genuine
            duplicate of an existing one
    """
    key_pattern: Any = (err.details or {}).get(MONGO_ERROR_KEY_PATTERN)

    if not isinstance(key_pattern, dict) or not key_pattern:
        return True

    return set(key_pattern) == {PUBLIC_ID_FIELD}


def duplicate_key_details(err: DuplicateKeyError | BulkWriteError) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    Reads which unique index a refused write violated, and with which value

    A single-document write reports it on the error itself; an unordered ``insert_many`` reports one
    entry per refused document under ``writeErrors`` - the first duplicate-key entry is the one named

    Args:
        err (DuplicateKeyError | BulkWriteError): The error the driver raised

    Returns:
        tuple[dict[str, Any], dict[str, Any]]: The violated index's key pattern and the duplicated key
            value, each empty when the server did not report it
    """
    details: dict[str, Any] = err.details or {}

    if isinstance(err, BulkWriteError):
        details = next(
            (write_error for write_error in details.get(MONGO_WRITE_ERRORS_KEY) or []
             if write_error.get(MONGO_ERROR_CODE_KEY) == MONGO_DUPLICATE_KEY_ERROR_CODE),
            {},
        )

    key_pattern: Any = details.get(MONGO_ERROR_KEY_PATTERN)
    key_value: Any = details.get(MONGO_ERROR_KEY_VALUE)

    return (
        key_pattern if isinstance(key_pattern, dict) else {},
        key_value if isinstance(key_value, dict) else {},
    )


def is_duplicate_key_bulk_error(err: BulkWriteError) -> bool:
    """
    Answers whether every document an unordered bulk insert refused was refused as a duplicate

    Only then is the batch's failure a duplicate: a batch that also hit a validation or any other
    error is reported as the insert failure it is

    Args:
        err (BulkWriteError): The error the driver raised

    Returns:
        bool: True when there are write errors and every one carries the duplicate-key code
    """
    write_errors: list[dict[str, Any]] = (err.details or {}).get(MONGO_WRITE_ERRORS_KEY) or []

    return bool(write_errors) and all(
        write_error.get(MONGO_ERROR_CODE_KEY) == MONGO_DUPLICATE_KEY_ERROR_CODE for write_error in write_errors
    )


def duplicate_key_message(collection: str, key_pattern: dict[str, Any], key_value: dict[str, Any]) -> str:
    """
    The log- and trace-facing text of a duplicate-key refusal

    Args:
        collection (str): The collection the write addressed
        key_pattern (dict[str, Any]): The violated index's keys
        key_value (dict[str, Any]): The duplicated value

    Returns:
        str: E.g. ``Duplicate key error in collection 'x': {'name': 'a'} already exists (index on ['name'])``
    """
    return (
        f"Duplicate key error in collection '{collection}': {key_value} already exists "
        f"(index on {sorted(key_pattern)})"
    )
