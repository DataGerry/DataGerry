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
Unit tests for the object-export routes

Covers the status-code mapping and branch selection of `GET /exporter/template/<type_id>`, the one
export route that reads no CmdbObject: the not-found and no-fields guards, the two manager-error arms,
and that a successful call goes through the CSV writer with the built header and never touches an
object. The handler is unwrapped past its decorators and driven in a Flask test_request_context with the
manager patched, so no Mongo and no blueprint registration run.
"""
from typing import Any, Callable
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask
from werkzeug.exceptions import HTTPException

from cmdb.interface.rest_api.routes.exporter_routes.exporter_object_routes import (
    export_object_import_template,
)
from cmdb.errors.manager.types_manager import TypesManagerGetError
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_PATH: str = 'cmdb.interface.rest_api.routes.exporter_routes.exporter_object_routes'

HTTP_BAD_REQUEST: int = 400
HTTP_NOT_FOUND: int = 404
HTTP_SERVER_ERROR: int = 500

TYPE_ID: int = 5
TEMPLATE_URL: str = '/template/5'

BUILT_HEADER: list[str] = ['Public ID [public_id]', 'Active [active]', 'Name [dg-name]']


def _unwrap(func: Callable[..., Any]) -> Callable[..., Any]:
    """Strips the decorator chain (route / protect / verify_api_access / insert_request_user)."""
    inner = func

    while hasattr(inner, '__wrapped__'):
        inner = inner.__wrapped__

    return inner


@pytest.fixture(name='flask_app')
def fixture_flask_app() -> Flask:
    """A minimal Flask app to host the test_request_context calls."""
    return Flask(__name__)


def _types_manager(**attributes: Any) -> MagicMock:
    """Builds a TypesManager stand-in with the given return values / side effects."""
    manager = MagicMock()

    for name, value in attributes.items():
        setattr(manager, name, value)

    return manager


def _drive(flask_app: Flask, manager: MagicMock) -> tuple[Any, MagicMock]:
    """Drives the unwrapped handler with the manager and the CSV format patched."""
    with patch(f'{ROUTE_PATH}.ManagerProvider.get_manager', return_value=manager), \
         patch(f'{ROUTE_PATH}.type_has_template_fields', return_value=True), \
         patch(f'{ROUTE_PATH}.build_object_template_header', return_value=BUILT_HEADER), \
         patch(f'{ROUTE_PATH}.CsvExportFormat') as csv_format, \
         flask_app.test_request_context(TEMPLATE_URL):
        response = _unwrap(export_object_import_template)(type_id=TYPE_ID, request_user=MagicMock())

    return response, csv_format


def _expect_status(flask_app: Flask, manager: MagicMock, expected_code: int, **patches: Any) -> None:
    """Asserts that driving the handler aborts with the expected status code."""
    with patch(f'{ROUTE_PATH}.ManagerProvider.get_manager', return_value=manager), \
         patch(f'{ROUTE_PATH}.type_has_template_fields', return_value=patches.get('has_fields', True)), \
         flask_app.test_request_context(TEMPLATE_URL):
        with pytest.raises(HTTPException) as exc_info:
            _unwrap(export_object_import_template)(type_id=TYPE_ID, request_user=MagicMock())

    assert exc_info.value.code == expected_code


def test_template_is_written_through_the_csv_writer(flask_app: Flask) -> None:
    """The built header is handed to the CSV writer with NO data rows."""
    manager = _types_manager(get_type_instance=MagicMock(return_value=MagicMock(label='Router')))

    _, csv_format = _drive(flask_app, manager)

    csv_format.return_value.csv_writer.assert_called_once_with(BUILT_HEADER, [])


def test_template_answers_a_csv_attachment(flask_app: Flask) -> None:
    """The response is a CSV download whose filename carries the template marker."""
    manager = _types_manager(get_type_instance=MagicMock(return_value=MagicMock(label='Router')))

    response, _ = _drive(flask_app, manager)

    assert 'attachment;' in response.headers['Content-Disposition']
    assert '_template.' in response.headers['Content-Disposition']


def test_template_reads_the_type_only(flask_app: Flask) -> None:
    """Exactly one type lookup and nothing else - a template needs no object."""
    manager = _types_manager(get_type_instance=MagicMock(return_value=MagicMock(label='Router')))

    _drive(flask_app, manager)

    manager.get_type_instance.assert_called_once_with(TYPE_ID)


def test_missing_type_maps_to_404(flask_app: Flask) -> None:
    """A type that does not exist has no template."""
    manager = _types_manager(get_type_instance=MagicMock(return_value=None))

    _expect_status(flask_app, manager, HTTP_NOT_FOUND)


def test_type_without_fields_maps_to_400(flask_app: Flask) -> None:
    """A type with no field to fill in is refused rather than answered with identity columns only."""
    manager = _types_manager(get_type_instance=MagicMock(return_value=MagicMock(label='Router')))

    _expect_status(flask_app, manager, HTTP_BAD_REQUEST, has_fields=False)


def test_manager_get_error_maps_to_400(flask_app: Flask) -> None:
    """A TypesManagerGetError is translated to HTTP 400."""
    manager = _types_manager(get_type_instance=MagicMock(side_effect=TypesManagerGetError('x')))

    _expect_status(flask_app, manager, HTTP_BAD_REQUEST)


def test_unexpected_error_maps_to_500(flask_app: Flask) -> None:
    """Any other exception is translated to HTTP 500."""
    manager = _types_manager(get_type_instance=MagicMock(side_effect=RuntimeError('boom')))

    _expect_status(flask_app, manager, HTTP_SERVER_ERROR)
