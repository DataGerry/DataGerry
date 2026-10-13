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
The public_id counter half of the MongoDatabaseManager

Every collection whose documents carry a public_id has a counter document in `PUBLIC_ID_COUNTER_COLLECTION`, keyed by
the collection's name, holding the highest id handed out. This half seeds, peeks, reserves, raises, resets and sets
those counters; the manager inherits it, so every caller keeps calling the same methods on the same object
"""
from logging import Logger, getLogger

from pymongo import ReturnDocument

from cmdb.database.database_constants import MONGO_SORT_DESCENDING, PUBLIC_ID_COUNTER_COLLECTION
from cmdb.database.retry import retry_operation

from cmdb.errors.database import DocumentGetError, DocumentUpdateError, PublicIdCounterInitError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                          MongoPublicIdCounterMixin - CLASS                                           #
# -------------------------------------------------------------------------------------------------------------------- #
class MongoPublicIdCounterMixin:
    """
    The public_id counters: seed, peek, reserve, raise, reset and set

    A mixin of MongoDatabaseManager - it reads collections through `get_collection` (MongoDatabaseAdminMixin) and
    the highest stored id through the manager's `find_one_by`
    """

    def _raise_counter_to_stored_id(self, collection: str, db_name: str, public_id: int) -> None:
        """
        Raises a collection's public_id counter to an id a caller supplied, once the document is stored

        The document is stored by then, so a failure here is NOT a failed insert: reported as one, the caller
        would answer "insert failed" for a document that exists, and its retry would be refused as a duplicate of
        itself. It is logged instead. A counter left below the stored id costs a later insert one retry - it
        draws the taken id, collides on the public_id index and draws again

        Args:
            collection (str): Name of the collection the document was stored in
            db_name (str): Name of the database owning the collection
            public_id (int): The id the caller supplied
        """
        try:
            self.update_public_id_counter(collection, db_name, value=public_id)
        except DocumentUpdateError as err:
            LOGGER.error(
                "[insert] Stored ID %s in '%s', but its public_id counter could not be raised to it: %s",
                public_id, collection, err,
            )


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


    @retry_operation
    def reset_public_id_counter(self, collection: str, db_name: str, counter_id: str) -> int:
        """
        Sets a public_id counter to the highest public_id still stored in a collection - downwards too

        `update_public_id_counter` only ever raises a counter. After documents were deleted for good (a
        configuration reset) the counter has to come back down, so the next insert continues right after what is
        kept: 0 for an emptied collection. Creates the counter when it does not exist yet

        Args:
            collection (str): The collection whose highest public_id the counter is set to
            db_name (str): Name of the database owning the collection
            counter_id (str): The `_id` of the counter document

        Raises:
            DocumentUpdateError: If the highest public_id could not be read or the counter not written

        Returns:
            int: The value the counter was set to
        """
        try:
            highest_id: int = self.get_highest_id(collection, db_name)

            self.get_collection(PUBLIC_ID_COUNTER_COLLECTION, db_name).update_one(
                {'_id': counter_id}, {'$set': {'counter': highest_id}}, upsert=True
            )

            return highest_id
        except Exception as err:
            raise DocumentUpdateError(f"Failed to reset the public_id counter '{counter_id}': {err}") from err


    @retry_operation
    def set_public_id_counter(self, counter_id: str, db_name: str, value: int) -> None:
        """
        Sets a public_id counter to exactly the given value - downwards too - creating it when missing

        For restoring a counter as another system recorded it (a configuration import), where
        `update_public_id_counter` would only ever raise it

        Args:
            counter_id (str): The `_id` of the counter document
            db_name (str): Name of the database owning the counter
            value (int): The counter's new value

        Raises:
            DocumentUpdateError: If the counter could not be written
        """
        try:
            self.get_collection(PUBLIC_ID_COUNTER_COLLECTION, db_name).update_one(
                {'_id': counter_id}, {'$set': {'counter': value}}, upsert=True
            )
        except Exception as err:
            raise DocumentUpdateError(f"Failed to set the public_id counter '{counter_id}': {err}") from err


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


    @retry_operation
    def get_highest_id(self, collection: str, db_name: str) -> int:
        """
        Returns the highest public_id stored in a collection

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
