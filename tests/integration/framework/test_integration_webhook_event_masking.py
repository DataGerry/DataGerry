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
Integration tests for the webhook-log masking stage, against a real MongoDB and the real event manager

The stage the list route puts first, run by ``WebhooksEventManager.iterate_items`` with a caller's ``$match`` after
it. Pinned: a denied event's values come back null while its row is kept, the caller's stage cannot find it by a
field value - neither in the rows nor in the total - and an allowed event is untouched
"""
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.query_builder import BuilderParameters
from cmdb.manager.webhooks_event_manager import WebhooksEventManager
from cmdb.models.webhook_model.cmdb_webhook_event import CmdbWebhookEvent
from cmdb.interface.rest_api.routes.webhook_routes.webhook_event_access import build_event_masking_stage
# -------------------------------------------------------------------------------------------------------------------- #

DENIED_TYPE_ID: int = 98201
ALLOWED_TYPE_ID: int = 98202
DENIED_EVENT_ID: int = 98211
ALLOWED_EVENT_ID: int = 98212
EVENT_IDS: list[int] = [DENIED_EVENT_ID, ALLOWED_EVENT_ID]
SECRET_VALUE: str = 'masked-in-the-pipeline'


def _event(public_id: int, type_id: int) -> dict[str, Any]:
    """A stored event for an object of the given type, carrying the same field value"""
    snapshot: dict[str, Any] = {'public_id': 5, 'type_id': type_id, 'fields': [{'name': 'f', 'value': SECRET_VALUE}]}

    return {
        'public_id': public_id, 'event_time': None, 'operation': 'UPDATE', 'webhook_id': 1,
        'object_before': snapshot, 'object_after': snapshot, 'changes': {'f': SECRET_VALUE},
        'response_code': 200, 'status': True,
    }


@pytest.fixture(name='manager', autouse=True)
def fixture_manager(database_manager: MongoDatabaseManager, database_name: str):
    """Two events of the same shape, one per type; purged after"""
    events = database_manager.get_collection(CmdbWebhookEvent.COLLECTION, database_name)
    events.delete_many({'public_id': {'$in': EVENT_IDS}})
    events.insert_many([_event(DENIED_EVENT_ID, DENIED_TYPE_ID), _event(ALLOWED_EVENT_ID, ALLOWED_TYPE_ID)])
    yield WebhooksEventManager(database_manager)
    events.delete_many({'public_id': {'$in': EVENT_IDS}})


def _iterate(manager: WebhooksEventManager, *stages: dict[str, Any]) -> tuple[dict[int, Any], int]:
    """The seeded events the stages answer, by public_id, and the total"""
    criteria: list[dict[str, Any]] = [
        build_event_masking_stage([DENIED_TYPE_ID]),
        {'$match': {'public_id': {'$in': EVENT_IDS}}},
        *stages,
    ]
    result = manager.iterate_items(BuilderParameters(criteria=criteria, limit=0))

    return {event.public_id: event for event in result.results}, result.total


def test_the_denied_event_keeps_its_row_and_loses_its_values(manager) -> None:
    """Both snapshots and the diff are null; the allowed event is untouched"""
    events, total = _iterate(manager)

    assert total == len(EVENT_IDS)
    denied = events[DENIED_EVENT_ID]
    assert (denied.object_before, denied.object_after, denied.changes) == (None, None, None)
    assert denied.webhook_id == 1
    assert events[ALLOWED_EVENT_ID].object_after['fields'][0]['value'] == SECRET_VALUE


def test_a_later_match_on_a_masked_value_cannot_find_it(manager) -> None:
    """Neither in the rows nor in the total - the oracle a response-only mask would leave"""
    events, total = _iterate(manager, {'$match': {'object_before.fields.value': SECRET_VALUE}})

    assert set(events) == {ALLOWED_EVENT_ID}
    assert total == 1
