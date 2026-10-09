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
This module contains all Database error classes
"""
from typing import Any

# -------------------------------------------------------------------------------------------------------------------- #

class DataBaseError(Exception):
    """
    Raised to catch all Database related errors
    """
    def __init__(self, err: str | Exception) -> None:
        """
        Raised to catch all Database related errors

        Takes the wrapped exception itself as readily as a message: str() reads the same either way,
        but args[0] then carries the error being wrapped, which a caller can branch on

        Args:
            err (str | Exception): The message, or the error being wrapped
        """
        super().__init__(err)

# ------------------------------------------------- DATABASE - ERRORS ------------------------------------------------ #

class DatabaseConnectionError(DataBaseError):
    """
    Error if connection to database broke up or unable to connect
    """


class DatabaseAlreadyExistsError(DataBaseError):
    """
    Error when database already exists
    """


class DatabaseNotFoundError(DataBaseError):
    """
    Error when database does not exist
    """


class SetDatabaseError(DataBaseError):
    """
    Error if database could not be set for a connector
    """


class CollectionAlreadyExistsError(DataBaseError):
    """
    Raised when trying to create a collection that alrady exists
    """


class GetCollectionError(DataBaseError):
    """
    Raised when a collection could not be retrieved
    """


class DeleteCollectionError(DataBaseError):
    """
    Raised when a collection could not be deleted
    """


class CreateIndexesError(DataBaseError):
    """
    Raised when indexes for a collection could not be created
    """


class GetIndexesError(DataBaseError):
    """
    Raised when indexes for a collection could not be retrieved
    """


class DropIndexError(DataBaseError):
    """
    Raised when an index of a collection could not be dropped
    """


class DocumentInsertError(DataBaseError):
    """
    Raised if a document could not be created in a collection
    """


class DocumentUpdateError(DataBaseError):
    """
    Raised if a document could not be updated in a collection
    """


class DocumentDuplicateKeyError(DataBaseError):
    """
    Raised when a write was refused because it would duplicate a unique index

    The marker every duplicate-key refusal shares, whichever write raised it: a route catching the
    manager error of its operation finds it with ``cmdb.utils.find_cause`` and can answer "that name is
    taken" instead of reporting a database failure. It carries the violated index's key pattern and the
    duplicated key value as the server reported them, so no caller has to read them out of the message
    """
    def __init__(
            self,
            err: str | Exception,
            key_pattern: dict[str, Any] | None = None,
            key_value: dict[str, Any] | None = None) -> None:
        """
        Raised when a write was refused because it would duplicate a unique index

        Args:
            err (str | Exception): The message, or the error being wrapped
            key_pattern (dict[str, Any] | None): The violated index's keys, e.g. ``{'object_id': 1, ...}``;
                empty when the server did not report them. Defaults to None
            key_value (dict[str, Any] | None): The duplicated value per key; empty when not reported.
                Defaults to None
        """
        super().__init__(err)
        self.key_pattern: dict[str, Any] = dict(key_pattern or {})
        self.key_value: dict[str, Any] = dict(key_value or {})


class DocumentInsertDuplicateKeyError(DocumentInsertError, DocumentDuplicateKeyError):
    """
    Raised if an insert would duplicate a unique index - still a DocumentInsertError to every caller
    """


class DocumentUpdateDuplicateKeyError(DocumentUpdateError, DocumentDuplicateKeyError):
    """
    Raised if an update would duplicate a unique index - still a DocumentUpdateError to every caller
    """


class DocumentTooLargeError(DataBaseError):
    """
    Raised when a write was refused because a document would exceed MongoDB's 16 MB document limit

    The marker every such refusal shares, whichever write raised it and whether the driver refused the document
    before sending it or the server refused the result of an update: a route catching the manager error of its
    operation finds it with ``cmdb.utils.find_cause`` and answers "the document is too large" instead of
    reporting a database failure
    """


class DocumentInsertTooLargeError(DocumentInsertError, DocumentTooLargeError):
    """
    Raised if an insert would exceed the document size limit - still a DocumentInsertError to every caller
    """


class DocumentUpdateTooLargeError(DocumentUpdateError, DocumentTooLargeError):
    """
    Raised if an update would exceed the document size limit - still a DocumentUpdateError to every caller
    """


class DocumentDeleteError(DataBaseError):
    """
    Raised if a document could not be deleted from a collection
    """


class DocumentGetError(DataBaseError):
    """
    Raised if a document could not be retrieved from a collection
    """


class DocumentAggregationError(DataBaseError):
    """
    Raised if an aggregation operation fails
    """


class DocumentQueryTimeLimitError(DocumentAggregationError):
    """
    Raised when the server stopped an aggregation because it ran past its time budget (``maxTimeMS``)

    Still a DocumentAggregationError to every caller. A route finds it in the error chain with
    ``cmdb.utils.find_cause`` and answers that the query took too long, naming the budget it carries

    Attributes:
        time_limit_ms (int): The budget the aggregation ran past, in milliseconds
    """
    def __init__(self, err: str | Exception, time_limit_ms: int) -> None:
        """
        Raised when the server stopped an aggregation because it ran past its time budget

        Args:
            err (str | Exception): The message, or the driver's ExecutionTimeout
            time_limit_ms (int): The budget the aggregation ran past, in milliseconds
        """
        super().__init__(err)
        self.time_limit_ms: int = time_limit_ms


class PublicIdCounterInitError(DataBaseError):
    """
    Raised if a public_id counter could not be initialised
    """


class CollectionInitError(DataBaseError):
    """
    Raised when a collection could not be initialised
    """


class DocumentLockTimeoutError(DataBaseError):
    """
    Raised when a MongoDB LockTimeout occurs
    """


class DocumentNetworkError(DataBaseError):
    """
    Raised when an insert fails due to network or timeout issues
    """


# The two failures that say nothing about the request: the operation may succeed if simply repeated. Every
# layer that wraps errors lets these through unchanged, so the route layer can answer them as a server
# error (423 / 503, the app's error handlers in responses/error_handlers.py) instead of as the operation's own -
# usually 400 - failure
TRANSIENT_DATABASE_ERRORS: tuple[type[DataBaseError], ...] = (DocumentLockTimeoutError, DocumentNetworkError)
