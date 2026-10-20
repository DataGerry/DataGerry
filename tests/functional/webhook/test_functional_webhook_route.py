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

Covers CRUD over the GenericManager-backed WebhooksManager: HTTP status codes, the 404 on a missing
id, the manager-error -> 400 / 500 mappings, and the public_id pinning on update.

The write routes read their payload from the JSON body, and a key the body leaves out from the query
string (``read_write_payload``). Both halves are covered: the body classes below, and the query-string
tests, which are the fallback a query-only client still gets.

Also covered: the write-route VALIDATION (``parse_webhook_params``, which ends by holding the document
against ``CmdbWebhook.SCHEMA``) - a missing name or url, a non-http(s) or host-less url, an
event_types that is not a non-empty list of known WebhookEventType values and an unreadable active
flag are all 400, and a missing active flag is stored as True. Plus the DELETE route without a
trailing slash, and the per-route error tails.
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
from cmdb.interface.rest_api.routes.routes_helper import WRITE_PAYLOAD_NOT_AN_OBJECT_MSG
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
# The seeded test user: every write route makes the caller the webhook's owner
ADMIN_USER_ID: int = 1

ALL_WEBHOOK_IDS: list[int] = [WEBHOOK_ID_FOR_GET, WEBHOOK_ID_FOR_UPDATE, WEBHOOK_ID_FOR_DELETE]
CREATE_NAME: str = 'Created Webhook'


def _webhook_query(name: str = 'Hook', url: str = 'http://example.test/hook',
                   event_types: str = "['CREATE']", active: str = 'true') -> str:
    """Builds the query string the create/update routes parse (event_types is a Python-literal string)."""
    return urlencode({'name': name, 'url': url, 'event_types': event_types, 'active': active})


def _webhook_body(name: str = CREATE_NAME, **overrides: Any) -> dict[str, Any]:
    """Builds a typed JSON body for the create/update routes (event_types a list, active a bool)."""
    body: dict[str, Any] = {'name': name, 'url': 'http://example.test/hook', 'event_types': ['CREATE'],
                            'active': True}
    body.update(overrides)

    return body


def _stored_by_name(database_manager: MongoDatabaseManager, database_name: str,
                    name: str = CREATE_NAME) -> dict[str, Any] | None:
    """Reads a stored webhook back by its name, without the Mongo _id."""
    return database_manager.get_collection(CmdbWebhook.COLLECTION, database_name).find_one({'name': name},
                                                                                           {'_id': 0})


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
    """POST /webhooks/ creates a CmdbWebhook - here from query params alone, the fallback."""

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
        The slash-less form is served directly, not via a redirect

        Registering the route as ``/<public_id>/`` while its GET/PUT siblings carry no slash
        would make the frontend's slash-less DELETE (webhook.service.ts) take a 308 first.
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
    parse_webhook_params validates a CmdbWebhook write, sent here as query params

    Without it, every case below is a 200 that stores an unusable webhook. The same rules for a JSON
    body are in TestBodyPayload and in the helper's unit tests.
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
        literal_eval alone accepts any literal

        An int or a dict stored as-is, or an unknown name stored verbatim, could never match the
        manager's ``{'event_types': operation}`` filter, so the webhook would look active in the UI and
        silently never fire.
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
        The response is built without a read-back and still matches the stored document

        The response is CmdbWebhook.to_json(instance); update_item stores exactly that, so the
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

    The write routes carry validation and the DELETE route has no
    trailing slash, so what the frontend actually sends is replayed here rather than reasoned about. The
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

    def test_create_as_the_frontend_sends_it(self, rest_api, database_manager: MongoDatabaseManager,
                                             database_name: str) -> None:
        """POST webhooks/ with the FE's query params AND its body - the body is what is stored"""
        response = rest_api.post(f'{ROUTE_URL}/?{self._frontend_params()}', json=_webhook_body())

        assert response.status_code == HTTPStatus.OK
        assert _stored_by_name(database_manager, database_name)['event_types'] == ['CREATE']

    def test_create_with_an_inactive_webhook(self, rest_api, database_manager: MongoDatabaseManager,
                                             database_name: str) -> None:
        """active false is accepted and is not mistaken for a missing value, in either half"""
        response = rest_api.post(f'{ROUTE_URL}/?{self._frontend_params(active="false")}',
                                 json=_webhook_body(active=False))

        assert response.status_code == HTTPStatus.OK
        assert _stored_by_name(database_manager, database_name)['active'] is False

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
        """PUT webhooks/<id> with the params in the query AND the body, as the service does - body wins"""
        _insert_webhook(database_manager, database_name, WEBHOOK_ID_FOR_UPDATE)
        query = self._frontend_params(name='Renamed', public_id=str(WEBHOOK_ID_FOR_UPDATE))

        response = rest_api.put(f'{ROUTE_URL}/{WEBHOOK_ID_FOR_UPDATE}?{query}',
                                json={'public_id': WEBHOOK_ID_FOR_UPDATE, 'name': 'Renamed',
                                      'url': 'http://example.test/hook',
                                      'event_types': ['CREATE'], 'active': True})

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
        stored = database_manager.get_collection(CmdbWebhook.COLLECTION, database_name)\
            .find_one({'public_id': WEBHOOK_ID_FOR_UPDATE})
        assert stored['event_types'] == ['CREATE']

    def test_delete_as_the_frontend_sends_it(self, rest_api, database_manager: MongoDatabaseManager,
                                            database_name: str) -> None:
        """
        DELETE webhooks/<id> - the FE never sends the trailing slash

        This is the call that would take a 308 first if the route carried a slash its siblings
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
        the backend's scheme + host check.
        """
        assert rest_api.post(f'{ROUTE_URL}/?{self._frontend_params(url=url)}').status_code == HTTPStatus.OK


