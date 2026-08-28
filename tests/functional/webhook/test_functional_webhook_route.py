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

Since 2026-08-27 also: the write-route VALIDATION, which is the whole guard a webhook document gets
because ``CmdbWebhook.SCHEMA`` is never applied - a missing name or url, a non-http(s) or host-less
url, and an event_types that is not a non-empty list of known WebhookEventType values are all 400 now
(each of them used to be a 200 that stored an unusable webhook). Plus the DELETE route without its
odd trailing slash, and the per-route error tails that no test reached.
"""
from http import HTTPStatus
from typing import Any
from urllib.parse import urlencode
import json

import pytest
from werkzeug.exceptions import NotFound

from cmdb.database import MongoDatabaseManager
from cmdb.manager.webhooks_manager import WebhooksManager
from cmdb.models.webhook_model.cmdb_webhook_model import CmdbWebhook
from cmdb.errors.manager.webhooks_manager import (
    WebhooksManagerInsertError,
    WebhooksManagerGetError,
    WebhooksManagerUpdateError,
    WebhooksManagerDeleteError,
    WebhooksManagerIterationError,
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
    """DELETE /webhooks/<id> removes a webhook."""

    def test_delete_removes_webhook(self, rest_api,
                                   database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A DELETE succeeds and a subsequent GET returns 404."""
        _insert_webhook(database_manager, database_name, WEBHOOK_ID_FOR_DELETE)

        response = rest_api.delete(f'{ROUTE_URL}/{WEBHOOK_ID_FOR_DELETE}')

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
        assert rest_api.get(f'{ROUTE_URL}/{WEBHOOK_ID_FOR_DELETE}').status_code == HTTPStatus.NOT_FOUND

    def test_delete_missing_returns_404(self, rest_api) -> None:
        """Deleting a non-existent webhook returns 404."""
        assert rest_api.delete(f'{ROUTE_URL}/{MISSING_WEBHOOK_ID}').status_code == HTTPStatus.NOT_FOUND

    def test_delete_needs_no_trailing_slash(self, rest_api,
                                           database_manager: MongoDatabaseManager,
                                           database_name: str) -> None:
        """
        The slash-less form is served directly, not via a redirect (regression)

        The route used to be registered as ``/<public_id>/`` while its GET/PUT siblings had no slash,
        so the frontend's slash-less DELETE (webhook.service.ts) took a 308 first.
        """
        _insert_webhook(database_manager, database_name, WEBHOOK_ID_FOR_DELETE)

        response = rest_api.delete(f'{ROUTE_URL}/{WEBHOOK_ID_FOR_DELETE}')

        assert response.status_code != HTTPStatus.PERMANENT_REDIRECT
        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)


def _raiser(exc: Exception):
    """Returns a function that ignores its args and raises the given exception."""
    def _fail(*_args, **_kwargs):
        raise exc
    return _fail


