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
Database update 20261115: stamp every CmdbObjectRelationLog with the CmdbTypes of the two objects it records

A relation log is as readable as the relation it records, judged by ``relation_parent_type_id`` /
``relation_child_type_id`` on the log. A new log is stamped by its writer; this update gives the stored ones the same
two keys. Each side is resolved from the object id the log names for it, from two sources in turn:

1. **the live object** - its ``type_id``
2. **the object's own history** - for an object that is gone, the ``type_id`` stamped on its CmdbObjectLogs

A side neither source answers stores null, which the read rule does not refuse - the entry stays readable. The
object, not the relation, is the source: a relation can be re-pointed to other objects after a log was written, so
its current types need not be the ones the log recorded.

Only a log missing either key is selected, and every log the update visits leaves with both (a value or null), so a
second run selects nothing. A run stopped part-way leaves the visited logs stamped and the rest selectable
"""
from logging import Logger, getLogger
from typing import Any

from pymongo import UpdateOne

from cmdb.database.updater.base_database_update import BaseDatabaseUpdate

from cmdb.errors.updater import UpdaterException
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# The literals of this migration are frozen: it must keep meaning what it meant when it shipped
RELATION_LOGS_COLLECTION: str = 'framework.objectRelationLogs'
OBJECTS_COLLECTION: str = 'framework.objects'
OBJECT_LOGS_COLLECTION: str = 'framework.logs'

PARENT_ID_FIELD: str = 'object_relation_parent_id'
CHILD_ID_FIELD: str = 'object_relation_child_id'
PARENT_TYPE_FIELD: str = 'relation_parent_type_id'
CHILD_TYPE_FIELD: str = 'relation_child_type_id'

PUBLIC_ID_FIELD: str = 'public_id'
TYPE_ID_FIELD: str = 'type_id'
OBJECT_ID_FIELD: str = 'object_id'
LOG_TYPE_FIELD: str = 'log_type'
OBJECT_LOG_TYPE: str = 'CmdbObjectLog'
MONGO_ID_FIELD: str = '_id'

# The logs this update visits: relation logs missing either type key
UNSTAMPED_LOG_CRITERIA: dict[str, Any] = {'$or': [
    {PARENT_TYPE_FIELD: {'$exists': False}},
    {CHILD_TYPE_FIELD: {'$exists': False}},
]}

# How many logs are resolved and stamped per round
BATCH_SIZE: int = 500


def is_object_id(value: Any) -> bool:
    """
    Tells whether a stored endpoint value can name an object

    Args:
        value (Any): The stored ``object_relation_parent_id`` / ``object_relation_child_id``

    Returns:
        bool: True for a whole number that is not a bool
    """
    return isinstance(value, int) and not isinstance(value, bool)


def collect_object_ids(logs: list[dict[str, Any]]) -> set[int]:
    """
    Collects the object ids a batch of logs names, on either side

    Args:
        logs (list[dict[str, Any]]): The logs, carrying both endpoint ids

    Returns:
        set[int]: Every usable object id
    """
    return {
        log.get(field) for log in logs for field in (PARENT_ID_FIELD, CHILD_ID_FIELD) if is_object_id(log.get(field))
    }


def build_logged_type_pipeline(object_ids: list[int]) -> list[dict[str, Any]]:
    """
    Builds the aggregation answering, per gone object, the type its own CmdbObjectLogs carry

    Args:
        object_ids (list[int]): public_ids of the objects no longer stored

    Returns:
        list[dict[str, Any]]: The pipeline; each result is ``{_id: object_id, type_id: type}``
    """
    return [
        {'$match': {
            LOG_TYPE_FIELD: OBJECT_LOG_TYPE,
            OBJECT_ID_FIELD: {'$in': object_ids},
            TYPE_ID_FIELD: {'$type': 'number'},
        }},
        {'$group': {MONGO_ID_FIELD: f'${OBJECT_ID_FIELD}', TYPE_ID_FIELD: {'$first': f'${TYPE_ID_FIELD}'}}},
    ]


def build_stamp_operation(log: dict[str, Any], type_by_object: dict[int, int]) -> UpdateOne:
    """
    Builds the write stamping one log with the types of its two objects (null for a side not resolved)

    The filter repeats the unstamped criteria, so a log stamped meanwhile is not overwritten

    Args:
        log (dict[str, Any]): The log, carrying its ``_id`` and both endpoint ids
        type_by_object (dict[int, int]): The resolved type per object id

    Returns:
        UpdateOne: The write
    """
    return UpdateOne(
        {MONGO_ID_FIELD: log[MONGO_ID_FIELD], **UNSTAMPED_LOG_CRITERIA},
        {'$set': {
            PARENT_TYPE_FIELD: type_by_object.get(log.get(PARENT_ID_FIELD)),
            CHILD_TYPE_FIELD: type_by_object.get(log.get(CHILD_ID_FIELD)),
        }},
    )

# ---------------------------------------------- Update20261115 - CLASS ---------------------------------------------- #

class Update20261115(BaseDatabaseUpdate):
    """
    Stamps every stored CmdbObjectRelationLog with the types of the two objects it records - from the live objects,
    else from the objects' own logs, else null

    Extends: BaseDatabaseUpdate
    """
    def creation_date(self) -> int:
        return 20261115


    def description(self) -> str:
        return "Stamps every CmdbObjectRelationLog with the CmdbTypes of its two objects"


    def start_update(self) -> None:
        """
        Stamps the unstamped logs in batches, then bumps the version

        Raises:
            UpdaterException: If a read or a write failed
        """
        try:
            remaining = self.dbm.find(
                collection=RELATION_LOGS_COLLECTION,
                db_name=self.db_name,
                filter=UNSTAMPED_LOG_CRITERIA,
                projection={MONGO_ID_FIELD: 1, PARENT_ID_FIELD: 1, CHILD_ID_FIELD: 1},
            )

            batch: list[dict[str, Any]] = []
            visited: int = 0

            for log in remaining:
                batch.append(log)

                if len(batch) >= BATCH_SIZE:
                    visited += self._stamp_batch(batch)
                    batch = []

            if batch:
                visited += self._stamp_batch(batch)

            LOGGER.info("[updater_20261115] Stamped %s ObjectRelationLog(s) with their objects' types", visited)

            self.increase_updater_version(self.creation_date())
        except Exception as err:
            raise UpdaterException(err) from err


    def _stamp_batch(self, logs: list[dict[str, Any]]) -> int:
        """
        Resolves the types of a batch's objects and stamps every log of it

        Args:
            logs (list[dict[str, Any]]): The logs, carrying their ``_id`` and both endpoint ids

        Returns:
            int: How many logs were stamped
        """
        type_by_object: dict[int, int] = self._resolve_types(collect_object_ids(logs))

        self.dbm.bulk_write(
            RELATION_LOGS_COLLECTION, self.db_name, [build_stamp_operation(log, type_by_object) for log in logs],
        )

        return len(logs)


    def _resolve_types(self, object_ids: set[int]) -> dict[int, int]:
        """
        Resolves each object's type: the live object first, the object's own logs for the rest

        Args:
            object_ids (set[int]): The object ids to resolve

        Returns:
            dict[int, int]: The type per resolved object id; an unresolved id is absent
        """
        if not object_ids:
            return {}

        type_by_object: dict[int, int] = {
            document[PUBLIC_ID_FIELD]: document[TYPE_ID_FIELD]
            for document in self.dbm.find_all(
                OBJECTS_COLLECTION,
                self.db_name,
                filter={PUBLIC_ID_FIELD: {'$in': sorted(object_ids)}},
                projection={MONGO_ID_FIELD: 0, PUBLIC_ID_FIELD: 1, TYPE_ID_FIELD: 1},
            )
            if TYPE_ID_FIELD in document
        }

        gone: list[int] = sorted(object_ids - type_by_object.keys())

        if gone:
            for result in self.dbm.aggregate_all(
                    OBJECT_LOGS_COLLECTION, self.db_name, build_logged_type_pipeline(gone)):
                type_by_object[result[MONGO_ID_FIELD]] = result[TYPE_ID_FIELD]

        return type_by_object
