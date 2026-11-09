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
Unit tests for the headers the JSON error envelope keeps

The envelope replaces Werkzeug's HTML page, so only the body changes: every header the exception carries for its
status - `Allow` on a 405, `Retry-After`, `WWW-Authenticate` - reaches the client, and only `Content-Type` is the
JSON body's own. The body stays the envelope whatever the exception carries
"""
from collections.abc import Iterator
from http import HTTPStatus

import pytest
from flask import Flask, Response
from werkzeug.datastructures import WWWAuthenticate
from werkzeug.exceptions import HTTPException, MethodNotAllowed, NotFound, TooManyRequests, Unauthorized

from cmdb.errors.database import DocumentLockTimeoutError, DocumentNetworkError
from cmdb.interface.rest_api.responses.error_handlers import (
    REPLACED_HEADER,
    carried_headers,
    database_locked,
    database_unavailable,
    http_exception,
)
# -------------------------------------------------------------------------------------------------------------------- #

ENVELOPE_KEYS: set[str] = {'description', 'message', 'response', 'status'}
JSON_MIMETYPE: str = 'application/json'

ALLOWED_METHODS: list[str] = ['GET', 'POST']
RETRY_AFTER_SECONDS: int = 30
CUSTOM_HEADER: tuple[str, str] = ('X-Custom-Header', 'carried')
FOREIGN_CONTENT_TYPE: str = 'text/plain'
CARRIED_RESPONSE_STATUS: int = 418
CARRIED_RESPONSE_BODY: str = 'a body of its own'


class _HeaderedError(HTTPException):
    """An HTTPException whose headers spell Content-Type in lower case and carry one header of their own"""
    code = HTTPStatus.BAD_REQUEST

    def get_headers(self, environ=None, scope=None) -> list[tuple[str, str]]:
        """A lower-case content type plus one custom header"""
        return [(REPLACED_HEADER.lower(), FOREIGN_CONTENT_TYPE), CUSTOM_HEADER]


@pytest.fixture(autouse=True)
def _request_context() -> Iterator[None]:
    """The envelope names the requested URL, so every call needs a request"""
    with Flask(__name__).test_request_context():
        yield


class TestTheStatusHeadersAreKept:
    """What Werkzeug's page would have sent besides its body"""

    def test_a_405_names_the_allowed_methods(self) -> None:
        """RFC 9110 requires Allow on a 405"""
        response: Response = http_exception(MethodNotAllowed(valid_methods=ALLOWED_METHODS))

        assert response.status_code == HTTPStatus.METHOD_NOT_ALLOWED
        assert response.headers['Allow'] == ', '.join(ALLOWED_METHODS)

    def test_a_retry_after_is_kept(self) -> None:
        """The header a 429 or 503 uses to say when to come back"""
        response: Response = http_exception(TooManyRequests(retry_after=RETRY_AFTER_SECONDS))

        assert response.headers['Retry-After'] == str(RETRY_AFTER_SECONDS)

    def test_a_repeated_header_stays_repeated(self) -> None:
        """Two challenges are two WWW-Authenticate headers - one must not replace the other"""
        challenges = [WWWAuthenticate('basic', {'realm': 'datagerry'}), WWWAuthenticate('bearer')]

        response: Response = http_exception(Unauthorized(www_authenticate=challenges))

        assert response.headers.getlist('WWW-Authenticate') == [challenge.to_header() for challenge in challenges]

    def test_a_status_without_headers_adds_none(self) -> None:
        """A 404 answers exactly the JSON body's own headers, as before"""
        response: Response = http_exception(NotFound())

        assert set(response.headers.keys()) == {'Content-Type', 'Content-Length'}


class TestTheBodyIsStillTheEnvelope:
    """Only the headers were added - the body and its type are the envelope's"""

    @pytest.mark.parametrize('error', [
        MethodNotAllowed(valid_methods=ALLOWED_METHODS),
        TooManyRequests(retry_after=RETRY_AFTER_SECONDS),
        _HeaderedError(),
    ], ids=['405', '429', 'custom'])
    def test_the_body_is_json_with_one_content_type(self, error: HTTPException) -> None:
        """Werkzeug's text/html Content-Type never reaches the client"""
        response: Response = http_exception(error)

        assert response.mimetype == JSON_MIMETYPE
        assert response.headers.getlist('Content-Type') == [response.content_type]
        assert set(response.get_json()) == ENVELOPE_KEYS
        assert response.get_json()['status'] == response.status_code

    def test_a_carried_response_is_not_used(self) -> None:
        """abort(Response) still answers the envelope - the frontend reads `message` off every failure"""
        error = HTTPException(response=Response(CARRIED_RESPONSE_BODY, status=CARRIED_RESPONSE_STATUS))

        response: Response = http_exception(error)

        assert response.mimetype == JSON_MIMETYPE
        assert set(response.get_json()) == ENVELOPE_KEYS
        assert response.status_code != CARRIED_RESPONSE_STATUS


class TestCarriedHeaders:
    """The list the handler copies"""

    def test_content_type_is_left_out_whatever_its_case(self) -> None:
        """The comparison is case-insensitive; every other header is kept in order"""
        assert carried_headers(_HeaderedError()) == [CUSTOM_HEADER]

    def test_a_405_carries_allow_only(self) -> None:
        """Werkzeug's Content-Type is the only header dropped"""
        assert carried_headers(MethodNotAllowed(valid_methods=ALLOWED_METHODS)) == [
            ('Allow', ', '.join(ALLOWED_METHODS)),
        ]


class TestTheTransientAnswersCarryNoRetryAfter:
    """423 and 503 say "try again" in the body only - a Retry-After value is not chosen"""

    @pytest.mark.parametrize('handler, error', [
        (database_unavailable, DocumentNetworkError('lost')),
        (database_locked, DocumentLockTimeoutError('locked')),
    ], ids=['503', '423'])
    def test_no_retry_after(self, handler, error: Exception) -> None:
        """Unchanged by carrying the headers: these exceptions are built without one"""
        response: Response = handler(error)

        assert 'Retry-After' not in response.headers
