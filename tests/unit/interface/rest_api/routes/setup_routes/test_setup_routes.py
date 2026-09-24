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
Unit tests for cmdb.interface.rest_api.routes.setup_routes.setup_routes

Each handler is unwrapped past its decorator chain (route / verify_api_access) and driven inside a
Flask test_request_context; the cached-user manager is patched at the route module path (`get_cached_user_manager`) and the database
drop goes through the app's MagicMock database_manager, so no MongoDB is involved

Pinned here: the error mapping of all three routes (a missing database only produces a 400, a failed
drop a 500), delete_cached_user's payload branches - in particular that a LIST of emails deletes
multiple cached users (previously broken by an isinstance(..., list[str]) check that raised
TypeError -> 500) - and that an HTTPException raised by a collaborator keeps its own status instead
of being flattened into a 500
"""
from typing import Any, Callable, Iterator
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask
from werkzeug.exceptions import HTTPException, NotFound

from cmdb.errors.database import DatabaseNotFoundError, DatabaseConnectionError
from cmdb.interface.rest_api.routes.setup_routes.setup_routes import (
    delete_subscription,
    delete_cached_user,
    delete_all_cached_users,
    refuse_outside_cloud_mode,
    NOT_IN_CLOUD_MODE_MESSAGE,
)
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_PATH: str = 'cmdb.interface.rest_api.routes.setup_routes.setup_routes'
SUBSCRIPTIONS_ROUTE: str = '/subscriptions'
CACHE_USER_ROUTE: str = '/cache/user'
CACHE_USER_ALL_ROUTE: str = '/cache/user/all'
DELETE_METHOD: str = 'DELETE'
DATABASE_PARAM: str = 'database'
DB_NAME: str = 'tenant_db'
OK_STATUS: int = 200


def _unwrap(func: Callable[..., Any]) -> Callable[..., Any]:
    """Strips the decorator chain (route / verify_api_access) to reach the raw handler."""
    inner = func

    while hasattr(inner, '__wrapped__'):
        inner = inner.__wrapped__

    return inner


@pytest.fixture(name='flask_app')
def fixture_flask_app() -> Flask:
    """A minimal Flask app exposing a database_manager for the drop and for manager construction."""
    app = Flask(__name__)
    app.database_manager = MagicMock()

    return app


@pytest.fixture(name='cached_user_manager')
def fixture_cached_user_manager() -> Iterator[MagicMock]:
    """Patches `get_cached_user_manager` at the route path and yields the manager instance mock."""
    manager = MagicMock()

    with patch(f'{ROUTE_PATH}.get_cached_user_manager', return_value=manager):
        yield manager


class TestTheCloudModeBackstop:
    """
    The `before_request` guard on the blueprint

    It is a backstop, not the primary control: `init_rest_api` does not register this blueprint
    outside cloud mode, so in normal operation it never runs. That makes it unreachable through the
    app, which is why it is exercised directly here - a guard nobody can call is worth having only if
    something proves it works.
    """

    def test_it_refuses_outside_cloud_mode(self, flask_app: Flask) -> None:
        """The whole point: on-premise this surface does not exist."""
        flask_app.cloud_mode = False

        with flask_app.test_request_context(SUBSCRIPTIONS_ROUTE, method=DELETE_METHOD):
            with pytest.raises(HTTPException) as err:
                refuse_outside_cloud_mode()

        assert err.value.code == NotFound.code

    def test_the_refusal_says_why(self, flask_app: Flask) -> None:
        """404 rather than a bare one, so an operator is not left guessing."""
        flask_app.cloud_mode = False

        with flask_app.test_request_context(SUBSCRIPTIONS_ROUTE, method=DELETE_METHOD):
            with pytest.raises(HTTPException) as err:
                refuse_outside_cloud_mode()

        assert NOT_IN_CLOUD_MODE_MESSAGE in str(err.value)

    def test_it_passes_in_cloud_mode(self, flask_app: Flask) -> None:
        """Where the routes do belong, the backstop must be invisible."""
        flask_app.cloud_mode = True

        with flask_app.test_request_context(SUBSCRIPTIONS_ROUTE, method=DELETE_METHOD):
            assert refuse_outside_cloud_mode() is None

    @pytest.mark.parametrize('route', [SUBSCRIPTIONS_ROUTE, CACHE_USER_ROUTE, CACHE_USER_ALL_ROUTE])
    def test_it_covers_every_route_on_the_blueprint(self, route: str) -> None:
        """
        Blueprint-wide is the point

        Registered on the blueprint, so EVERY route it carries is covered - including one added later,
        which a per-handler check would rely on someone remembering. A per-route guard that was relied
        on, and was inert in one mode, is what published this surface in the first place.

        The blueprint is mounted on a throwaway app here precisely because the real one does not mount
        it outside cloud mode.
        """
        from cmdb.interface.rest_api.routes.setup_routes.setup_routes import setup_blueprint

        app = Flask(__name__)
        app.cloud_mode = False
        app.database_manager = MagicMock()
        app.register_blueprint(setup_blueprint, url_prefix='/setup')

        assert app.test_client().delete(f'/setup{route}').status_code == NotFound.code


class TestDeleteSubscription:
    """delete_subscription drops the database named by the 'database' query parameter."""

    def test_drops_the_named_database(self, flask_app: Flask) -> None:
        """The database name from the query parameter is dropped and True is answered."""
        route = f'{SUBSCRIPTIONS_ROUTE}?{DATABASE_PARAM}={DB_NAME}'

        with flask_app.test_request_context(route, method=DELETE_METHOD):
            response = _unwrap(delete_subscription)()

        flask_app.database_manager.drop_database.assert_called_once_with(DB_NAME)
        assert response.status_code == OK_STATUS

    def test_missing_query_arguments_abort_400(self, flask_app: Flask) -> None:
        """A request without any query argument is rejected with 400."""
        with flask_app.test_request_context(SUBSCRIPTIONS_ROUTE, method=DELETE_METHOD):
            with pytest.raises(HTTPException) as exc_info:
                _unwrap(delete_subscription)()

        assert exc_info.value.code == 400
        flask_app.database_manager.drop_database.assert_not_called()

    def test_missing_database_argument_aborts_400(self, flask_app: Flask) -> None:
        """Query arguments without the 'database' one are rejected with 400."""
        with flask_app.test_request_context(f'{SUBSCRIPTIONS_ROUTE}?other=x', method=DELETE_METHOD):
            with pytest.raises(HTTPException) as exc_info:
                _unwrap(delete_subscription)()

        assert exc_info.value.code == 400
        flask_app.database_manager.drop_database.assert_not_called()

    def test_empty_database_argument_aborts_400(self, flask_app: Flask) -> None:
        """An empty '?database=' is rejected with 400 instead of reaching the drop."""
        with flask_app.test_request_context(f'{SUBSCRIPTIONS_ROUTE}?{DATABASE_PARAM}=', method=DELETE_METHOD):
            with pytest.raises(HTTPException) as exc_info:
                _unwrap(delete_subscription)()

        assert exc_info.value.code == 400
        flask_app.database_manager.drop_database.assert_not_called()

    def test_unknown_database_aborts_400(self, flask_app: Flask) -> None:
        """An unknown database name is a client error (400)."""
        flask_app.database_manager.drop_database.side_effect = DatabaseNotFoundError(DB_NAME)
        route = f'{SUBSCRIPTIONS_ROUTE}?{DATABASE_PARAM}={DB_NAME}'

        with flask_app.test_request_context(route, method=DELETE_METHOD):
            with pytest.raises(HTTPException) as exc_info:
                _unwrap(delete_subscription)()

        assert exc_info.value.code == 400

    def test_failed_drop_aborts_500(self, flask_app: Flask) -> None:
        """
        A failing drop is a server error (500)

        Regression: it must not be reported as 400 'database does not exist', which delete_database
        collapsed every failure - a connection failure included - into DatabaseNotFoundError
        """
        flask_app.database_manager.drop_database.side_effect = DatabaseConnectionError('down')
        route = f'{SUBSCRIPTIONS_ROUTE}?{DATABASE_PARAM}={DB_NAME}'

        with flask_app.test_request_context(route, method=DELETE_METHOD):
            with pytest.raises(HTTPException) as exc_info:
                _unwrap(delete_subscription)()

        assert exc_info.value.code == 500

    def test_unexpected_error_aborts_500(self, flask_app: Flask) -> None:
        """An unmapped error from the drop reaches the outer handler as a 500."""
        flask_app.database_manager.drop_database.side_effect = RuntimeError('boom')
        route = f'{SUBSCRIPTIONS_ROUTE}?{DATABASE_PARAM}={DB_NAME}'

        with flask_app.test_request_context(route, method=DELETE_METHOD):
            with pytest.raises(HTTPException) as exc_info:
                _unwrap(delete_subscription)()

        assert exc_info.value.code == 500


class TestDeleteCachedUser:
    """delete_cached_user branches on the 'email' payload type."""

    def test_single_email_deletes_one(self, flask_app: Flask, cached_user_manager: MagicMock) -> None:
        """A string 'email' deletes exactly that cached user."""
        with flask_app.test_request_context(CACHE_USER_ROUTE, method=DELETE_METHOD, json={'email': 'a@x.io'}):
            response = _unwrap(delete_cached_user)()

        cached_user_manager.delete_cached_user.assert_called_once_with('a@x.io')
        cached_user_manager.delete_multiple_cached_users.assert_not_called()
        assert response.status_code == OK_STATUS

    def test_list_of_emails_deletes_multiple(self, flask_app: Flask, cached_user_manager: MagicMock) -> None:
        """A list 'email' deletes multiple cached users (regression: was a TypeError -> 500)."""
        emails = ['a@x.io', 'b@x.io']

        with flask_app.test_request_context(CACHE_USER_ROUTE, method=DELETE_METHOD, json={'email': emails}):
            _unwrap(delete_cached_user)()

        cached_user_manager.delete_multiple_cached_users.assert_called_once_with(emails)
        cached_user_manager.delete_cached_user.assert_not_called()

    def test_invalid_email_type_aborts_400(self, flask_app: Flask, cached_user_manager: MagicMock) -> None:
        """A non-string, non-list 'email' is rejected with 400."""
        del cached_user_manager  # only needed to activate the get_cached_user_manager patch

        with flask_app.test_request_context(CACHE_USER_ROUTE, method=DELETE_METHOD, json={'email': 5}):
            with pytest.raises(HTTPException) as exc_info:
                _unwrap(delete_cached_user)()

        assert exc_info.value.code == 400

    def test_missing_email_key_aborts_400(self, flask_app: Flask, cached_user_manager: MagicMock) -> None:
        """A payload without the 'email' key is rejected with 400."""
        del cached_user_manager  # only needed to activate the get_cached_user_manager patch

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

    def test_manager_error_aborts_500(self, flask_app: Flask, cached_user_manager: MagicMock) -> None:
        """A failing eviction is a 500."""
        cached_user_manager.delete_cached_user.side_effect = RuntimeError('boom')

        with flask_app.test_request_context(CACHE_USER_ROUTE, method=DELETE_METHOD, json={'email': 'a@x.io'}):
            with pytest.raises(HTTPException) as exc_info:
                _unwrap(delete_cached_user)()

        assert exc_info.value.code == 500

    def test_manager_key_error_is_not_reported_as_a_missing_email(
        self,
        flask_app: Flask,
        cached_user_manager: MagicMock,
    ) -> None:
        """
        A KeyError from the manager is a 500, not a 400 (regression)

        The 'email' lookup and the manager calls must not share one try/except KeyError, or a KeyError
        raised inside the manager was answered with "'email' key not provided in the request payload!"
        """
        cached_user_manager.delete_cached_user.side_effect = KeyError('subscriptions')

        with flask_app.test_request_context(CACHE_USER_ROUTE, method=DELETE_METHOD, json={'email': 'a@x.io'}):
            with pytest.raises(HTTPException) as exc_info:
                _unwrap(delete_cached_user)()

        assert exc_info.value.code == 500


class TestDeleteAllCachedUsers:
    """delete_all_cached_users empties the whole cloud user cache."""

    def test_clears_the_cache(self, flask_app: Flask, cached_user_manager: MagicMock) -> None:
        """The cache is cleared and True is answered."""
        with flask_app.test_request_context(CACHE_USER_ALL_ROUTE, method=DELETE_METHOD):
            response = _unwrap(delete_all_cached_users)()

        cached_user_manager.clear_cache.assert_called_once_with()
        assert response.status_code == OK_STATUS

    def test_manager_error_aborts_500(self, flask_app: Flask, cached_user_manager: MagicMock) -> None:
        """A failing clear is a 500."""
        cached_user_manager.clear_cache.side_effect = RuntimeError('boom')

        with flask_app.test_request_context(CACHE_USER_ALL_ROUTE, method=DELETE_METHOD):
            with pytest.raises(HTTPException) as exc_info:
                _unwrap(delete_all_cached_users)()

        assert exc_info.value.code == 500

    def test_http_exception_keeps_its_status(self, flask_app: Flask, cached_user_manager: MagicMock) -> None:
        """An HTTPException from a collaborator passes through instead of becoming a 500."""
        cached_user_manager.clear_cache.side_effect = NotFound()

        with flask_app.test_request_context(CACHE_USER_ALL_ROUTE, method=DELETE_METHOD):
            with pytest.raises(HTTPException) as exc_info:
                _unwrap(delete_all_cached_users)()

        assert exc_info.value.code == 404
