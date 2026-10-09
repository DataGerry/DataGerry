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
Database update 20261005: stamp every CmdbObjectLog with the CmdbType of the object it records

The log reads are judged by the type ACL of the logged object, through the log's ``type_id``. A new log is stamped
by its writer; this update gives the stored ones the same key, from two sources:

1. **the live object** - for a log whose object still exists, the object's ``type_id``, copied server-side by one
   aggregation that joins each log to its object and ``$merge``s the type back onto the log
2. **the log's own snapshot** - for a log whose object is gone, the ``type_information.type_id`` of the rendered
   object its ``render_state`` holds (JSON-encoded bytes, so decoded here, in batches). A snapshot that cannot be
   decoded or names no type stores ``type_id: null`` - the entry stays readable, as the ACL stage only excludes
   the types it denies

Only a log without the key is selected, and every log the update visits leaves with the key (a value or null), so
a second run selects nothing. A run stopped part-way leaves the visited logs stamped and the rest selectable
"""
import json
from logging import Logger, getLogger
from typing import Any

from pymongo import UpdateOne

from cmdb.database.updater.base_database_update import BaseDatabaseUpdate

from cmdb.framework.rendering.render_constants import RenderTypeInfoKey
from cmdb.models.log_model.cmdb_meta_log import CmdbMetaLog
from cmdb.models.log_model.object_log_constants import OBJECT_LOG_TYPE, ObjectLogKey
from cmdb.models.object_model import CmdbObject
from cmdb.models.object_model.cmdb_object_key_enum import CmdbObjectKey

from cmdb.errors.updater import UpdaterException
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

TYPE_FIELD: str = ObjectLogKey.TYPE_ID.value
LOG_TYPE_FIELD: str = 'log_type'
MONGO_ID_FIELD: str = '_id'

# The logs this update visits: object logs that do not carry the key yet
UNSTAMPED_LOG_CRITERIA: dict[str, Any] = {LOG_TYPE_FIELD: OBJECT_LOG_TYPE, TYPE_FIELD: {'$exists': False}}

# The RenderResult block the snapshot names its type in - the attribute name is the stored key
RENDER_TYPE_INFORMATION_KEY: str = 'type_information'

# The joined object list of the live-object stage; it holds at most one type-only document
JOINED_OBJECT_FIELD: str = 'logged_object'

# How many snapshot-derived stamps are sent per bulk write
SNAPSHOT_BATCH_SIZE: int = 500


def build_live_object_stamp_pipeline() -> list[dict[str, Any]]:
    """
    Builds the aggregation stamping every unstamped log whose object exists with that object's type

    Runs over the logs collection and writes back into it (``$merge`` on ``_id``, existing documents only), so
    no log leaves the server. A log whose object is gone joins nothing and is left for the snapshot pass

    Returns:
        list[dict[str, Any]]: The aggregation pipeline
    """
    return [
        {'$match': UNSTAMPED_LOG_CRITERIA},
        {'$lookup': {
            'from': CmdbObject.COLLECTION,
            'localField': ObjectLogKey.OBJECT_ID.value,
            'foreignField': CmdbObjectKey.PUBLIC_ID.value,
            'pipeline': [{'$limit': 1}, {'$project': {MONGO_ID_FIELD: 0, CmdbObjectKey.TYPE_ID.value: 1}}],
            'as': JOINED_OBJECT_FIELD,
        }},
        {'$match': {f'{JOINED_OBJECT_FIELD}.0.{CmdbObjectKey.TYPE_ID.value}': {'$type': 'number'}}},
        {'$project': {
            MONGO_ID_FIELD: 1,
            TYPE_FIELD: {'$arrayElemAt': [f'${JOINED_OBJECT_FIELD}.{CmdbObjectKey.TYPE_ID.value}', 0]},
        }},
        {'$merge': {
            'into': CmdbMetaLog.COLLECTION,
            'on': MONGO_ID_FIELD,
            'whenMatched': 'merge',
            'whenNotMatched': 'discard',
        }},
    ]


def type_id_from_render_state(render_state: Any) -> int | None:
    """
    Reads the type a log's snapshot names, if it can

    Args:
        render_state (Any): The stored ``render_state`` - JSON-encoded bytes (or text, from older writers)

    Returns:
        int | None: The snapshot's ``type_information.type_id``, or None when the snapshot cannot be decoded or
            names no whole-number type
    """
    if isinstance(render_state, (bytes, bytearray)):
        render_state = render_state.decode('UTF-8', errors='replace')

    if not isinstance(render_state, str):
        return None

    try:
        snapshot: Any = json.loads(render_state)
    except ValueError:
        return None

    type_information: Any = snapshot.get(RENDER_TYPE_INFORMATION_KEY) if isinstance(snapshot, dict) else None
    type_id: Any = (
        type_information.get(RenderTypeInfoKey.TYPE_ID.value) if isinstance(type_information, dict) else None
    )

    if isinstance(type_id, bool) or not isinstance(type_id, int):
        return None

    return type_id


def build_snapshot_stamp_operation(log: dict[str, Any]) -> UpdateOne:
    """
    Builds the write stamping one log with the type its snapshot names (or null)

    The filter repeats the unstamped criteria, so a log stamped meanwhile - by the live-object pass of another
    run - is not overwritten

    Args:
        log (dict[str, Any]): The log, carrying its ``_id`` and ``render_state``

    Returns:
        UpdateOne: The write
    """
    return UpdateOne(
        {MONGO_ID_FIELD: log[MONGO_ID_FIELD], **UNSTAMPED_LOG_CRITERIA},
        {'$set': {TYPE_FIELD: type_id_from_render_state(log.get(ObjectLogKey.RENDER_STATE.value))}},
    )

# -------------------------------------------------------------------------------------------------------------------- #
#                                                Update20261005 - CLASS                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class Update20261005(BaseDatabaseUpdate):
    """
    Stamps every stored CmdbObjectLog with the type of the object it records - from the live object, else from
    the log's own snapshot

    Extends: BaseDatabaseUpdate
    """
    def creation_date(self) -> int:
        return 20261005


    def description(self) -> str:
        return "Stamps every CmdbObjectLog with the CmdbType of the object it records ('type_id')"


    def start_update(self) -> None:
        """
        Runs the live-object pass, then the snapshot pass over what is left, then bumps the version

        Raises:
            UpdaterException: If a read or a write failed
        """
        try:
            # Consumed so the $merge runs to its end before the remaining logs are selected
            list(self.dbm.aggregate(CmdbMetaLog.COLLECTION, self.db_name, build_live_object_stamp_pipeline()))

            stamped: int = self._stamp_from_snapshots()

            LOGGER.info("[Update20261005] Stamped %s log(s) whose object is gone from their snapshot", stamped)

            self.increase_updater_version(self.creation_date())
        except Exception as err:
            raise UpdaterException(err) from err


    def _stamp_from_snapshots(self) -> int:
        """
        Stamps every log still without the key from its snapshot, in batches

        Returns:
            int: How many logs were visited
        """
        remaining = self.dbm.find(
            collection=CmdbMetaLog.COLLECTION,
            db_name=self.db_name,
            filter=UNSTAMPED_LOG_CRITERIA,
            projection={MONGO_ID_FIELD: 1, ObjectLogKey.RENDER_STATE.value: 1},
        )

        batch: list[UpdateOne] = []
        visited: int = 0

        for log in remaining:
            batch.append(build_snapshot_stamp_operation(log))
            visited += 1

            if len(batch) >= SNAPSHOT_BATCH_SIZE:
                self.dbm.bulk_write(CmdbMetaLog.COLLECTION, self.db_name, batch)
                batch = []

        if batch:
            self.dbm.bulk_write(CmdbMetaLog.COLLECTION, self.db_name, batch)

        return visited
