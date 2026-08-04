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
This module provides the MongoDatabaseManager
"""
from logging import Logger, getLogger
import time
import threading
from typing import Any
from collections.abc import MutableMapping
from pymongo.database import Database
from pymongo.errors import (
    PyMongoError,
    CollectionInvalid,
    DuplicateKeyError,
    OperationFailure,
    NetworkTimeout,
    ConnectionFailure,
    ServerSelectionTimeoutError,
    ExecutionTimeout,
)
from pymongo import IndexModel, ReturnDocument
from pymongo.collection import Collection
from pymongo.cursor import Cursor
from pymongo.results import DeleteResult, UpdateResult

from cmdb.database.mongo_connector import MongoConnector
from cmdb.database.database_constants import (
    PUBLIC_ID_COUNTER_COLLECTION,
    MAX_DUPLICATE_KEY_RETRIES,
    BULK_WRITE_BATCH_SIZE,
    KEEPALIVE_PING_INTERVAL_SECONDS,
    MONGO_LOCK_TIMEOUT_ERROR_CODE,
    MONGO_SORT_DESCENDING,
)
from cmdb.database.database_utils import retry_operation

from cmdb.errors.database import (
    CollectionAlreadyExistsError,
    CreateIndexesError,
    GetIndexesError,
    DropIndexError,
    DatabaseConnectionError,
    DatabaseAlreadyExistsError,
    DatabaseNotFoundError,
    DeleteCollectionError,
    DocumentDeleteError,
    DocumentInsertError,
    DocumentUpdateError,
    DocumentGetError,
    DocumentAggregationError,
    GetCollectionError,
    PublicIdCounterInitError,
    DocumentLockTimeoutError,
    DocumentNetworkError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                             MongoDatabaseManager - CLASS                                             #
# -------------------------------------------------------------------------------------------------------------------- #
class MongoDatabaseManager:
    """
    PyMongo (MongoDB) implementation of the Database Manager
    """
    def __init__(self, host: str, port: int, database_name: str, mode: str = 'local') -> None:
        """
        Initialises the MongoDatabaseManager, its connector, and starts the keep-alive thread

        Args:
            host (str): MongoDB host
            port (int): MongoDB port
            database_name (str): Default database name used when a call omits an explicit db_name
            mode (str, optional): 'local' or 'cloud'; toggles TLS-related client options.
                                  Defaults to 'local'.
        """
        self._keepalive_thread: threading.Thread | None = None
        self.host: str = host
        self.port: int = int(port)
        self.db_name: str = database_name
        self.mode: str = mode  # 'local' or 'cloud'

        self.client_options: dict[str, Any] = {
            'connectTimeoutMS': 10000,  # Timeout after 10 seconds if no connection is made
            'socketTimeoutMS': 30000,  # Socket timeout (set to 30 seconds)
            'serverSelectionTimeoutMS': 10000, # Timeout for finding a suitable server in the cluster
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

        # Start keep-alive thread
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

    def __enter__(self):
        """
        Support with-statement for connection management
        """
        return self


    def target_database(self, db_name: str) -> str:
        """
        Resolves which database name an operation should target

        Args:
            db_name (str): Explicitly requested database name (may be empty/None)

        Returns:
            str: The given db_name when provided, otherwise the manager's default database name
        """
        return db_name if db_name else self.db_name


    def _start_keepalive(self) -> None:
        """
        Start a background thread that pings the MongoDB client every 50s
        """

        # Avoid multiple threads
        if self._keepalive_thread and self._keepalive_thread.is_alive():
            return

        def _keepalive():
            while True:
                try:
                    self.connector.client.admin.command("ping")
                except Exception as err:
                    LOGGER.warning("[MongoDB KeepAlive] Ping failed: %s", err)
                time.sleep(KEEPALIVE_PING_INTERVAL_SECONDS)

        t = threading.Thread(target=_keepalive, daemon=True)
        t.start()
        self._keepalive_thread = t

# ---------------------------------------------- BASE DATABASE OPERATIONS -------------------------------------------- #

    @retry_operation
    def check_database_exists(self, name: str) -> bool:
        """
        Checks if a database with the given name exists

        Args:
            name (str): Name of the database which should be checked

        Raises:
            DatabaseConnectionError: If connection to database could not be established

        Returns:
            bool: True if database with given name exists, else False
        """
        try:
            database_names = self.connector.client.list_database_names()

            return name in database_names
        except Exception as err:
            raise DatabaseConnectionError(f"Failed to check if database '{name}' exists: {err}") from err


    @retry_operation
    def create_database(self, name: str) -> Database[Any]:
        """
        Create a new empty database if it does not already exist

        Args:
            name (str): Name of the new database

        Raises:
            DatabaseAlreadyExistsError: If a database with this name already exists
            DatabaseConnectionError: If the database connection fails

        Returns:
            Database: Instance of the newly created database
        """
        try:
            if name in self.connector.client.list_database_names():
                raise DatabaseAlreadyExistsError(f"Database '{name}' already exists.")

            return self.connector.client[name]
        except DatabaseAlreadyExistsError as err:
            raise err
        except Exception as err:
            raise DatabaseConnectionError(f"Failed to create database '{name}': {err}") from err


    @retry_operation
    def drop_database(self, database: str | Database[Any]) -> None:
        """
        Deletes an existing database

        Args:
            database (str, Database): Name or instance of the database to be dropped

        Raises:
            DatabaseNotFoundError: If the specified database does not exist
            DatabaseConnectionError: If the database connection fails during the operation
        """
        try:
            if isinstance(database, Database):
                database = database.name

            if database not in self.connector.client.list_database_names():
                raise DatabaseNotFoundError(f"Database '{database}' not found.")

            self.connector.client.drop_database(database)
        except DatabaseNotFoundError as err:
            raise err
        except Exception as err:
            raise DatabaseConnectionError(f"Failed to drop database '{database}': {err}") from err


    @retry_operation
    def create_collection(self, collection_name: str, db_name: str) -> str:
        """
        Creates an empty MongoDB collection

        Args:
            collection_name (str): Name of collection which should be created
            db_name (str): Name of the database owning the collection

        Raises:
            CollectionAlreadyExistsError: If the collection already exists
            DatabaseConnectionError: If there is an issue with the database connection

        Returns:
            str: The name of the created collection
        """
        try:
            all_collections: list[str] = self.connector.get_database(
                self.target_database(db_name)
            ).list_collection_names()

            if collection_name not in all_collections:
                self.connector.get_database(self.target_database(db_name)).create_collection(collection_name)

            return collection_name
        except Exception as err:
            if isinstance(err, CollectionInvalid):
                raise CollectionAlreadyExistsError(str(err)) from err

            raise DatabaseConnectionError(f"Failed to create collection '{collection_name}': {err}") from err


    @retry_operation
    def get_collection(self, name: str, db_name: str) -> Collection[Any]:
        """
        Get a collection from the database

        Args:
            name (str): Collection name

        Raises:
            GetCollectionError: When the collection could not be retrieved

        Returns:
            (Collection): The requested collection
        """
        try:
            return self.connector.get_database(self.target_database(db_name))[name]
        except Exception as err:
            LOGGER.error("[get_collection] '%s' Exception: %s. Type: %s", name, err, type(err))
            raise GetCollectionError(str(err)) from err


    @retry_operation
    def delete_collection(self, collection: str, db_name: str) -> dict[str, Any]:
        """
        Delete an existing collection

        Args:
            collection (str): collection name
            db_name (str): Name of the database owning the collection

        Raises:
            DeleteCollectionError: When collection can't be deleted

        Returns:
            delete ack
        """
        try:
            return self.connector.get_database(self.target_database(db_name)).drop_collection(collection)
        except Exception as err:
            raise DeleteCollectionError(f"Failed to delete collection '{collection}': {err}") from err


    @retry_operation
    def create_indexes(self, collection: str, db_name: str, indexes: list[IndexModel]) -> list[str]:
        """
        Creates indexes for collection

        Args:
            collection (str): name of collection
            db_name (str): Name of the database owning the collection
            indexes (list[IndexModel]): list of IndexModels which should be created

        Raises:
            CreateIndexesError: When indexes can't be created

        Returns:
            list[str]: List of created indexes
        """
        try:
            return self.get_collection(collection, db_name).create_indexes(indexes)
        except Exception as err:
            raise CreateIndexesError(f"Failed to create indexes for collection '{collection}': {err}") from err


    def drop_index(self, collection: str, db_name: str, index_name: str) -> bool:
        """
        Drops a single named index from a collection if it is present

        Needed because index reconciliation is name-based and purely additive (see
        CollectionValidator.ensure_indexes): an index whose declared options changed must be dropped
        before it can be recreated, which only a migration should ever do. Absence is not an error -
        the method reports False so a re-run of the same migration is a no-op rather than a failure

        Args:
            collection (str): Name of the collection owning the index
            db_name (str): Name of the database owning the collection
            index_name (str): Name of the index to drop

        Raises:
            DropIndexError: When the index exists but could not be dropped

        Returns:
            bool: True if the index was dropped, False if no index of that name existed
        """
        try:
            if index_name not in self.get_index_info(collection, db_name):
                return False

            self.get_collection(collection, db_name).drop_index(index_name)

            return True
        except Exception as err:
            raise DropIndexError(
                f"Failed to drop index '{index_name}' for collection '{collection}': {err}"
            ) from err


    @retry_operation
    def get_index_info(self, collection: str, db_name: str) -> MutableMapping[str, Any]:
        """
        Retrieves index information for a collection

        Args:
            collection (str): name of collection
            db_name (str): Name of the database owning the collection

        Raises:
            GetIndexesError: When the index information could not be retrieved

        Returns:
            MutableMapping[str, Any]: Index information of the collection
        """
        try:
            return self.get_collection(collection, db_name).index_information()
        except Exception as err:
            raise GetIndexesError(
                f"Failed to retrieve index information for collection '{collection}': {err}"
            ) from err


    @retry_operation
    def status(self) -> bool:
        """
        Check if connector has connection to MongoDB

        Returns
            bool: True is connected, else False
        """
        return self.connector.is_connected()

# --------------------------------------------------- CRUD - CREATE -------------------------------------------------- #

    @retry_operation
    def insert(self, collection: str, db_name: str, data: dict[str, Any], skip_public: bool = False) -> int | None:
        """
        Adds a document to a collection with retry on duplicate public_id.

        Args:
            collection (str): Name of the database collection.
            db_name (str): Name of the database owning the collection
            data (dict): Data to be inserted.
            skip_public (bool): If True, skips public ID creation and counter increment; the
                                document is inserted as-is and may legitimately carry no public_id
                                (e.g. a collection keyed by a string id).

        Raises:
            DocumentInsertError: If the document could not be created.
            DocumentNetworkError: If a network or timeout error occurs.
            DocumentLockTimeoutError: If a lock or execution timeout occurs.

        Returns:
            int | None: The document's public_id, or None when skip_public is set and the document
                        carries no public_id.
        """
        try:
            if skip_public:
                self.get_collection(collection, db_name).insert_one(data)
                return data.get('public_id')

            for attempt in range(MAX_DUPLICATE_KEY_RETRIES):
                if 'public_id' not in data:
                    data['public_id'] = self.get_next_public_id(collection, db_name, inc_id=True)

                try:
                    self.get_collection(collection, db_name).insert_one(data)
                    return data['public_id']

                except DuplicateKeyError:
                    LOGGER.debug(
                        "Duplicate public_id %s detected on attempt %d, retrying...",
                        data['public_id'], attempt + 1
                    )
                    data.pop('public_id', None)

                except ExecutionTimeout as err:
                    LOGGER.debug("ExecutionTimeout on attempt %d: %s", attempt + 1, err, exc_info=True)
                    raise DocumentLockTimeoutError(f"Execution timeout: {err}") from err

                except OperationFailure as err:
                    if err.code == MONGO_LOCK_TIMEOUT_ERROR_CODE:  # MongoDB LockTimeout
                        LOGGER.debug("LockTimeout on attempt %d: %s", attempt + 1, err, exc_info=True)
                        raise DocumentLockTimeoutError(f"Lock timeout: {err}") from err
                    raise DocumentInsertError(f"Operation failure: {err}") from err

            raise DocumentInsertError(
                f"Failed to insert document after {MAX_DUPLICATE_KEY_RETRIES} duplicate key attempts"
            )

        # Let the already-typed errors raised inside the loop propagate unchanged - otherwise the
        # generic ``except Exception`` below would re-wrap a DocumentLockTimeoutError as a plain
        # DocumentInsertError, hiding the lock-timeout type from callers
        except (DocumentLockTimeoutError, DocumentNetworkError, DocumentInsertError):
            raise

        except (ServerSelectionTimeoutError, NetworkTimeout, ConnectionFailure, PyMongoError) as net_err:
            LOGGER.debug("Network exception: %s", net_err, exc_info=True)
            raise DocumentNetworkError(f"Network/timeout error while inserting document: {net_err}") from net_err

        except Exception as err:
            LOGGER.debug("Insert exception: %s. Type: %s", err, type(err), exc_info=True)
            raise DocumentInsertError(
                f"Failed to insert document into collection '{collection}': {err}"
        ) from err


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

            return [doc["public_id"] for doc in data]

        except DuplicateKeyError as err:
            raise DocumentInsertError(f"Duplicate public_id detected in insert_many: {err}") from err

        except (ServerSelectionTimeoutError, NetworkTimeout, ConnectionFailure) as net_err:
            raise DocumentNetworkError(f"Network/timeout error while inserting documents: {net_err}") from net_err

        except Exception as err:
            raise DocumentInsertError(
                f"Failed to insert many documents into collection '{collection}': {err}"
            ) from err


    @retry_operation
    def bulk_write(self, collection: str, db_name: str, operations: list[Any]) -> None:
        """
        Performs a bulk write operation on the specified collection.

        Args:
            collection (str): Name of the database collection.
            db_name (str): Name of the database owning the collection
            operations (list): List of pymongo operations (e.g., UpdateOne, DeleteOne, etc.)

        Raises:
            DocumentInsertError: If bulk write fails.
        """
        try:
            for i in range(0, len(operations), BULK_WRITE_BATCH_SIZE):
                batch = operations[i:i + BULK_WRITE_BATCH_SIZE]
                self.get_collection(collection, db_name).bulk_write(batch, ordered=False)
        except Exception as err:
            raise DocumentInsertError(f"Failed bulk write in collection '{collection}': {err}") from err


    @retry_operation
    def init_public_id_counter(self, collection: str, db_name: str) -> int:
        """
        Initializes a public ID counter for the given collection

        Args:
            collection (str): Name of the collection for which the counter is initialised
            db_name (str): Name of the database owning the collection

        Raises:
            PublicIdCounterInitError: When the public_id counter could not be initialised

        Returns:
            int: The highest existing ID in the collection, which is set as the counter's initial value
        """
        try:
            highest_id = self.get_highest_id(collection, db_name)

            self.get_collection(PUBLIC_ID_COUNTER_COLLECTION, db_name).insert_one(
                {'_id': collection, 'counter': highest_id}
            )

            return highest_id
        except Exception as err:
            raise PublicIdCounterInitError(
                f"Failed to initialize public ID counter for collection '{collection}': {err}"
            ) from err


    @retry_operation
    def get_next_public_id(self, collection: str, db_name: str, inc_id: bool = False) -> int:
        """
        Returns the next public_id for a collection

        Args:
            collection (str): Name of the database collection
            db_name (str): Name of the database owning the collection
            inc_id (bool, optional): If True, atomically reserves (consumes) the id by incrementing
                                     the counter; if False, only peeks at the next id without
                                     reserving it. Defaults to False.

        Raises:
            DocumentGetError: If the next public_id could not be determined

        Returns:
            int: The next public_id (reserved when inc_id is True)
        """
        try:
            if not inc_id:
                cur_count = self.get_collection(
                    PUBLIC_ID_COUNTER_COLLECTION,
                    db_name
                ).find_one({'_id': collection})

                return (cur_count['counter'] + 1) if cur_count else 1

            ids: list[int] = self.reserve_public_ids(collection, db_name, 1)

            return ids[0]

        except Exception as err:
            raise DocumentGetError(f"Error retrieving next public_id for collection '{collection}': {err}") from err


    @retry_operation
    def reserve_public_ids(self, collection: str, db_name: str, amount: int) -> list[int]:
        """
        Atomically reserves a contiguous block of public_ids for bulk inserts

        Increments the collection's counter by 'amount' in a single atomic operation (creating the
        counter document if missing) and returns the reserved id range.

        Args:
            collection (str): Name of the database collection
            db_name (str): Name of the database owning the collection
            amount (int): How many consecutive public_ids to reserve

        Raises:
            DocumentGetError: If the ids could not be reserved

        Returns:
            list[int]: The reserved public_ids, in ascending order
        """
        try:
            doc = self.get_collection(PUBLIC_ID_COUNTER_COLLECTION, db_name).find_one_and_update(
                {"_id": collection},
                {"$inc": {"counter": amount}},
                upsert=True,
                return_document=ReturnDocument.AFTER
            )

            new_max = doc["counter"]
            start = new_max - amount + 1

            return list(range(start, new_max + 1))

        except Exception as err:
            raise DocumentGetError(
                f"Failed to reserve public_ids for collection '{collection}': {err}"
            ) from err

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

    @retry_operation
    def update(
        self,
        collection: str,
        db_name: str,
        criteria: dict[str, Any],
        data: dict[str, Any],
        *args: Any,
        add_to_set: bool = True,
        plain: bool = False,
        **kwargs: Any
    ) -> UpdateResult:
        """
        Updates a document inside the specified collection

        Args:
            collection (str): The name of the database collection.
            db_name (str): Name of the database owning the collection
            criteria (dict): The filter used to match the document to be updated
            data (dict): The update data to apply
            add_to_set (bool): If True, wraps `data` in '$set' unless it already contains update operators. 
                                         Defaults to True.
            *args: Additional positional arguments for the update operation
            **kwargs: Additional keyword arguments for the update operation

        Raises:
            DocumentUpdateError: When document could not be updated

        Returns:
            UpdateResult: The result of the update operation
        """
        try:
            # Apply '$set' only if no update operators are present
            if not plain:
                update_data = {'$set': data} if add_to_set and not any(k.startswith('$') for k in data) else data
            else:
                update_data = data

            result = self.get_collection(collection, db_name).update_one(criteria, update_data, *args, **kwargs)

            return result
        except Exception as err:
            LOGGER.error("[update] Exception: %s. Type: %s", err, type(err))
            raise DocumentUpdateError(f"Failed to update document in '{collection}': {err}") from err


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

            # If something got created, update the public_id counter in database
            if result.upserted_id:
                self.update_public_id_counter(collection, db_name, data['public_id'], increment=True)

            return result
        except Exception as err:
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
            LOGGER.error("[upsert] Exception: %s. Type: %s", err, type(err))
            raise DocumentUpdateError(f"Failed to upsert document in '{collection}': {err}") from err


    @retry_operation
    def unset_update_many(
        self,
        collection: str,
        db_name: str,
        criteria: dict[str, Any],
        field: str,
        *args: Any,
        **kwargs: Any
    ) -> UpdateResult:
        """
        Removes a field from multiple documents in the specified collection

        Args:
            collection (str): The name of the database collection
            db_name (str): Name of the database owning the collection
            criteria (dict): The filter used to match documents for updating
            field (str): The field to remove from the matched documents
            *args: Additional positional arguments for the update operation
            **kwargs: Additional keyword arguments for the update operation

        Raises:
            DocumentUpdateError: If the update operation fails

        Returns:
            UpdateResult: The result of the update operation
        """
        try:
            update_data = {'$unset': {field: 1}}

            result = self.get_collection(collection, db_name).update_many(criteria, update_data, *args, **kwargs)

            if result.modified_count == 0:
                LOGGER.warning(
                    "[unset_update_many] No documents matched criteria: %s in collection: %s", criteria, collection
                )

            return result
        except Exception as err:
            raise DocumentUpdateError(f"Failed to unset field '{field}' in '{collection}': {err}") from err


    @retry_operation
    def update_many(
            self,
            collection: str,
            db_name: str,
            criteria: dict[str, Any],
            update: dict[str, Any] | list[dict[str, Any]],
            add_to_set: bool = False,
            plain: bool = False) -> UpdateResult:
        """
        Updates multiple documents that match the filter in a collection

        Args:
            collection (str): Name of database collection
            db_name (str): Name of the database owning the collection
            criteria (dict): The filter used to match the documents for updating
            update (dict | list): The modifications to apply
            add_to_set(bool): If True, uses '$addToSet' to add values to an array without duplicates.
                              If False, uses '$set' to update fields. Defaults to False.

        Raises:
            DocumentUpdateError: If the update operation fails

        Returns:
            UpdateResult: The result of the update operation
        """
        try:
            if not plain:
                update_operator = "$addToSet" if add_to_set else "$set"
                formatted_data = {update_operator: update}
            else:
                formatted_data = update

            return self.get_collection(collection, db_name).update_many(criteria, formatted_data)
        except Exception as err:
            raise DocumentUpdateError(f"Failed to update documents in '{collection}': {err}") from err


    def update_many_pull(
            self,
            collection: str,
            db_name: str,
            criteria: dict[str, Any],
            update: dict[str, Any]) -> UpdateResult:
        """
        Removes array elements from documents matching the filter using a `$pull` update

        The given `update` is wrapped in a `$pull` operator, so `criteria={'types_filter': 5}` with
        `update={'types_filter': 5}` removes 5 from the `types_filter` array of every matching document

        Args:
            collection (str): Name of database collection
            db_name (str): Name of the database holding the collection
            criteria (dict): The filter used to match the documents for updating
            update (dict): The `$pull` specification of the array elements to remove

        Raises:
            DocumentUpdateError: If the update operation fails

        Returns:
            UpdateResult: The result of the update operation
        """
        try:
            formatted_data = {"$pull": update}

            return self.get_collection(collection, db_name).update_many(criteria, formatted_data)
        except Exception as err:
            raise DocumentUpdateError(f"Failed to update documents in '{collection}': {err}") from err


    def update_many_raw(
        self,
        collection: str,
        db_name: str,
        filter_query: dict[str, Any],
        update: dict[str, Any],
        array_filters: list[dict[str, Any]] | None = None,
    ) -> UpdateResult:
        """
        Updates multiple documents using a raw update document (no '$set' wrapping)

        Args:
            collection (str): Name of the database collection
            db_name (str): Name of the database owning the collection
            filter_query (dict[str, Any]): Filter selecting the documents to update
            update (dict[str, Any]): Raw update document; must already contain its update operators
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
            raise DocumentUpdateError(
                f"Error updating documents in collection '{collection}': {err}"
            ) from err


    @retry_operation
    def update_public_id_counter(
        self,
        collection: str,
        db_name: str,
        value: int | None = None,
        increment: bool = False
    ) -> None:
        """
        Updates or increments the public_id counter for the given collection.

        Args:
            collection (str): Name of the collection.
            db_name (str): Name of the database owning the collection
            value (int | None): The new value to set for the counter.
                Ignored if `increment` is True.
            increment (bool): If True, increments the counter by 1.

        Raises:
            DocumentUpdateError: If the update operation fails.
        """
        try:
            working_collection = self.get_collection(PUBLIC_ID_COUNTER_COLLECTION, db_name)
            query = {"_id": collection}

            if increment:
                # Try to increment existing counter
                result = working_collection.update_one(query, {"$inc": {"counter": 1}})
                if result.matched_count == 0:
                    # No counter doc yet — create it starting at 1
                    working_collection.insert_one({"_id": collection, "counter": 1})

                return

            if value is not None:
                counter_doc = working_collection.find_one(query)

                if not counter_doc:
                    # Create counter doc starting at given value (min 1)
                    working_collection.insert_one({"_id": collection, "counter": max(1, value)})
                    return

                if value > counter_doc["counter"]:
                    working_collection.update_one(query, {"$set": {"counter": value}})
                return

            raise DocumentUpdateError("No valid update operation specified.")

        except Exception as err:
            raise DocumentUpdateError(
                f"Failed to update PublicID counter for '{collection}': {err}"
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
            DocumentGetError: When documents could not be retrieved

        Returns:
            list: A list of retrieved documents
        """
        try:
            found_documents = self.find(collection, db_name, *args, **kwargs)

            return list(found_documents)
        except Exception as err:
            LOGGER.error("[find_all] Can't retrive documents. Error: %s", err)
            raise DocumentGetError(f"Failed to retrieve documents from '{collection}': {err}") from err


    @retry_operation
    def find(self, collection: str, db_name: str, *args: Any, **kwargs: Any) -> Cursor[Any]:
        """
        Retrieves documents from the specified collection with optional filters and projections
        
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
    def aggregate(self, collection: str, db_name: str, *args: Any, **kwargs: Any) -> Cursor[Any]:
        """
        Perform aggregation on MongoDB

        Args:
            collection (str): Name of the database collection
            db_name (str): Name of the database owning the collection
            *args: Additional arguments for the aggregation pipeline
            **kwargs: Additional keyword arguments for the aggregation operation
        Raises:
            DocumentAggregationError: If the aggregation operation fails

        Returns:
            Cursor: The computed aggregation results as a cursor
        """
        try:
            return self.get_collection(collection, db_name).aggregate(*args, **kwargs)
        except Exception as err:
            raise DocumentAggregationError(f"Aggregation operation failed: {err}") from err


    @retry_operation
    def get_highest_id(self, collection: str, db_name: str) -> int:
        """
        Wrapper function that calls get_document_with_highest_id() and returns the highest public_id

        Args:
            collection (str): Name of database collection
            db_name (str): Name of the database owning the collection

        Raises:
            DocumentGetError: When documents could not be retrieved

        Returns:
            int: Highest public id or 0 if no document is found
        """
        try:
            formatted_sort = [('public_id', MONGO_SORT_DESCENDING)]

            # Get the highest public_id document
            highest_id_doc = self.find_one_by(collection=collection, db_name=db_name, sort=formatted_sort)

            # If no document is found, return 0
            if highest_id_doc is None:
                return 0

            return int(highest_id_doc['public_id'])

        except Exception as err:
            raise DocumentGetError(
                f"Failed to retrieve the highest public_id from collection '{collection}': {err}"
            ) from err

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
    def delete_many(self, collection: str, db_name: str, **requirements: Any) -> DeleteResult:
        """
        Removes all documents that match the filter from the collection

        Args:
            collection (str): Name of the database collection
            db_name (str): Name of the database owning the collection
            requirements (Any): Specifies the deletion criteria using query operators

        Raises:
            DocumentDeleteError: When documents could not be deleted

        Returns:
            DeleteResult: The result of the delete operation, including the number of documents deleted
        """
        try:
            return self.get_collection(collection, db_name).delete_many(requirements)
        except Exception as err:
            raise DocumentDeleteError(f"Error deleting documents from collection '{collection}': {err}") from err


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
