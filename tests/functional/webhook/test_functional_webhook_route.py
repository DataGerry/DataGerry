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
Functional smoke for the ``/webhooks`` REST routes

Covers CRUD over the GenericManager-backed WebhooksManager: HTTP status codes, the query-param
event_types parsing (400 on missing/invalid), the 404 on a missing id, the manager-error -> 400 / 500
mappings, and the public_id pinning on update. Params arrive as query args (parse_request_parameters).
"""
from http import HTTPStatus
from typing import Any
from urllib.parse import urlencode

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.webhooks_manager import WebhooksManager
from cmdb.models.webhook_model.cmdb_webhook_model import CmdbWebhook
from cmdb.errors.manager import (
    BaseManagerInsertError,
    BaseManagerGetError,
    BaseManagerUpdateError,
    BaseManagerDeleteError,
    BaseManagerIterationError,
)
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_URL: str = '/webhooks'

WEBHOOK_ID_FOR_GET: int = 97801
WEBHOOK_ID_FOR_UPDATE: int = 97802
WEBHOOK_ID_FOR_DELETE: int = 97803
MISSING_WEBHOOK_ID: int = 97899

ALL_WEBHOOK_IDS: list[int] = [WEBHOOK_ID_FOR_GET, WEBHOOK_ID_FOR_UPDATE, WEBHOOK_ID_FOR_DELETE]
CREATE_NAME: str = 'Created Webhook'


def _webhook_query(name: str = 'Hook', url: str = 'http://example.test/hook',
                   event_types: str = "['CREATE']", active: str = 'true') -> str:
    """Builds the query string the create/update routes parse (event_types is a Python-literal string)."""
    return urlencode({'name': name, 'url': url, 'event_types': event_types, 'active': active})


def _webhook_doc(public_id: int, name: str = 'Hook') -> dict[str, Any]:
    """Builds a CmdbWebhook document for direct insertion."""
    return {'public_id': public_id, 'name': name, 'url': 'http://example.test/hook',
            'event_types': ['CREATE', 'UPDATE'], 'active': True}


@pytest.fixture(autouse=True)
def _cleanup(database_manager: MongoDatabaseManager, database_name: str):
    """Removes any webhooks seeded by a test, before and after each test."""
    def _purge() -> None:
        database_manager.get_collection(CmdbWebhook.COLLECTION, database_name)\
            .delete_many({'public_id': {'$in': ALL_WEBHOOK_IDS}})
        database_manager.get_collection(CmdbWebhook.COLLECTION, database_name)\
            .delete_many({'name': CREATE_NAME})

    _purge()
    yield
    _purge()


def _insert_webhook(database_manager: MongoDatabaseManager, database_name: str, public_id: int) -> None:
    """Inserts a CmdbWebhook doc directly via the collection."""
    database_manager.get_collection(CmdbWebhook.COLLECTION, database_name).insert_one(_webhook_doc(public_id))


class TestCreateWebhook:
    """POST /webhooks/ creates a CmdbWebhook from query params."""

    def test_creates_webhook(self, rest_api, database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A POST with valid params succeeds and the webhook is persisted."""
        response = rest_api.post(f'{ROUTE_URL}/?{_webhook_query(name=CREATE_NAME)}')

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.CREATED)
        assert database_manager.get_collection(CmdbWebhook.COLLECTION, database_name)\
            .find_one({'name': CREATE_NAME}) is not None

    def test_missing_event_types_returns_400(self, rest_api) -> None:
        """A POST without event_types is rejected with 400."""
        query = urlencode({'name': 'X', 'url': 'http://x', 'active': 'true'})

        assert rest_api.post(f'{ROUTE_URL}/?{query}').status_code == HTTPStatus.BAD_REQUEST

    def test_invalid_event_types_returns_400(self, rest_api) -> None:
        """A POST whose event_types is not a valid Python literal is rejected with 400."""
        assert rest_api.post(f'{ROUTE_URL}/?{_webhook_query(event_types="not-a-list")}').status_code \
            == HTTPStatus.BAD_REQUEST


