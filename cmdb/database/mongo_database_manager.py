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
The MongoDatabaseManager: the connection, its keep-alive, and every document operation (insert, update, read, delete)

The database / collection / index administration and the public_id counters are its two mixins
(`mongo_database_admin_mixin`, `mongo_public_id_counter_mixin`); how a failed write is read is `mongo_error_helper`
"""
from logging import Logger, getLogger
import time
import threading
from typing import Any
from pymongo.errors import (
    BulkWriteError,
    DuplicateKeyError,
    NetworkTimeout,
    ConnectionFailure,
    ServerSelectionTimeoutError,
    ExecutionTimeout,
)
from pymongo.cursor import Cursor
from pymongo.results import DeleteResult, UpdateResult

from cmdb.database.mongo_connector import MongoConnector
from cmdb.database.mongo_database_admin_mixin import MongoDatabaseAdminMixin
from cmdb.database.mongo_error_helper import (
    duplicate_key_details,
    duplicate_key_message,
    is_document_too_large,
    is_duplicate_key_bulk_error,
    is_public_id_conflict,
    typed_insert_failure,
)
from cmdb.database.mongo_public_id_counter_mixin import MongoPublicIdCounterMixin
from cmdb.database.database_constants import (
    MAX_DUPLICATE_KEY_RETRIES,
    PUBLIC_ID_FIELD,
    BULK_WRITE_BATCH_SIZE,
    KEEPALIVE_PING_INTERVAL_SECONDS,
    DOCUMENT_TOO_LARGE_MESSAGE,
    MONGO_CONNECT_TIMEOUT_MS,
    MONGO_SERVER_SELECTION_TIMEOUT_MS,
    MONGO_SOCKET_TIMEOUT_MS,
    MONGO_MAX_TIME_OPTION,
)
from cmdb.database.retry import retry_operation

from cmdb.errors.database import (
    DocumentDeleteError,
    DocumentInsertError,
    DocumentInsertDuplicateKeyError,
    DocumentUpdateError,
    DocumentUpdateDuplicateKeyError,
    DocumentInsertTooLargeError,
    DocumentUpdateTooLargeError,
    DocumentGetError,
    DocumentAggregationError,
    DocumentQueryTimeLimitError,
    DocumentNetworkError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                             MongoDatabaseManager - CLASS                                             #
# -------------------------------------------------------------------------------------------------------------------- #
class MongoDatabaseManager(MongoDatabaseAdminMixin, MongoPublicIdCounterMixin):
    """
    PyMongo (MongoDB) implementation of the Database Manager

    Three parts, one object: the connection and the document operations live here, the database / collection / index
    administration in `MongoDatabaseAdminMixin`, the public_id counters in `MongoPublicIdCounterMixin`. Callers see
    one manager; how a failed write is read is `mongo_error_helper`'s
    """
    def __init__(self, host: str, port: int, database_name: str, mode: str = 'local', *,
                 start_keepalive: bool = True) -> None:
        """
        Initialises the MongoDatabaseManager, its connector, and starts the keep-alive thread unless told not to

        Args:
            host (str): MongoDB host
            port (int): MongoDB port
            database_name (str): Default database name used when a call omits an explicit db_name
            mode (str, optional): 'cloud' for the HOSTED cloud product, which connects with TLS; 'local' for
                everything else - on premise and the cloud product on a developer machine (``--cloud --local``)
                alike, both without TLS. Not the app's ``local_mode``. Defaults to 'local'.
            start_keepalive (bool): Whether to start the keep-alive thread now. A manager built in a process that
                forks afterwards passes False: a thread must not be running across a fork
                (`cmdb.process_management.fork_safety`). `reset_connection` starts it later, in the forked child.
                Defaults to True
        """
        self._keepalive_thread: threading.Thread | None = None
        self.host: str = host
        self.port: int = int(port)
        self.db_name: str = database_name
        self.mode: str = mode  # 'cloud' = hosted, with TLS; 'local' = on premise or a developer machine

        self.client_options: dict[str, Any] = {
            'connectTimeoutMS': MONGO_CONNECT_TIMEOUT_MS,
            'socketTimeoutMS': MONGO_SOCKET_TIMEOUT_MS,
            'serverSelectionTimeoutMS': MONGO_SERVER_SELECTION_TIMEOUT_MS,
            'maxIdleTimeMS': 30000,
            'retryReads': True,  # Enable retryable reads (helpful for fault tolerance)
            'retryWrites': True,
            'minPoolSize': 1,
            'maxPoolSize': 25,  # Maximum number of connections in the connection pool
            'wtimeoutMS': 2500,  # Timeout for waiting for write acknowledgment
            'readPreference': 'primaryPreferred',  # Read from the primary node by default
        }

        # Only enable SSL if in cloud mode
        if self.mode == 'cloud':
            self.client_options['ssl'] = True  # Enable SSL for cloud mode
        else:
            self.client_options['ssl'] = False  # Disable SSL for local mode

        self.connector: MongoConnector = MongoConnector(self.host, self.port, self.client_options)

        if start_keepalive:
            self._start_keepalive()


    @retry_operation
    def reset_connection(self) -> None:
        """
        Reset the MongoConnector to create a fresh MongoDB connection
        """
        self.connector.disconnect()
        self.connector = MongoConnector(self.host, self.port, self.client_options)

        # Restart keep-alive for the new client
        self._start_keepalive()

    def __enter__(self) -> "MongoDatabaseManager":
        """
        Support with-statement for connection management

        Returns:
            MongoDatabaseManager: This manager, so the block binds it with `as`
        """
        return self


    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> bool:
        """
        Closes the connection when the with-block ends

        The other half of the protocol: `__enter__` alone makes a `with` statement fail at ENTRY
        with a TypeError, so both are needed for the support this class advertises. Closing is the
        connector's own no-raise disconnect - a failed close reports the same disconnected status a
        successful one does (see the note on `MongoConnector.disconnect`).

        **The keep-alive thread outlives this block**, because it cannot be stopped: it re-creates the
        client within its ping interval, so a `with` block releases the
        connection rather than ending the manager's life

        Args:
            exc_type (Any): Exception class raised inside the block, or None
            exc_value (Any): The exception instance, or None
            traceback (Any): The traceback, or None

        Returns:
            bool: False - an exception raised inside the block is never suppressed
        """
        self.connector.disconnect()

        return False


    def _keepalive_once(self) -> None:
        """
        Pings the MongoDB client once, reporting a failure without raising

        **The client is read fresh on every call, and that is load-bearing.** `reset_connection`
        replaces `self.connector` while the keep-alive thread keeps running - the thread that survives
        the reset is the one that must follow the NEW connector, so caching the client in a local (or
        in the thread's closure) would leave the keep-alive pinging a disconnected client forever while
        the live one is never pinged.

        A failed ping is logged and nothing else: the loop has no state to change and no way to report,
        so a permanently unreachable database produces one warning per interval and `status()` stays
        the only thing that answers whether the connection is up
        """
        try:
            self.connector.client.admin.command("ping")
        except Exception as err:
            LOGGER.warning("[MongoDB KeepAlive] Ping failed: %s", err)


    def _start_keepalive(self) -> None:
        """
        Start a background thread that pings the MongoDB client every 50s

        **At most one thread per manager, and it is never replaced.** A live thread makes this a no-op,
        which is what `reset_connection` relies on: it calls this again after building a new connector,
        the existing thread is still running, and that thread picks the new client up on its next ping
        (see `_keepalive_once`). The thread is a daemon and has no stop flag, so it ends with the
        process - a disconnect does not stay closed
        """

        # Avoid multiple threads
        if self._keepalive_thread and self._keepalive_thread.is_alive():
            return

        def _keepalive() -> None:
            # The loop itself carries no logic and cannot be exercised from a test - it never returns.
            # Everything that can fail lives in _keepalive_once, which is called directly instead
            while True:
                self._keepalive_once()
                time.sleep(KEEPALIVE_PING_INTERVAL_SECONDS)

        t = threading.Thread(target=_keepalive, daemon=True)
        t.start()
        self._keepalive_thread = t

# ---------------------------------------------- BASE DATABASE OPERATIONS -------------------------------------------- #


    @retry_operation
    def status(self) -> bool:
        """
        Reports whether the database answered a connection probe

        A plain boolean, because `MongoConnector.is_connected` catches the connection error rather
        than re-raising it. A raise would be inherited by this method and reach `GET /rest/` as a 500, where it
        means to answer `connected: false`; `GET /settings/system/deployment/` reads it too. A failed probe is
        answered from memory for `MONGO_PROBE_DOWN_CACHE_S` (see `is_connected`).

        Returns:
            bool: True when the database answered, False when it did not
        """
        return self.connector.is_connected()

# --------------------------------------------------- CRUD - CREATE -------------------------------------------------- #

    @retry_operation
    def insert(self, collection: str, db_name: str, data: dict[str, Any], skip_public: bool = False) -> int | None:
        """
        Adds a document to a collection with retry on duplicate public_id.

        The retry covers the public_id index only. A duplicate-key error from any other unique index
        means the document duplicates one already stored, so it is reported as such immediately - see
        is_public_id_conflict.

        **A caller-supplied public_id is honoured and the counter is raised to match it.** Two write
        paths choose the id themselves rather than drawing it from the counter: `POST /objects/` (an
        id that is already taken is a 400) and the object importer (an unused id is imported under
        that id). Without the reconciliation the counter would stay below the stored id, so every
        later insert would first draw an id that is already taken, burn a retry - and a block of
        MAX_DUPLICATE_KEY_RETRIES consecutive supplied ids would exhaust the loop and fail the insert
        outright. `update_public_id_counter` only ever moves the counter forward (max(counter, value)),
        so reconciling costs one counter write on the rare explicit-id insert and nothing otherwise.

        Args:
            collection (str): Name of the database collection.
            db_name (str): Name of the database owning the collection
            data (dict): Data to be inserted.
            skip_public (bool): If True, skips public ID creation and counter increment; the
                                document is inserted as-is and may legitimately carry no public_id
                                (e.g. a collection keyed by a string id).

        **Every failure of the write is sorted the same way on both paths** (``typed_insert_failure``): a duplicate
        key, a lock or time-limit timeout, the 16 MB limit and a lost connection each raise their own error, and
        anything else is a plain ``DocumentInsertError`` - never a network error, which every layer above treats
        as worth retrying. Once a caller-supplied id is stored, a failed counter update is logged, not raised: the
        document exists (``_raise_counter_to_stored_id``).

        Raises:
            DocumentInsertDuplicateKeyError: If the document duplicates a unique index - on the ``skip_public`` path
                the public_id index included, since the caller chose the id
            DocumentInsertTooLargeError: If the document exceeds MongoDB's 16 MB limit
            DocumentLockTimeoutError: If a lock or execution timeout occurs
            DocumentNetworkError: If the connection to the server failed
            DocumentInsertError: If the document could not be created for any other reason, or no free public_id
                was found within MAX_DUPLICATE_KEY_RETRIES attempts

        Returns:
            int | None: The document's public_id, or None when skip_public is set and the document
                        carries no public_id.
        """
        if skip_public:
            try:
                self.get_collection(collection, db_name).insert_one(data)
            except Exception as err:
                # The caller chose the id, so even a public_id clash is a genuine duplicate - nothing to retry
                raise typed_insert_failure(err, collection) from err

            return data.get(PUBLIC_ID_FIELD)

        for attempt in range(MAX_DUPLICATE_KEY_RETRIES):
            # A caller-supplied id is not drawn from the counter, so the counter has to be told
            # about it - see the note in the docstring
            caller_supplied_id: bool = PUBLIC_ID_FIELD in data

            if not caller_supplied_id:
                try:
                    data[PUBLIC_ID_FIELD] = self.get_next_public_id(collection, db_name, inc_id=True)
                except DocumentGetError as err:
                    raise DocumentInsertError(
                        f"Failed to draw a public_id for collection '{collection}': {err}"
                    ) from err

            try:
                self.get_collection(collection, db_name).insert_one(data)
            except DuplicateKeyError as err:
                if not is_public_id_conflict(err):
                    # A different unique index was violated, so the document is a real duplicate of one
                    # already stored - e.g. a CmdbExtendableOption value that already exists in its
                    # OptionType. Retrying with a new public_id cannot help, and doing it anyway would
                    # consume MAX_DUPLICATE_KEY_RETRIES ids from the counter before failing with an error
                    # blaming the public_id
                    raise typed_insert_failure(err, collection) from err

                LOGGER.debug(
                    "Duplicate public_id %s detected on attempt %d, retrying...", data[PUBLIC_ID_FIELD], attempt + 1,
                )
                data.pop(PUBLIC_ID_FIELD, None)
                continue
            except Exception as err:
                raise typed_insert_failure(err, collection) from err

            if caller_supplied_id:
                self._raise_counter_to_stored_id(collection, db_name, data[PUBLIC_ID_FIELD])

            return data[PUBLIC_ID_FIELD]

        raise DocumentInsertError(
            f"Failed to insert document after {MAX_DUPLICATE_KEY_RETRIES} duplicate key attempts"
        )


    @retry_operation
    def insert_many(
        self,
        collection: str,
        db_name: str,
        data: list[dict[str, Any]],
        skip_public: bool = False
    ) -> list[int]:
        """
        Inserts multiple documents into a collection.

        Args:
            collection (str): Name of the collection.
            db_name (str): Name of the database owning the collection
            data (list[dict]): Documents to insert.
            skip_public (bool): If True, assumes public_id is already assigned.

        Returns:
            list[int]: List of inserted public_ids
        """
        try:
            if not data:
                return []

            if not skip_public:
                # Assign public_ids individually (slow but safe fallback)
                for doc in data:
                    if "public_id" not in doc:
                        doc["public_id"] = self.get_next_public_id(collection, db_name, inc_id=True)

            self.get_collection(collection, db_name).insert_many(data, ordered=False)

            # A document restored as-is (skip_public) may carry no public_id; it is inserted, just not listed
            return [doc["public_id"] for doc in data if "public_id" in doc]

        except BulkWriteError as err:
            # An unordered insert_many never raises DuplicateKeyError: every refused document is listed
            # in one BulkWriteError, the duplicates by their code
            if is_document_too_large(err):
                raise DocumentInsertTooLargeError(
                    DOCUMENT_TOO_LARGE_MESSAGE.format(collection=collection, err=err)
                ) from err
            if not is_duplicate_key_bulk_error(err):
                raise DocumentInsertError(
                    f"Failed to insert many documents into collection '{collection}': {err}"
                ) from err

            key_pattern, key_value = duplicate_key_details(err)

            raise DocumentInsertDuplicateKeyError(
                duplicate_key_message(collection, key_pattern, key_value),
                key_pattern=key_pattern,
                key_value=key_value,
            ) from err

        except (ServerSelectionTimeoutError, NetworkTimeout, ConnectionFailure) as net_err:
            raise DocumentNetworkError(f"Network/timeout error while inserting documents: {net_err}") from net_err

        except Exception as err:
            if is_document_too_large(err):
                raise DocumentInsertTooLargeError(
                    DOCUMENT_TOO_LARGE_MESSAGE.format(collection=collection, err=err)
                ) from err
            raise DocumentInsertError(
                f"Failed to insert many documents into collection '{collection}': {err}"
            ) from err


    @retry_operation
    def bulk_write(self, collection: str, db_name: str, operations: list[Any]) -> int:
        """
        Performs a bulk write operation on the specified collection.

        The operations are sent unordered in batches of ``BULK_WRITE_BATCH_SIZE``; each operation is
        atomic on its own document, the batch as a whole is not

        Args:
            collection (str): Name of the database collection.
            db_name (str): Name of the database owning the collection
            operations (list): List of pymongo operations (e.g., UpdateOne, DeleteOne, etc.)

        Raises:
            DocumentInsertError: If bulk write fails.

        Returns:
            int: How many documents the operations modified, summed over the batches
        """
        modified: int = 0

        try:
            for i in range(0, len(operations), BULK_WRITE_BATCH_SIZE):
                batch = operations[i:i + BULK_WRITE_BATCH_SIZE]
                modified += self.get_collection(collection, db_name).bulk_write(batch, ordered=False).modified_count

            return modified
        except Exception as err:
            if is_document_too_large(err):
                raise DocumentInsertTooLargeError(
                    DOCUMENT_TOO_LARGE_MESSAGE.format(collection=collection, err=err)
                ) from err
            raise DocumentInsertError(f"Failed bulk write in collection '{collection}': {err}") from err

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

    @retry_operation
    def update(
        self,
        collection: str,
        db_name: str,
        criteria: dict[str, Any],
        data: dict[str, Any],
        *args: Any,
        **kwargs: Any
    ) -> UpdateResult:
        """
        Updates a document inside the specified collection

        ``data`` is either field values, which are wrapped in ``$set``, or an update document whose keys are
        operators (``$set``, ``$unset``, ``$push``, ...), which is sent as it is

        Args:
            collection (str): The name of the database collection.
            db_name (str): Name of the database owning the collection
            criteria (dict): The filter used to match the document to be updated
            data (dict): The field values to set, or an update document of operators
            *args: Additional positional arguments for the update operation
            **kwargs: Additional keyword arguments for the update operation

        Raises:
            DocumentUpdateError: When document could not be updated

        Returns:
            UpdateResult: The result of the update operation
        """
        try:
            # Apply '$set' only if no update operators are present
            update_data = data if any(key.startswith('$') for key in data) else {'$set': data}

            result = self.get_collection(collection, db_name).update_one(criteria, update_data, *args, **kwargs)

            return result
        except DuplicateKeyError as err:
            key_pattern, key_value = duplicate_key_details(err)

            raise DocumentUpdateDuplicateKeyError(
                duplicate_key_message(collection, key_pattern, key_value),
                key_pattern=key_pattern,
                key_value=key_value,
            ) from err
        except Exception as err:
            if is_document_too_large(err):
                raise DocumentUpdateTooLargeError(
                    DOCUMENT_TOO_LARGE_MESSAGE.format(collection=collection, err=err)
                ) from err
            LOGGER.error("[update] Exception: %s. Type: %s", err, type(err))
            raise DocumentUpdateError(f"Failed to update document in '{collection}': {err}") from err


    @retry_operation
    def replace(
            self,
            collection: str,
            db_name: str,
            criteria: dict[str, Any],
            document: dict[str, Any]) -> UpdateResult:
        """
        Replaces the one document matching the criteria with the given document, entirely

        Unlike `update`, which sets the given keys and keeps every other stored one, this writes the document
        exactly: a key the replacement lacks is gone afterwards. It is what restoring a snapshot needs - an
        undone update must remove the keys the update added, not only reset the ones it changed. The `_id` of
        the stored document is kept whether or not the replacement carries it

        Args:
            collection (str): The name of the database collection
            db_name (str): Name of the database owning the collection
            criteria (dict[str, Any]): The filter matching the document to replace
            document (dict[str, Any]): The document to store in its place

        Raises:
            DocumentUpdateDuplicateKeyError: When the replacement would duplicate a unique index
            DocumentUpdateError: When the document could not be replaced

        Returns:
            UpdateResult: The outcome of the replace (matched / modified counts)
        """
        replacement: dict[str, Any] = {key: value for key, value in document.items() if key != '_id'}

        try:
            return self.get_collection(collection, db_name).replace_one(criteria, replacement)
        except DuplicateKeyError as err:
            key_pattern, key_value = duplicate_key_details(err)

            raise DocumentUpdateDuplicateKeyError(
                duplicate_key_message(collection, key_pattern, key_value),
                key_pattern=key_pattern,
                key_value=key_value,
            ) from err
        except Exception as err:
            if is_document_too_large(err):
                raise DocumentUpdateTooLargeError(
                    DOCUMENT_TOO_LARGE_MESSAGE.format(collection=collection, err=err)
                ) from err
            LOGGER.error("[replace] Exception: %s. Type: %s", err, type(err))
            raise DocumentUpdateError(f"Failed to replace document in '{collection}': {err}") from err


    @retry_operation
    def upsert_set(self, collection:str, db_name: str, data: dict[str, Any]) -> UpdateResult:
        """
        Performs an upsert operation on a specified MongoDB collection.
        
        This function attempts to update a document in the given collection by matching the 
        `public_id` field. If the document does not exist, it will insert the document 
        with the provided data.

        Args:
            collection (str): The name of the MongoDB collection where the upsert operation 
            db_name (str): Name of the database owning the collection
                            will be performed.
            data (dict): A dictionary containing the data to be inserted or updated. 
                        The dictionary should contain at least the 'public_id' field 
                        to identify the document.

        Returns:
            UpdateResult: The result of the update operation, providing information 
                        about the modified or inserted document.

        Raises:
            DocumentUpdateError: If an error occurs during the upsert operation, 
                                an exception is raised with details about the failure.
        """
        try:
            result = self.get_collection(collection, db_name).update_one(
                        {"public_id": data['public_id']},
                        {"$set": data},  # Update the fields of the document
                        upsert=True  # Insert if document does not exist)
                    )

            # If something got created, the id came from the caller (the criteria IS the public_id),
            # so the counter is raised TO that id rather than bumped by one: an upsert creating
            # public_id 500 while the counter sits at 3 has to leave it at 500, not 4
            if result.upserted_id:
                self.update_public_id_counter(collection, db_name, value=data['public_id'])

            return result
        except Exception as err:
            if is_document_too_large(err):
                raise DocumentUpdateTooLargeError(
                    DOCUMENT_TOO_LARGE_MESSAGE.format(collection=collection, err=err)
                ) from err
            LOGGER.error("[upsert_set] Exception: %s. Type: %s", err, type(err))
            raise DocumentUpdateError(f"Failed to update/create document in '{collection}': {err}") from err


    @retry_operation
    def upsert(
        self,
        collection: str,
        db_name: str,
        criteria: dict[str, Any],
        data: dict[str, Any],
    ) -> UpdateResult:
        """
        Inserts or updates a single document matched by arbitrary criteria

        The matched document's fields are set from `data` (via `$set`); if no document matches,
        a new one is inserted carrying both the criteria keys and `data`. Unlike `upsert_set`,
        the match is not tied to `public_id`, so this also supports `_id`-keyed singletons

        Args:
            collection (str): The name of the MongoDB collection
            db_name (str): The target database name
            criteria (dict[str, Any]): The filter selecting the document to upsert
            data (dict[str, Any]): The fields to set on the matched (or newly inserted) document

        Raises:
            DocumentUpdateError: If an error occurs during the upsert operation

        Returns:
            UpdateResult: The outcome of the upsert (matched / modified / upserted info)
        """
        try:
            return self.get_collection(collection, db_name).update_one(criteria, {'$set': data}, upsert=True)
        except Exception as err:
            if is_document_too_large(err):
                raise DocumentUpdateTooLargeError(
                    DOCUMENT_TOO_LARGE_MESSAGE.format(collection=collection, err=err)
                ) from err
            LOGGER.error("[upsert] Exception: %s. Type: %s", err, type(err))
            raise DocumentUpdateError(f"Failed to upsert document in '{collection}': {err}") from err


    @retry_operation
    def update_many(
            self,
            collection: str,
            db_name: str,
            criteria: dict[str, Any],
            update: dict[str, Any],
            add_to_set: bool = False) -> UpdateResult:
        """
        Sets fields - or adds array members - on every document matching the filter

        ``update`` holds field values, not operators: it is wrapped in ``$set``, or in ``$addToSet`` when
        ``add_to_set`` is True. An update that brings its own operators, or is a pipeline, goes to
        ``update_many_raw``

        Args:
            collection (str): Name of database collection
            db_name (str): Name of the database owning the collection
            criteria (dict): The filter used to match the documents for updating
            update (dict): The field values to set, or the array members to add
            add_to_set (bool): If True, wraps ``update`` in '$addToSet' (adds each value to its array unless it
                is already there); if False, in '$set'. Defaults to False

        Raises:
            DocumentUpdateError: If the update operation fails

        Returns:
            UpdateResult: The result of the update operation
        """
        try:
            update_operator = "$addToSet" if add_to_set else "$set"

            return self.get_collection(collection, db_name).update_many(criteria, {update_operator: update})
        except Exception as err:
            if is_document_too_large(err):
                raise DocumentUpdateTooLargeError(
                    DOCUMENT_TOO_LARGE_MESSAGE.format(collection=collection, err=err)
                ) from err
            raise DocumentUpdateError(f"Failed to update documents in '{collection}': {err}") from err


    @retry_operation
    def update_many_raw(
        self,
        collection: str,
        db_name: str,
        filter_query: dict[str, Any],
        update: dict[str, Any] | list[dict[str, Any]],
        array_filters: list[dict[str, Any]] | None = None,
    ) -> UpdateResult:
        """
        Updates multiple documents using a raw update document (no '$set' wrapping)

        The one many-document update that takes its operators from the caller: ``$pull``, ``$unset``, ``$inc``
        or an aggregation pipeline (a list of stages) reach MongoDB as given

        Args:
            collection (str): Name of the database collection
            db_name (str): Name of the database owning the collection
            filter_query (dict[str, Any]): Filter selecting the documents to update
            update (dict[str, Any] | list[dict[str, Any]]): Raw update document carrying its own operators, or
                an aggregation pipeline
            array_filters (list[dict[str, Any]] | None, optional): Positional array filters for
                                                                   targeting nested array elements.
                                                                   Defaults to None.

        Raises:
            DocumentUpdateError: If the update operation fails

        Returns:
            UpdateResult: The result of the update operation
        """
        try:
            kwargs = {}
            if array_filters:
                kwargs["array_filters"] = array_filters

            return self.get_collection(collection, db_name).update_many(
                filter_query,
                update,
                **kwargs,
            )
        except Exception as err:
            if is_document_too_large(err):
                raise DocumentUpdateTooLargeError(
                    DOCUMENT_TOO_LARGE_MESSAGE.format(collection=collection, err=err)
                ) from err
            raise DocumentUpdateError(
                f"Error updating documents in collection '{collection}': {err}"
            ) from err

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

    @retry_operation
    def get_distinct(self, collection: str, db_name: str, key: str, criteria: dict[str, Any]) -> list[Any]:
        """
        Returns the distinct values of a field across documents matching the criteria

        Args:
            collection (str): Name of the database collection
            db_name (str): Name of the database owning the collection
            key (str): The field whose distinct values are returned
            criteria (dict[str, Any]): Filter selecting the documents to scan

        Raises:
            DocumentGetError: If the distinct query fails

        Returns:
            list[Any]: The distinct values (empty list if none found)
        """
        try:
            result: list[Any] = self.get_collection(collection, db_name).distinct(key, criteria)

            return result if result else []
        except Exception as err:
            LOGGER.error("[distinct] Can't retrive distinct documents. Error: %s", err)
            raise DocumentGetError(
                f"Failed to retrieve distinct documents from collection '{collection}': {err}"
            ) from err


    @retry_operation
    def find_all(self, collection: str, db_name: str, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        """
        Retrieves documents from the specified collection (returned as a list)

        Args:
            collection (str): The name of the collection to search in
            db_name (str): Name of the database owning the collection
            *args: Positional arguments for the search operation
            **kwargs: Keyword arguments for filtering, sorting, etc

        Raises:
            DocumentGetError: When documents could not be retrieved - `find`'s own error passed on as it is, a failure
                while reading the cursor wrapped once

        Returns:
            list: A list of retrieved documents
        """
        found_documents: Cursor[Any] = self.find(collection, db_name, *args, **kwargs)

        try:
            return list(found_documents)
        except Exception as err:
            LOGGER.error("[find_all] Can't retrieve documents. Error: %s", err)
            raise DocumentGetError(f"Failed to retrieve documents from '{collection}': {err}") from err


    @retry_operation
    def find(self, collection: str, db_name: str, *args: Any, **kwargs: Any) -> Cursor[Any]:
        """
        Retrieves documents from the specified collection with optional filters and projections

        Only the query and its first batch run here, inside the error handling and the retry; a later batch is
        fetched while the caller reads the cursor, so a failure there reaches the caller as a raw driver error. The
        cursor is kept for reads that stream a whole collection without holding it in memory - the updaters, whose
        tail turns any failure into an UpdaterException. A read that needs every result as a list uses ``find_all``,
        which reads the cursor inside the error handling

        Args:
            collection (str): The name of the collection to search in.
            db_name (str): Name of the database owning the collection
            *args: Positional arguments for the find operation (e.g., query filter).
            **kwargs: Keyword arguments for filtering, sorting, limiting, etc.
                    Automatically adds 'projection' to exclude _id if not provided

        Raises:
            DocumentGetError: When documents could not be retrieved

        Returns:
            Cursor: MongoDB Cursor object with the results of the query
        """
        try:
            if 'projection' not in kwargs:
                kwargs.update({'projection': {'_id': 0}})

            return self.get_collection(collection, db_name).find(*args, **kwargs)
        except Exception as err:
            raise DocumentGetError(f"Failed to retrieve documents from collection '{collection}': {err}") from err


    @retry_operation
    def find_one_by(self, collection: str, db_name: str, *args: Any, **kwargs: Any) -> dict[str, Any] | None:
        """
        Find one specific document by special requirements

        Args:
            collection (str): Name of the database collection
            db_name (str): Name of the database owning the collection
            *args: Positional arguments for the find operation (e.g., query filter)
            **kwargs: Keyword arguments for filtering, sorting, limiting, etc

        Raises:
            DocumentGetError: If the retrieval fails due to an error

        Returns:
            dict: The found document or None if no document matches the criteria
        """
        try:
            cursor_result = self.find(collection, db_name, limit=1, *args, **kwargs)

            result = next(cursor_result, None)

            return result  # Return None if no result is found
        except Exception as err:
            raise DocumentGetError(f"Failed to retrieve document from collection '{collection}': {err}") from err


    @retry_operation
    def find_one(
        self,
        collection: str,
        db_name: str,
        public_id: int,
        *args: Any,
        **kwargs: Any
    ) -> dict[str, Any] | None:
        """
        Retrieves a single document with the given public_id from the specified collection

        Args:
            collection (str): Name of the database collection.
            db_name (str): Name of the database owning the collection
            public_id (int): The public_id of the document to retrieve
            *args: Additional arguments for the find operation
            **kwargs: Additional keyword arguments for the find operation

        Raises:
            DocumentGetError: If there is an issue retrieving the document

        Returns:
            dict: The document with the given public_id, or None if not found
        """
        try:
            cursor_result = self.find(collection, db_name, {'public_id': public_id}, limit=1, *args, **kwargs)

            for result in cursor_result.limit(-1):
                return result
        except Exception as err:
            raise DocumentGetError(
                f"Failed to retrieve document with public_id {public_id} from collection '{collection}': {err}"
            ) from err


    @retry_operation
    def count(
        self,
        collection: str,
        db_name: str,
        criteria: dict[str, Any] | None = None,
        limit: int | None = None,
    ) -> int:
        """
        Count documents based on criteria parameters

        Args:
            collection (str): Name of database collection
            db_name (str): Name of the database owning the collection
            criteria (dict): Document count requirements (default is empty criteria)
            limit (int | None): Stop counting after this many matches. Use ``limit=1`` for an
                existence check, which lets the server short-circuit instead of counting every
                match. Defaults to None (count them all)

        Raises:
            DocumentGetError: When the count operation fails

        Returns:
            int: The count of the documents that match the criteria, capped at 'limit' when given
        """
        # Ensure criteria is a dictionary (defaulting to empty if None is provided)
        criteria = criteria or {}

        try:
            if limit is not None:
                return self.get_collection(collection, db_name).count_documents(criteria, limit=limit)

            return self.get_collection(collection, db_name).count_documents(criteria)
        except Exception as err:
            raise DocumentGetError(
                f"Failed to count documents in collection '{collection}': {err}"
            ) from err


    @retry_operation
    def aggregate_all(
            self,
            collection: str,
            db_name: str,
            pipeline: list[dict[str, Any]],
            **kwargs: Any) -> list[dict[str, Any]]:
        """
        Runs an aggregation and reads every result

        The cursor is read to the end HERE, inside the error handling and the retry: a later batch is computed while
        the cursor is read, so a cursor handed back would fail in its caller as a raw driver error - neither retried
        nor typed - instead of a DocumentAggregationError. That is why the manager hands out no cursor-returning
        aggregation; a pipeline ending in ``$merge`` / ``$out`` answers an empty list once its write has run

        Args:
            collection (str): Name of the database collection
            db_name (str): Name of the database owning the collection
            pipeline (list[dict[str, Any]]): The aggregation stages
            **kwargs: Further aggregation options (e.g. ``allowDiskUse``)

        Raises:
            DocumentAggregationError: If the aggregation failed, on its first batch or a later one

        Returns:
            list[dict[str, Any]]: Every result of the aggregation
        """
        try:
            return list(self.get_collection(collection, db_name).aggregate(pipeline, **kwargs))
        except Exception as err:
            raise DocumentAggregationError(f"Aggregation operation failed: {err}") from err


    @retry_operation
    def aggregate_within_time_limit(
            self,
            collection: str,
            db_name: str,
            pipeline: list[dict[str, Any]],
            time_limit_ms: int,
            **kwargs: Any) -> list[dict[str, Any]]:
        """
        Runs an aggregation under a server-side time budget and reads every result

        The budget is the aggregation's ``maxTimeMS``: past it the server stops the aggregation itself - checked
        between documents, so it bounds a read over many documents, not one expensive document. The cursor
        is read to the end HERE, inside the error handling, because a later batch is computed while it is read - a
        cursor handed back would fail in its caller, outside the sorting below

        Args:
            collection (str): Name of the database collection
            db_name (str): Name of the database owning the collection
            pipeline (list[dict[str, Any]]): The aggregation stages
            time_limit_ms (int): The server-side time budget, in milliseconds
            **kwargs: Further aggregation options (e.g. ``allowDiskUse``)

        Raises:
            DocumentQueryTimeLimitError: If the server stopped the aggregation on its time budget
            DocumentAggregationError: If the aggregation failed for any other reason

        Returns:
            list[dict[str, Any]]: Every result of the aggregation
        """
        try:
            return list(self.get_collection(collection, db_name).aggregate(
                pipeline, **{**kwargs, MONGO_MAX_TIME_OPTION: time_limit_ms},
            ))
        except ExecutionTimeout as err:
            raise DocumentQueryTimeLimitError(err, time_limit_ms) from err
        except Exception as err:
            raise DocumentAggregationError(f"Aggregation operation failed: {err}") from err

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

    @retry_operation
    def delete(self, collection: str, db_name: str, criteria: dict[str, Any]) -> DeleteResult:
        """
        Deletes a document from the specified collection based on the given criteria

        Args:
            collection (str): Name of the database collection
            db_name (str): Name of the database owning the collection
            criteria (dict): Filter query to identify the document to delete

        Raises:
            DocumentDeleteError: When the document could not be deleted

        Returns:
            DeleteResult: Contains the result of the delete operation
        """
        try:
            result = self.get_collection(collection, db_name).delete_one(criteria)

            return result
        except Exception as err:
            raise DocumentDeleteError(f"Error deleting document from collection '{collection}': {err}") from err


    @retry_operation
    def find_one_and_delete(self, collection: str, db_name: str, criteria: dict[str, Any]) -> dict[str, Any] | None:
        """
        Deletes the first document matching the criteria and answers the document it deleted

        The read and the delete are one atomic step, so the answer is exactly what THIS call removed: a
        document another writer deleted first is answered as None, never as a document of its own. `_id`
        is left out, like every other read of this manager

        Args:
            collection (str): Name of the database collection
            db_name (str): Name of the database owning the collection
            criteria (dict[str, Any]): Filter selecting the document to delete

        Raises:
            DocumentDeleteError: When the document could not be deleted

        Returns:
            dict[str, Any] | None: The deleted document, or None when nothing matched
        """
        try:
            return self.get_collection(collection, db_name).find_one_and_delete(criteria, projection={'_id': 0})
        except Exception as err:
            raise DocumentDeleteError(f"Error deleting a document from collection '{collection}': {err}") from err


    @retry_operation
    def delete_many_raw(self, collection: str, db_name: str, filter_query: dict[str, Any]) -> DeleteResult:
        """
        Deletes all documents matching a raw filter query

        Args:
            collection (str): Name of the database collection
            db_name (str): Name of the database owning the collection
            filter_query (dict[str, Any]): Filter selecting the documents to delete

        Raises:
            DocumentDeleteError: If the delete operation fails

        Returns:
            DeleteResult: The result of the delete operation
        """
        try:
            return self.get_collection(collection, db_name).delete_many(filter_query)
        except Exception as err:
            raise DocumentDeleteError(f"Error deleting documents from collection '{collection}': {err}") from err
