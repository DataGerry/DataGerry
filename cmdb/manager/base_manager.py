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
Implementation of the BaseManager for all Managers requiring a database connection
"""
from logging import Logger, getLogger
from typing import Any

from pymongo.results import DeleteResult, UpdateResult
from pymongo.cursor import Cursor
from pymongo.command_cursor import CommandCursor

from cmdb.database import MongoDatabaseManager
from cmdb.manager.query_builder import BaseQueryBuilder, BuilderParameters

from cmdb.models.user_model import CmdbUser
from cmdb.security.acl.permission import AccessControlPermission

from cmdb.errors.database import (
    DocumentInsertError,
    DocumentGetError,
    DocumentUpdateError,
    DocumentDeleteError,
    DocumentAggregationError,
)
from cmdb.errors.manager import (
    BaseManagerInitError,
    BaseManagerInsertError,
    BaseManagerGetError,
    BaseManagerUpdateError,
    BaseManagerDeleteError,
    BaseManagerIterationError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                  BaseManager - CLASS                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
class BaseManager:
    """
    This is the base class for every FrameworkManager
    """

    def __init__(self, collection: str, dbm: MongoDatabaseManager, db_name: str | None) -> None:
        """
        Initializes the class with a collection name and database manager

        Args:
            collection (str): Name of the MongoDB collection
            dbm (MongoDatabaseManager): An instance of the database manager

        Raises:
            BaseManagerInitError: If the initialisation fails
        """
        try:
            self.collection: str = collection
            self.query_builder = BaseQueryBuilder()
            self.dbm: MongoDatabaseManager = dbm
            self.db_name: str = db_name if db_name else dbm.db_name
        except Exception as err:
            raise BaseManagerInitError(str(err)) from err

# --------------------------------------------------- CRUD - CREATE -------------------------------------------------- #

    def insert(self, data: dict[str, Any], skip_public: bool = False) -> int:
        """
        Insert document into database

        Args:
            data (dict): The document data which should be inserted
            skip_public (bool): If True, skips public ID creation and counter increment. Defaults to False.

        Raises:
            BaseManagerInsertError: When the insertion failed

        Returns:
            int: The newly assigned public_id of the inserted document
        """
        try:
            return self.dbm.insert(self.collection, self.db_name, data, skip_public)
        except DocumentInsertError as err:
            raise BaseManagerInsertError(str(err)) from err


    def insert_many(
        self,
        data: list[dict[str, Any]],
        skip_public: bool = False,
    ) -> None:
        """
        Insert multiple documents into the manager's collection.

        Args:
            data (list[dict]): Documents to insert (public_id must be pre-assigned if skip_public=True)
            skip_public (bool): Skip public_id generation (default True for bulk inserts)
        """
        try:
            if skip_public:
                return self.dbm.insert_many(self.collection, self.db_name, data, skip_public)

            # If you ever want public_id generation here in the future:
            for item in data:
                if "public_id" not in item:
                    item["public_id"] = self.dbm.get_next_public_id(
                        self.collection,
                        self.db_name,
                        inc_id=True
                    )

            return self.dbm.insert_many(self.collection, self.db_name, data)

        except Exception as err:
            raise BaseManagerInsertError(str(err)) from err

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

    def iterate_query(
        self,
        builder_params: BuilderParameters,
        user: CmdbUser | None = None,
        permission: AccessControlPermission | None = None
    ) -> tuple[list, int]:
        """
        Performs an aggregation on the database

        Args:
            builder_params (BuilderParameters): Parameters to define the query
            user (CmdbUser | None): The user making the request. Defaults to None
            permission (AccessControlPermission | None): Permission to check. Defaults to None

        Raises:
            BaseManagerIterationError: If the aggregation process fails

        Returns:
            tuple[list, int]: A tuple containing the aggregation results and the total count
        """
        try:
            query: list[dict] = self.query_builder.build(builder_params, user, permission)
            count_query: list[dict] = self.query_builder.count(builder_params.get_criteria())

            aggregation_result = list(self.aggregate(query))
            total_cursor = self.aggregate(count_query)

            total = next(total_cursor, {}).get('total', 0)

            return aggregation_result , total
        except Exception as err:
            raise BaseManagerIterationError(str(err)) from err


    def get_one(self, *args: Any, **kwargs: Any) -> dict[str, Any] | None:
        """
        Retrieves a single document from MongoDB

        Args:
            *args: Positional arguments for the 'find_one' query
            **kwargs: Keyword arguments for the 'find_one' query

        Raises:
            BaseManagerGetError: If the document could not be retrieved

        Returns:
            dict | None: The found document or None if no document matches the query
        """
        try:
            return self.dbm.find_one(self.collection, self.db_name, *args, **kwargs)
        except DocumentGetError as err:
            raise BaseManagerGetError(str(err)) from err


    def get_one_from_other_collection(self, collection: str, public_id: int) -> dict[str, Any] | None:
        """
        Retrieves a single document from another MongoDB collection

        Args:
            collection (str): The name of the collection to search in
            public_id (int): The public ID of the document to retrieve

        Raises:
            BaseManagerGetError: When the find_one operation fails
        
        Returns:
            dict[str, Any] | None: The found document as a dictionary or None if no document matches the query
        """
        try:
            return self.dbm.find_one(collection, self.db_name, public_id)
        except DocumentGetError as err:
            raise BaseManagerGetError(str(err)) from err


    def get_many_from_other_collection(
            self,
            collection: str,
            sort: str = 'public_id',
            direction: int = -1,
            limit: int = 0,
            **requirements: Any) -> list[dict[str, Any]]:
        """
        Retrieves documents from a given collection that match the specified requirements

        Args:
            collection (str): The name of the target collection
            sort (str): Field to sort by (default: 'public_id')
            direction (int): Sorting direction (1 for ascending, -1 for descending)
            limit (int): umber of documents to retrieve (0 for no limit)
            **requirements (dict): Key-value pairs for filtering the documents

        Raises:
            BaseManagerGetError: If an error occurs during the retrieval process

        Returns:
            list[dict]: List of documents that match the filtering criteria
        """
        try:
            requirements_filter = requirements if requirements else {}
            formatted_sort = [(sort, direction)]

            return self.dbm.find_all(collection=collection,
                                     db_name=self.db_name,
                                     limit=limit,
                                     filter=requirements_filter,
                                     sort=formatted_sort)
        except DocumentGetError as err:
            raise BaseManagerGetError(str(err)) from err


    def get(self, *args: Any, **kwargs: Any) -> Cursor:
        """
        General method to retrieve documents from the collection using MongoDB's 'find' operation

        Args:
            *args: Positional arguments for the 'find' query
            **kwargs: Keyword arguments for the 'find' query

        Raises:
            BaseManagerGetError: If an error occurs during the retrieval process

        Returns:
            Cursor: A cursor that points to the result set of the 'find' operation
        """
        try:
            return self.dbm.find(self.collection, self.db_name, *args, **kwargs)
        except DocumentGetError as err:
            raise BaseManagerGetError(err) from err


    def find_all(self, *args, **kwargs) -> list[dict]:
        """
        Retrieves all documents that match the given criteria using the 'find' method

        Args:
            *args: Positional arguments for the 'find' query
            **kwargs: Keyword arguments for the 'find' query

        Raises:
            BaseManagerFindError: If an error occurs during the find operation

        Returns:
            list[dict]: A list of documents matching the search criteria
        """
        try:
            found_documents = self.find(*args, **kwargs)

            try:
                return list(found_documents)
            except Exception as err:
                raise BaseManagerGetError(err) from err
        except BaseManagerGetError as err:
            raise err


    def find(self, *args: Any, criteria: dict = None, **kwargs: Any) -> Cursor:
        """
        Retrieves documents from the specified collection that match the given criteria.

        Args:
            *args: Additional positional arguments for the 'find' operation
            criteria (dict | None): The filter criteria for the find query. Defaults to Nones
            **kwargs: Additional keyword arguments for the 'find' operation

        Raises:
            BaseManagerGetError: If an error occurs while retrieving documents from the collection

        Returns:
            Cursor: A cursor for the result set, allowing iteration over the documents that match the criteria
        """
        try:
            if criteria is None:
                criteria = {}

            return self.dbm.find(collection=self.collection, db_name=self.db_name, filter=criteria, *args, **kwargs)
        except DocumentGetError as err:
            raise BaseManagerGetError(err) from err


    def get_one_by(self, criteria: dict[str, Any], collection: str | None = None) -> dict[str, Any] | None:
        """
        Retrieves a single document defined by the given criteria

        Args:
            criteria (dict): The filter for the document to be retrieved

        Raises:
            BaseManagerGetError: If an error occurs during the 'find_one_by' operation

        Returns:
            dict | None: The found document, or None if no document matches the criteria
        """
        try:
            target_collection = collection or self.collection

            return self.dbm.find_one_by(target_collection, self.db_name, criteria)
        except DocumentGetError as err:
            raise BaseManagerGetError(str(err)) from err


    def get_many(
        self,
        sort: str = 'public_id',
        direction: int = -1,
        limit: int=0,
        **requirements: Any
    ) -> list[dict[str, Any]]:
        """
        Retrieves documents from the database filtered by the provided requirements

        Args:
            sort (str): The field to sort the results by. Default is 'public_id'
            direction (int): The sorting direction. 1 for ascending, -1 for descending. Default is -1
            limit (int): The maximum number of documents to retrieve. 0 means no limit (default is 0)
            **requirements (dict): Dictionary of key-value pairs used as filters for the query

        Raises:
            BaseManagerGetError: If the retrieval of documents fails

        Returns:
            list[dict]: A list of documents that match the criteria
        """
        try:
            requirements_filter = requirements if requirements else {}
            formatted_sort = [(sort, direction)]

            return self.dbm.find_all(collection=self.collection,
                                     db_name=self.db_name,
                                    limit=limit,
                                    filter=requirements_filter,
                                    sort=formatted_sort)
        except DocumentGetError as err:
            raise BaseManagerGetError(str(err)) from err


    def aggregate(self, *args, **kwargs) -> CommandCursor:
        """
        Performs a MongoDB aggregation operation on the collection

        Args:
            *args: Positional arguments for the aggregation pipeline
            **kwargs: Keyword arguments for additional aggregation options

        Raises:
            BaseManagerIterationError: If an error occurs during the aggregation operation

        Returns:
            CommandCursor: A cursor that can be iterated over to access the aggregation results
        """
        try:
            return self.dbm.aggregate(self.collection, self.db_name, *args, **kwargs)
        except DocumentAggregationError as err:
            raise BaseManagerIterationError(err) from err


    def aggregate_from_other_collection(self, collection: str, *args, **kwargs) -> CommandCursor:
        """
        Performs a MongoDB aggregation operation on the specified collection

        Args:
            collection (str): The name of the collection to perform the aggregation on
            *args: Positional arguments for the aggregation pipeline
            **kwargs: Keyword arguments for additional aggregation options

        Raises:
            BaseManagerIterationError: If an error occurs during the aggregation operation

        Returns:
            CommandCursor: A cursor that can be iterated over to access the aggregation results
        """
        try:
            return self.dbm.aggregate(collection, self.db_name, *args, **kwargs)
        except DocumentAggregationError as err:
            raise BaseManagerIterationError(str(err)) from err


    def get_next_public_id(self, inc_id: bool = False) -> int:
        """
        Retrieves the next public_id for the collection

        Raises:
            BaseManagerGetError: If retrieving the next public_id fails for any reason

        Returns:
            int: The next public_id for the collection
        """
        try:
            return self.dbm.get_next_public_id(self.collection, self.db_name, inc_id)
        except DocumentGetError as err:
            raise BaseManagerGetError(str(err)) from err


    def reserve_public_ids(self, amount: int) -> list[int]:
        """TODO: document"""
        try:
            return self.dbm.reserve_public_ids(self.collection, self.db_name, amount)
        except DocumentGetError as err:
            raise BaseManagerGetError(str(err)) from err


    def count_documents(self, collection: str, *args: Any, **kwargs: Any) -> int:
        """
        Counts the number of documents in a collection based on the given filter

        Args:
            collection (str): The name of the collection to count documents from
            *args: Positional arguments for the 'count' operation
            **kwargs: Keyword arguments for the 'count' operation (e.g., filter criteria)

        Raises:
            BaseManagerGetError: If an error occurs during the 'count' operation

        Returns:
            int: The number of documents that match the given criteria
        """
        try:
            return self.dbm.count(collection, self.db_name, *args, **kwargs)
        except DocumentGetError as err:
            raise BaseManagerGetError(str(err)) from err

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

    def update(
        self,
        criteria: dict[str, Any],
        data: dict[str, Any],
        *args: Any,
        add_to_set: bool = True,
        plain: bool = False,
        col: str | None = None,
        **kwargs: Any
    ) -> UpdateResult:
        """
        Updates a document in the database with the specified criteria and new data

        Args:
            criteria (dict): The filter used to match the document(s) to be updated
            data (dict): The update data to apply to the matched document(s)
            *args: Additional positional arguments passed to the update operation
            add_to_set (bool): If True, wraps `data` in `$set` unless the `data` already contains update
                                         operators. Defaults to True
            plain (bool): If true, then no modification of data
            **kwargs: Additional keyword arguments passed to the update operation


        Raises:
            BaseManagerUpdateError: If an error occurs during the update operation

        Returns:
            UpdateResult: An object containing the outcome of the update operation, such as the number of documents
                          matched and modified
        """
        try:
            collection = col if col else self.collection

            return self.dbm.update(collection, self.db_name, criteria, data, *args, add_to_set, plain, **kwargs)
        except DocumentUpdateError as err:
            raise BaseManagerUpdateError(str(err)) from err


    def upsert_set(self, data: dict, collection:str | None = None) -> UpdateResult:
        """
        Performs an upsert operation on a specified MongoDB collection.

        This method attempts to update a document in the specified collection (or a default
        collection if none is provided) by matching the `public_id` field. If the document
        does not exist, it will insert the document with the provided data.

        Args:
            data (dict): A dictionary containing the data to be inserted or updated.
                        The dictionary should contain at least the 'public_id' field
                        to identify the document.
            collection (str | None): The name of the MongoDB collection where the upsert
                                        operation will be performed. If not provided, the
                                        method will use the default collection.

        Returns:
            UpdateResult: The result of the update operation, providing information
                        about the modified or inserted document.

        Raises:
            BaseManagerUpdateError: If an error occurs during the upsert operation,
                                    a custom exception is raised with details about the failure.
        """
        try:
            target_collection = collection if collection else self.collection

            return self.dbm.upsert_set(target_collection, self.db_name, data)
        except DocumentUpdateError as err:
            raise BaseManagerUpdateError(str(err)) from err


    def update_many(
            self,
            criteria: dict,
            update: dict,
            add_to_set: bool = False,
            plain: bool = False) -> UpdateResult:
        """
        Updates multiple documents in the collection that match the given filter

        Args:
            criteria (dict): A dictionary specifying the filter criteria for selecting documents to update
            update (dict): A dictionary containing the update operations to be applied
            add_to_set (bool): If True, wraps `update` in '$set' unless it already contains update
                                         operators. Defaults to False
            plain (bool): If True, sends the update dict as-is without wrapping it in an operator.
                                    Defaults to False

        Raises:
            BaseManagerUpdateError: If the update operation fails

        Returns:
            UpdateResult: The result of the update operation, containing metadata about the operation's success
        """
        try:
            return self.dbm.update_many(self.collection, self.db_name, criteria, update, add_to_set, plain)
        except DocumentUpdateError as err:
            raise BaseManagerUpdateError(str(err)) from err


    def update_many_pull(self, criteria: dict, update: dict) -> UpdateResult:
        """
        Updates multiple documents in the collection that match the given filter

        Args:
            criteria (dict): A dictionary specifying the filter criteria for selecting documents to update
            update (dict): A dictionary containing the update operations to be applied

        Raises:
            BaseManagerUpdateError: If the update operation fails

        Returns:
            UpdateResult: The result of the update operation, containing metadata about the operation's success
        """
        try:
            return self.dbm.update_many_pull(self.collection, self.db_name, criteria, update)
        except DocumentUpdateError as err:
            raise BaseManagerUpdateError(str(err)) from err


    def update_many_raw(self, filter_query: dict, update: dict, array_filters: list[dict] | None = None):
        """TODO: document"""
        try:
            return self.dbm.update_many_raw(
                collection=self.collection,
                db_name=self.db_name,
                filter_query=filter_query,
                update=update,
                array_filters=array_filters,
            )
        except DocumentUpdateError as err:
            raise BaseManagerUpdateError(str(err)) from err

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

    def delete(self, criteria: dict, collection: str | None = None) -> bool:
        """
        Deletes a document from the collection that matches the given criteria

        Args:
            criteria (dict): A dictionary specifying the filter criteria for selecting the document to delete

        Raises:
            BaseManagerDeleteError: If the deletion operation fails

        Returns:
            bool: True if the deletion was acknowledged, otherwise False
        """
        try:
            target_collection = self.collection

            if collection:
                target_collection = collection

            result = self.dbm.delete(target_collection, self.db_name, criteria)

            return result.acknowledged and result.deleted_count > 0
        except Exception as err:
            raise BaseManagerDeleteError(str(err)) from err


    def delete_many(self, filter_query: dict) -> DeleteResult:
        """
        Deletes multiple documents from the collection that match the given filter criteria

        Args:
            filter_query (dict): A dictionary specifying the filter criteria for selecting documents to delete

        Raises:
            BaseManagerDeleteError: If the deletion operation fails

        Returns:
            DeleteResult: The result of the delete operation, containing details about the number of deleted documents
        """
        try:
            return self.dbm.delete_many(collection=self.collection, db_name=self.db_name, **filter_query)
        except DocumentDeleteError as err:
            raise BaseManagerDeleteError(err) from err


    def delete_many_raw(self, filter_query: dict) -> DeleteResult:
        """TODO: document"""
        try:
            return self.dbm.delete_many_raw(
                collection=self.collection,
                db_name=self.db_name,
                filter_query=filter_query
            )
        except DocumentDeleteError as err:
            raise BaseManagerDeleteError(err) from err
