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
Unit tests for cmdb.interface.rest_api.routes.importer_routes.importer_route_utils

Pure request-parsing helpers exercised inside a minimal Flask request context (no REST API booted):
``get_file_in_request`` (returns the uploaded file, aborts 400 when absent) and
``get_element_from_data_request`` (parses a JSON form field, returns None when the field is missing
or not valid JSON).
"""
import json
from io import BytesIO

import pytest
from flask import Flask, request
from werkzeug.exceptions import HTTPException

from cmdb.interface.rest_api.routes.importer_routes.importer_route_utils import (
    get_file_in_request,
    get_element_from_data_request,
)
# -------------------------------------------------------------------------------------------------------------------- #

app = Flask(__name__)


class TestGetFileInRequest:
    """get_file_in_request returns the uploaded file or aborts 400 when it is missing."""

    def test_returns_file_when_present(self) -> None:
        """The uploaded file is returned when the named field is present."""
        with app.test_request_context(
            '/', method='POST',
            data={'file': (BytesIO(b'content'), 'import.csv')},
            content_type='multipart/form-data',
        ):
            result = get_file_in_request('file', request.files)

            assert result.filename == 'import.csv'

    def test_missing_file_aborts_400(self) -> None:
        """A missing file field aborts with 400."""
        with app.test_request_context('/', method='POST', data={}, content_type='multipart/form-data'):
            with pytest.raises(HTTPException) as exc:
                get_file_in_request('file', request.files)

            assert exc.value.code == 400


class TestGetElementFromDataRequest:
    """get_element_from_data_request parses a JSON form field, or returns None on miss / bad JSON."""

    def test_parses_json_field(self) -> None:
        """A valid JSON form field is parsed into a Python object."""
        with app.test_request_context(
            '/', method='POST',
            data={'cfg': json.dumps({'a': 1})},
            content_type='multipart/form-data',
        ):
            assert get_element_from_data_request('cfg', request) == {'a': 1}

    def test_missing_field_returns_none(self) -> None:
        """A missing form field returns None."""
        with app.test_request_context('/', method='POST', data={}, content_type='multipart/form-data'):
            assert get_element_from_data_request('cfg', request) is None

    def test_invalid_json_returns_none(self) -> None:
        """A form field that is not valid JSON returns None."""
        with app.test_request_context(
            '/', method='POST',
            data={'cfg': 'not-json'},
            content_type='multipart/form-data',
        ):
            assert get_element_from_data_request('cfg', request) is None
