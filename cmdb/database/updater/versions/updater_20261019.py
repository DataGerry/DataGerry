# DATAGERRY - OpenSource Enterprise CMDB
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
Database update 20261019: a CmdbCategory no longer lists a CmdbType that was deleted

Deleting a CmdbType takes its id out of the `types` array of every CmdbCategory. Until this version that cleanup sent
an update that removed nothing, so every type deleted until now left its id behind in the category that held it - an
id that resolves to nothing. This update takes those ids out the way the type delete now does.

Only an integer entry is judged; anything else in a `types` array is left as it is. Ids are read in batches, so a
large installation sends bounded queries.

Re-run safe: the listed ids and the types that still exist are read again on every run, and a second run finds no id
left to take out
"""
from logging import Logger, getLogger
from typing import Any

from cmdb.database.updater.base_database_update import BaseDatabaseUpdate

from cmdb.errors.updater import UpdaterException
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# The literals of this migration are frozen: it must keep meaning what it meant when it shipped
CATEGORIES_COLLECTION: str = 'framework.categories'
TYPES_COLLECTION: str = 'framework.types'
PUBLIC_ID_FIELD: str = 'public_id'
TYPES_FIELD: str = 'types'
MONGO_ID_FIELD: str = '_id'

# How many ids one existence read and one cleanup update name at most
ID_BATCH_SIZE: int = 1000

# -------------------------------------------------------------------------------------------------------------------- #

def listed_type_ids(categories: list[dict[str, Any]]) -> list[int]:
    """
    Answers every integer CmdbType id the given category documents list, once and ascending

    A bool is an int in Python but never a type id, so it is not counted

    Args:
        categories (list[dict[str, Any]]): Category documents carrying their `types`

    Returns:
        list[int]: The listed ids, ascending
    """
    listed: set[int] = set()

    for category in categories:
        types: Any = category.get(TYPES_FIELD)

        if isinstance(types, list):
            listed.update(value for value in types if isinstance(value, int) and not isinstance(value, bool))

    return sorted(listed)


def pull_update(type_ids: list[int]) -> dict[str, Any]:
    """
    Builds the update taking the given ids out of a category's `types`

    Args:
        type_ids (list[int]): The ids to take out

    Returns:
        dict[str, Any]: The update document
    """
    return {'$pull': {TYPES_FIELD: {'$in': type_ids}}}


def batches(ids: list[int], size: int) -> list[list[int]]:
    """
    Splits ids into consecutive batches of at most `size`

    Args:
        ids (list[int]): The ids
        size (int): The largest batch

    Returns:
        list[list[int]]: The batches, in order
    """
    return [ids[start:start + size] for start in range(0, len(ids), size)]

# ---------------------------------------------- Update20261019 - CLASS ---------------------------------------------- #

class Update20261019(BaseDatabaseUpdate):
    """
    Takes the ids of deleted CmdbTypes out of the CmdbCategories that list them

    Extends: BaseDatabaseUpdate
    """
    def creation_date(self) -> int:
        return 20261019


    def description(self) -> str:
        return "Removes deleted CmdbTypes from the CmdbCategories that still list them"


    def start_update(self) -> None:
        """
        Finds the listed type ids whose type is gone and takes them out of every category, then bumps the version

        Raises:
            UpdaterException: If a read or an update fails
        """
        try:
            missing: list[int] = self.find_deleted_type_ids()
            changed: int = self.remove(missing)

            if changed:
                LOGGER.info(
                    "[updater_20261019] Removed %s deleted Type(s) from %s Categories", len(missing), changed,
                )

            self.increase_updater_version(self.creation_date())
        except Exception as err:
            raise UpdaterException(err) from err


    def find_deleted_type_ids(self) -> list[int]:
        """
        Answers the ids a category lists although no CmdbType carries them any more

        Returns:
            list[int]: The ids, ascending
        """
        listed: list[int] = listed_type_ids(list(self.dbm.find(
            CATEGORIES_COLLECTION,
            self.db_name,
            {TYPES_FIELD: {'$exists': True, '$ne': []}},
            projection={TYPES_FIELD: 1, MONGO_ID_FIELD: 0},
        )))
        existing: set[int] = set()

        for batch in batches(listed, ID_BATCH_SIZE):
            existing.update(
                document[PUBLIC_ID_FIELD] for document in self.dbm.find(
                    TYPES_COLLECTION,
                    self.db_name,
                    {PUBLIC_ID_FIELD: {'$in': batch}},
                    projection={PUBLIC_ID_FIELD: 1, MONGO_ID_FIELD: 0},
                )
            )

        return [type_id for type_id in listed if type_id not in existing]


    def remove(self, type_ids: list[int]) -> int:
        """
        Takes the ids out of every category listing them, a batch per update

        Args:
            type_ids (list[int]): The ids of the deleted CmdbTypes

        Returns:
            int: How many categories were changed
        """
        changed: int = 0

        for batch in batches(type_ids, ID_BATCH_SIZE):
            changed += self.dbm.update_many_raw(
                CATEGORIES_COLLECTION,
                self.db_name,
                {TYPES_FIELD: {'$in': batch}},
                pull_update(batch),
            ).modified_count

        return changed
