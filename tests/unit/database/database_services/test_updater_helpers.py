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
Unit tests for cmdb.database.database_services.updater_helpers

Pure tests: the HTTP layer (requests.get) and the environment are mocked, so no Service Portal or
network is contacted. Covers the local-mode shortcut, the x-access-token / DG_SP_BASE_URL guards,
the success path, the non-200 / timeout / connection / unexpected error paths, and the safe
error-message extraction from malformed response bodies.
"""
from typing import Any
from unittest.mock import patch, MagicMock

import pytest
import requests

from cmdb.errors.security import NoAccessTokenError, RequestError, RequestTimeoutError
from cmdb.database.database_services.updater_helpers import (
    get_db_names_from_service_portal,
    _build_service_portal_headers,
    _fetch_db_names_from_portal,
    _extract_response_error_message,
)
# -------------------------------------------------------------------------------------------------------------------- #

MODULE: str = 'cmdb.database.database_services.updater_helpers'
TOKEN_ENV: str = 'X-ACCESS-TOKEN'
BASE_URL_ENV: str = 'DG_SP_BASE_URL'
TOKEN_VALUE: str = 'secret-token'
BASE_URL_VALUE: str = 'http://portal.example'
LOCAL_DB_NAMES: list[str] = ['testdb1', 'testdb2', 'testdb3']
FULL_ENV: dict[str, str] = {TOKEN_ENV: TOKEN_VALUE, BASE_URL_ENV: BASE_URL_VALUE}


def _make_response(status_code: int, json_payload: Any = None, text: str = '') -> MagicMock:
    """Builds a stand-in requests.Response with a fixed status code, JSON payload and raw text"""
    response: MagicMock = MagicMock(spec=requests.Response)
    response.status_code = status_code
    response.text = text
    response.json.return_value = json_payload

    return response

# -------------------------------------------------------------------------------------------------------------------- #
#                                       get_db_names_from_service_portal                                               #
# -------------------------------------------------------------------------------------------------------------------- #

def test_local_mode_returns_fixed_db_names() -> None:
    """Local mode returns the fixed names without contacting the Service Portal"""
    with patch(f'{MODULE}.requests.get') as mock_get:
        assert get_db_names_from_service_portal(local_mode=True) == LOCAL_DB_NAMES
        mock_get.assert_not_called()


def test_success_returns_response_json() -> None:
    """A 200 response returns the decoded JSON list of database names"""
    with patch.dict('os.environ', FULL_ENV, clear=True), patch(f'{MODULE}.requests.get') as mock_get:
        mock_get.return_value = _make_response(200, json_payload=['db_a', 'db_b'])

        assert get_db_names_from_service_portal() == ['db_a', 'db_b']
        mock_get.assert_called_once()


def test_missing_token_raises_no_access_token_error() -> None:
    """A missing x-access-token raises NoAccessTokenError before any request is made"""
    with patch.dict('os.environ', {BASE_URL_ENV: BASE_URL_VALUE}, clear=True):
        with pytest.raises(NoAccessTokenError):
            get_db_names_from_service_portal()


def test_missing_base_url_raises_request_error() -> None:
    """A missing DG_SP_BASE_URL raises RequestError instead of building a malformed URL"""
    with patch.dict('os.environ', {TOKEN_ENV: TOKEN_VALUE}, clear=True):
        with pytest.raises(RequestError, match='DG_SP_BASE_URL'):
            get_db_names_from_service_portal()


def test_non_200_raises_request_error_with_message() -> None:
    """A non-200 response raises RequestError carrying the body's 'message'"""
    with patch.dict('os.environ', FULL_ENV, clear=True), patch(f'{MODULE}.requests.get') as mock_get:
        mock_get.return_value = _make_response(404, json_payload={'message': 'not found'})

        with pytest.raises(RequestError, match='not found'):
            get_db_names_from_service_portal()


def test_timeout_raises_request_timeout_error() -> None:
    """A request timeout is surfaced as RequestTimeoutError"""
    with patch.dict('os.environ', FULL_ENV, clear=True), patch(f'{MODULE}.requests.get') as mock_get:
        mock_get.side_effect = requests.exceptions.Timeout()

        with pytest.raises(RequestTimeoutError):
            get_db_names_from_service_portal()


def test_connection_error_raises_request_error() -> None:
    """A general requests exception is surfaced as RequestError"""
    with patch.dict('os.environ', FULL_ENV, clear=True), patch(f'{MODULE}.requests.get') as mock_get:
        mock_get.side_effect = requests.exceptions.ConnectionError()

        with pytest.raises(RequestError):
            get_db_names_from_service_portal()


def test_unexpected_error_is_wrapped_in_request_error() -> None:
    """An unexpected failure while reading a 200 body is wrapped in RequestError"""
    response: MagicMock = _make_response(200)
    response.json.side_effect = ValueError('broken json')

    with patch.dict('os.environ', FULL_ENV, clear=True), patch(f'{MODULE}.requests.get') as mock_get:
        mock_get.return_value = response

        with pytest.raises(RequestError):
            get_db_names_from_service_portal()

# -------------------------------------------------------------------------------------------------------------------- #
#                                         _build_service_portal_headers                                                #
# -------------------------------------------------------------------------------------------------------------------- #

def test_build_headers_returns_token_header() -> None:
    """The headers carry the x-access-token from the environment"""
    with patch.dict('os.environ', {TOKEN_ENV: TOKEN_VALUE}, clear=True):
        assert _build_service_portal_headers() == {'x-access-token': TOKEN_VALUE}


def test_build_headers_raises_without_token() -> None:
    """Building headers without a token raises NoAccessTokenError"""
    with patch.dict('os.environ', {}, clear=True):
        with pytest.raises(NoAccessTokenError):
            _build_service_portal_headers()

# -------------------------------------------------------------------------------------------------------------------- #
#                                       _extract_response_error_message                                                #
# -------------------------------------------------------------------------------------------------------------------- #

def test_extract_message_from_json_message_field() -> None:
    """A JSON body with a 'message' field yields that message"""
    response: MagicMock = _make_response(500, json_payload={'message': 'boom'}, text='ignored')

    assert _extract_response_error_message(response) == 'boom'


def test_extract_message_falls_back_to_text_when_message_absent() -> None:
    """A JSON dict without a 'message' field falls back to the raw response text"""
    response: MagicMock = _make_response(500, json_payload={'code': 7}, text='raw-body')

    assert _extract_response_error_message(response) == 'raw-body'


def test_extract_message_falls_back_to_text_for_non_dict_json() -> None:
    """A non-dict JSON body (e.g. a list) falls back to the raw response text"""
    response: MagicMock = _make_response(500, json_payload=['unexpected'], text='raw-body')

    assert _extract_response_error_message(response) == 'raw-body'


def test_extract_message_falls_back_to_text_for_non_json_body() -> None:
    """A body that is not valid JSON falls back to the raw response text"""
    response: MagicMock = _make_response(500, text='plain-error')
    response.json.side_effect = ValueError('not json')

    assert _extract_response_error_message(response) == 'plain-error'

# -------------------------------------------------------------------------------------------------------------------- #
#                                          _fetch_db_names_from_portal                                                 #
# -------------------------------------------------------------------------------------------------------------------- #

def test_fetch_db_names_missing_base_url_raises() -> None:
    """The fetch helper raises RequestError when DG_SP_BASE_URL is unset"""
    with patch.dict('os.environ', {}, clear=True):
        with pytest.raises(RequestError, match='DG_SP_BASE_URL'):
            _fetch_db_names_from_portal({'x-access-token': TOKEN_VALUE})
