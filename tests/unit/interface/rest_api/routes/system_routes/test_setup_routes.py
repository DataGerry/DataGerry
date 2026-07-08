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
Unit tests for cmdb.interface.rest_api.routes.system_routes.setup_routes

The handler is unwrapped past its decorator chain and driven inside a Flask test_request_context;
CachedUserManager is patched at the route module path. These pin delete_cached_user's branch logic -
in particular that a LIST of emails deletes multiple cached users (previously broken by an
isinstance(..., list[str]) check that raised TypeError -> 500)
"""
from typing import Any, Callable
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask
from werkzeug.exceptions import HTTPException

from cmdb.interface.rest_api.routes.system_routes.setup_routes import delete_cached_user
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_PATH: str = 'cmdb.interface.rest_api.routes.system_routes.setup_routes'
CACHE_USER_ROUTE: str = '/cache/user'
DELETE_METHOD: str = 'DELETE'


def _unwrap(func: Callable[..., Any]) -> Callable[..., Any]:
    """Strips the decorator chain (route / verify_api_access) to reach the raw handler."""
    inner = func

    while hasattr(inner, '__wrapped__'):
        inner = inner.__wrapped__

    return inner


@pytest.fixture(name='flask_app')
def fixture_flask_app() -> Flask:
    """A minimal Flask app exposing a database_manager for CachedUserManager construction."""
    app = Flask(__name__)
    app.database_manager = MagicMock()

    return app


@pytest.fixture(name='cached_user_manager')
def fixture_cached_user_manager() -> MagicMock:
    """Patches CachedUserManager at the route path and yields the manager instance mock."""
    manager = MagicMock()

    with patch(f'{ROUTE_PATH}.CachedUserManager', return_value=manager):
        yield manager


class TestDeleteCachedUser:
    """delete_cached_user branches on the 'email' payload type."""

    def test_single_email_deletes_one(self, flask_app: Flask, cached_user_manager: MagicMock) -> None:
        """A string 'email' deletes exactly that cached user."""
        with flask_app.test_request_context(CACHE_USER_ROUTE, method=DELETE_METHOD, json={'email': 'a@x.io'}):
            _unwrap(delete_cached_user)()

        cached_user_manager.delete_cached_user.assert_called_once_with('a@x.io')
        cached_user_manager.delete_multiple_cached_users.assert_not_called()

    def test_list_of_emails_deletes_multiple(self, flask_app: Flask, cached_user_manager: MagicMock) -> None:
        """A list 'email' deletes multiple cached users (regression: was a TypeError -> 500)."""
        emails = ['a@x.io', 'b@x.io']

        with flask_app.test_request_context(CACHE_USER_ROUTE, method=DELETE_METHOD, json={'email': emails}):
            _unwrap(delete_cached_user)()

        cached_user_manager.delete_multiple_cached_users.assert_called_once_with(emails)
        cached_user_manager.delete_cached_user.assert_not_called()

    def test_invalid_email_type_aborts_400(self, flask_app: Flask, cached_user_manager: MagicMock) -> None:
        """A non-string, non-list 'email' is rejected with 400."""
        del cached_user_manager  # only needed to activate the CachedUserManager patch

        with flask_app.test_request_context(CACHE_USER_ROUTE, method=DELETE_METHOD, json={'email': 5}):
            with pytest.raises(HTTPException) as exc_info:
                _unwrap(delete_cached_user)()

        assert exc_info.value.code == 400

    def test_missing_email_key_aborts_400(self, flask_app: Flask, cached_user_manager: MagicMock) -> None:
        """A payload without the 'email' key is rejected with 400."""
        del cached_user_manager  # only needed to activate the CachedUserManager patch

        with flask_app.test_request_context(CACHE_USER_ROUTE, method=DELETE_METHOD, json={'other': 'x'}):
            with pytest.raises(HTTPException) as exc_info:
                _unwrap(delete_cached_user)()

        assert exc_info.value.code == 400

    def test_empty_payload_aborts_400(self, flask_app: Flask, cached_user_manager: MagicMock) -> None:
        """An empty payload is rejected with 400 before touching the manager."""
        del cached_user_manager

        with flask_app.test_request_context(CACHE_USER_ROUTE, method=DELETE_METHOD, json={}):
            with pytest.raises(HTTPException) as exc_info:
                _unwrap(delete_cached_user)()

        assert exc_info.value.code == 400

    def test_non_object_body_aborts_400(self, flask_app: Flask, cached_user_manager: MagicMock) -> None:
        """A non-object JSON body (e.g. a bare list) is rejected with 400, not a 500."""
        del cached_user_manager

        with flask_app.test_request_context(CACHE_USER_ROUTE, method=DELETE_METHOD, json=['a@x.io']):
            with pytest.raises(HTTPException) as exc_info:
                _unwrap(delete_cached_user)()

        assert exc_info.value.code == 400
