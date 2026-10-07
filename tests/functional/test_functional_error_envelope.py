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
Every REST failure answers the JSON envelope, and a transient DB error says so

Both rules are checked here as requests rather than as unit calls - what matters is what a client
receives.

**415 answers JSON, not `text/html`.** Werkzeug raises 415 while parsing the request, before any
route runs, so no `abort()` in the route layer produces it and no census of the route layer can see
it. One handler registered for the `HTTPException` class covers every status, instead of a
hand-picked list with Flask's HTML page as the fallthrough.

**A database lock timeout answers 423 and a lost connection 503, not `500 internal server error`.**
The app registers a handler for each (`responses/error_handlers.py`), so every route answers them the same
way - as long as the error survives the manager and the route's tail unwrapped. `handle_route_errors` re-raises
them; a route with a hand-written `except Exception` of its own would need an arm that re-raises them first.
"""
from http import HTTPStatus
from unittest.mock import patch

import pytest

from cmdb.errors.database import DocumentLockTimeoutError, DocumentNetworkError
from cmdb.interface.rest_api.responses.error_handlers import DATABASE_LOCKED_MSG, DATABASE_UNAVAILABLE_MSG
from cmdb.manager import TypesManager
# -------------------------------------------------------------------------------------------------------------------- #

ENVELOPE_KEYS: set[str] = {'description', 'message', 'response', 'status'}

ROUTES_MODULE: str = 'cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_routes'
# A body the object create's schema accepts, so the request reaches the insert
OBJECT_PAYLOAD: dict = {'type_id': 1, 'fields': [], 'active': True, 'version': '1.0.0', 'author_id': 1}


class TestEveryFailureIsJson:
    """The envelope is frontend contract: the Angular interceptor reads `message` off it."""

    def test_an_unsupported_media_type_answers_json(self, rest_api) -> None:
        """
        The rule, as a request

        Werkzeug refuses the body before the route is reached, so this is a status the route layer
        cannot be audited for.
        """
        response = rest_api.post('/objects/', data='<xml/>', content_type='application/xml')

        assert response.status_code == HTTPStatus.UNSUPPORTED_MEDIA_TYPE
        assert response.mimetype == 'application/json'
        assert set(response.get_json()) == ENVELOPE_KEYS

    def test_no_error_response_is_html(self, rest_api) -> None:
        """
        The family, not the single case

        Four different failure kinds - an unknown route, a wrong method, a malformed body and an
        unsupported media type - reach the error path by four different mechanisms.
        """
        responses = [
            rest_api.get('/definitely-not-a-route'),
            rest_api.delete('/types/'),
            rest_api.post('/objects/', data='{', content_type='application/json'),
            rest_api.post('/objects/', data='<xml/>', content_type='application/xml'),
        ]

        assert [r.mimetype for r in responses] == ['application/json'] * 4

    def test_the_status_in_the_body_matches_the_status_of_the_response(self, rest_api) -> None:
        """A client that trusts the body must not be told something different by the header."""
        response = rest_api.post('/objects/', data='<xml/>', content_type='application/xml')

        assert response.get_json()['status'] == response.status_code


class TestATransientDatabaseErrorIsReportedAsTransient:
    """
    423 / 503 rather than 500 - the difference between "retry" and "something is broken"

    Provoking a real Mongo lock timeout is not something a test can do reliably, so the error is raised where the
    database layer would raise it, and the request goes through the client: the app's handlers answer it even under
    the test client, which otherwise lets an unhandled error through
    """

    @pytest.mark.parametrize('error, expected, message', [
        (DocumentLockTimeoutError('lock timeout'), HTTPStatus.LOCKED, DATABASE_LOCKED_MSG),
        (DocumentNetworkError('network error'), HTTPStatus.SERVICE_UNAVAILABLE, DATABASE_UNAVAILABLE_MSG),
    ], ids=['lock timeout -> 423', 'network error -> 503'])
    def test_the_object_create_answers_it(self, rest_api, error, expected, message) -> None:
        """The route's shared tail (handle_route_errors) re-raises them to the app's handler"""
        with patch(f'{ROUTES_MODULE}.apply_object_insert', side_effect=error):
            response = rest_api.post('/objects/', json=OBJECT_PAYLOAD)

        assert response.status_code == expected
        assert set(response.get_json()) == ENVELOPE_KEYS
        assert response.get_json()['message'] == message

    @pytest.mark.parametrize('error, expected', [
        (DocumentLockTimeoutError('lock timeout'), HTTPStatus.LOCKED),
        (DocumentNetworkError('network error'), HTTPStatus.SERVICE_UNAVAILABLE),
    ], ids=['lock timeout -> 423', 'network error -> 503'])
    def test_a_route_on_the_shared_tail_answers_it(self, rest_api, monkeypatch, error, expected) -> None:
        """
        GET /types/<id> ends in handle_route_errors, which re-raises the pair. With no handler for them the error
        escaped every one and Flask answered a bare 500 - this is the route family the fix is for
        """
        def _raise(*_args, **_kwargs):
            raise error

        monkeypatch.setattr(TypesManager, 'get_type', _raise)

        response = rest_api.get('/types/1')

        assert response.status_code == expected
        assert set(response.get_json()) == ENVELOPE_KEYS

    def test_an_ordinary_failure_of_the_object_create_is_still_its_500(self, rest_api) -> None:
        """Everything else still ends in the route's own catch-all"""
        with patch(f'{ROUTES_MODULE}.apply_object_insert', side_effect=RuntimeError('something else')):
            response = rest_api.post('/objects/', json=OBJECT_PAYLOAD)

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert response.get_json()['message'] not in (DATABASE_LOCKED_MSG, DATABASE_UNAVAILABLE_MSG)
