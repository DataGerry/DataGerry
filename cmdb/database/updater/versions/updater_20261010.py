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
Database update 20261010: drop the type ids that name no CmdbType from every stored CmdbCategory

A category write drops an id no CmdbType carries instead of refusing the write. A category stored before - one
that still names a deleted type, or holds an entry that is no type id at all - is cleaned once here, so the
category tree and the next save see only real types. Types are read as ids only; one ``$pull`` per database
removes every other entry from every category that holds one.

Idempotent by construction: only a category holding an entry outside the stored type ids is selected, and the
write leaves none behind
"""
from typing import Any

from cmdb.database.updater.base_database_update import BaseDatabaseUpdate

from cmdb.errors.updater import UpdaterException
# -------------------------------------------------------------------------------------------------------------------- #

# The literals of this migration are frozen: it must keep meaning what it meant when it shipped
CATEGORY_COLLECTION: str = 'framework.categories'
TYPE_COLLECTION: str = 'framework.types'
TYPES_FIELD: str = 'types'
PUBLIC_ID_FIELD: str = 'public_id'


def build_category_cleanup(type_ids: list[int]) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    Builds the filter and the update that remove every entry outside the given type ids

    Args:
        type_ids (list[int]): public_ids of every stored CmdbType

    Returns:
        tuple[dict[str, Any], dict[str, Any]]: The filter selecting a category holding such an entry, and
            the ``$pull`` removing them
    """
    outside: dict[str, Any] = {'$nin': type_ids}

    return {TYPES_FIELD: {'$elemMatch': outside}}, {'$pull': {TYPES_FIELD: outside}}


class Update20261010(BaseDatabaseUpdate):
    """
    Removes every entry that names no stored CmdbType from the ``types`` of every CmdbCategory

    Extends: BaseDatabaseUpdate
    """
    def creation_date(self) -> int:
        return 20261010


    def description(self) -> str:
        return "Removes the type ids that name no type from every category"


    def start_update(self) -> None:
        """
        Reads the ids of every stored CmdbType, pulls every other entry from the categories, then bumps the version

        Raises:
            UpdaterException: If the read or the write failed
        """
        try:
            type_ids: list[int] = [
                document[PUBLIC_ID_FIELD]
                for document in self.dbm.find(
                    collection=TYPE_COLLECTION,
                    db_name=self.db_name,
                    filter={},
                    projection={PUBLIC_ID_FIELD: 1, '_id': 0},
                )
            ]

            filter_query, update = build_category_cleanup(type_ids)

            self.dbm.update_many_raw(
                collection=CATEGORY_COLLECTION,
                db_name=self.db_name,
                filter_query=filter_query,
                update=update,
            )

            self.increase_updater_version(self.creation_date())
        except Exception as err:
            raise UpdaterException(err) from err
