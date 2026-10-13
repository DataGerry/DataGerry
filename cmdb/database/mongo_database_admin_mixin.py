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
The database, collection and index administration half of the MongoDatabaseManager

Kept apart from the document operations so each half stays readable; the manager inherits it, so every caller keeps
calling the same methods on the same object
"""
from logging import Logger, getLogger
from typing import Any
from collections.abc import MutableMapping

from pymongo import IndexModel
from pymongo.collection import Collection
from pymongo.database import Database
from pymongo.errors import CollectionInvalid

from cmdb.database.mongo_connector import MongoConnector
from cmdb.database.retry import retry_operation

from cmdb.errors.database import (
    CollectionAlreadyExistsError,
    CreateIndexesError,
    DatabaseAlreadyExistsError,
    DatabaseConnectionError,
    DatabaseNotFoundError,
    DropIndexError,
    GetCollectionError,
    GetIndexesError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                             MongoDatabaseAdminMixin - CLASS                                          #
# -------------------------------------------------------------------------------------------------------------------- #
class MongoDatabaseAdminMixin:
    """
    Databases, collections and indexes: create, look up, drop

    A mixin of MongoDatabaseManager - it reads the manager's connector and default database name
    """
    connector: MongoConnector
    db_name: str

    def target_database(self, db_name: str) -> str:
        """
        Resolves which database name an operation should target

        Args:
            db_name (str): Explicitly requested database name (may be empty/None)

        Returns:
            str: The given db_name when provided, otherwise the manager's default database name
        """
        return db_name if db_name else self.db_name


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
                raise CollectionAlreadyExistsError(err) from err

            raise DatabaseConnectionError(f"Failed to create collection '{collection_name}': {err}") from err


    @retry_operation
    def get_collection(self, name: str, db_name: str) -> Collection[Any]:
        """
        Get a collection from the database

        Args:
            name (str): Collection name
            db_name (str): Name of the database owning the collection; empty means the manager's default

        Raises:
            GetCollectionError: When the collection could not be retrieved

        Returns:
            (Collection): The requested collection
        """
        try:
            return self.connector.get_database(self.target_database(db_name))[name]
        except Exception as err:
            LOGGER.error("[get_collection] '%s' Exception: %s. Type: %s", name, err, type(err))
            raise GetCollectionError(err) from err


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


    @retry_operation
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
