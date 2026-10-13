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
Database update 20261016: one CmdbRelation links one ordered pair of objects once

Since this version a CmdbObjectRelation's (relation_id, relation_parent_id, relation_child_id) is unique, and a
unique index named ``relation_pair`` is the guarantee. MongoDB refuses to build a unique index over a collection that
holds a duplicate, and the startup index reconciliation only logs that refusal, so this update first removes every
duplicate and then builds the index itself.

**Which instance stays.** The lowest public_id of each pair - the oldest. Every other instance of the pair is removed.
The reverse pair (the child as parent) is another pair and is left alone; values are compared exactly, as the index
compares them.

**What a removed instance leaves behind.** Before an instance is deleted, a DELETE entry is written into its history
(``framework.objectRelationLogs``) carrying its field values as ``changes`` - a route's DELETE entry carries none, but
this one is the only record of values nobody chose to delete. The whole document is logged as a warning as well.

Re-run safe: the duplicates are recomputed from what is stored; a history entry is written only when this update has
not written one for that instance yet (so a run interrupted between the entry and the delete does not record it
twice); each delete is by public_id; an index of that name that is already unique is left alone - one that is not is
dropped and rebuilt
"""
from datetime import datetime, timezone
from logging import Logger, getLogger
from typing import Any

from pymongo import ASCENDING, IndexModel

from cmdb.database.updater.base_database_update import BaseDatabaseUpdate

from cmdb.errors.updater import UpdaterException
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# The literals of this migration are frozen: it must keep meaning what it meant when it shipped
OBJECT_RELATION_COLLECTION: str = 'framework.objectRelations'
OBJECT_RELATION_LOG_COLLECTION: str = 'framework.objectRelationLogs'
PUBLIC_ID_FIELD: str = 'public_id'
RELATION_ID_FIELD: str = 'relation_id'
PARENT_ID_FIELD: str = 'relation_parent_id'
CHILD_ID_FIELD: str = 'relation_child_id'
FIELD_VALUES_FIELD: str = 'field_values'
FIELD_VALUE_NAME: str = 'name'
FIELD_VALUE_VALUE: str = 'value'
MONGO_ID_FIELD: str = '_id'
PAIR_FIELDS: tuple[str, ...] = (RELATION_ID_FIELD, PARENT_ID_FIELD, CHILD_ID_FIELD)
PAIR_INDEX: str = 'relation_pair'
INDEX_UNIQUE_KEY: str = 'unique'
GROUP_IDS: str = 'ids'
GROUP_COUNT: str = 'count'

LOG_ACTION: str = 'action'
LOG_ACTION_DELETE: str = 'DELETE'
LOG_CREATION_TIME: str = 'creation_time'
LOG_AUTHOR_ID: str = 'author_id'
LOG_AUTHOR_NAME: str = 'author_name'
LOG_OBJECT_RELATION_ID: str = 'object_relation_id'
LOG_PARENT_ID: str = 'object_relation_parent_id'
LOG_CHILD_ID: str = 'object_relation_child_id'
LOG_CHANGES: str = 'changes'
UPDATE_AUTHOR_NAME: str = 'DataGerry database update 20261016 (duplicate relation removed)'

# Every (relation, parent, child) held by more than one instance, with the public_ids holding it
DUPLICATE_PAIRS_PIPELINE: list[dict[str, Any]] = [
    {'$group': {
        MONGO_ID_FIELD: {field: f'${field}' for field in PAIR_FIELDS},
        GROUP_IDS: {'$push': f'${PUBLIC_ID_FIELD}'},
        GROUP_COUNT: {'$sum': 1},
    }},
    {'$match': {GROUP_COUNT: {'$gt': 1}}},
]


def extra_instance_ids(groups: list[dict[str, Any]]) -> list[int]:
    """
    The public_ids to remove - every instance of a duplicated pair but the lowest one

    Args:
        groups (list[dict[str, Any]]): The duplicated pairs as ``DUPLICATE_PAIRS_PIPELINE`` answers them

    Returns:
        list[int]: The public_ids, ascending; an id that is no int is never chosen
    """
    extras: list[int] = []

    for group in groups:
        ids: list[int] = sorted(public_id for public_id in group.get(GROUP_IDS) or []
                                if isinstance(public_id, int) and not isinstance(public_id, bool))
        extras.extend(ids[1:])

    return sorted(extras)


def removal_log_entry(instance: dict[str, Any], now: datetime) -> dict[str, Any]:
    """
    The history entry a removed duplicate leaves behind

    Args:
        instance (dict[str, Any]): The stored CmdbObjectRelation about to be removed
        now (datetime): When it is removed

    Returns:
        dict[str, Any]: A DELETE entry whose ``changes`` keep the instance's field values (name -> value)
    """
    field_values: Any = instance.get(FIELD_VALUES_FIELD)

    return {
        LOG_ACTION: LOG_ACTION_DELETE,
        LOG_CREATION_TIME: now,
        LOG_AUTHOR_ID: None,
        LOG_AUTHOR_NAME: UPDATE_AUTHOR_NAME,
        LOG_PARENT_ID: instance.get(PARENT_ID_FIELD),
        LOG_CHILD_ID: instance.get(CHILD_ID_FIELD),
        LOG_OBJECT_RELATION_ID: instance.get(PUBLIC_ID_FIELD),
        LOG_CHANGES: {
            entry[FIELD_VALUE_NAME]: entry.get(FIELD_VALUE_VALUE)
            for entry in (field_values if isinstance(field_values, list) else [])
            if isinstance(entry, dict) and isinstance(entry.get(FIELD_VALUE_NAME), str)
        },
    }

# -------------------------------------------------------------------------------------------------------------------- #
#                                                Update20261016 - CLASS                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class Update20261016(BaseDatabaseUpdate):
    """
    Removes duplicate CmdbObjectRelation pairs and makes the pair unique

    Extends: BaseDatabaseUpdate
    """
    def creation_date(self) -> int:
        return 20261016


    def description(self) -> str:
        return "Removes duplicate object relations of one pair and makes the pair unique"


    def start_update(self) -> None:
        """
        Removes the duplicates first, then builds the index, then bumps the version

        The order is not optional: the unique index cannot be built while a duplicate is stored

        Raises:
            UpdaterException: If a read, a history entry, a delete or the index build failed
        """
        try:
            removed: list[int] = self.remove_duplicates()

            if removed:
                LOGGER.warning("[Update20261016] Removed %d duplicate object relation(s): %s", len(removed), removed)

            if self.build_unique_pair_index():
                LOGGER.info("[Update20261016] Built the unique '%s' index on %s",
                            PAIR_INDEX, OBJECT_RELATION_COLLECTION)

            self.increase_updater_version(self.creation_date())
        except Exception as err:
            raise UpdaterException(err) from err


    def remove_duplicates(self) -> list[int]:
        """
        Removes every instance whose pair an instance with a lower public_id holds, recording each in its history

        Returns:
            list[int]: The public_ids removed, ascending
        """
        groups: list[dict[str, Any]] = list(self.dbm.aggregate(
            OBJECT_RELATION_COLLECTION, self.db_name, DUPLICATE_PAIRS_PIPELINE,
        ))
        extras: list[int] = extra_instance_ids(groups)

        if not extras:
            return []

        instances: list[dict[str, Any]] = list(self.dbm.find(
            OBJECT_RELATION_COLLECTION, self.db_name, filter={PUBLIC_ID_FIELD: {'$in': extras}},
            projection={MONGO_ID_FIELD: 0}, sort=[(PUBLIC_ID_FIELD, ASCENDING)],
        ))
        now: datetime = datetime.now(timezone.utc)

        for instance in instances:
            public_id: int = instance[PUBLIC_ID_FIELD]
            self.record_removal(instance, now)
            LOGGER.warning("[Update20261016] Object relation %s duplicates the pair of an older one - removed: %r",
                           public_id, instance)
            self.dbm.delete(OBJECT_RELATION_COLLECTION, self.db_name, {PUBLIC_ID_FIELD: public_id})

        return [instance[PUBLIC_ID_FIELD] for instance in instances]


    def record_removal(self, instance: dict[str, Any], now: datetime) -> bool:
        """
        Writes the removal into the instance's history, unless this update already did

        Args:
            instance (dict[str, Any]): The stored CmdbObjectRelation about to be removed
            now (datetime): When it is removed

        Returns:
            bool: True when an entry was written, False when one from an earlier run exists
        """
        written_before: dict[str, Any] | None = self.dbm.get_collection(
            OBJECT_RELATION_LOG_COLLECTION, self.db_name,
        ).find_one({LOG_OBJECT_RELATION_ID: instance.get(PUBLIC_ID_FIELD), LOG_AUTHOR_NAME: UPDATE_AUTHOR_NAME})

        if written_before:
            return False

        self.dbm.insert(OBJECT_RELATION_LOG_COLLECTION, self.db_name, removal_log_entry(instance, now))

        return True


    def build_unique_pair_index(self) -> bool:
        """
        Builds the unique index on the pair, unless it is already in place

        An index of that name that is not unique is dropped first: MongoDB refuses to recreate an index under the same
        name with other options

        Returns:
            bool: True when the index was built, False when it was already unique
        """
        index_info: dict[str, Any] = dict(self.dbm.get_index_info(OBJECT_RELATION_COLLECTION, self.db_name))
        existing: dict[str, Any] | None = index_info.get(PAIR_INDEX)

        if existing is not None and existing.get(INDEX_UNIQUE_KEY, False):
            return False

        if existing is not None:
            self.dbm.drop_index(OBJECT_RELATION_COLLECTION, self.db_name, PAIR_INDEX)

        self.dbm.create_indexes(OBJECT_RELATION_COLLECTION, self.db_name, [
            IndexModel([(field, ASCENDING) for field in PAIR_FIELDS], name=PAIR_INDEX, unique=True),
        ])

        return True