class TestGetWebhook:
    """GET single + list."""

    def test_get_single_returns_webhook(self, rest_api,
                                       database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A seeded id returns 200 with the matching webhook."""
        _insert_webhook(database_manager, database_name, WEBHOOK_ID_FOR_GET)

        response = rest_api.get(f'{ROUTE_URL}/{WEBHOOK_ID_FOR_GET}')

        assert response.status_code == HTTPStatus.OK

    def test_get_single_missing_returns_404(self, rest_api) -> None:
        """A missing id returns 404."""
        assert rest_api.get(f'{ROUTE_URL}/{MISSING_WEBHOOK_ID}').status_code == HTTPStatus.NOT_FOUND

    def test_get_list_returns_results_envelope(self, rest_api,
                                              database_manager: MongoDatabaseManager, database_name: str) -> None:
        """GET /webhooks/ returns a results envelope whose length matches X-Total-Count."""
        _insert_webhook(database_manager, database_name, WEBHOOK_ID_FOR_GET)

        response = rest_api.get(f'{ROUTE_URL}/')

        assert response.status_code == HTTPStatus.OK
        body = response.get_json()
        assert len(body['results']) == int(response.headers['X-Total-Count'])


class TestUpdateWebhook:
    """PUT/PATCH /webhooks/<id> updates a webhook and pins its identity to the URL."""

    def test_update_persists_name(self, rest_api,
                                 database_manager: MongoDatabaseManager, database_name: str) -> None:
        """After PUT, the stored webhook reflects the new name."""
        _insert_webhook(database_manager, database_name, WEBHOOK_ID_FOR_UPDATE)

        response = rest_api.put(f'{ROUTE_URL}/{WEBHOOK_ID_FOR_UPDATE}?{_webhook_query(name="Renamed")}')

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
        stored = database_manager.get_collection(CmdbWebhook.COLLECTION, database_name)\
            .find_one({'public_id': WEBHOOK_ID_FOR_UPDATE})
        assert stored['name'] == 'Renamed'

    def test_update_pins_public_id_to_url(self, rest_api,
                                        database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A body public_id different from the URL is ignored (identity stays the URL id)."""
        _insert_webhook(database_manager, database_name, WEBHOOK_ID_FOR_UPDATE)
        query = _webhook_query(name='Pinned') + f'&public_id={MISSING_WEBHOOK_ID}'

        response = rest_api.put(f'{ROUTE_URL}/{WEBHOOK_ID_FOR_UPDATE}?{query}')

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
        collection = database_manager.get_collection(CmdbWebhook.COLLECTION, database_name)
        assert collection.find_one({'public_id': WEBHOOK_ID_FOR_UPDATE})['name'] == 'Pinned'
        assert collection.find_one({'public_id': MISSING_WEBHOOK_ID}) is None

    def test_update_missing_returns_404(self, rest_api) -> None:
        """Updating a non-existent webhook returns 404."""
        assert rest_api.put(f'{ROUTE_URL}/{MISSING_WEBHOOK_ID}?{_webhook_query()}').status_code \
            == HTTPStatus.NOT_FOUND


class TestDeleteWebhook:
    """DELETE /webhooks/<id>/ removes a webhook."""

    def test_delete_removes_webhook(self, rest_api,
                                   database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A DELETE succeeds and a subsequent GET returns 404."""
        _insert_webhook(database_manager, database_name, WEBHOOK_ID_FOR_DELETE)

        response = rest_api.delete(f'{ROUTE_URL}/{WEBHOOK_ID_FOR_DELETE}/')

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
        assert rest_api.get(f'{ROUTE_URL}/{WEBHOOK_ID_FOR_DELETE}').status_code == HTTPStatus.NOT_FOUND

    def test_delete_missing_returns_404(self, rest_api) -> None:
        """Deleting a non-existent webhook returns 404."""
        assert rest_api.delete(f'{ROUTE_URL}/{MISSING_WEBHOOK_ID}/').status_code == HTTPStatus.NOT_FOUND


def _raiser(exc: Exception):
    """Returns a function that ignores its args and raises the given exception."""
    def _fail(*_args, **_kwargs):
        raise exc
    return _fail


class TestErrorMapping:
    """The routes map manager failures to the documented HTTP statuses."""

    def test_create_insert_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A BaseManagerInsertError on create surfaces as 400."""
        monkeypatch.setattr(WebhooksManager, 'insert_item', _raiser(BaseManagerInsertError('boom')))

        assert rest_api.post(f'{ROUTE_URL}/?{_webhook_query()}').status_code == HTTPStatus.BAD_REQUEST

    def test_create_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error on create surfaces as 500."""
        monkeypatch.setattr(WebhooksManager, 'insert_item', _raiser(RuntimeError('boom')))

        assert rest_api.post(f'{ROUTE_URL}/?{_webhook_query()}').status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_get_single_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A BaseManagerGetError on get-single surfaces as 400."""
        monkeypatch.setattr(WebhooksManager, 'get_item', _raiser(BaseManagerGetError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/{WEBHOOK_ID_FOR_GET}').status_code == HTTPStatus.BAD_REQUEST

    def test_list_iteration_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A BaseManagerIterationError on list surfaces as 400."""
        monkeypatch.setattr(WebhooksManager, 'iterate_items', _raiser(BaseManagerIterationError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/').status_code == HTTPStatus.BAD_REQUEST

    def test_list_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error on list surfaces as 500."""
        monkeypatch.setattr(WebhooksManager, 'iterate_items', _raiser(RuntimeError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/').status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_update_error_returns_400(self, rest_api, monkeypatch,
                                     database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A BaseManagerUpdateError on update surfaces as 400."""
        _insert_webhook(database_manager, database_name, WEBHOOK_ID_FOR_UPDATE)
        monkeypatch.setattr(WebhooksManager, 'update_item', _raiser(BaseManagerUpdateError('boom')))

        assert rest_api.put(f'{ROUTE_URL}/{WEBHOOK_ID_FOR_UPDATE}?{_webhook_query()}').status_code \
            == HTTPStatus.BAD_REQUEST

    def test_delete_error_returns_400(self, rest_api, monkeypatch,
                                     database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A BaseManagerDeleteError on delete surfaces as 400."""
        _insert_webhook(database_manager, database_name, WEBHOOK_ID_FOR_DELETE)
        monkeypatch.setattr(WebhooksManager, 'delete_item', _raiser(BaseManagerDeleteError('boom')))

        assert rest_api.delete(f'{ROUTE_URL}/{WEBHOOK_ID_FOR_DELETE}/').status_code == HTTPStatus.BAD_REQUEST
