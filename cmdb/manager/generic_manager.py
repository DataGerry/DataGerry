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
This module contains the implementation of the GenericManager
"""
from logging import Logger, getLogger
from typing import Any

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
    Generic CRUD manager for a single CmdbDAO model

    Wraps BaseManager with a concrete model class and a per-operation exception map, exposing typed
    item-level CRUD (insert_item / get_item / iterate_items / update_item / delete_item). Domain
    managers subclass it and pass their model and exception mapping; a failure in any operation is
    wrapped in the matching exception from that map

    Extends: BaseManager
    """

    def __init__(
        self,
        dbm: MongoDatabaseManager,
        model: type[CmdbDAO],
        exceptions: dict[str, type[Exception]],
        database: str | None = None
    ) -> None:
        """
        Initialises the GenericManager

        Args:
            dbm (MongoDatabaseManager): Database interaction manager
            model (type[CmdbDAO]): The CmdbDAO subclass this manager stores and (de)serialises
            exceptions (dict[str, type[Exception]]): Maps an operation key ('init', 'insert', 'get',
                'iterate', 'update', 'delete') to the exception raised when that operation fails
            database (str | None): Target database name, used in cloud mode. Defaults to None

        Raises:
            Exception: The 'init' entry of `exceptions` (or a bare Exception) if initialisation fails
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
        Inserts a document into the manager's collection

        A model instance is serialised via the model's to_json() before insertion; a dict is
        inserted unchanged

        Args:
            document (dict[str, Any] | CmdbDAO): The document or model instance to insert

        Raises:
            Exception: The configured 'insert' exception if the insertion fails

        Returns:
            int: The public_id of the created document
        """
        try:
            if isinstance(document, self.model):
                document = self.model.to_json(document)

            return self.insert(document)
        except Exception as err:
            LOGGER.error("[insert_item] Exception: %s. Type: %s", err, type(err))
            raise self.exceptions.get("insert", Exception)(f"Insertion error: {err}") from err

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

    def get_item(self, public_id: int, as_dict: bool = False) -> dict[str, Any] | CmdbDAO | None:
        """
        Retrieves a single item by its public_id

        Args:
            public_id (int): The public_id of the item to retrieve
            as_dict (bool): If True return the raw document, otherwise a model instance. Defaults to False

        Raises:
            Exception: The configured 'get' exception if the retrieval fails

        Returns:
            dict[str, Any] | CmdbDAO | None: The document or model instance, or None if no match exists
        """
        try:
            data = self.get_one(public_id)

            if not data:
                return None

            return data if as_dict else self.model.from_data(data)
        except Exception as err:
            LOGGER.error("[get_item] Exception: %s. Type: %s", err, type(err))
            raise self.exceptions.get("get", Exception)(f"Retrieval error: {err}") from err


    def iterate_items(self, builder_params: BuilderParameters) -> IterationResult[CmdbDAO]:
        """
        Retrieves multiple items matching the given query parameters

        Args:
            builder_params (BuilderParameters): Filter, sort and pagination parameters

        Raises:
            Exception: The configured 'iterate' exception if the iteration fails

        Returns:
            IterationResult[CmdbDAO]: The matched model instances together with the total count
        """
        try:
            aggregation_result, total = self.iterate_query(builder_params)
            return IterationResult(aggregation_result, total, self.model)
        except Exception as err:
            LOGGER.error("[iterate_items] Exception: %s. Type: %s", err, type(err))
            raise self.exceptions.get("iterate", Exception)(f"Iteration error: {err}") from err

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

    def update_item(self, public_id: int, data: CmdbDAO | dict[str, Any]) -> None:
        """
        Updates the item with the given public_id

        A model instance is serialised via the model's to_json() before the update

        Args:
            public_id (int): The public_id of the item to update
            data (CmdbDAO | dict[str, Any]): The new document or model instance

        Raises:
            Exception: The configured 'update' exception if the update fails
        """
        try:
            if isinstance(data, self.model):
                data = self.model.to_json(data)

            self.update({'public_id': public_id}, data)
        except Exception as err:
            LOGGER.error("[update_item] Exception: %s. Type: %s", err, type(err))
            raise self.exceptions.get("update", Exception)(f"Update error: {err}") from err

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

    def delete_item(self, public_id: int) -> bool:
        """
        Deletes the item with the given public_id

        Args:
            public_id (int): The public_id of the item to delete

        Raises:
            Exception: The configured 'delete' exception if the deletion fails

        Returns:
            bool: True if a document was deleted, False otherwise
        """
        try:
            return self.delete({'public_id': public_id})
        except Exception as err:
            LOGGER.error("[delete_item] Exception: %s. Type: %s", err, type(err))
            raise self.exceptions.get("delete", Exception)(f"Deletion error: {err}") from err
