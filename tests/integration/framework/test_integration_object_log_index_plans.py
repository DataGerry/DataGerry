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
Integration tests: a date-ordered page of an object-log list is read off an index, not sorted in memory

Builds the exact pipeline `LogsManager.iterate` runs (`BaseQueryBuilder.build`) for each log list and asks MongoDB for
its winning plan, with the indexes `CmdbMetaLog` declares:

  - the exists / notexists split, the delete-log list and the per-object list, sorted by ``log_time`` in both
    directions, plan without a blocking SORT stage
  - the same holds with the type-ACL condition (``type_id $nin``) the lists add for a restricted caller
  - the split's ``$in`` of actions is what makes it possible: the old ``$ne`` DELETE keeps the SORT
  - a page of logs sharing one ``log_time`` is the same on every request, and two pages never overlap

The test session builds no declared index, so each test builds them and drops what it built
"""
from datetime import datetime, timezone
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.query_builder import BaseQueryBuilder, BuilderParameters
from cmdb.models.log_model.cmdb_meta_log import CmdbMetaLog
from cmdb.models.log_model.log_action_enum import LogAction
from cmdb.models.log_model.object_log_constants import OBJECT_LOG_TYPE
from cmdb.interface.rest_api.routes.framework_routes.cmdb_logs.logs_helper import build_object_log_existence_filter
# -------------------------------------------------------------------------------------------------------------------- #

FIRST_LOG_ID: int = 78001
LOG_COUNT: int = 120
OBJECT_COUNT: int = 6
FIRST_OBJECT_ID: int = 78501
DELETED_OBJECT_IDS: list[int] = [FIRST_OBJECT_ID, FIRST_OBJECT_ID + 1]
DENIED_TYPE_IDS: list[int] = [78901, 78902]
TYPE_ID: int = 78900
LOG_TIME_KEY: str = 'log_time'
PAGE_SIZE: int = 10
MONGO_ID_INDEX: str = '_id_'
BLOCKING_SORT_STAGE: str = 'SORT'
STAGE_KEY: str = 'stage'
ORDERS: list[int] = [1, -1]
# Every seeded log shares this one instant, so only the tie-break orders them
SHARED_LOG_TIME: datetime = datetime(2026, 11, 11, 12, 0, 0, tzinfo=timezone.utc)
SEEDED_IDS: dict[str, Any] = {'public_id': {'$gte': FIRST_LOG_ID, '$lt': FIRST_LOG_ID + LOG_COUNT}}
DENIED_TYPES_CONDITION: dict[str, Any] = {'type_id': {'$nin': DENIED_TYPE_IDS}}
NE_DELETE_CONDITION: dict[str, Any] = {'log_type': OBJECT_LOG_TYPE, 'action': {'$ne': LogAction.DELETE.value}}


def _log_doc(offset: int) -> dict[str, Any]:
    """An object log; every fifth one a delete, objects taken in turn"""
    action: LogAction = LogAction.DELETE if offset % 5 == 0 else LogAction.EDIT

    return {'public_id': FIRST_LOG_ID + offset, 'log_type': OBJECT_LOG_TYPE, 'action': action.value,
            'action_name': action.name, 'object_id': FIRST_OBJECT_ID + offset % OBJECT_COUNT, 'type_id': TYPE_ID,
            LOG_TIME_KEY: SHARED_LOG_TIME}


@pytest.fixture(name='logs')
def fixture_logs(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[Any]:
    """The seeded logs behind the declared indexes; the logs and every index built here are removed after"""
    logs = database_manager.get_collection(CmdbMetaLog.COLLECTION, database_name)
    logs.delete_many(SEEDED_IDS)
    had_indexes: set[str] = set(logs.index_information())
    logs.create_indexes(CmdbMetaLog.get_index_keys())
    logs.insert_many([_log_doc(offset) for offset in range(LOG_COUNT)])

    yield logs

    logs.delete_many(SEEDED_IDS)

    for index_name in set(logs.index_information()) - had_indexes - {MONGO_ID_INDEX}:
        logs.drop_index(index_name)


def _pipeline(criteria: dict[str, Any], order: int) -> list[dict[str, Any]]:
    """The pipeline a list route runs for the first page in log_time order"""
    return BaseQueryBuilder().build(BuilderParameters(criteria, PAGE_SIZE, 0, LOG_TIME_KEY, order))


def _winning_stages(database_manager: MongoDatabaseManager, database_name: str,
                    pipeline: list[dict[str, Any]]) -> set[str]:
    """Every stage name of the winning plan, searched through the nesting (it differs between server versions)"""
    explain: dict[str, Any] = database_manager.connector.get_database(database_name).command(
        'explain', {'aggregate': CmdbMetaLog.COLLECTION, 'pipeline': pipeline, 'cursor': {}},
        verbosity='queryPlanner',
    )
    pending: list[Any] = [explain]
    names: set[str] = set()

    while pending:
        node: Any = pending.pop()

        if isinstance(node, dict):
            if 'rejectedPlans' in node:
                node = {key: value for key, value in node.items() if key != 'rejectedPlans'}
            if isinstance(node.get(STAGE_KEY), str):
                names.add(node[STAGE_KEY])
            pending.extend(node.values())
        elif isinstance(node, list):
            pending.extend(node)

    return names


LIST_CRITERIA: dict[str, dict[str, Any]] = {
    'exists': build_object_log_existence_filter(DELETED_OBJECT_IDS, object_exists=True),
    'notexists': build_object_log_existence_filter(DELETED_OBJECT_IDS, object_exists=False),
    'deleted': {'log_type': OBJECT_LOG_TYPE, 'action': LogAction.DELETE.value},
    'per-object': {'log_type': OBJECT_LOG_TYPE, 'object_id': FIRST_OBJECT_ID + 2},
}


@pytest.mark.usefixtures('logs')
@pytest.mark.parametrize('order', ORDERS, ids=['ascending', 'descending'])
@pytest.mark.parametrize('list_name', list(LIST_CRITERIA))
def test_a_date_page_is_read_off_an_index(database_manager: MongoDatabaseManager, database_name: str,
                                          list_name: str, order: int) -> None:
    """No blocking SORT: the page is cut from an ordered index read"""
    stages: set[str] = _winning_stages(database_manager, database_name, _pipeline(LIST_CRITERIA[list_name], order))

    assert BLOCKING_SORT_STAGE not in stages


@pytest.mark.usefixtures('logs')
@pytest.mark.parametrize('list_name', list(LIST_CRITERIA))
def test_the_acl_condition_keeps_the_index_plan(database_manager: MongoDatabaseManager, database_name: str,
                                                list_name: str) -> None:
    """A restricted caller's `type_id $nin` is filtered on the way, the order still comes from the index"""
    criteria: dict[str, Any] = {**LIST_CRITERIA[list_name], **DENIED_TYPES_CONDITION}

    stages: set[str] = _winning_stages(database_manager, database_name, _pipeline(criteria, -1))

    assert BLOCKING_SORT_STAGE not in stages


