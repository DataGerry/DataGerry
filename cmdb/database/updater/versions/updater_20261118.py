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
Database update 20261118: gives every CmdbObject the ``special_type`` marker of its CmdbType

An object's marker is its type's, and never changes after the create. The object create stored whatever the request
body carried instead: an API client leaving the key out stored null on a Supernet, Subnet or Rack object - whose
object page then shows no IPAM or rack overview - and one sending a marker stored it on an object of any type.

Per type, one update: the objects of a type carrying a marker get it where they hold another value; the objects of
the types carrying none get null where they hold a value. An object whose type no longer exists is left as it is.

Re-run safe: each statement selects only the objects whose marker differs from their type's, so a completed run finds
nothing, and an interrupted one resumes with the types it had not reached. The version is bumped only after every
type is done
"""
from logging import Logger, getLogger
from typing import Any

from cmdb.database.mongo_database_manager import MongoDatabaseManager
from cmdb.database.updater.base_database_update import BaseDatabaseUpdate

from cmdb.errors.updater import UpdaterException
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# The literals of this migration are frozen: it must keep meaning what it meant when it shipped
TYPES_COLLECTION: str = 'framework.types'
OBJECTS_COLLECTION: str = 'framework.objects'
PUBLIC_ID: str = 'public_id'
TYPE_ID: str = 'type_id'
SPECIAL_TYPE: str = 'special_type'
NO_SPECIAL_TYPE: None = None


def read_type_markers(dbm: MongoDatabaseManager, db_name: str) -> tuple[dict[str, list[int]], list[int]]:
    """
    Reads every type's marker

    Args:
        dbm (MongoDatabaseManager): Database manager used for the read
        db_name (str): Name of the database owning the collection

    Returns:
        tuple[dict[str, list[int]], list[int]]: The type ids by the marker they carry, and the ids of the types
            carrying none (an empty marker counts as none)
    """
    marked: dict[str, list[int]] = {}
    unmarked: list[int] = []

    for type_document in dbm.find_all(TYPES_COLLECTION, db_name, {},
                                      projection={'_id': 0, PUBLIC_ID: 1, SPECIAL_TYPE: 1}):
        marker: Any = type_document.get(SPECIAL_TYPE)

        if marker:
            marked.setdefault(marker, []).append(type_document[PUBLIC_ID])
        else:
            unmarked.append(type_document[PUBLIC_ID])

    return marked, unmarked


def build_marker_criteria(type_ids: list[int], marker: str | None) -> dict[str, Any]:
    """
    Builds the filter selecting the objects of the given types whose marker is not the given one

    Args:
        type_ids (list[int]): The types, all carrying ``marker``
        marker (str | None): Their marker, None for the types carrying none

    Returns:
        dict[str, Any]: The MongoDB filter
    """
    return {TYPE_ID: {'$in': type_ids}, SPECIAL_TYPE: {'$ne': marker}}

# ---------------------------------------------- Update20261118 - CLASS ---------------------------------------------- #

class Update20261118(BaseDatabaseUpdate):
    """
    Gives every CmdbObject the ``special_type`` marker of its CmdbType

    Extends: BaseDatabaseUpdate
    """
    def creation_date(self) -> int:
        return 20261118


    def description(self) -> str:
        return "Gives every Object the special_type marker of its Type"


    def start_update(self) -> None:
        """
        Writes each type's marker onto its objects where they hold another value, then bumps the version

        Raises:
            UpdaterException: If the types cannot be read, an object update fails or the version cannot be written
        """
        try:
            marked, unmarked = read_type_markers(self.dbm, self.db_name)
            statements: list[tuple[list[int], str | None]] = [(type_ids, marker) for marker, type_ids in marked.items()]

            if unmarked:
                statements.append((unmarked, NO_SPECIAL_TYPE))

            for type_ids, marker in statements:
                result = self.dbm.update_many(OBJECTS_COLLECTION, self.db_name,
                                              build_marker_criteria(type_ids, marker), {SPECIAL_TYPE: marker})

                if result.modified_count:
                    LOGGER.info("[updater_20261118] Set special_type %s on %s object(s)", marker,
                                result.modified_count)

            self.increase_updater_version(self.creation_date())
        except Exception as err:
            raise UpdaterException(err) from err
