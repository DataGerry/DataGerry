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
Unit tests for the request size limits and the size-limit answer of cmdb.interface.route_utils

A minimal Flask app, no REST API booted. Pinned:

  - every app config carries the body limit, and the upload limits are larger than it - the type import's form
    field included, which Werkzeug otherwise caps at 500 KB
  - ``accepts_upload`` raises the limits for its own request only, before the handler reads the body
  - ``abort_if_too_large`` answers a write refused on the 16 MB limit - wherever it sits in the cause chain - with
    the one 400, and lets anything else through
  - both shared error decorators answer it with that 400 before their own mapping: ``handle_route_errors`` instead
    of its 500, ``handle_manager_errors`` instead of the route's table message
"""
from http import HTTPStatus

import pytest
from flask import Flask, request
from werkzeug.exceptions import HTTPException

from cmdb.interface.config import Config, DevelopmentConfig, ProductionConfig, TestingConfig
from cmdb.interface.request_limits_constants import DOCUMENT_TOO_LARGE_RESPONSE_MESSAGE, MEBIBYTE, RequestSizeLimit
from cmdb.interface.route_utils import (
    abort_if_too_large,
    accepts_upload,
    handle_manager_errors,
    handle_route_errors,
)
from cmdb.errors.database import DocumentInsertError, DocumentInsertTooLargeError, DocumentUpdateTooLargeError
# -------------------------------------------------------------------------------------------------------------------- #

WERKZEUG_DEFAULT_FORM_MEMORY: int = 500_000
SMALL_LIMIT: int = 1_000
LARGE_LIMIT: int = 100_000
TABLE_MESSAGE: str = 'Failed to insert the thing!'


class _ThingManagerInsertError(Exception):
    """A manager's insert error, wrapping the database layer's"""


def _too_large_from_the_manager() -> _ThingManagerInsertError:
    """A manager error whose cause is the typed size refusal, the way managers wrap"""
    try:
        try:
            raise DocumentInsertTooLargeError('too large')
        except DocumentInsertTooLargeError as err:
            raise _ThingManagerInsertError(err) from err
    except _ThingManagerInsertError as wrapped:
        return wrapped


class TestTheLimits:
    """The numbers, and where they apply"""

    @pytest.mark.parametrize('config', [Config, DevelopmentConfig, ProductionConfig, TestingConfig])
    def test_every_app_config_carries_the_body_limit(self, config: type) -> None:
        """from_object copies it onto app.config, so Werkzeug answers a larger body with 413"""
        app = Flask(__name__)
        app.config.from_object(config)

        assert app.config['MAX_CONTENT_LENGTH'] == RequestSizeLimit.MAX_CONTENT_LENGTH

    def test_the_body_limit_leaves_room_above_one_document(self) -> None:
        """A single stored document may be 16 MB; a body may carry more than one"""
        assert RequestSizeLimit.MAX_CONTENT_LENGTH > 16 * MEBIBYTE

    def test_the_upload_limits_are_above_the_body_limit(self) -> None:
        """A file is a different order of size from a JSON body, and the type import's field is more than 500 KB"""
        assert RequestSizeLimit.UPLOAD_MAX_CONTENT_LENGTH > RequestSizeLimit.MAX_CONTENT_LENGTH
        assert RequestSizeLimit.TYPE_IMPORT_MAX_FORM_MEMORY_SIZE > WERKZEUG_DEFAULT_FORM_MEMORY


