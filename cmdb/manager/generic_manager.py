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
from typing import Any, Iterable

from cmdb.utils import coerce_document_dates

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

    A model that declares DATE_FIELDS also opts into date normalisation on the write paths that take
    a raw dict: those keys are coerced into real BSON dates before the document is stored, so a
    caller cannot persist the '$date' wrapper the frontend sends (see _normalize_dates)

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

# -------------------------------------------------- HELPER METHODS -------------------------------------------------- #

    def _normalize_dates(self, document: dict[str, Any]) -> None:
        """
        Coerces the model's declared date fields of a raw document into real BSON dates, in place

        Only does something for a model that declares DATE_FIELDS. A date reaches a write path as the
        Mongo extended-JSON wrapper the frontend sends, as a timestamp string, or already as a
        datetime, and only a real date can be sorted, range-filtered or formatted by MongoDB - so the
        shape is settled here, once, rather than in each route that happens to build a document

        Args:
            document (dict[str, Any]): The document to normalise in place

        Raises:
            ValueError: If a present, non-empty date field cannot be read as a timestamp. Refusing is
                deliberate: a guessed date is stored as confidently as a correct one
        """
        # Read defensively: not every model this manager is built with extends CmdbDAO
        # (CmdbUserSetting does not), so the attribute is not guaranteed to exist
        date_fields: tuple[str, ...] = getattr(self.model, 'DATE_FIELDS', ())

        if not date_fields:
            return

        unusable_dates: list[str] = coerce_document_dates(document, date_fields)

        if unusable_dates:
            raise ValueError(f"Unreadable date value(s) for: {unusable_dates}")

# --------------------------------------------------- CRUD - CREATE -------------------------------------------------- #

    def _normalize_document(self, document: dict[str, Any]) -> None:
        """
        Runs the model's own document normalisation over a raw document, in place

        The hook a CmdbDAO model uses to fill the optional keys a payload omitted with their empty
        values, so a dict written directly is stored the same way one built through the model would
        be. Read with getattr: not every model of a GenericManager is a CmdbDAO - CmdbUserSetting is
        not - and a model that declares no hook simply has nothing to normalise

        Args:
            document (dict[str, Any]): The document to normalise in place
        """
        normalize = getattr(self.model, 'normalize_document', None)

        if normalize:
            normalize(document)


    def insert_item(self, document: dict[str, Any] | CmdbDAO) -> int:
        """
        Inserts a document into the manager's collection

        A model instance is serialised via the model's to_json() before insertion; a dict is passed
        through the model's own document normalisation first - its declared date fields (see
        _normalize_dates) and its normalize_document hook, which is what fills the optional keys a
        payload omitted with their empty values instead of storing null

        Args:
            document (dict[str, Any] | CmdbDAO): The document or model instance to insert

        Raises:
            Exception: The configured 'insert' exception if the insertion fails, including a date
                field that could not be read

        Returns:
            int: The public_id of the created document
        """
        try:
            if isinstance(document, self.model):
                document = self.model.to_json(document)
            else:
                self._normalize_dates(document)
                self._normalize_document(document)

            return self.insert(document)
        except Exception as err:
            LOGGER.error("[insert_item] Exception: %s. Type: %s", err, type(err))
            raise self.exceptions.get("insert", Exception)(f"Insertion error: {err}") from err


    def insert_many_items(self, documents: list[dict[str, Any]]) -> list[int]:
        """
        Inserts several raw documents into the manager's collection in one call

        The batch counterpart of insert_item for dicts: each document is normalised the same way
        before the batch is written - date fields and the normalize_document hook - so a bulk create
        cannot bypass what the single-document path enforces

        Args:
            documents (list[dict[str, Any]]): The documents to insert

        Raises:
            Exception: The configured 'insert' exception if the insertion fails, including a date
                field that could not be read

        Returns:
            list[int]: The public_ids of the created documents
        """
        try:
            for document in documents:
                self._normalize_dates(document)
                self._normalize_document(document)

            return self.insert_many(documents)
        except Exception as err:
            LOGGER.error("[insert_many_items] Exception: %s. Type: %s", err, type(err))
            raise self.exceptions.get("insert", Exception)(f"Insertion error: {err}") from err

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

    def find_existing_public_ids(self, public_ids: Iterable[int]) -> set[int]:
        """
        Reports which of the given public_ids exist in the manager's collection

        One projected '$in' query, so a caller validating a list of references does not read a document
        per id - and reads no payload at all, only the ids themselves

        Args:
            public_ids (Iterable[int]): The public_ids to look for; an empty selection queries nothing

        Raises:
            Exception: The configured 'get' exception if the lookup fails

        Returns:
            set[int]: The subset that exists. Subtract it from the input to get the unknown ids
        """
        wanted: list[int] = list(public_ids or [])

        if not wanted:
            return set()

        try:
            documents: list[dict[str, Any]] = self.find(
                criteria={CmdbDAO.PUBLIC_ID_KEY: {'$in': wanted}},
                projection={CmdbDAO.PUBLIC_ID_KEY: 1},
            )

            return {document[CmdbDAO.PUBLIC_ID_KEY] for document in documents}
        except Exception as err:
            LOGGER.error("[find_existing_public_ids] Exception: %s. Type: %s", err, type(err))
            raise self.exceptions.get("get", Exception)(f"Retrieval error: {err}") from err


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

        A model instance is serialised via the model's to_json() before the update; a dict is passed
        through the model's own document normalisation first (see insert_item)

        Args:
            public_id (int): The public_id of the item to update
            data (CmdbDAO | dict[str, Any]): The new document or model instance

        Raises:
            Exception: The configured 'update' exception if the update fails
        """
        try:
            if isinstance(data, self.model):
                data = self.model.to_json(data)
            else:
                self._normalize_dates(data)
                self._normalize_document(data)

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
