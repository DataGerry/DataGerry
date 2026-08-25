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
    Base class for every manager that needs database access

    Holds the target collection, database name and a BaseQueryBuilder, and provides the low-level
    MongoDB CRUD, aggregation and public_id helpers that domain managers build on. Database errors
    are wrapped in the BaseManager* exception hierarchy
    """

    def __init__(self, collection: str, dbm: MongoDatabaseManager, db_name: str | None) -> None:
        """
        Initialises the manager for a single MongoDB collection

        Args:
            collection (str): Name of the MongoDB collection this manager operates on
            dbm (MongoDatabaseManager): Database interaction manager
            db_name (str | None): Target database name; falls back to dbm.db_name when None
                (used to target a tenant database in cloud mode)

        Raises:
            BaseManagerInitError: If the initialisation fails
        """
        try:
            self.collection: str = collection
            self.query_builder: BaseQueryBuilder = BaseQueryBuilder()
            self.dbm: MongoDatabaseManager = dbm
            self.db_name: str = db_name if db_name else dbm.db_name
        except Exception as err:
            raise BaseManagerInitError(str(err)) from err

# --------------------------------------------------- CRUD - CREATE -------------------------------------------------- #

    def insert(self, data: dict[str, Any], skip_public: bool = False) -> int | None:
        """
        Inserts a single document into the manager's collection

        Args:
            data (dict[str, Any]): The document to insert
            skip_public (bool): If True, skip public_id generation and the counter increment; the
                document is inserted as-is and may carry no public_id (e.g. a collection keyed by a
                string id). Defaults to False

        Raises:
            BaseManagerInsertError: When the insertion failed

        Returns:
            int | None: The public_id of the inserted document, or None when skip_public is set and
                the document carries no public_id
        """
        try:
            return self.dbm.insert(self.collection, self.db_name, data, skip_public)
        except DocumentInsertError as err:
            raise BaseManagerInsertError(str(err)) from err


    def insert_many(
        self,
        data: list[dict[str, Any]],
        skip_public: bool = False,
    ) -> list[int]:
        """
        Inserts multiple documents into the manager's collection

        When skip_public is False, any document without a public_id is assigned the next one before
        insertion; when True, the documents are inserted as-is (each must already carry a public_id)

        Args:
            data (list[dict[str, Any]]): The documents to insert
            skip_public (bool): If True, skip public_id generation. Defaults to False

        Raises:
            BaseManagerInsertError: When the insertion failed

        Returns:
            list[int]: The public_ids of the inserted documents
        """
        try:
            if skip_public:
                return self.dbm.insert_many(self.collection, self.db_name, data, skip_public)

            # Assign the next public_id to every document that does not already carry one
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

    def get_distinct(self, key: str, criteria: dict[str, Any]) -> list[Any]:
        """
        Returns the distinct values of a field across documents matching the criteria

        Args:
            key (str): The document field whose distinct values are returned
            criteria (dict[str, Any]): Filter selecting which documents to consider

        Raises:
            BaseManagerGetError: If the distinct query fails

        Returns:
            list[Any]: The distinct values found for the field
        """
        try:
            return self.dbm.get_distinct(self.collection, self.db_name, key, criteria)
        except Exception as err:
            raise BaseManagerGetError(str(err)) from err


    def aggregate_query(
        self,
        builder_params: BuilderParameters,
        user: CmdbUser | None = None,
        permission: AccessControlPermission | None = None
    ) -> list[dict[str, Any]]:
        """
        Performs the data aggregation of a query WITHOUT the accompanying count aggregation

        The data half of ``iterate_query``, split out for callers that never read the total: a count
        is a second full aggregation over the same criteria, so a caller which only consumes the rows
        (e.g. running a CmdbReport) pays for it twice otherwise. Use this whenever no total is needed
        and ``iterate_query`` when it is - the two build the identical data pipeline

        Args:
            builder_params (BuilderParameters): Parameters to define the query
            user (CmdbUser | None): The user making the request. Defaults to None
            permission (AccessControlPermission | None): Permission to check. Defaults to None

        Raises:
            BaseManagerIterationError: If the aggregation process fails

        Returns:
            list[dict[str, Any]]: The aggregation results
        """
        try:
            query: list[dict] = self.query_builder.build(builder_params, user, permission)

            return list(self.aggregate(query))
        except Exception as err:
            raise BaseManagerIterationError(str(err)) from err


    def iterate_query(
        self,
        builder_params: BuilderParameters,
        user: CmdbUser | None = None,
        permission: AccessControlPermission | None = None
    ) -> tuple[list[dict[str, Any]], int]:
        """
        Performs an aggregation on the database, plus a second one for the total document count

        Delegates the data half to ``aggregate_query``; only the count pipeline is run here. Callers
        that discard the total should call ``aggregate_query`` directly instead of ignoring the
        second element of the returned tuple

        Args:
            builder_params (BuilderParameters): Parameters to define the query
            user (CmdbUser | None): The user making the request. Defaults to None
            permission (AccessControlPermission | None): Permission to check. Defaults to None

        Raises:
            BaseManagerIterationError: If the aggregation process fails

        Returns:
            tuple[list[dict[str, Any]], int]: The aggregation results and the total document count
        """
        try:
            aggregation_result: list[dict[str, Any]] = self.aggregate_query(builder_params, user, permission)

            count_query: list[dict] = self.query_builder.count(builder_params.get_criteria())
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


    def count_from_other_collection(self, collection: str, criteria: dict[str, Any] | None = None) -> int:
        """
        Counts the documents in another collection that match the given criteria

        The cross-collection counterpart of count_documents (which targets this manager's own
        collection); used to test for referencing documents without loading them

        Args:
            collection (str): The name of the collection to count in
            criteria (dict[str, Any] | None): Filter selecting which documents to count. Defaults to None

        Raises:
            BaseManagerGetError: When the count operation fails

        Returns:
            int: The number of documents in the other collection matching the criteria
        """
        try:
            return self.dbm.count(collection, self.db_name, criteria)
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
            limit (int): Number of documents to retrieve (0 for no limit)
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
            raise BaseManagerGetError(str(err)) from err


    def find_all(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        """
        Retrieves all documents that match the given criteria using the 'find' method

        Args:
            *args: Positional arguments for the 'find' query
            **kwargs: Keyword arguments for the 'find' query

        Raises:
            BaseManagerGetError: If an error occurs during the find operation

        Returns:
            list[dict[str, Any]]: A list of documents matching the search criteria
        """
        return self.find(*args, **kwargs)


    def find(self, criteria: dict | None = None, **kwargs: Any) -> list[dict[str, Any]]:
        """
        Retrieves documents from this manager's collection that match the given criteria

        Args:
            criteria (dict | None): The filter criteria for the find query. Defaults to None
            **kwargs: Additional keyword arguments for the 'find' operation (projection, sort, limit)

        Raises:
            BaseManagerGetError: If an error occurs while retrieving documents from the collection

        Returns:
            list[dict[str, Any]]: A list of dictionaries matching the criteria
        """
        try:
            if criteria is None:
                criteria = {}

            return list(self.dbm.find(
                self.collection,
                self.db_name,
                filter=criteria,
                **kwargs
            ))
        except DocumentGetError as err:
            raise BaseManagerGetError(str(err)) from err


    def get_one_by(self, criteria: dict[str, Any], collection: str | None = None) -> dict[str, Any] | None:
        """
        Retrieves a single document defined by the given criteria

        Args:
            criteria (dict[str, Any]): The filter for the document to be retrieved
            collection (str | None): Collection to search; defaults to this manager's collection when None

        Raises:
            BaseManagerGetError: If an error occurs during the 'find_one_by' operation

        Returns:
            dict | None: The found document, or None if no document matches the criteria
        """
        try:
            target_collection: str = collection or self.collection

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


    def aggregate(self, *args: Any, **kwargs: Any) -> CommandCursor:
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
            raise BaseManagerIterationError(str(err)) from err


    def aggregate_from_other_collection(self, collection: str, *args: Any, **kwargs: Any) -> CommandCursor:
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

        Args:
            inc_id (bool): If True, increment the stored counter so the id is consumed.
                Defaults to False

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
        """
        Reserves a batch of public_ids for the collection

        Args:
            amount (int): Number of public_ids to reserve

        Raises:
            BaseManagerGetError: If reserving the public_ids fails

        Returns:
            list[int]: The reserved public_ids
        """
        try:
            return self.dbm.reserve_public_ids(self.collection, self.db_name, amount)
        except DocumentGetError as err:
            raise BaseManagerGetError(str(err)) from err


    def count_documents(self, criteria: dict[str, Any] | None = None, limit: int | None = None) -> int:
        """
        Counts the number of documents in a collection based on the given filter

        Args:
            criteria (dict[str, Any] | None): Filter selecting documents to count. Defaults to None
            limit (int | None): Stop counting after this many matches; ``limit=1`` turns the count
                into an existence check the server can short-circuit. Defaults to None (count all)

        Raises:
            BaseManagerGetError: If an error occurs during the 'count' operation

        Returns:
            int: The number of documents that match the given criteria, capped at 'limit' when given
        """
        try:
            return self.dbm.count(self.collection, self.db_name, criteria, limit)
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
        collection: str | None = None,
        **kwargs: Any
    ) -> UpdateResult:
        """
        Updates the document(s) in the collection matching the given criteria

        Args:
            criteria (dict[str, Any]): The filter selecting the document(s) to update
            data (dict[str, Any]): The update data to apply to the matched document(s)
            *args: Additional positional arguments passed to the update operation
            add_to_set (bool): If True, wrap `data` in `$set` unless it already contains update
                operators. Defaults to True
            plain (bool): If True, send `data` as-is without wrapping it in an operator.
                Defaults to False
            collection (str | None): Collection to update; defaults to this manager's collection when None
            **kwargs: Additional keyword arguments passed to the update operation

        Raises:
            BaseManagerUpdateError: If an error occurs during the update operation

        Returns:
            UpdateResult: The outcome of the update, including the matched and modified counts
        """
        try:
            target_collection = collection or self.collection

            return self.dbm.update(
                target_collection, self.db_name, criteria, data, *args,
                add_to_set=add_to_set, plain=plain, **kwargs
            )
        except DocumentUpdateError as err:
            raise BaseManagerUpdateError(str(err)) from err


    def upsert(
        self,
        criteria: dict[str, Any],
        data: dict[str, Any],
        collection: str | None = None,
    ) -> UpdateResult:
        """
        Inserts or updates a single document matched by arbitrary criteria

        Sets the matched document's fields from `data`; if nothing matches, inserts a new document
        carrying both the criteria keys and `data`. The match is by arbitrary criteria (not tied to
        `public_id`), so this supports `_id`-keyed singletons

        Args:
            criteria (dict[str, Any]): The filter selecting the document to upsert
            data (dict[str, Any]): The fields to set on the matched (or newly inserted) document
            collection (str | None): Collection to upsert into; defaults to this manager's
                collection when None

        Raises:
            BaseManagerUpdateError: If an error occurs during the upsert operation

        Returns:
            UpdateResult: The outcome of the upsert (matched / modified / upserted info)
        """
        try:
            target_collection = collection if collection else self.collection

            return self.dbm.upsert(target_collection, self.db_name, criteria, data)
        except DocumentUpdateError as err:
            raise BaseManagerUpdateError(str(err)) from err


    def update_many(
            self,
            criteria: dict[str, Any],
            update: dict[str, Any],
            add_to_set: bool = False,
            plain: bool = False
    ) -> UpdateResult:
        """
        Updates multiple documents in the collection that match the given filter

        Args:
            criteria (dict[str, Any]): Filter selecting the documents to update
            update (dict[str, Any]): The update operations to apply
            add_to_set (bool): If True, wrap `update` in `$set` unless it already contains update
                operators. Defaults to False
            plain (bool): If True, send `update` as-is without wrapping it in an operator.
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


    def update_many_pull(self, criteria: dict[str, Any], update: dict[str, Any]) -> UpdateResult:
        """
        Removes array elements from documents matching the filter using a `$pull` update

        Args:
            criteria (dict[str, Any]): Filter selecting the documents to update
            update (dict[str, Any]): The `$pull` specification of the elements to remove

        Raises:
            BaseManagerUpdateError: If the update operation fails

        Returns:
            UpdateResult: The outcome of the update, including the matched and modified counts
        """
        try:
            return self.dbm.update_many_pull(self.collection, self.db_name, criteria, update)
        except DocumentUpdateError as err:
            raise BaseManagerUpdateError(str(err)) from err


    def update_many_raw(
        self,
        filter_query: dict[str, Any],
        update: dict[str, Any],
        array_filters: list[dict] | None = None,
    ) -> UpdateResult:
        """
        Updates multiple documents using a raw update spec, with optional array filters

        The update is passed through unchanged (it must carry its own operators); array_filters
        supply the identifiers for positional `$[<identifier>]` updates

        Args:
            filter_query (dict[str, Any]): Filter selecting the documents to update
            update (dict[str, Any]): The raw update document (must include its own operators)
            array_filters (list[dict] | None): Array filters for positional updates. Defaults to None

        Raises:
            BaseManagerUpdateError: If the update operation fails

        Returns:
            UpdateResult: The outcome of the update, including the matched and modified counts
        """
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


    def bulk_write(self, operations: list[Any]) -> None:
        """
        Performs a bulk write on the current manager's collection.

        Args:
            operations (list): List of pymongo operations (e.g., UpdateOne, DeleteOne, etc.)

        Raises:
            BaseManagerUpdateError: If the bulk write fails.
        """
        try:
            self.dbm.bulk_write(self.collection, self.db_name, operations)
        except DocumentInsertError as err:
            raise BaseManagerUpdateError(f"Bulk write failed in collection '{self.collection}': {err}") from err

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

    def delete(self, criteria: dict[str, Any], collection: str | None = None) -> bool:
        """
        Deletes a document from the collection that matches the given criteria

        Args:
            criteria (dict[str, Any]): Filter selecting the document to delete
            collection (str | None): Collection to delete from; defaults to this manager's
                collection when None

        Raises:
            BaseManagerDeleteError: If the deletion operation fails

        Returns:
            bool: True if the deletion was acknowledged, otherwise False
        """
        try:
            target_collection = collection or self.collection

            result = self.dbm.delete(target_collection, self.db_name, criteria)

            return result.acknowledged and result.deleted_count > 0
        except DocumentDeleteError as err:
            raise BaseManagerDeleteError(str(err)) from err


    def delete_many(self, filter_query: dict[str, Any]) -> DeleteResult:
        """
        Deletes multiple documents from the collection that match the given filter criteria

        Args:
            filter_query (dict[str, Any]): Dictionary specifying the filter criteria for selecting documents to delete

        Raises:
            BaseManagerDeleteError: If the deletion operation fails

        Returns:
            DeleteResult: The result of the delete operation, containing details about the number of deleted documents
        """
        try:
            return self.dbm.delete_many(collection=self.collection, db_name=self.db_name, **filter_query)
        except DocumentDeleteError as err:
            raise BaseManagerDeleteError(str(err)) from err


    def delete_many_raw(self, filter_query: dict[str, Any]) -> DeleteResult:
        """
        Deletes every document matching the given raw filter

        Args:
            filter_query (dict[str, Any]): The raw MongoDB filter selecting documents to delete

        Raises:
            BaseManagerDeleteError: If the deletion operation fails

        Returns:
            DeleteResult: The outcome of the delete, including the deleted document count
        """
        try:
            return self.dbm.delete_many_raw(
                collection=self.collection,
                db_name=self.db_name,
                filter_query=filter_query
            )
        except DocumentDeleteError as err:
            raise BaseManagerDeleteError(str(err)) from err


    def delete_many_from_other_collection(self, collection: str, filter_query: dict[str, Any]) -> DeleteResult:
        """
        Deletes every document matching the raw filter from another collection

        The cross-collection counterpart of delete_many / delete_many_raw (which target this manager's
        own collection); used to cascade a delete into referencing collections in a single round-trip
        instead of fetching the referencing documents and deleting them one by one

        Args:
            collection (str): The name of the collection to delete from
            filter_query (dict[str, Any]): The raw MongoDB filter selecting documents to delete
                                           (supports operators, e.g. {'public_id': {'$in': [...]}})

        Raises:
            BaseManagerDeleteError: If the deletion operation fails

        Returns:
            DeleteResult: The outcome of the delete, including the deleted document count
        """
        try:
            return self.dbm.delete_many_raw(collection=collection, db_name=self.db_name, filter_query=filter_query)
        except DocumentDeleteError as err:
            raise BaseManagerDeleteError(str(err)) from err
