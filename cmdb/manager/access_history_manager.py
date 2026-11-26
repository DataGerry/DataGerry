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
This module contains the implementation of the AccessHistoryManager - the access change history

The history is written by the server only and never changed: this manager inserts entries and reads them; a write
ledger may remove the entries of a request it undoes, and the retention expires old ones through a TTL index
(``apply_retention``). Nothing else in ``cmdb/`` updates or deletes them (a tripwire holds it)
"""
from logging import Logger, getLogger
from typing import Any

from pymongo.errors import PyMongoError

from cmdb.database import MongoDatabaseManager
from cmdb.manager.generic_manager import GenericManager

from cmdb.models.access_model import HISTORY_TTL_INDEX_NAME, AccessHistoryKey, CmdbAccessHistory

from cmdb.errors.database import GetCollectionError
from cmdb.errors.manager import BaseManagerGetError, BaseManagerInsertError
from cmdb.errors.manager.access_history_manager import (
    ACCESS_HISTORY_MANAGER_ERRORS,
    AccessHistoryManagerInsertError,
    AccessHistoryManagerUpdateError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# Seconds in a day - the retention is set in days, the TTL index counts seconds
SECONDS_PER_DAY: int = 86400

# -------------------------------------------------------------------------------------------------------------------- #
#                                           AccessHistoryManager - CLASS                                              #
# -------------------------------------------------------------------------------------------------------------------- #
class AccessHistoryManager(GenericManager):
    """
    The AccessHistoryManager inserts and reads the entries of the access change history

    Extends: GenericManager
    """
    def __init__(self, dbm: MongoDatabaseManager, database: str | None = None) -> None:
        """
        Set the database connection for the AccessHistoryManager

        Args:
            dbm (MongoDatabaseManager): Database interaction manager
            database (str | None): Name of the database the dbm should connect to. Only used in cloud mode
        """
        super().__init__(dbm, CmdbAccessHistory, ACCESS_HISTORY_MANAGER_ERRORS, database)

# --------------------------------------------------- CRUD - CREATE -------------------------------------------------- #

    def insert_entries(self, entries: list[dict[str, Any]]) -> list[int]:
        """
        Writes entries with one id reservation and one insert

        Args:
            entries (list[dict[str, Any]]): The entries without their public_ids

        Raises:
            AccessHistoryManagerInsertError: When the ids could not be reserved or the entries not written

        Returns:
            list[int]: The new public_ids, in the order of ``entries``; empty for no entries
        """
        if not entries:
            return []

        try:
            public_ids: list[int] = self.reserve_public_ids(len(entries))
            documents: list[dict[str, Any]] = [
                CmdbAccessHistory.to_json(CmdbAccessHistory.from_data({**entry,
                                                                       AccessHistoryKey.PUBLIC_ID.value: public_id}))
                for public_id, entry in zip(public_ids, entries, strict=True)]

            return self.insert_many(documents, skip_public=True)
        except (BaseManagerGetError, BaseManagerInsertError, *self._model_errors) as err:
            LOGGER.error("[insert_entries] Exception: %s. Type: %s", err, type(err))
            raise AccessHistoryManagerInsertError(err) from err

# ------------------------------------------------------ RETENTION --------------------------------------------------- #

    def apply_retention(self, days: int) -> None:
        """
        Expires entries older than the given days through a TTL index on their time - none for 0 (kept forever)

        The index is created, its expiry changed in place (``collMod``) or dropped; re-run safe

        Args:
            days (int): The retention in days; 0 keeps every entry

        Raises:
            AccessHistoryManagerUpdateError: When the index could not be changed
        """
        try:
            collection: Any = self.dbm.get_collection(self.collection, self.db_name)
            existing: dict[str, Any] = collection.index_information()

            if days <= 0:
                if HISTORY_TTL_INDEX_NAME in existing:
                    collection.drop_index(HISTORY_TTL_INDEX_NAME)

                return

            seconds: int = days * SECONDS_PER_DAY

            if HISTORY_TTL_INDEX_NAME in existing:
                collection.database.command('collMod', self.collection, index={
                    'name': HISTORY_TTL_INDEX_NAME, 'expireAfterSeconds': seconds})
            else:
                collection.create_index([(AccessHistoryKey.TIME.value, 1)], name=HISTORY_TTL_INDEX_NAME,
                                        expireAfterSeconds=seconds)
        except (PyMongoError, GetCollectionError) as err:
            LOGGER.error("[apply_retention] Exception: %s. Type: %s", err, type(err))
            raise AccessHistoryManagerUpdateError(err) from err
