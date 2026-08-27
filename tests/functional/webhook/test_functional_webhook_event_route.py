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
Functional smoke for the ``/webhook_events`` REST routes

Covers the read + delete routes over the GenericManager-backed WebhooksEventManager: HTTP status
codes, the 404 on a missing id, and the manager-error -> 400 / 500 mappings. WebhookEvents are
created internally (on object changes), so these routes are read/delete only.
"""
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.webhooks_event_manager import WebhooksEventManager
from cmdb.models.webhook_model.cmdb_webhook_event import CmdbWebhookEvent
from cmdb.errors.manager.webhooks_event_manager import (
    WebhooksEventManagerGetError,
    WebhooksEventManagerDeleteError,
    WebhooksEventManagerIterationError,
)
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_URL: str = '/webhook_events'

EVENT_ID_FOR_GET: int = 97901
EVENT_ID_FOR_DELETE: int = 97902
MISSING_EVENT_ID: int = 97999

ALL_EVENT_IDS: list[int] = [EVENT_ID_FOR_GET, EVENT_ID_FOR_DELETE]


def _event_doc(public_id: int) -> dict[str, Any]:
    """Builds a CmdbWebhookEvent document for direct insertion."""
    return {
        'public_id': public_id, 'event_time': None, 'operation': 'CREATE', 'webhook_id': 1,
        'object_before': None, 'object_after': {'public_id': 5}, 'changes': None,
        'response_code': 200, 'status': True,
    }


@pytest.fixture(autouse=True)
def _cleanup(database_manager: MongoDatabaseManager, database_name: str):
    """Removes any webhook events seeded by a test, before and after each test."""
    def _purge() -> None:
        database_manager.get_collection(CmdbWebhookEvent.COLLECTION, database_name)\
            .delete_many({'public_id': {'$in': ALL_EVENT_IDS}})

    _purge()
    yield
    _purge()


def _insert_event(database_manager: MongoDatabaseManager, database_name: str, public_id: int) -> None:
    """Inserts a CmdbWebhookEvent doc directly via the collection."""
    database_manager.get_collection(CmdbWebhookEvent.COLLECTION, database_name).insert_one(_event_doc(public_id))


class TestGetWebhookEvent:
    """GET single + list."""

    def test_get_single_returns_event(self, rest_api,
                                     database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A seeded id returns 200."""
        _insert_event(database_manager, database_name, EVENT_ID_FOR_GET)

        assert rest_api.get(f'{ROUTE_URL}/{EVENT_ID_FOR_GET}').status_code == HTTPStatus.OK

    def test_get_single_missing_returns_404(self, rest_api) -> None:
        """A missing id returns 404."""
        assert rest_api.get(f'{ROUTE_URL}/{MISSING_EVENT_ID}').status_code == HTTPStatus.NOT_FOUND

    def test_get_list_returns_results_envelope(self, rest_api,
                                              database_manager: MongoDatabaseManager, database_name: str) -> None:
        """GET /webhook_events/ returns a results envelope whose length matches X-Total-Count."""
        _insert_event(database_manager, database_name, EVENT_ID_FOR_GET)

        response = rest_api.get(f'{ROUTE_URL}/')

        assert response.status_code == HTTPStatus.OK
        body = response.get_json()
        assert len(body['results']) == int(response.headers['X-Total-Count'])


class TestDeleteWebhookEvent:
    """DELETE /webhook_events/<id>/ removes an event."""

    def test_delete_removes_event(self, rest_api,
                                 database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A DELETE succeeds and a subsequent GET returns 404."""
        _insert_event(database_manager, database_name, EVENT_ID_FOR_DELETE)

        response = rest_api.delete(f'{ROUTE_URL}/{EVENT_ID_FOR_DELETE}/')

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
        assert rest_api.get(f'{ROUTE_URL}/{EVENT_ID_FOR_DELETE}').status_code == HTTPStatus.NOT_FOUND

    def test_delete_missing_returns_404(self, rest_api) -> None:
        """Deleting a non-existent event returns 404."""
        assert rest_api.delete(f'{ROUTE_URL}/{MISSING_EVENT_ID}/').status_code == HTTPStatus.NOT_FOUND


def _raiser(exc: Exception):
    """Returns a function that ignores its args and raises the given exception."""
    def _fail(*_args, **_kwargs):
        raise exc
    return _fail


class TestErrorMapping:
    """The routes map manager failures to the documented HTTP statuses."""

    def test_get_single_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A WebhooksEventManagerGetError on get-single surfaces as 400."""
        monkeypatch.setattr(WebhooksEventManager, 'get_item', _raiser(WebhooksEventManagerGetError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/{EVENT_ID_FOR_GET}').status_code == HTTPStatus.BAD_REQUEST

    def test_list_iteration_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A WebhooksEventManagerIterationError on list surfaces as 400."""
        monkeypatch.setattr(WebhooksEventManager, 'iterate_items', _raiser(WebhooksEventManagerIterationError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/').status_code == HTTPStatus.BAD_REQUEST

    def test_list_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error on list surfaces as 500."""
        monkeypatch.setattr(WebhooksEventManager, 'iterate_items', _raiser(RuntimeError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/').status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_delete_error_returns_400(self, rest_api, monkeypatch,
                                     database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A WebhooksEventManagerDeleteError on delete surfaces as 400."""
        _insert_event(database_manager, database_name, EVENT_ID_FOR_DELETE)
        monkeypatch.setattr(WebhooksEventManager, 'delete_item', _raiser(WebhooksEventManagerDeleteError('boom')))

        assert rest_api.delete(f'{ROUTE_URL}/{EVENT_ID_FOR_DELETE}/').status_code == HTTPStatus.BAD_REQUEST
