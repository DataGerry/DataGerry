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
The public_id counter half of the BaseManager

Every collection whose documents carry a public_id has a counter the database layer keeps. These methods peek at and
reserve ids of the manager's own collection, and reset or set a counter - which the configuration transfer does for
any collection. `BaseManager` inherits them, so every manager keeps calling them on itself
"""
from cmdb.database import MongoDatabaseManager

from cmdb.errors.database import DocumentGetError, DocumentUpdateError
from cmdb.errors.manager import BaseManagerGetError, BaseManagerUpdateError
# -------------------------------------------------------------------------------------------------------------------- #

# -------------------------------------------------------------------------------------------------------------------- #
#                                          PublicIdCounterAccessMixin - CLASS                                          #
# -------------------------------------------------------------------------------------------------------------------- #
class PublicIdCounterAccessMixin:
    """
    Peeks at, reserves, resets and sets public_id counters

    A mixin of BaseManager - it reaches the database through the manager's `dbm`, `db_name` and `collection`
    """
    dbm: MongoDatabaseManager
    db_name: str
    collection: str

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
            raise BaseManagerGetError(err) from err


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
            raise BaseManagerGetError(err) from err


    def reset_public_id_counter_of(self, collection: str, counter_id: str) -> int:
        """
        Sets another collection's public_id counter to the highest public_id still stored there - downwards too

        Args:
            collection (str): The collection whose highest public_id the counter is set to
            counter_id (str): The `_id` of the counter document

        Raises:
            BaseManagerUpdateError: If the counter could not be reset

        Returns:
            int: The value the counter was set to
        """
        try:
            return self.dbm.reset_public_id_counter(collection, self.db_name, counter_id)
        except DocumentUpdateError as err:
            raise BaseManagerUpdateError(err) from err


    def set_public_id_counter_of(self, counter_id: str, value: int) -> None:
        """
        Sets a public_id counter to exactly the given value - downwards too

        The counter is named by its own `_id`, not by a collection: unlike `reset_public_id_counter_of`, it reads no
        stored document, so it needs nothing but the counter. The counter of the manager's own collection is the one
        whose `_id` is the collection's name

        Args:
            counter_id (str): The `_id` of the counter document - for a collection's counter, the collection's name
            value (int): The counter's new value

        Raises:
            BaseManagerUpdateError: If the counter could not be written
        """
        try:
            self.dbm.set_public_id_counter(counter_id, self.db_name, value)
        except DocumentUpdateError as err:
            raise BaseManagerUpdateError(err) from err
