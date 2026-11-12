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
Integration tests for cmdb.database.updater.versions.updater_20261115 against a real MongoDB

Seeds relation logs without type stamps - between two live objects, between a live object and a deleted one whose
object logs carry its type, and between two objects that left nothing behind - next to logs already stamped, runs
the migration, and asserts:

  - a live object's side gets that object's type, each side its own
  - a deleted object's side gets the type its own object logs carry
  - a side nothing answers stores null, so the entry stays readable
  - a log already stamped (a value or null) is left alone; nothing else of a log changes
  - a second run changes nothing
"""
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.database.updater.versions.updater_20261115 import Update20261115
from cmdb.models.log_model import CmdbObjectRelationLog
from cmdb.models.log_model.cmdb_meta_log import CmdbMetaLog
from cmdb.models.log_model.object_log_constants import OBJECT_LOG_TYPE
from cmdb.models.object_model import CmdbObject
# -------------------------------------------------------------------------------------------------------------------- #

LIVE_PARENT_ID: int = 98101
LIVE_CHILD_ID: int = 98102
GONE_OBJECT_ID: int = 98103
LOST_PARENT_ID: int = 98104
LOST_CHILD_ID: int = 98105
LIVE_PARENT_TYPE: int = 98111
LIVE_CHILD_TYPE: int = 98112
LOGGED_TYPE: int = 98113
STAMPED_TYPE: int = 98114

LIVE_LOG_ID: int = 98121
GONE_LOG_ID: int = 98122
LOST_LOG_ID: int = 98123
STAMPED_LOG_ID: int = 98124
NULL_STAMPED_LOG_ID: int = 98125
ALL_LOG_IDS: list[int] = [LIVE_LOG_ID, GONE_LOG_ID, LOST_LOG_ID, STAMPED_LOG_ID, NULL_STAMPED_LOG_ID]
OBJECT_LOG_ID: int = 98131

PARENT_TYPE_KEY: str = 'relation_parent_type_id'
CHILD_TYPE_KEY: str = 'relation_child_type_id'


def _log(public_id: int, parent_id: int, child_id: int, **extra: Any) -> dict[str, Any]:
    """A stored relation log written before the types were stamped"""
    return {
        'public_id': public_id, 'object_relation_id': public_id, 'object_relation_parent_id': parent_id,
        'object_relation_child_id': child_id, 'action': 'DELETE', 'author_id': 1, 'author_name': 'admin',
        'changes': {}, **extra,
    }


@pytest.fixture(name='relation_logs', autouse=True)
def fixture_relation_logs(database_manager: MongoDatabaseManager, database_name: str):
    """The seeded relation logs, the two live objects and the deleted object's own log, purged before and after"""
    relation_logs = database_manager.get_collection(CmdbObjectRelationLog.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    object_logs = database_manager.get_collection(CmdbMetaLog.COLLECTION, database_name)

    def _purge() -> None:
        relation_logs.delete_many({'public_id': {'$in': ALL_LOG_IDS}})
        objects.delete_many({'public_id': {'$in': [LIVE_PARENT_ID, LIVE_CHILD_ID]}})
        object_logs.delete_many({'public_id': OBJECT_LOG_ID})

    _purge()
    objects.insert_many([
        {'public_id': LIVE_PARENT_ID, 'type_id': LIVE_PARENT_TYPE, 'fields': []},
        {'public_id': LIVE_CHILD_ID, 'type_id': LIVE_CHILD_TYPE, 'fields': []},
    ])
    object_logs.insert_one({
        'public_id': OBJECT_LOG_ID, 'log_type': OBJECT_LOG_TYPE, 'object_id': GONE_OBJECT_ID, 'type_id': LOGGED_TYPE,
        'action': 3, 'action_name': 'DELETE', 'user_id': 1, 'user_name': 'admin', 'changes': [],
    })
    relation_logs.insert_many([
        _log(LIVE_LOG_ID, LIVE_PARENT_ID, LIVE_CHILD_ID),
        _log(GONE_LOG_ID, LIVE_PARENT_ID, GONE_OBJECT_ID),
        _log(LOST_LOG_ID, LOST_PARENT_ID, LOST_CHILD_ID),
        _log(STAMPED_LOG_ID, LIVE_PARENT_ID, LIVE_CHILD_ID,
             relation_parent_type_id=STAMPED_TYPE, relation_child_type_id=STAMPED_TYPE),
        _log(NULL_STAMPED_LOG_ID, LIVE_PARENT_ID, LIVE_CHILD_ID, relation_parent_type_id=None,
             relation_child_type_id=None),
    ])
    yield relation_logs
    _purge()


def _types(relation_logs: Any, public_id: int) -> tuple[Any, Any]:
    """The two stamped types of one relation log"""
    document: dict[str, Any] = relation_logs.find_one({'public_id': public_id})

    return document[PARENT_TYPE_KEY], document[CHILD_TYPE_KEY]


def _run(database_manager: MongoDatabaseManager, database_name: str) -> None:
    """One run of the migration"""
    Update20261115(database_manager, database_name).start_update()


def test_a_live_objects_side_gets_that_objects_type(relation_logs, database_manager, database_name) -> None:
    """Each side its own - a swap fails"""
    _run(database_manager, database_name)

    assert _types(relation_logs, LIVE_LOG_ID) == (LIVE_PARENT_TYPE, LIVE_CHILD_TYPE)


def test_a_deleted_objects_side_gets_the_type_of_its_own_logs(relation_logs, database_manager, database_name) -> None:
    """The live side from the object, the gone side from its object log"""
    _run(database_manager, database_name)

    assert _types(relation_logs, GONE_LOG_ID) == (LIVE_PARENT_TYPE, LOGGED_TYPE)


def test_a_side_nothing_answers_stores_null(relation_logs, database_manager, database_name) -> None:
    """The entry stays readable"""
    _run(database_manager, database_name)

    assert _types(relation_logs, LOST_LOG_ID) == (None, None)


def test_stamped_logs_are_left_alone(relation_logs, database_manager, database_name) -> None:
    """A value or null - both are a finished stamp"""
    _run(database_manager, database_name)

    assert _types(relation_logs, STAMPED_LOG_ID) == (STAMPED_TYPE, STAMPED_TYPE)
    assert _types(relation_logs, NULL_STAMPED_LOG_ID) == (None, None)


def test_nothing_else_of_a_log_changes(relation_logs, database_manager, database_name) -> None:
    """Only the two keys are added"""
    before: dict[str, Any] = relation_logs.find_one({'public_id': GONE_LOG_ID}, {'_id': 0})

    _run(database_manager, database_name)

    after: dict[str, Any] = relation_logs.find_one({'public_id': GONE_LOG_ID}, {'_id': 0})
    assert {key: value for key, value in after.items() if key not in (PARENT_TYPE_KEY, CHILD_TYPE_KEY)} == before


def test_a_second_run_changes_nothing(relation_logs, database_manager, database_name) -> None:
    """Every visited log left with both keys"""
    _run(database_manager, database_name)
    first: list[dict[str, Any]] = list(relation_logs.find({'public_id': {'$in': ALL_LOG_IDS}}, {'_id': 0}))

    _run(database_manager, database_name)

    assert list(relation_logs.find({'public_id': {'$in': ALL_LOG_IDS}}, {'_id': 0})) == first
