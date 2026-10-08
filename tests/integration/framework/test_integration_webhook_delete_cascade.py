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
Integration tests of deleting a CmdbWebhook together with its delivery log, against real collections

The delete handler runs with real managers: the webhook goes, exactly its own events go with it in one statement,
another webhook's events stay - and when deleting the events fails, the write ledger puts the webhook back under its
old id, identical to what was stored, with every event still in place
"""
from typing import Any, Iterator
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask
from werkzeug.exceptions import HTTPException

from cmdb.database import MongoDatabaseManager
from cmdb.errors.manager.webhooks_event_manager import WebhooksEventManagerDeleteError
from cmdb.manager import WebhooksEventManager, WebhooksManager
from cmdb.manager.manager_provider_model import ManagerType
from cmdb.models.webhook_model.cmdb_webhook_event import CmdbWebhookEvent
from cmdb.models.webhook_model.cmdb_webhook_model import CmdbWebhook
from cmdb.models.webhook_model.webhook_event_constants import WebhookEventKey
from cmdb.interface.rest_api.routes.webhook_routes.webhook_routes import delete_webhook
# -------------------------------------------------------------------------------------------------------------------- #

DELETED_WEBHOOK_ID: int = 9661
OTHER_WEBHOOK_ID: int = 9662
DELETED_EVENT_IDS: list[int] = [9671, 9672]
OTHER_EVENT_ID: int = 9673
EVENT_IDS: list[int] = [*DELETED_EVENT_IDS, OTHER_EVENT_ID]
ROUTE_PATH: str = 'cmdb.interface.rest_api.routes.webhook_routes.webhook_routes'


def _webhook(public_id: int) -> dict[str, Any]:
    """A stored CmdbWebhook."""
    return {'public_id': public_id, 'name': f'hook-{public_id}', 'url': 'https://x.io/hook', 'event_types': ['CREATE'],
            'active': True}


def _event(public_id: int, webhook_id: int) -> dict[str, Any]:
    """A stored delivery of a webhook."""
    return {'public_id': public_id, WebhookEventKey.WEBHOOK_ID.value: webhook_id, 'operation': 'CREATE',
            'object_before': None, 'object_after': None, 'changes': None, 'status': True, 'response_code': 200}


@pytest.fixture(name='collections')
def fixture_collections(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[tuple[Any, Any]]:
    """Two webhooks, two events of the one deleted and one of the other; all removed afterwards."""
    webhooks = database_manager.get_collection(CmdbWebhook.COLLECTION, database_name)
    events = database_manager.get_collection(CmdbWebhookEvent.COLLECTION, database_name)
    webhooks.delete_many({'public_id': {'$in': [DELETED_WEBHOOK_ID, OTHER_WEBHOOK_ID]}})
    events.delete_many({'public_id': {'$in': EVENT_IDS}})
    webhooks.insert_many([_webhook(DELETED_WEBHOOK_ID), _webhook(OTHER_WEBHOOK_ID)])
    events.insert_many([*(_event(event_id, DELETED_WEBHOOK_ID) for event_id in DELETED_EVENT_IDS),
                        _event(OTHER_EVENT_ID, OTHER_WEBHOOK_ID)])

    yield webhooks, events

    webhooks.delete_many({'public_id': {'$in': [DELETED_WEBHOOK_ID, OTHER_WEBHOOK_ID]}})
    events.delete_many({'public_id': {'$in': EVENT_IDS}})


def _delete(database_manager: MongoDatabaseManager, events_manager: WebhooksEventManager | None = None) -> Any:
    """Runs the delete handler with real managers."""
    managers = {
        ManagerType.WEBHOOKS: WebhooksManager(database_manager),
        ManagerType.WEBHOOKS_EVENT: events_manager or WebhooksEventManager(database_manager),
    }
    handler = delete_webhook

    while hasattr(handler, '__wrapped__'):
        handler = handler.__wrapped__

    with Flask(__name__).test_request_context('/', method='DELETE'), \
         patch(f'{ROUTE_PATH}.ManagerProvider.get_manager', side_effect=lambda kind, _user: managers[kind]):
        return handler(public_id=DELETED_WEBHOOK_ID, request_user=MagicMock())


def _stored_event_ids(events: Any) -> list[int]:
    """The fixture's events still stored."""
    return sorted(doc['public_id'] for doc in events.find({'public_id': {'$in': EVENT_IDS}}))


def test_the_webhook_goes_with_exactly_its_own_events(database_manager: MongoDatabaseManager, collections) -> None:
    """Its two events are deleted; the other webhook and its event stay"""
    webhooks, events = collections

    _delete(database_manager)

    assert webhooks.find_one({'public_id': DELETED_WEBHOOK_ID}) is None
    assert webhooks.find_one({'public_id': OTHER_WEBHOOK_ID}) is not None
    assert _stored_event_ids(events) == [OTHER_EVENT_ID]


def test_the_manager_answers_how_many_events_it_deleted(database_manager: MongoDatabaseManager, collections) -> None:
    """The count is the webhook's own events - the other webhook's are not matched"""
    _webhooks, events = collections

    deleted = WebhooksEventManager(database_manager).delete_events_of_webhook(DELETED_WEBHOOK_ID)

    assert deleted == len(DELETED_EVENT_IDS)
    assert _stored_event_ids(events) == [OTHER_EVENT_ID]


def test_a_failed_event_delete_restores_the_webhook_exactly(
    database_manager: MongoDatabaseManager, collections,
) -> None:
    """400, the webhook back under its old id and identical, every event still stored"""
    webhooks, events = collections
    before: dict[str, Any] = webhooks.find_one({'public_id': DELETED_WEBHOOK_ID}, {'_id': 0})
    failing_events = WebhooksEventManager(database_manager)

    with patch.object(failing_events, 'delete_events_of_webhook', side_effect=WebhooksEventManagerDeleteError('x')):
        with pytest.raises(HTTPException) as exc_info:
            _delete(database_manager, failing_events)

    assert exc_info.value.code == 400
    assert webhooks.find_one({'public_id': DELETED_WEBHOOK_ID}, {'_id': 0}) == before
    assert _stored_event_ids(events) == EVENT_IDS
