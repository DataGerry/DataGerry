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
Every REST failure answers the JSON envelope, and a transient DB error says so (tier 2 T135 / T185)

Two defects, both verified against the running app before they were fixed, and both kept here as
requests rather than as unit calls - what made each one real was what a client received.

**415 answered `text/html`.** The API registered nine status codes by hand and anything else fell
through to Flask's HTML page. `abort()` appears 1300+ times in `cmdb/` and never with 415, which is
exactly why nobody found it: Werkzeug raises it while parsing the request, before any route runs, so
no census of the route layer could see it. One handler registered for the `HTTPException` class
closes the family.

**A database lock timeout answered `500 internal server error`.** `route_utils.handle_db_errors` maps
`DocumentLockTimeoutError` to 423 and `DocumentNetworkError` to 503 - but it is the *outermost*
decorator, so it only ever sees what escapes the handler, and the handler ended in
`except Exception: abort(500, …)`. Two layers re-wrapped the error before that: the manager turned it
into `ObjectsManagerInsertError` (→ 400) and the route's own catch-all claimed whatever was left. So
a retryable condition was reported as an internal server error, and the 423 branch had never once
executed in production.
"""
from http import HTTPStatus
from unittest.mock import MagicMock, patch

import pytest
from werkzeug.exceptions import HTTPException

from cmdb.errors.database import DocumentLockTimeoutError, DocumentNetworkError
from cmdb.interface.route_utils import handle_db_errors
# -------------------------------------------------------------------------------------------------------------------- #

ENVELOPE_KEYS: set[str] = {'description', 'message', 'response', 'status'}

ROUTES_MODULE: str = 'cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_routes'


class TestEveryFailureIsJson:
    """The envelope is frontend contract: the Angular interceptor reads `message` off it."""

    def test_an_unsupported_media_type_answers_json(self, rest_api) -> None:
        """
        The defect, as a request

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

    The decorated route is rebuilt here rather than called through the client, because provoking a
    real Mongo lock timeout is not something a test can do reliably. What is exercised is the part
    that was broken: whether the error survives the route body long enough for the decorator to map
    it.
    """

    @staticmethod
    def _guarded_route():
        """The route handler with its `handle_db_errors` decorator, minus auth and validation."""
        from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects import objects_routes

        body = objects_routes.insert_cmdb_object

        while hasattr(body, '__wrapped__'):
            body = body.__wrapped__

        return handle_db_errors(body)

    @pytest.mark.parametrize('error, expected', [
        (DocumentLockTimeoutError('lock timeout'), HTTPStatus.LOCKED),
        (DocumentNetworkError('network error'), HTTPStatus.SERVICE_UNAVAILABLE),
    ], ids=['lock timeout -> 423', 'network error -> 503'])
    def test_it_reaches_the_status_the_decorator_maps_it_to(self, rest_api, error, expected) -> None:
        """Both were 500 before: the route's own `except Exception` got there first."""
        with patch(f'{ROUTES_MODULE}.apply_object_insert', side_effect=error), \
             patch(f'{ROUTES_MODULE}.ManagerProvider.get_manager', return_value=MagicMock()), \
             rest_api.application.test_request_context('/objects/', method='POST', json={}):
            with pytest.raises(HTTPException) as exc_info:
                self._guarded_route()(data={'type_id': 1, 'fields': []}, request_user=MagicMock())

        assert exc_info.value.code == expected

    def test_an_ordinary_failure_is_still_a_500(self, rest_api) -> None:
        """
        The arm that must not widen

        Re-raising the two transient database errors is only correct while everything else still
        ends in the route's own catch-all.
        """
        with patch(f'{ROUTES_MODULE}.apply_object_insert', side_effect=RuntimeError('something else')), \
             patch(f'{ROUTES_MODULE}.ManagerProvider.get_manager', return_value=MagicMock()), \
             rest_api.application.test_request_context('/objects/', method='POST', json={}):
            with pytest.raises(HTTPException) as exc_info:
                self._guarded_route()(data={'type_id': 1, 'fields': []}, request_user=MagicMock())

        assert exc_info.value.code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_a_423_answers_the_json_envelope_over_the_wire(self, rest_api) -> None:
        """
        The two halves of this pass, joined

        423 is now reachable *and* it is JSON. Before, it was neither: unreachable through the route,
        and HTML if anything had ever raised it.
        """
        from cmdb.interface.rest_api.responses.error_handlers import http_exception
        from werkzeug.exceptions import Locked

        with rest_api.application.test_request_context('/objects/', method='POST'):
            response = http_exception(Locked('Database collection currently in use. Please try again!'))

        assert response.status_code == HTTPStatus.LOCKED
        assert response.mimetype == 'application/json'
        assert response.get_json()['message'] == 'Database collection currently in use. Please try again!'
