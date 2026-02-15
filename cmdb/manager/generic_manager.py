# DataGerry - OpenSource Enterprise CMDB
# Copyright (C) 2025 becon GmbH
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
This module contains the implementation of the GenericManager
"""
from logging import Logger, getLogger
from typing import Type, Any

from cmdb.database import MongoDatabaseManager

from cmdb.manager.base_manager import BaseManager
from cmdb.manager.query_builder import BuilderParameters

from cmdb.models.cmdb_dao import CmdbDAO

from cmdb.framework.results import IterationResult
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                GenericManager - CLASS                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class GenericManager(BaseManager):
    """
    A generic manager that provides common CRUD operations
    """

    def __init__(
        self,
        dbm: MongoDatabaseManager,
        model: Type[CmdbDAO],
        exceptions: dict[str, Type[Exception]],
        database: str | None = None
    ) -> None:
        """
        Initializes the GenericManager

        Args:
            dbm (MongoDatabaseManager): Database interaction manager
            model (Type[CmdbDAO]): The model class this manager handles
            exceptions (Dict[str, Type[Exception]]): A mapping of operations to their specific exceptions
            database (str | None): The database name (optional, for cloud mode)
        """
        try:
            self.model = model
            self.exceptions: dict[str, type[Exception]] = exceptions
            super().__init__(model.COLLECTION, dbm, database)
        except Exception as err:
            raise exceptions.get("init", Exception)(f"Initialization error: {err}") from err

# --------------------------------------------------- CRUD - CREATE -------------------------------------------------- #

    def insert_item(self, document: dict[str, Any] | CmdbDAO) -> int:
        """
        Inserts an document into the database

        Args:
            document (dict | CmdbDAO): The data to be inserted.

        Returns:
            int: The public_id of the created document

        Raises:
            Custom insert exception based on the specific manager
        """
        try:
            if isinstance(document, self.model):
                document = self.model.to_json(document)

            return self.insert(document)
        except Exception as err:
            LOGGER.error("[insert_document] Exception: %s. Type: %s", err, type(err))
            raise self.exceptions.get("insert", Exception)(f"Insertion error: {err}") from err

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

    def get_item(self, public_id: int, as_dict: bool = False) -> dict[str, Any] | CmdbDAO | None:
        """
        Retrieves an item from the database by its public_id

        Args:
            public_id (int): The public_id of the item

        Raises:
            Custom get exception based on the specific manager

        Returns:
            dict | CmdbDAO | None: An instance of the model if found, else None
        """
        try:
            data = self.get_one(public_id)

            if not data:
                return None

            return data if as_dict else self.model.from_data(data)
        except Exception as err:
            raise self.exceptions.get("get", Exception)(f"Retrieval error: {err}") from err


    def iterate_items(self, builder_params: BuilderParameters) -> IterationResult[CmdbDAO]:
        """
        Retrieves multiple items from the database using filters

        Args:
            builder_params (BuilderParameters): Query parameters

        Raises:
            Custom iteration exception based on the specific manager

        Returns:
            IterationResult[CmdbDAO]: A list of matching items
        """
        try:
            aggregation_result, total = self.iterate_query(builder_params)
            return IterationResult(aggregation_result, total, self.model)
        except Exception as err:
            LOGGER.error("[iterate_items] Exception: %s. Type: %s", err, type(err))
            raise self.exceptions.get("iterate", Exception)(f"Iteration error: {err}") from err


    def count_items(self, criteria: dict | None = None) -> int:
        """
        Counts the total number of items in the collection

        Returns:
            int: The total count

        Raises:
            Custom get exception based on the specific manager
        """
        try:
            if criteria:
                return self.count_documents(self.collection, criteria=criteria)

            return self.count_documents(self.collection)
        except Exception as err:
            raise self.exceptions.get("get", Exception)(f"Counting error: {err}") from err

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

    def update_item(self, public_id: int, data: CmdbDAO | dict[str, Any]) -> None:
        """
        Updates an item in the database

        Args:
            public_id (int): The public_id of the item to update
            data (CmdbDAO | dict): The updated data

        Raises:
            Custom update exception based on the specific manager
        """
        try:
            if isinstance(data, self.model):
                data = self.model.to_json(data)

            self.update({'public_id': public_id}, data)
        except Exception as err:
            LOGGER.error("[update_document] Exception: %s. Type: %s", err, type(err))
            raise self.exceptions.get("update", Exception)(f"Update error: {err}") from err

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

    def delete_item(self, public_id: int) -> bool:
        """
        Deletes an item from the database

        Args:
            public_id (int): The public_id of the item to delete

        Raises:
            Custom delete exception based on the specific manager

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            return self.delete({'public_id': public_id})
        except Exception as err:
            raise self.exceptions.get("delete", Exception)(f"Deletion error: {err}") from err
