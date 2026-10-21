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
Integration tests for cmdb.database.updater.versions.updater_20261005 against a real MongoDB

Seeds object logs without a type - of a live object, of a deleted object with a readable snapshot, of a deleted
object with a broken snapshot - next to logs that already carry one and a log of another kind, runs the
migration, and asserts:

  - a log of a live object gets that object's type, also when its snapshot names another one
  - a log of a deleted object gets the type its snapshot names, and a broken snapshot stores null
  - a log already stamped (a value or null) and a log of another kind are left alone; nothing else of a log changes
  - a second run changes nothing
"""
import json
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.database.updater.versions.updater_20261005 import Update20261005
from cmdb.models.log_model.cmdb_meta_log import CmdbMetaLog
from cmdb.models.log_model.object_log_constants import OBJECT_LOG_TYPE
from cmdb.models.object_model import CmdbObject
# -------------------------------------------------------------------------------------------------------------------- #

LIVE_OBJECT_ID: int = 97901
GONE_OBJECT_ID: int = 97902
BROKEN_OBJECT_ID: int = 97903
LIVE_TYPE_ID: int = 97911
SNAPSHOT_TYPE_ID: int = 97912
STALE_SNAPSHOT_TYPE_ID: int = 97913
STAMPED_TYPE_ID: int = 97914

LIVE_LOG_ID: int = 97921
GONE_LOG_ID: int = 97922
BROKEN_LOG_ID: int = 97923
STAMPED_LOG_ID: int = 97924
NULL_STAMPED_LOG_ID: int = 97925
OTHER_KIND_LOG_ID: int = 97926
ALL_LOG_IDS: list[int] = [
    LIVE_LOG_ID, GONE_LOG_ID, BROKEN_LOG_ID, STAMPED_LOG_ID, NULL_STAMPED_LOG_ID, OTHER_KIND_LOG_ID,
]

OTHER_LOG_KIND: str = 'CmdbOtherLog'
TYPE_ID: str = 'type_id'


def _snapshot(type_id: int) -> bytes:
    """A render_state as the writer stores it, naming one type"""
    return json.dumps({'object_information': {}, 'type_information': {'type_id': type_id}}).encode('UTF-8')


def _log(public_id: int, object_id: int, render_state: Any, log_type: str = OBJECT_LOG_TYPE, **extra: Any) -> dict:
    """A stored object log written before the type was stamped"""
    return {
        'public_id': public_id, 'log_type': log_type, 'object_id': object_id, 'action': 1, 'action_name': 'EDIT',
        'version': '1.0.1', 'user_id': 1, 'user_name': 'admin', 'comment': '', 'changes': [],
        'render_state': render_state, **extra,
    }


@pytest.fixture(name='logs', autouse=True)
def fixture_logs(database_manager: MongoDatabaseManager, database_name: str):
    """The seeded logs and the one live object, purged before and after"""
    logs = database_manager.get_collection(CmdbMetaLog.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)

    def _purge() -> None:
        logs.delete_many({'public_id': {'$in': ALL_LOG_IDS}})
        objects.delete_many({'public_id': LIVE_OBJECT_ID})

    _purge()
    objects.insert_one({'public_id': LIVE_OBJECT_ID, 'type_id': LIVE_TYPE_ID, 'fields': []})
    logs.insert_many([
        _log(LIVE_LOG_ID, LIVE_OBJECT_ID, _snapshot(STALE_SNAPSHOT_TYPE_ID)),
        _log(GONE_LOG_ID, GONE_OBJECT_ID, _snapshot(SNAPSHOT_TYPE_ID)),
        _log(BROKEN_LOG_ID, BROKEN_OBJECT_ID, b'not json'),
        _log(STAMPED_LOG_ID, LIVE_OBJECT_ID, _snapshot(SNAPSHOT_TYPE_ID), **{TYPE_ID: STAMPED_TYPE_ID}),
        _log(NULL_STAMPED_LOG_ID, LIVE_OBJECT_ID, _snapshot(SNAPSHOT_TYPE_ID), **{TYPE_ID: None}),
        _log(OTHER_KIND_LOG_ID, LIVE_OBJECT_ID, _snapshot(SNAPSHOT_TYPE_ID), log_type=OTHER_LOG_KIND),
    ])
    yield logs
    _purge()


def _run(database_manager: MongoDatabaseManager, database_name: str) -> None:
    """One run of the migration"""
    Update20261005(database_manager, database_name).start_update()


def _stored(logs: Any, public_id: int) -> dict[str, Any]:
    """One stored log, without _id"""
    return logs.find_one({'public_id': public_id}, {'_id': 0})


class TestTheStamp:
    """Each source, and what is left alone"""

    def test_a_live_object_gives_its_own_type(self, logs, database_manager, database_name) -> None:
        """The live object wins over a snapshot that names another type"""
        _run(database_manager, database_name)

        assert _stored(logs, LIVE_LOG_ID)[TYPE_ID] == LIVE_TYPE_ID

    def test_a_deleted_object_gives_the_type_its_snapshot_names(self, logs, database_manager, database_name) -> None:
        """No object to join - the snapshot is decoded"""
        _run(database_manager, database_name)

        assert _stored(logs, GONE_LOG_ID)[TYPE_ID] == SNAPSHOT_TYPE_ID

    def test_a_broken_snapshot_stores_null(self, logs, database_manager, database_name) -> None:
        """The key is there, with no type - readable, and never visited again"""
        _run(database_manager, database_name)

        stored = _stored(logs, BROKEN_LOG_ID)
        assert TYPE_ID in stored
        assert stored[TYPE_ID] is None

    @pytest.mark.parametrize('public_id, expected', [
        (STAMPED_LOG_ID, STAMPED_TYPE_ID), (NULL_STAMPED_LOG_ID, None),
    ], ids=['value', 'null'])
    def test_a_stamped_log_is_left_alone(self, logs, database_manager, database_name, public_id, expected) -> None:
        """Even where its object is live and names another type"""
        _run(database_manager, database_name)

        assert _stored(logs, public_id)[TYPE_ID] == expected

    def test_a_log_of_another_kind_is_left_alone(self, logs, database_manager, database_name) -> None:
        """Only object logs are stamped"""
        _run(database_manager, database_name)

        assert TYPE_ID not in _stored(logs, OTHER_KIND_LOG_ID)

    def test_nothing_else_of_a_log_changes(self, logs, database_manager, database_name) -> None:
        """The merge writes the type alone"""
        before = _stored(logs, LIVE_LOG_ID)

        _run(database_manager, database_name)

        assert _stored(logs, LIVE_LOG_ID) == {**before, TYPE_ID: LIVE_TYPE_ID}


def test_a_second_run_changes_nothing(logs, database_manager: MongoDatabaseManager, database_name: str) -> None:
    """Every visited log left with the key, so the second run selects none of them"""
    _run(database_manager, database_name)
    first: list[dict[str, Any]] = [_stored(logs, public_id) for public_id in ALL_LOG_IDS]

    _run(database_manager, database_name)

    assert [_stored(logs, public_id) for public_id in ALL_LOG_IDS] == first