class TestBodyPayload:
    """The write routes read the JSON body, and the query string only for a key the body leaves out."""

    def test_create_from_the_body_alone_stores_the_typed_document(
            self, rest_api, database_manager: MongoDatabaseManager, database_name: str) -> None:
        """No query string at all: the body is the whole payload, stored as sent"""
        body = _webhook_body(event_types=['CREATE', 'DELETE'], active=False)

        response = rest_api.post(f'{ROUTE_URL}/', json=body)

        assert response.status_code == HTTPStatus.OK
        stored = _stored_by_name(database_manager, database_name)
        assert stored == {**body, 'public_id': response.get_json(), 'owner_id': ADMIN_USER_ID}

    def test_the_body_wins_over_the_query_string_key_by_key(
            self, rest_api, database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A key in both halves is read from the body; a key only in the query string still counts"""
        query = urlencode({'name': 'From query', 'url': 'https://query.test/hook', 'event_types': "['UPDATE']"})

        response = rest_api.post(f'{ROUTE_URL}/?{query}', json={'name': CREATE_NAME, 'event_types': ['DELETE']})

        assert response.status_code == HTTPStatus.OK
        stored = _stored_by_name(database_manager, database_name)
        assert stored['event_types'] == ['DELETE']
        assert stored['url'] == 'https://query.test/hook'

    @pytest.mark.parametrize('body', [['CREATE'], 'text', 7], ids=['list', 'string', 'number'])
    def test_a_body_that_is_not_an_object_is_a_400(self, rest_api, body: Any) -> None:
        """It was meant as the payload, so it is refused rather than silently replaced by the query"""
        response = rest_api.post(f'{ROUTE_URL}/?{_webhook_query(name=CREATE_NAME)}', json=body)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'] == WRITE_PAYLOAD_NOT_AN_OBJECT_MSG.format(entity='Webhook')

    def test_a_client_public_id_on_create_is_ignored(
            self, rest_api, database_manager: MongoDatabaseManager, database_name: str) -> None:
        """The id is reserved from the counter; a body can not choose it"""
        response = rest_api.post(f'{ROUTE_URL}/', json=_webhook_body(public_id=MISSING_WEBHOOK_ID))

        assert response.status_code == HTTPStatus.OK
        assert response.get_json() != MISSING_WEBHOOK_ID
        assert database_manager.get_collection(CmdbWebhook.COLLECTION, database_name)\
            .find_one({'public_id': MISSING_WEBHOOK_ID}) is None

    @pytest.mark.parametrize('overrides', [
        {'name': 5}, {'url': ['http://example.test/hook']}, {'event_types': 'CREATE'},
        {'event_types': ['CREATE', 'NOPE']}, {'event_types': []}, {'url': 'ftp://example.test/hook'},
    ], ids=['name-int', 'url-list', 'event-types-bare-string', 'event-types-unknown', 'event-types-empty',
            'url-ftp'])
    def test_an_unusable_body_is_a_400(self, rest_api, overrides: dict[str, Any]) -> None:
        """A body is validated by the same rules as a query string"""
        assert rest_api.post(f'{ROUTE_URL}/', json=_webhook_body(**overrides)).status_code \
            == HTTPStatus.BAD_REQUEST

    def test_update_from_the_body_alone(self, rest_api, database_manager: MongoDatabaseManager,
                                        database_name: str) -> None:
        """The update route reads the body the same way, and answers the document as stored"""
        _insert_webhook(database_manager, database_name, WEBHOOK_ID_FOR_UPDATE)
        body = _webhook_body(name='Renamed', event_types=['UPDATE'])

        response = rest_api.put(f'{ROUTE_URL}/{WEBHOOK_ID_FOR_UPDATE}', json=body)

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
        stored = database_manager.get_collection(CmdbWebhook.COLLECTION, database_name)\
            .find_one({'public_id': WEBHOOK_ID_FOR_UPDATE}, {'_id': 0})
        assert stored == {**body, 'public_id': WEBHOOK_ID_FOR_UPDATE, 'owner_id': ADMIN_USER_ID}
        assert response.get_json()['result'] == stored

    def test_update_pins_a_body_public_id_to_the_url(self, rest_api, database_manager: MongoDatabaseManager,
                                                     database_name: str) -> None:
        """A body naming another id can not move the webhook there"""
        _insert_webhook(database_manager, database_name, WEBHOOK_ID_FOR_UPDATE)

        response = rest_api.put(f'{ROUTE_URL}/{WEBHOOK_ID_FOR_UPDATE}',
                                json=_webhook_body(name='Pinned', public_id=MISSING_WEBHOOK_ID))

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
        collection = database_manager.get_collection(CmdbWebhook.COLLECTION, database_name)
        assert collection.find_one({'public_id': WEBHOOK_ID_FOR_UPDATE})['name'] == 'Pinned'
        assert collection.find_one({'public_id': MISSING_WEBHOOK_ID}) is None


class TestActiveFlag:
    """A missing active flag is stored as True; an unreadable one is refused."""

    def test_a_body_without_active_stores_an_active_webhook(
            self, rest_api, database_manager: MongoDatabaseManager, database_name: str) -> None:
        """Left out, the flag is the schema default - the webhook delivers"""
        body = _webhook_body()
        del body['active']

        assert rest_api.post(f'{ROUTE_URL}/', json=body).status_code == HTTPStatus.OK
        assert _stored_by_name(database_manager, database_name)['active'] is True

    def test_a_query_without_active_stores_an_active_webhook(
            self, rest_api, database_manager: MongoDatabaseManager, database_name: str) -> None:
        """The same for a query-only client - it used to be stored switched off"""
        query = urlencode({'name': CREATE_NAME, 'url': 'http://example.test/hook', 'event_types': "['CREATE']"})

        assert rest_api.post(f'{ROUTE_URL}/?{query}').status_code == HTTPStatus.OK
        assert _stored_by_name(database_manager, database_name)['active'] is True

    @pytest.mark.parametrize('active', ['yes', 1, 'on'], ids=['yes', 'int-one', 'on'])
    def test_an_unreadable_active_is_a_400(self, rest_api, active: Any) -> None:
        """Each of these used to become False silently"""
        assert rest_api.post(f'{ROUTE_URL}/', json=_webhook_body(active=active)).status_code \
            == HTTPStatus.BAD_REQUEST