class TestAcceptsUpload:
    """A route raises the limits for its own request"""

    @staticmethod
    def _app() -> Flask:
        """An app with a small body limit, one plain route and one upload route"""
        app = Flask(__name__)
        app.config['MAX_CONTENT_LENGTH'] = SMALL_LIMIT

        @app.post('/plain')
        def plain() -> str:
            return str(len(request.get_data()))

        @app.post('/upload')
        @accepts_upload(LARGE_LIMIT, LARGE_LIMIT)
        def upload() -> str:
            return str(len(request.form.get('field', '')))

        return app

    def test_a_plain_route_keeps_the_app_limit(self) -> None:
        """Werkzeug's own 413"""
        client = self._app().test_client()

        assert client.post('/plain', data=b'x' * (SMALL_LIMIT + 1)).status_code == HTTPStatus.REQUEST_ENTITY_TOO_LARGE

    def test_the_upload_route_takes_more(self) -> None:
        """A body and a form field above the app's limits pass"""
        response = self._app().test_client().post('/upload', data={'field': 'y' * (SMALL_LIMIT * 10)})

        assert response.status_code == HTTPStatus.OK
        assert response.get_data(as_text=True) == str(SMALL_LIMIT * 10)

    def test_the_upload_route_still_has_a_limit(self) -> None:
        """Its own, not none"""
        response = self._app().test_client().post('/upload', data={'field': 'y' * (LARGE_LIMIT + 1)})

        assert response.status_code == HTTPStatus.REQUEST_ENTITY_TOO_LARGE

    def test_without_a_form_limit_werkzeugs_stays(self) -> None:
        """Only the body limit is raised when no form limit is given"""
        app = Flask(__name__)

        @app.post('/body-only')
        @accepts_upload(LARGE_LIMIT)
        def body_only() -> str:
            return str(request.max_form_memory_size)

        assert app.test_client().post('/body-only').get_data(as_text=True) == str(WERKZEUG_DEFAULT_FORM_MEMORY)


class TestAbortIfTooLarge:
    """The one 400 for a write refused on the size limit"""

    def test_the_typed_error_is_a_400(self) -> None:
        """Insert or update alike"""
        for err in (DocumentInsertTooLargeError('x'), DocumentUpdateTooLargeError('x')):
            with Flask(__name__).app_context(), pytest.raises(HTTPException) as caught:
                abort_if_too_large(err)

            assert caught.value.code == HTTPStatus.BAD_REQUEST
            assert caught.value.description == DOCUMENT_TOO_LARGE_RESPONSE_MESSAGE

    def test_it_is_found_through_the_managers_wrapping(self) -> None:
        """The route catches the manager's error; the cause chain carries the database layer's"""
        with Flask(__name__).app_context(), pytest.raises(HTTPException) as caught:
            abort_if_too_large(_too_large_from_the_manager())

        assert caught.value.code == HTTPStatus.BAD_REQUEST

    def test_any_other_error_is_left_to_the_caller(self) -> None:
        """Returns, so the arm reports the failure its own way"""
        assert abort_if_too_large(DocumentInsertError('outage')) is None
        assert abort_if_too_large(RuntimeError('boom')) is None


class TestTheSharedDecorators:
    """Both answer the size limit before their own mapping"""

    def test_the_generic_tail_answers_400_not_500(self) -> None:
        """A route with no rule of its own for the write"""
        @handle_route_errors('while creating the thing')
        def route() -> None:
            raise _too_large_from_the_manager()

        with Flask(__name__).test_request_context(), pytest.raises(HTTPException) as caught:
            route()

        assert caught.value.code == HTTPStatus.BAD_REQUEST
        assert caught.value.description == DOCUMENT_TOO_LARGE_RESPONSE_MESSAGE

    def test_the_generic_tail_keeps_its_500_otherwise(self) -> None:
        """Nothing else changes"""
        @handle_route_errors('while creating the thing')
        def route() -> None:
            raise RuntimeError('boom')

        with Flask(__name__).test_request_context(), pytest.raises(HTTPException) as caught:
            route()

        assert caught.value.code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_the_error_table_answers_the_size_not_its_message(self) -> None:
        """The table's 'Failed to insert' would read like an outage"""
        @handle_manager_errors({_ThingManagerInsertError: TABLE_MESSAGE})
        def route() -> None:
            raise _too_large_from_the_manager()

        with Flask(__name__).test_request_context(), pytest.raises(HTTPException) as caught:
            route()

        assert caught.value.description == DOCUMENT_TOO_LARGE_RESPONSE_MESSAGE

    def test_the_error_table_keeps_its_message_otherwise(self) -> None:
        """A mapped error that is not the size limit"""
        @handle_manager_errors({_ThingManagerInsertError: TABLE_MESSAGE})
        def route() -> None:
            raise _ThingManagerInsertError('outage')

        with Flask(__name__).test_request_context(), pytest.raises(HTTPException) as caught:
            route()

        assert caught.value.description == TABLE_MESSAGE
