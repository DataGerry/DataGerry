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
Functional coverage of the delivery-log LIST shape: a row is the event's summary, the single read the whole event

Over the real app: every listed row carries exactly the summary keys and none of the object values, while
``GET /webhook_events/<id>`` still answers the snapshots; the frontend's search (an ``$addFields`` + ``$match`` on a
stringified ``webhook_id``) and its ``event_time`` sort keep working; and the pager total is unchanged
"""
import json
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.webhook_model.cmdb_webhook_event import CmdbWebhookEvent
from cmdb.models.webhook_model.webhook_event_constants import WEBHOOK_EVENT_SUMMARY_KEYS, WebhookEventKey
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_URL: str = '/webhook_events'
EARLIER_EVENT_ID: int = 97911
LATER_EVENT_ID: int = 97912
OTHER_WEBHOOK_EVENT_ID: int = 97913
EVENT_IDS: list[int] = [EARLIER_EVENT_ID, LATER_EVENT_ID, OTHER_WEBHOOK_EVENT_ID]
WEBHOOK_ID: int = 97920
OTHER_WEBHOOK_ID: int = 97930
SNAPSHOT: dict[str, Any] = {'public_id': 5, 'fields': [{'name': 'a', 'value': 'v', 'type': 'text'}]}
SUMMARY_KEYS: list[str] = [key.value for key in WEBHOOK_EVENT_SUMMARY_KEYS]
NOW: datetime = datetime.now(timezone.utc)


def _event(public_id: int, webhook_id: int, event_time: datetime) -> dict[str, Any]:
    """An UPDATE delivery with both snapshots and a diff."""
    return {
        'public_id': public_id, 'event_time': event_time, 'operation': 'UPDATE', 'webhook_id': webhook_id,
        'object_before': SNAPSHOT, 'object_after': SNAPSHOT, 'changes': {'a': 'v'}, 'response_code': 200,
        'status': True,
    }


@pytest.fixture(name='events', autouse=True)
def fixture_events(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[Any]:
    """Three deliveries, two of one webhook; removed afterwards."""
    events = database_manager.get_collection(CmdbWebhookEvent.COLLECTION, database_name)
    events.delete_many({'public_id': {'$in': EVENT_IDS}})
    events.insert_many([
        _event(EARLIER_EVENT_ID, WEBHOOK_ID, NOW - timedelta(minutes=5)),
        _event(LATER_EVENT_ID, WEBHOOK_ID, NOW),
        _event(OTHER_WEBHOOK_EVENT_ID, OTHER_WEBHOOK_ID, NOW),
    ])

    yield events

    events.delete_many({'public_id': {'$in': EVENT_IDS}})


def _list(rest_api, stages: list[dict[str, Any]] | None = None, query: str = '') -> Any:
    """GET /webhook_events/ narrowed to the seeded events, with the caller's stages after."""
    own: list[dict[str, Any]] = [{'$match': {'public_id': {'$in': EVENT_IDS}}}]
    response = rest_api.get(f'{ROUTE_URL}/?limit=0{query}&filter={json.dumps(own + (stages or []))}')

    assert response.status_code == HTTPStatus.OK

    return response


def test_a_listed_row_carries_exactly_the_summary(rest_api) -> None:
    """Every row: the six scalar keys, no snapshot, no diff"""
    rows = _list(rest_api).get_json()['results']

    assert len(rows) == len(EVENT_IDS)
    assert all(list(row) == SUMMARY_KEYS for row in rows)


def test_the_single_read_still_answers_the_whole_event(rest_api) -> None:
    """What was sent is read here - both snapshots and the diff"""
    event = rest_api.get(f'{ROUTE_URL}/{LATER_EVENT_ID}').get_json()

    assert event[WebhookEventKey.OBJECT_AFTER.value] == SNAPSHOT
    assert event[WebhookEventKey.OBJECT_BEFORE.value] == SNAPSHOT
    assert event[WebhookEventKey.CHANGES.value] == {'a': 'v'}


def test_the_frontends_search_still_finds_its_rows(rest_api) -> None:
    """The log viewer's $addFields + $match on the stringified webhook id runs before the trim"""
    search: list[dict[str, Any]] = [
        {'$addFields': {'webhook_id_str': {'$toString': '$webhook_id'}}},
        {'$match': {'$or': [{'webhook_id_str': {'$regex': str(WEBHOOK_ID)}}]}},
    ]

    rows = _list(rest_api, search).get_json()['results']

    assert sorted(row['public_id'] for row in rows) == [EARLIER_EVENT_ID, LATER_EVENT_ID]
    assert all('webhook_id_str' not in row for row in rows)


def test_a_filter_on_a_snapshot_value_still_matches(rest_api) -> None:
    """The caller's stages see the stored event before the projection trims it"""
    rows = _list(rest_api, [{'$match': {'object_after.fields.value': 'v'}}]).get_json()['results']

    assert len(rows) == len(EVENT_IDS)


def test_the_event_time_sort_and_the_total_are_kept(rest_api) -> None:
    """Sorted on a summary key after the trim; X-Total-Count still counts every matching event"""
    response = _list(rest_api, [{'$match': {'webhook_id': WEBHOOK_ID}}], '&sort=event_time&order=-1')

    assert [row['public_id'] for row in response.get_json()['results']] == [LATER_EVENT_ID, EARLIER_EVENT_ID]
    assert int(response.headers['X-Total-Count']) == 2
