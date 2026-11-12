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
Functional tests: the object-log lists page by date without repeating or losing a log, through the real REST app

Seeds logs that share one ``log_time`` (as the logs of one bulk edit do) far in the future, so a date-descending page
holds only them, and pages through ``/logs/object/notexists`` and ``/logs/object/deleted`` with ``?sort=log_time``:

  - two consecutive pages never share a log, and together they are the newest seeded logs in public_id order
  - the same page asked twice answers the same logs
  - the response shape is unchanged: the date sort is answered 200 with the usual envelope
"""
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.log_model.cmdb_meta_log import CmdbMetaLog
from cmdb.models.log_model.cmdb_object_log import CmdbObjectLog
from cmdb.models.log_model.log_action_enum import LogAction
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_URL: str = '/logs/object'
FIRST_LOG_ID: int = 91001
LOGS_PER_LIST: int = 12
FIRST_OBJECT_ID: int = 91501
PAGE_SIZE: int = 5
DESCENDING: int = -1
# Later than any log another test stores, so a date-descending page starts with the seeded logs
SHARED_LOG_TIME: datetime = datetime(2099, 1, 1, tzinfo=timezone.utc)
EDIT_IDS: list[int] = list(range(FIRST_LOG_ID, FIRST_LOG_ID + LOGS_PER_LIST))
DELETE_IDS: list[int] = list(range(FIRST_LOG_ID + LOGS_PER_LIST, FIRST_LOG_ID + 2 * LOGS_PER_LIST))
LIST_IDS: dict[str, list[int]] = {'notexists': EDIT_IDS, 'deleted': DELETE_IDS}


def _log_doc(public_id: int, action: LogAction) -> dict[str, Any]:
    """An object log of an object that no longer exists, at the shared time"""
    return {'public_id': public_id, 'log_type': CmdbObjectLog.__name__, 'action': action.value,
            'action_name': action.name, 'object_id': FIRST_OBJECT_ID + public_id % 3, 'version': '1.0.0',
            'user_id': 1, 'user_name': 'admin', 'changes': [], 'comment': 'date-paging', 'render_state': None,
            'log_time': SHARED_LOG_TIME}


@pytest.fixture(autouse=True)
def _seed(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[None]:
    """The edit and delete logs - removed again after"""
    logs = database_manager.get_collection(CmdbMetaLog.COLLECTION, database_name)
    seeded: dict[str, Any] = {'public_id': {'$in': EDIT_IDS + DELETE_IDS}}
    logs.delete_many(seeded)
    logs.insert_many([_log_doc(log_id, LogAction.EDIT) for log_id in EDIT_IDS]
                     + [_log_doc(log_id, LogAction.DELETE) for log_id in DELETE_IDS])
    yield
    logs.delete_many(seeded)


def _page(rest_api, list_name: str, page: int) -> list[int]:
    """The public_ids of one date-descending page, in the order answered"""
    response = rest_api.get(f'{ROUTE_URL}/{list_name}',
                            query_string={'sort': 'log_time', 'order': DESCENDING, 'limit': PAGE_SIZE, 'page': page})

    assert response.status_code == HTTPStatus.OK

    return [entry['public_id'] for entry in response.get_json()['results']]


@pytest.mark.parametrize('list_name', list(LIST_IDS))
def test_two_pages_share_no_log_and_follow_public_id(rest_api, list_name: str) -> None:
    """The tie on log_time is broken by public_id, descending like the sort"""
    first: list[int] = _page(rest_api, list_name, 1)
    second: list[int] = _page(rest_api, list_name, 2)

    newest: list[int] = sorted(LIST_IDS[list_name], reverse=True)[:2 * PAGE_SIZE]
    assert first + second == newest


@pytest.mark.parametrize('list_name', list(LIST_IDS))
def test_the_same_page_answers_the_same_logs(rest_api, list_name: str) -> None:
    """Repeatable"""
    assert _page(rest_api, list_name, 1) == _page(rest_api, list_name, 1)