@pytest.mark.usefixtures('logs')
def test_ne_delete_would_keep_the_in_memory_sort(database_manager: MongoDatabaseManager, database_name: str) -> None:
    """The control: why the split lists its actions"""
    stages: set[str] = _winning_stages(database_manager, database_name, _pipeline(NE_DELETE_CONDITION, -1))

    assert BLOCKING_SORT_STAGE in stages


def _page_ids(logs: Any, page: int, order: int) -> list[int]:
    """One page of the seeded edit logs in log_time order, as the list route reads it"""
    criteria: dict[str, Any] = {**build_object_log_existence_filter([], object_exists=True), **SEEDED_IDS}
    pipeline = BaseQueryBuilder().build(BuilderParameters(criteria, PAGE_SIZE, page * PAGE_SIZE, LOG_TIME_KEY, order))

    return [document['public_id'] for document in logs.aggregate(pipeline)]


@pytest.mark.parametrize('order', ORDERS, ids=['ascending', 'descending'])
def test_logs_sharing_a_time_page_without_overlap(logs: Any, order: int) -> None:
    """Every seeded log has the same log_time; public_id decides, so pages are disjoint and repeatable"""
    first: list[int] = _page_ids(logs, 0, order)
    second: list[int] = _page_ids(logs, 1, order)

    assert len(first) == len(second) == PAGE_SIZE
    assert not set(first) & set(second)
    assert first == _page_ids(logs, 0, order)
    assert first + second == sorted(first + second, reverse=order == -1)