class TestErrorMapping:
    """The routes map manager failures to the documented HTTP statuses."""

    def test_create_insert_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A WebhooksManagerInsertError on create surfaces as 400."""
        monkeypatch.setattr(WebhooksManager, 'insert_item', _raiser(WebhooksManagerInsertError('boom')))

        assert rest_api.post(f'{ROUTE_URL}/?{_webhook_query()}').status_code == HTTPStatus.BAD_REQUEST

    def test_create_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error on create surfaces as 500."""
        monkeypatch.setattr(WebhooksManager, 'insert_item', _raiser(RuntimeError('boom')))

        assert rest_api.post(f'{ROUTE_URL}/?{_webhook_query()}').status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_get_single_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A WebhooksManagerGetError on get-single surfaces as 400."""
        monkeypatch.setattr(WebhooksManager, 'get_item', _raiser(WebhooksManagerGetError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/{WEBHOOK_ID_FOR_GET}').status_code == HTTPStatus.BAD_REQUEST

    def test_list_iteration_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A WebhooksManagerIterationError on list surfaces as 400."""
        monkeypatch.setattr(WebhooksManager, 'iterate_items', _raiser(WebhooksManagerIterationError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/').status_code == HTTPStatus.BAD_REQUEST

    def test_list_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error on list surfaces as 500."""
        monkeypatch.setattr(WebhooksManager, 'iterate_items', _raiser(RuntimeError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/').status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_update_error_returns_400(self, rest_api, monkeypatch,
                                     database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A WebhooksManagerUpdateError on update surfaces as 400."""
        _insert_webhook(database_manager, database_name, WEBHOOK_ID_FOR_UPDATE)
        monkeypatch.setattr(WebhooksManager, 'update_item', _raiser(WebhooksManagerUpdateError('boom')))

        assert rest_api.put(f'{ROUTE_URL}/{WEBHOOK_ID_FOR_UPDATE}?{_webhook_query()}').status_code \
            == HTTPStatus.BAD_REQUEST

    def test_delete_error_returns_400(self, rest_api, monkeypatch,
                                     database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A WebhooksManagerDeleteError on delete surfaces as 400."""
        _insert_webhook(database_manager, database_name, WEBHOOK_ID_FOR_DELETE)
        monkeypatch.setattr(WebhooksManager, 'delete_item', _raiser(WebhooksManagerDeleteError('boom')))

        assert rest_api.delete(f'{ROUTE_URL}/{WEBHOOK_ID_FOR_DELETE}').status_code == HTTPStatus.BAD_REQUEST


class TestCreateValidation:
    """
    parse_webhook_params is the only validation a CmdbWebhook document gets

    The routes read query args, so ``CmdbWebhook.SCHEMA`` - which marks name, url and event_types
    required - never runs. Every case below was a 200 that stored an unusable webhook.
    """

    def test_missing_name_returns_400(self, rest_api) -> None:
        """A webhook with no name is refused instead of being stored with name=None."""
        query = urlencode({'url': 'http://example.test/hook', 'event_types': "['CREATE']", 'active': 'true'})

        assert rest_api.post(f'{ROUTE_URL}/?{query}').status_code == HTTPStatus.BAD_REQUEST

    def test_blank_name_returns_400(self, rest_api) -> None:
        """Whitespace is not a name."""
        assert rest_api.post(f'{ROUTE_URL}/?{_webhook_query(name="   ")}').status_code == HTTPStatus.BAD_REQUEST

    def test_missing_url_returns_400(self, rest_api) -> None:
        """A webhook with no target URL would fail every delivery, so it is refused."""
        query = urlencode({'name': 'Hook', 'event_types': "['CREATE']", 'active': 'true'})

        assert rest_api.post(f'{ROUTE_URL}/?{query}').status_code == HTTPStatus.BAD_REQUEST

    @pytest.mark.parametrize('url', ['file:///etc/passwd', 'ftp://example.test/hook', 'not-a-url',
                                     'http://', ''], ids=['file', 'ftp', 'no-scheme', 'no-host', 'empty'])
    def test_unusable_url_returns_400(self, rest_api, url: str) -> None:
        """The server fetches this URL itself, so the scheme and the host are checked."""
        assert rest_api.post(f'{ROUTE_URL}/?{_webhook_query(url=url)}').status_code == HTTPStatus.BAD_REQUEST

    def test_https_url_is_accepted(self, rest_api) -> None:
        """
        https is allowed alongside http - the guard must not reject valid targets

        Created under CREATE_NAME so the module's autouse cleanup purges it.
        """
        response = rest_api.post(f'{ROUTE_URL}/?{_webhook_query(name=CREATE_NAME, url="https://example.test/h")}')

        assert response.status_code == HTTPStatus.OK

    @pytest.mark.parametrize('event_types', ['42', "'CREATE'", '[]', "{'a': 1}", "['NOT_AN_EVENT']",
                                             "['CREATE', 'NOPE']"],
                             ids=['int', 'bare-string', 'empty-list', 'dict', 'unknown', 'one-unknown'])
    def test_event_types_that_are_not_a_known_list_return_400(self, rest_api, event_types: str) -> None:
        """
        literal_eval alone accepted any literal

        An int or a dict was stored as-is and an unknown name was stored verbatim; either way the
        webhook could never match the manager's ``{'event_types': operation}`` filter, so it looked
        active in the UI and silently never fired.
        """
        query = _webhook_query(name='Bad types', event_types=event_types)

        assert rest_api.post(f'{ROUTE_URL}/?{query}').status_code == HTTPStatus.BAD_REQUEST

    def test_json_list_of_known_types_is_accepted(self, rest_api) -> None:
        """The frontend sends JSON.stringify(array), i.e. double-quoted names - that must keep working."""
        query = _webhook_query(name=CREATE_NAME, event_types='["CREATE", "UPDATE"]')

        assert rest_api.post(f'{ROUTE_URL}/?{query}').status_code == HTTPStatus.OK

    def test_update_validates_the_same_way(self, rest_api, database_manager: MongoDatabaseManager,
                                           database_name: str) -> None:
        """The update route shares the guard, so it can not turn a valid webhook into an unusable one."""
        _insert_webhook(database_manager, database_name, WEBHOOK_ID_FOR_UPDATE)
        query = _webhook_query(url='file:///etc/passwd')

        response = rest_api.put(f'{ROUTE_URL}/{WEBHOOK_ID_FOR_UPDATE}?{query}')

        assert response.status_code == HTTPStatus.BAD_REQUEST
        stored = database_manager.get_collection(CmdbWebhook.COLLECTION, database_name)\
            .find_one({'public_id': WEBHOOK_ID_FOR_UPDATE})
        assert stored['url'] == 'http://example.test/hook'


class TestUnexpectedErrorMapping:
    """Each route reports an error it does not map as a 500 rather than letting it escape."""

    def test_get_single_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unmapped failure while reading one webhook."""
        monkeypatch.setattr(WebhooksManager, 'get_item', _raiser(RuntimeError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/{MISSING_WEBHOOK_ID}').status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_update_get_error_returns_400(self, rest_api, monkeypatch) -> None:
        """The update route reads the webhook first, so a read failure has its own arm there."""
        monkeypatch.setattr(WebhooksManager, 'get_item', _raiser(WebhooksManagerGetError('boom')))

        response = rest_api.put(f'{ROUTE_URL}/{MISSING_WEBHOOK_ID}?{_webhook_query()}')

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_update_unexpected_error_returns_500(self, rest_api, monkeypatch,
                                                 database_manager: MongoDatabaseManager,
                                                 database_name: str) -> None:
        """An unmapped failure while writing the update."""
        _insert_webhook(database_manager, database_name, WEBHOOK_ID_FOR_UPDATE)
        monkeypatch.setattr(WebhooksManager, 'update_item', _raiser(RuntimeError('boom')))

        response = rest_api.put(f'{ROUTE_URL}/{WEBHOOK_ID_FOR_UPDATE}?{_webhook_query()}')

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_delete_get_error_returns_400(self, rest_api, monkeypatch) -> None:
        """The delete route reads the webhook before removing it, so the read can fail there too."""
        monkeypatch.setattr(WebhooksManager, 'get_item', _raiser(WebhooksManagerGetError('boom')))

        assert rest_api.delete(f'{ROUTE_URL}/{MISSING_WEBHOOK_ID}').status_code == HTTPStatus.BAD_REQUEST

    def test_delete_unexpected_error_returns_500(self, rest_api, monkeypatch,
                                                 database_manager: MongoDatabaseManager,
                                                 database_name: str) -> None:
        """An unmapped failure while deleting a webhook that was found."""
        _insert_webhook(database_manager, database_name, WEBHOOK_ID_FOR_DELETE)
        monkeypatch.setattr(WebhooksManager, 'delete_item', _raiser(RuntimeError('boom')))

        assert rest_api.delete(f'{ROUTE_URL}/{WEBHOOK_ID_FOR_DELETE}').status_code \
            == HTTPStatus.INTERNAL_SERVER_ERROR


class TestHttpExceptionPassThrough:
    """An HTTPException raised inside a route keeps its own status instead of becoming a 500."""

    def test_list_keeps_the_status(self, rest_api, monkeypatch) -> None:
        """The list route had no re-raise arm, so an abort inside it would have become a 500."""
        monkeypatch.setattr(WebhooksManager, 'iterate_items', _raiser(NotFound()))

        assert rest_api.get(f'{ROUTE_URL}/').status_code == HTTPStatus.NOT_FOUND


class TestUpdateResponseShape:
    """The update response is built from the written instance rather than read back."""

    def test_response_matches_the_stored_document(self, rest_api,
                                                  database_manager: MongoDatabaseManager,
                                                  database_name: str) -> None:
        """
        Dropping the read-back must not change the payload

        The response is now CmdbWebhook.to_json(instance); update_item stores exactly that, so the
        body and the stored document have to agree key for key.
        """
        _insert_webhook(database_manager, database_name, WEBHOOK_ID_FOR_UPDATE)
        query = _webhook_query(name='Renamed', url='https://example.test/new')

        response = rest_api.put(f'{ROUTE_URL}/{WEBHOOK_ID_FOR_UPDATE}?{query}')

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
        stored = database_manager.get_collection(CmdbWebhook.COLLECTION, database_name)\
            .find_one({'public_id': WEBHOOK_ID_FOR_UPDATE}, {'_id': 0})
        body = response.get_json()
        payload = body.get('result', body) if isinstance(body, dict) else body
        assert payload == stored

class TestFrontendContract:
    """
    Replays the exact request shapes ``app/src/app/toolbox/webhook/services/webhook.service.ts`` builds

    The 2026-08-27 sweep added validation to the write routes and moved the DELETE route off its
    trailing slash, so what the frontend actually sends is pinned here rather than reasoned about. The
    Angular form (``webhook-form.component.ts``) validates more strictly than the backend does - its
    url pattern demands a dotted host - so every payload it can produce has to be accepted.
    """

    @staticmethod
    def _frontend_params(**overrides: Any) -> str:
        """
        Builds a query string the way the Angular service does

        It walks the webhook object and JSON.stringify()s any non-primitive, so ``event_types`` arrives
        double-quoted and ``active`` as the string 'true'/'false'.
        """
        payload: dict[str, Any] = {
            'name': CREATE_NAME,
            'url': 'http://example.test/hook',
            'event_types': json.dumps(['CREATE', 'UPDATE', 'DELETE']),
            'active': 'true',
        }
        payload.update(overrides)

        return urlencode(payload)

    def test_create_as_the_frontend_sends_it(self, rest_api) -> None:
        """POST webhooks/ with the FE's query params (it also sends a body, which the route ignores)."""
        response = rest_api.post(f'{ROUTE_URL}/?{self._frontend_params()}',
                                 json={'name': CREATE_NAME, 'url': 'http://example.test/hook',
                                       'event_types': ['CREATE'], 'active': True})

        assert response.status_code == HTTPStatus.OK

    def test_create_with_an_inactive_webhook(self, rest_api) -> None:
        """active='false' is accepted and is not mistaken for a missing value."""
        response = rest_api.post(f'{ROUTE_URL}/?{self._frontend_params(active="false")}')

        assert response.status_code == HTTPStatus.OK

    def test_list_as_the_frontend_sends_it(self, rest_api) -> None:
        """GET webhooks/ with the FE's pager params."""
        query = urlencode({'limit': '10', 'sort': 'public_id', 'order': '1', 'page': '1'})

        assert rest_api.get(f'{ROUTE_URL}/?{query}').status_code == HTTPStatus.OK

    def test_get_single_as_the_frontend_sends_it(self, rest_api, database_manager: MongoDatabaseManager,
                                                database_name: str) -> None:
        """GET webhooks/<id> - no trailing slash."""
        _insert_webhook(database_manager, database_name, WEBHOOK_ID_FOR_GET)

        assert rest_api.get(f'{ROUTE_URL}/{WEBHOOK_ID_FOR_GET}').status_code == HTTPStatus.OK

    def test_update_as_the_frontend_sends_it(self, rest_api, database_manager: MongoDatabaseManager,
                                            database_name: str) -> None:
        """PUT webhooks/<id> with the params in the query AND the body, as the service does."""
        _insert_webhook(database_manager, database_name, WEBHOOK_ID_FOR_UPDATE)
        query = self._frontend_params(name='Renamed', public_id=str(WEBHOOK_ID_FOR_UPDATE))

        response = rest_api.put(f'{ROUTE_URL}/{WEBHOOK_ID_FOR_UPDATE}?{query}',
                                json={'public_id': WEBHOOK_ID_FOR_UPDATE, 'name': 'Renamed',
                                      'url': 'http://example.test/hook',
                                      'event_types': ['CREATE'], 'active': True})

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)

    def test_delete_as_the_frontend_sends_it(self, rest_api, database_manager: MongoDatabaseManager,
                                            database_name: str) -> None:
        """
        DELETE webhooks/<id> - the FE never sends the trailing slash

        This is the call that used to take a 308 first, because the route carried a slash its siblings
        did not.
        """
        _insert_webhook(database_manager, database_name, WEBHOOK_ID_FOR_DELETE)

        response = rest_api.delete(f'{ROUTE_URL}/{WEBHOOK_ID_FOR_DELETE}')

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)

    @pytest.mark.parametrize('url', ['http://example.test/hook', 'https://example.test/hook',
                                     'https://sub.example.co.uk', 'http://example.test/a/b?c=d'])
    def test_every_url_the_frontend_pattern_allows_is_accepted(self, rest_api, url: str) -> None:
        """
        The backend guard must not be stricter than the FE's url pattern

        ``webhook-form.component.ts`` allows ^https?://<dotted-host>(/...)?$ - all of which must pass
        the scheme + host check added by this sweep.
        """
        assert rest_api.post(f'{ROUTE_URL}/?{self._frontend_params(url=url)}').status_code == HTTPStatus.OK
