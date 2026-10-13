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
Database update 20261014: make a CmdbRelation's technical name unique

Since this version ``relation_name`` identifies a relation, the way a CmdbType's ``name`` does, and a unique index
on it is the guarantee. MongoDB refuses to build a unique index over a collection that holds a duplicate, and the
startup index reconciliation only logs that refusal, so this update first renames every duplicate and then builds
the index itself.

**Which relation keeps the name.** The lowest public_id - the oldest, and the one an object relation most likely
points at. Every other relation of the name becomes ``<name>-<public_id>``; when that is taken too, ``-<public_id>``
is appended again until it is free. Names are compared exactly, as the index compares them: ``Rack`` and ``rack``
are two names. A relation's other documents name it by public_id only, so a rename changes nothing else.

Re-run safe: the duplicates are recomputed from the stored names, each rename is conditioned on the name it read,
and an index of that name that is already unique is left alone - one that is not is dropped and rebuilt
"""
from logging import Logger, getLogger
from typing import Any

from pymongo import ASCENDING, IndexModel

from cmdb.database.updater.base_database_update import BaseDatabaseUpdate

from cmdb.errors.updater import UpdaterException
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# The literals of this migration are frozen: it must keep meaning what it meant when it shipped
RELATION_COLLECTION: str = 'framework.relations'
RELATION_NAME_FIELD: str = 'relation_name'
PUBLIC_ID_FIELD: str = 'public_id'
MONGO_ID_FIELD: str = '_id'
RELATION_NAME_INDEX: str = 'relation_name'
INDEX_UNIQUE_KEY: str = 'unique'
RENAME_SEPARATOR: str = '-'


def duplicate_renames(relations: list[dict[str, Any]]) -> list[tuple[int, str, str]]:
    """
    The renames that leave every relation name held once - all but the lowest public_id of each name

    Args:
        relations (list[dict[str, Any]]): The stored relations, each with its public_id and name

    Returns:
        list[tuple[int, str, str]]: (public_id, stored name, new name) per relation to rename, by public_id
    """
    ordered: list[dict[str, Any]] = sorted(
        (relation for relation in relations
         if isinstance(relation.get(RELATION_NAME_FIELD), str) and isinstance(relation.get(PUBLIC_ID_FIELD), int)),
        key=lambda relation: relation[PUBLIC_ID_FIELD],
    )
    taken: set[str] = {relation[RELATION_NAME_FIELD] for relation in ordered}
    kept: set[str] = set()
    renames: list[tuple[int, str, str]] = []

    for relation in ordered:
        name: str = relation[RELATION_NAME_FIELD]

        if name not in kept:
            kept.add(name)
            continue

        public_id: int = relation[PUBLIC_ID_FIELD]
        new_name: str = f'{name}{RENAME_SEPARATOR}{public_id}'

        while new_name in taken:
            new_name = f'{new_name}{RENAME_SEPARATOR}{public_id}'

        taken.add(new_name)
        renames.append((public_id, name, new_name))

    return renames

# -------------------------------------------------------------------------------------------------------------------- #
# ---------------------------------------------- Update20261014 - CLASS ---------------------------------------------- #
# -------------------------------------------------------------------------------------------------------------------- #
class Update20261014(BaseDatabaseUpdate):
    """
    Renames duplicate CmdbRelation names and makes the name unique

    Extends: BaseDatabaseUpdate
    """
    def creation_date(self) -> int:
        return 20261014


    def description(self) -> str:
        return "Renames duplicate relation names and makes a relation's name unique"


    def start_update(self) -> None:
        """
        Renames first, then builds the index, then bumps the version

        The order is not optional: the unique index cannot be built while a duplicate is stored

        Raises:
            UpdaterException: If a read, a rename or the index build failed
        """
        try:
            self.rename_duplicates()

            if self.build_unique_name_index():
                LOGGER.info("[Update20261014] Built the unique '%s' index on %s",
                            RELATION_NAME_INDEX, RELATION_COLLECTION)

            self.increase_updater_version(self.creation_date())
        except Exception as err:
            raise UpdaterException(err) from err


    def rename_duplicates(self) -> list[tuple[int, str, str]]:
        """
        Renames every relation whose name a relation with a lower public_id holds

        Each rename is conditioned on the name that was read, so a name changed since is left alone

        Returns:
            list[tuple[int, str, str]]: (public_id, stored name, new name) of every rename attempted
        """
        relations: list[dict[str, Any]] = list(self.dbm.find(
            RELATION_COLLECTION,
            self.db_name,
            filter={},
            projection={PUBLIC_ID_FIELD: 1, RELATION_NAME_FIELD: 1, MONGO_ID_FIELD: 0},
        ))
        renames: list[tuple[int, str, str]] = duplicate_renames(relations)

        for public_id, name, new_name in renames:
            self.dbm.update(
                RELATION_COLLECTION,
                self.db_name,
                {PUBLIC_ID_FIELD: public_id, RELATION_NAME_FIELD: name},
                {RELATION_NAME_FIELD: new_name},
            )
            LOGGER.warning("[Update20261014] Relation %s %s: the name %r is held by an older relation - renamed "
                           "to %r", PUBLIC_ID_FIELD, public_id, name, new_name)

        return renames


    def build_unique_name_index(self) -> bool:
        """
        Builds the unique index on the relation name, unless it is already in place

        An index of that name that is not unique (an older declaration) is dropped first: MongoDB refuses to
        recreate an index under the same name with other options

        Returns:
            bool: True when the index was built, False when it was already unique
        """
        index_info: dict[str, Any] = dict(self.dbm.get_index_info(RELATION_COLLECTION, self.db_name))
        existing: dict[str, Any] | None = index_info.get(RELATION_NAME_INDEX)

        if existing is not None and existing.get(INDEX_UNIQUE_KEY, False):
            return False

        if existing is not None:
            self.dbm.drop_index(RELATION_COLLECTION, self.db_name, RELATION_NAME_INDEX)

        self.dbm.create_indexes(RELATION_COLLECTION, self.db_name, [
            IndexModel([(RELATION_NAME_FIELD, ASCENDING)], name=RELATION_NAME_INDEX, unique=True),
        ])

        return True
