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
The cross-collection half of the BaseManager

A manager owns one collection, and these methods read, count and delete in ANOTHER one of the same database - a
referencing collection a delete cascades into, a document of another type a check needs. `BaseManager` inherits
them, so every manager keeps calling them on itself. Every database error is wrapped in the BaseManager* exception
hierarchy, like the rest of the manager
"""
from typing import Any

from pymongo.results import DeleteResult

from cmdb.database import MongoDatabaseManager
from cmdb.manager.base_manager_constants import EMPTY_DELETE_FILTER_MSG

from cmdb.errors.database import DocumentGetError, DocumentDeleteError
from cmdb.errors.manager import BaseManagerGetError, BaseManagerDeleteError
# -------------------------------------------------------------------------------------------------------------------- #

# -------------------------------------------------------------------------------------------------------------------- #
#                                          OtherCollectionAccessMixin - CLASS                                          #
# -------------------------------------------------------------------------------------------------------------------- #
class OtherCollectionAccessMixin:
    """
    Reads, counts and deletes in a collection other than the manager's own

    A mixin of BaseManager - it reaches the database through the manager's `dbm` and `db_name`
    """
    dbm: MongoDatabaseManager
    db_name: str

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
            raise BaseManagerGetError(err) from err


    def count_from_other_collection(
            self,
            collection: str,
            criteria: dict[str, Any] | None = None,
            limit: int | None = None) -> int:
        """
        Counts the documents in another collection that match the given criteria

        The cross-collection counterpart of count_documents (which targets this manager's own
        collection); used to test for referencing documents without loading them

        Args:
            collection (str): The name of the collection to count in
            criteria (dict[str, Any] | None): Filter selecting which documents to count. Defaults to None
            limit (int | None): Stop counting after this many matches; ``limit=1`` turns the count
                into an existence check the server can short-circuit. Defaults to None (count all)

        Raises:
            BaseManagerGetError: When the count operation fails

        Returns:
            int: The number of documents in the other collection matching the criteria
        """
        try:
            return self.dbm.count(collection, self.db_name, criteria, limit)
        except DocumentGetError as err:
            raise BaseManagerGetError(err) from err


    def get_many_from_other_collection(
            self,
            collection: str,
            sort: str = 'public_id',
            direction: int = -1,
            limit: int = 0,
            projection: dict[str, Any] | None = None,
            *,
            criteria: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """
        Retrieves documents from a given collection that match the criteria

        Args:
            collection (str): The name of the target collection
            sort (str): Field to sort by (default: 'public_id')
            direction (int): Sorting direction (1 for ascending, -1 for descending)
            limit (int): Number of documents to retrieve (0 for no limit)
            projection (dict[str, Any] | None): The fields to return, as a MongoDB projection. When
                given it replaces the database layer's default (which only drops `_id`), so a caller
                reading a few keys of a large document does not pay for the rest - remember to
                exclude `_id` explicitly, since MongoDB returns it unless told otherwise
            criteria (dict[str, Any] | None): The MongoDB filter, as one dict - any key and any operator, a
                dotted path (`'multi_data_sections.section_id'`) included. None reads every document. Keyword-only,
                so a field named like an option (`sort`, `limit`, ...) is still a filter field

        Raises:
            BaseManagerGetError: If an error occurs during the retrieval process

        Returns:
            list[dict]: List of documents that match the filtering criteria
        """
        try:
            formatted_sort = [(sort, direction)]
            find_options: dict[str, Any] = {} if projection is None else {'projection': projection}

            return self.dbm.find_all(collection=collection,
                                     db_name=self.db_name,
                                     limit=limit,
                                     filter=criteria or {},
                                     sort=formatted_sort,
                                     **find_options)
        except DocumentGetError as err:
            raise BaseManagerGetError(err) from err


    def delete_many_from_other_collection(
            self,
            collection: str,
            filter_query: dict[str, Any],
            *,
            delete_all: bool = False) -> DeleteResult:
        """
        Deletes every document matching the raw filter from another collection

        The cross-collection counterpart of delete_many (which targets this manager's own collection); used to
        cascade a delete into referencing collections in a single round-trip
        instead of fetching the referencing documents and deleting them one by one.

        **An empty filter is refused unless `delete_all` says it is meant**, as `delete_many` refuses it: ``{}``
        matches every document, so a filter that came out empty would empty the collection. A deliberate full delete
        - of any collection, the manager's own included - passes ``delete_all=True``

        Args:
            collection (str): The name of the collection to delete from
            filter_query (dict[str, Any]): The raw MongoDB filter selecting documents to delete
                                           (supports operators, e.g. {'public_id': {'$in': [...]}})
            delete_all (bool): Whether an empty filter is meant, deleting every document of the collection. Keyword
                only. Defaults to False

        Raises:
            BaseManagerDeleteError: If the filter is empty without `delete_all` (nothing is deleted), or the deletion
                fails

        Returns:
            DeleteResult: The outcome of the delete, including the deleted document count
        """
        if not filter_query and not delete_all:
            raise BaseManagerDeleteError(EMPTY_DELETE_FILTER_MSG.format(collection=collection))

        try:
            return self.dbm.delete_many_raw(collection=collection, db_name=self.db_name, filter_query=filter_query)
        except DocumentDeleteError as err:
            raise BaseManagerDeleteError(err) from err
