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

Each handler is unwrapped past verify_api_access - keeping handle_route_errors, its error tail - and driven inside a
Flask test_request_context; the cached-user manager is patched at the route module path
(`get_cached_user_manager`) and the database drop goes through the app's MagicMock database_manager,
so no MongoDB is involved

Pinned here: the error mapping of all three routes (a missing database only produces a 400, a failed
drop a 500), delete_cached_user's payload branches - in particular that a LIST of emails deletes
multiple cached users (an isinstance(..., list[str]) check would raise TypeError -> 500) - and that
an HTTPException raised by a collaborator keeps its own status instead of being flattened into a 500.
Every route answers the flat ``true`` and logs its outcome at INFO; an eviction's addresses are normalised and
each entry must be a non-empty string
"""
import logging
from typing import Any, Callable, Iterator
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask
from werkzeug.exceptions import HTTPException, NotFound, Unauthorized

from cmdb.database.database_constants import DG_CACHE_DB
from cmdb.models.type_model import CmdbType
from cmdb.errors.database import DatabaseNotFoundError, DatabaseConnectionError
from cmdb.interface.rest_api.routes.setup_routes.setup_constants import SetupMessage
from cmdb.interface.rest_api.routes.setup_routes.setup_routes import (
    delete_subscription,
    delete_cached_user,
    delete_all_cached_users,
    refuse_anything_but_portal_credentials,
    refuse_outside_cloud_mode,
    NOT_IN_CLOUD_MODE_MESSAGE,
    PORTAL_CREDENTIALS_ONLY_MESSAGE,
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
    """
    Strips verify_api_access to reach the handler as handle_route_errors wraps it

    One layer only: the route's error tail is the decorator below it, and the error mapping is part of what these
    tests pin
    """
    return func.__wrapped__


PROCESS_DB: str = 'cmdb_process'


def _database_manager(tenant_shaped: bool = True, exists: bool = True) -> MagicMock:
    """A database manager whose named database exists and holds framework.types unless told otherwise"""
    dbm = MagicMock()
    dbm.db_name = PROCESS_DB
    dbm.check_database_exists.return_value = exists
    dbm.connector.get_database.return_value.list_collection_names.return_value = (
        [CmdbType.COLLECTION] if tenant_shaped else []
    )
    return dbm


@pytest.fixture(name='flask_app')
def fixture_flask_app() -> Flask:
    """A minimal Flask app exposing a database_manager for the drop and for manager construction."""
    app = Flask(__name__)
    app.database_manager = _database_manager()

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
        which a per-handler check would rely on someone remembering. A per-route guard that is inert in
        one mode publishes this whole surface.

        The blueprint is mounted on a throwaway app here precisely because the real one does not mount
        it outside cloud mode.
        """
        from cmdb.interface.rest_api.routes.setup_routes.setup_routes import setup_blueprint

        app = Flask(__name__)
        app.cloud_mode = False
        app.database_manager = MagicMock()
        app.register_blueprint(setup_blueprint, url_prefix='/setup')

        assert app.test_client().delete(f'/setup{route}').status_code == NotFound.code


class TestThePathsAreThePortalContract:
    """
    The three paths, spelled exactly as the Service Portal calls them: no trailing slash

    With strict_slashes on - as the REST app sets it - the slash form is a 404, not a redirect. Pinned so a change to
    the spelling is a deliberate change of the portal's contract, not a tidy-up
    """

    @staticmethod
    def _app() -> Flask:
        """The blueprint on a cloud-mode app with the REST app's slash setting"""
        from cmdb.interface.rest_api.routes.setup_routes.setup_routes import setup_blueprint

        app = Flask(__name__)
        app.url_map.strict_slashes = True
        app.cloud_mode = True
        app.database_manager = _database_manager()
        app.register_blueprint(setup_blueprint, url_prefix='/setup')

        return app

    def test_exactly_the_three_documented_paths_are_registered(self) -> None:
        """No slash variant, no fourth route"""
        rules: set[str] = {rule.rule for rule in self._app().url_map.iter_rules() if rule.rule.startswith('/setup')}

        assert rules == {f'/setup{route}' for route in (SUBSCRIPTIONS_ROUTE, CACHE_USER_ROUTE, CACHE_USER_ALL_ROUTE)}

    @pytest.mark.parametrize('route', [SUBSCRIPTIONS_ROUTE, CACHE_USER_ROUTE, CACHE_USER_ALL_ROUTE])
    def test_the_slash_form_is_a_404_that_runs_nothing(self, route: str) -> None:
        """Routing answers before any guard or handler: no drop, no cache manager"""
        app = self._app()

        with patch(f'{ROUTE_PATH}.get_cached_user_manager') as cache_builder:
            response = app.test_client().delete(f'/setup{route}/', headers={'Authorization': 'Basic cDpw'})

        assert response.status_code == NotFound.code
        app.database_manager.drop_database.assert_not_called()
        cache_builder.assert_not_called()


class TestThePortalCredentialsGuard:
    """
    The second `before_request`: only HTTP Basic - the Service Portal's channel - reaches a handler

    verify_api_access passes a Bearer request through untouched, and these routes have no insert_request_user to
    validate the token, so without this guard any Bearer header reached the teardown handlers.
    """

    @pytest.mark.parametrize('authorization', [None, 'Bearer not-a-token', 'Bearer eyJhbGciOiJSUzI1NiJ9.e30.sig',
                                               'Digest username="x"', 'Token abc', ''],
                             ids=['none', 'bearer-garbage', 'bearer-jwt-shaped', 'digest', 'token', 'empty'])
    def test_anything_but_basic_is_refused(self, flask_app: Flask, authorization: str | None) -> None:
        """401 - a tenant user's token, however privileged, is not the portal"""
        headers: dict[str, str] = {} if authorization is None else {'Authorization': authorization}

        with flask_app.test_request_context(SUBSCRIPTIONS_ROUTE, method=DELETE_METHOD, headers=headers):
            with pytest.raises(HTTPException) as err:
                refuse_anything_but_portal_credentials()

        assert err.value.code == Unauthorized.code
        assert err.value.description == PORTAL_CREDENTIALS_ONLY_MESSAGE

    @pytest.mark.parametrize('scheme', ['Basic', 'basic'])
    def test_basic_credentials_pass_to_the_portal_check(self, flask_app: Flask, scheme: str) -> None:
        """The portal's channel goes on to verify_api_access, which checks it with the portal"""
        headers: dict[str, str] = {'Authorization': f'{scheme} cG9ydGFsOnB3'}

        with flask_app.test_request_context(SUBSCRIPTIONS_ROUTE, method=DELETE_METHOD, headers=headers):
            assert refuse_anything_but_portal_credentials() is None

    @pytest.mark.parametrize('route', [SUBSCRIPTIONS_ROUTE, CACHE_USER_ROUTE, CACHE_USER_ALL_ROUTE])
    def test_it_covers_every_route_on_the_blueprint_in_cloud_mode(self, route: str) -> None:
        """
        Blueprint-wide: a Bearer request reaches no handler, and no manager is built

        In cloud mode, where the routes exist - the first guard passes and this one refuses
        """
        from cmdb.interface.rest_api.routes.setup_routes.setup_routes import setup_blueprint

        app = Flask(__name__)
        app.cloud_mode = True
        app.database_manager = MagicMock()
        app.register_blueprint(setup_blueprint, url_prefix='/setup')

        with patch(f'{ROUTE_PATH}.get_cached_user_manager') as cache_builder:
            response = app.test_client().delete(
                f'/setup{route}?{DATABASE_PARAM}={DB_NAME}',
                headers={'Authorization': 'Bearer anything'},
                json={'email': 'a@x.io'},
            )

        assert response.status_code == Unauthorized.code
        app.database_manager.drop_database.assert_not_called()
        cache_builder.assert_not_called()


class TestDeleteSubscription:
    """delete_subscription drops the database named by the 'database' query parameter."""

    def test_drops_the_named_database(self, flask_app: Flask, caplog: pytest.LogCaptureFixture) -> None:
        """The database name from the query parameter is dropped, True is answered and the drop is logged."""
        route = f'{SUBSCRIPTIONS_ROUTE}?{DATABASE_PARAM}={DB_NAME}'

        with caplog.at_level(logging.INFO, logger=ROUTE_PATH), \
             flask_app.test_request_context(route, method=DELETE_METHOD):
            response = _unwrap(delete_subscription)()

        flask_app.database_manager.drop_database.assert_called_once_with(DB_NAME)
        assert response.status_code == OK_STATUS
        assert response.get_json() is True
        assert f"Dropped the database '{DB_NAME}'" in caplog.text

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


class TestOnlyATenantDatabaseIsDropped:
    """delete_subscription drops nothing but an existing DataGerry tenant database (assert_tenant_database)"""

    @pytest.mark.parametrize('database', ['admin', 'config', 'local', DG_CACHE_DB, PROCESS_DB],
                             ids=['admin', 'config', 'local', 'user-cache', 'process-database'])
    def test_a_reserved_database_is_a_400_and_not_dropped(
            self, flask_app: Flask, database: str, caplog: pytest.LogCaptureFixture) -> None:
        """Refused by name, before anything is asked of the server - and the refusal is logged"""
        with caplog.at_level(logging.WARNING), \
             flask_app.test_request_context(f'{SUBSCRIPTIONS_ROUTE}?{DATABASE_PARAM}={database}', method=DELETE_METHOD):
            with pytest.raises(HTTPException) as exc_info:
                _unwrap(delete_subscription)()

        assert exc_info.value.code == 400
        assert exc_info.value.description == SetupMessage.RESERVED_DATABASE.value.format(database=database)
        flask_app.database_manager.drop_database.assert_not_called()
        flask_app.database_manager.check_database_exists.assert_not_called()
        assert f"reserved database '{database}'" in caplog.text

    def test_a_database_without_framework_collections_is_a_400_and_not_dropped(
            self, flask_app: Flask, caplog: pytest.LogCaptureFixture) -> None:
        """Another application's database on the same cluster"""
        flask_app.database_manager = _database_manager(tenant_shaped=False)

        with caplog.at_level(logging.WARNING), \
             flask_app.test_request_context(f'{SUBSCRIPTIONS_ROUTE}?{DATABASE_PARAM}={DB_NAME}', method=DELETE_METHOD):
            with pytest.raises(HTTPException) as exc_info:
                _unwrap(delete_subscription)()

        assert exc_info.value.code == 400
        assert exc_info.value.description == SetupMessage.NOT_A_TENANT_DATABASE.value.format(database=DB_NAME)
        flask_app.database_manager.drop_database.assert_not_called()
        flask_app.database_manager.connector.get_database.assert_called_once_with(DB_NAME)
        assert 'no DataGerry tenant database' in caplog.text

    def test_an_unknown_database_is_a_400_before_its_shape_is_asked(self, flask_app: Flask) -> None:
        """The existing 'does not exist' answer, not 'not a tenant'"""
        flask_app.database_manager = _database_manager(exists=False)

        with flask_app.test_request_context(f'{SUBSCRIPTIONS_ROUTE}?{DATABASE_PARAM}={DB_NAME}', method=DELETE_METHOD):
            with pytest.raises(HTTPException) as exc_info:
                _unwrap(delete_subscription)()

        assert exc_info.value.description == SetupMessage.UNKNOWN_DATABASE.value.format(database=DB_NAME)
        flask_app.database_manager.connector.get_database.assert_not_called()
        flask_app.database_manager.drop_database.assert_not_called()

    def test_the_shape_is_asked_for_framework_types_only(self, flask_app: Flask) -> None:
        """One filtered listing, not the whole collection list"""
        with flask_app.test_request_context(f'{SUBSCRIPTIONS_ROUTE}?{DATABASE_PARAM}={DB_NAME}', method=DELETE_METHOD):
            _unwrap(delete_subscription)()

        listing = flask_app.database_manager.connector.get_database.return_value.list_collection_names
        listing.assert_called_once_with(filter={'name': CmdbType.COLLECTION})
        flask_app.database_manager.drop_database.assert_called_once_with(DB_NAME)


class TestDeleteCachedUser:
    """delete_cached_user branches on the 'email' payload type."""

    def test_single_email_deletes_one(self, flask_app: Flask, cached_user_manager: MagicMock) -> None:
        """A string 'email' evicts exactly that cached user, answered with the flat true."""
        cached_user_manager.delete_multiple_cached_users.return_value = 1

        with flask_app.test_request_context(CACHE_USER_ROUTE, method=DELETE_METHOD, json={'email': 'a@x.io'}):
            response = _unwrap(delete_cached_user)()

        cached_user_manager.delete_multiple_cached_users.assert_called_once_with(['a@x.io'])
        assert response.status_code == OK_STATUS
        assert response.get_json() is True

    def test_list_of_emails_deletes_multiple(self, flask_app: Flask, cached_user_manager: MagicMock) -> None:
        """A list 'email' deletes multiple cached users rather than failing with a TypeError -> 500."""
        emails = ['a@x.io', 'b@x.io']
        cached_user_manager.delete_multiple_cached_users.return_value = 2

        with flask_app.test_request_context(CACHE_USER_ROUTE, method=DELETE_METHOD, json={'email': emails}):
            _unwrap(delete_cached_user)()

        cached_user_manager.delete_multiple_cached_users.assert_called_once_with(emails)

    def test_addresses_are_normalised_and_deduplicated(
            self, flask_app: Flask, cached_user_manager: MagicMock) -> None:
        """Stripped and lower-cased like every cloud entry point spells them, each once, in the order sent"""
        cached_user_manager.delete_multiple_cached_users.return_value = 2
        body: dict[str, Any] = {'email': ['  User@Acme.com ', 'b@x.io', 'user@acme.com']}

        with flask_app.test_request_context(CACHE_USER_ROUTE, method=DELETE_METHOD, json=body):
            _unwrap(delete_cached_user)()

        cached_user_manager.delete_multiple_cached_users.assert_called_once_with(['user@acme.com', 'b@x.io'])

    def test_a_single_address_is_normalised_too(self, flask_app: Flask, cached_user_manager: MagicMock) -> None:
        """The teardown of a differently-cased address used to leave the cached entry in place"""
        cached_user_manager.delete_multiple_cached_users.return_value = 1

        with flask_app.test_request_context(CACHE_USER_ROUTE, method=DELETE_METHOD, json={'email': ' A@X.io'}):
            _unwrap(delete_cached_user)()

        cached_user_manager.delete_multiple_cached_users.assert_called_once_with(['a@x.io'])

    @pytest.mark.parametrize('email', [[], '', '   ', ['a@x.io', ''], ['a@x.io', 7], [None], [{'$ne': None}]],
                             ids=['empty-list', 'empty-string', 'blank-string', 'empty-entry', 'number-entry',
                                  'null-entry', 'operator-entry'])
    def test_an_unusable_address_is_a_400_and_nothing_is_evicted(
            self, flask_app: Flask, cached_user_manager: MagicMock, email: Any) -> None:
        """The portal sends strings; anything else is refused before the cache is touched"""
        with flask_app.test_request_context(CACHE_USER_ROUTE, method=DELETE_METHOD, json={'email': email}):
            with pytest.raises(HTTPException) as exc_info:
                _unwrap(delete_cached_user)()

        assert exc_info.value.code == 400
        cached_user_manager.delete_multiple_cached_users.assert_not_called()

    def test_the_refusal_names_the_bad_positions(self, flask_app: Flask, cached_user_manager: MagicMock) -> None:
        """A long teardown list can be fixed from the message"""
        del cached_user_manager
        body: dict[str, Any] = {'email': ['a@x.io', 3, 'b@x.io', '']}

        with flask_app.test_request_context(CACHE_USER_ROUTE, method=DELETE_METHOD, json=body):
            with pytest.raises(HTTPException) as exc_info:
                _unwrap(delete_cached_user)()

        assert exc_info.value.description == SetupMessage.EMAIL_ITEMS.value.format(positions='1, 3')

    def test_the_outcome_is_logged(
            self, flask_app: Flask, cached_user_manager: MagicMock, caplog: pytest.LogCaptureFixture) -> None:
        """'Evicted 1 of 2' - the answer is true either way, the log tells them apart"""
        cached_user_manager.delete_multiple_cached_users.return_value = 1

        with caplog.at_level(logging.INFO, logger=ROUTE_PATH), \
             flask_app.test_request_context(CACHE_USER_ROUTE, method=DELETE_METHOD,
                                            json={'email': ['a@x.io', 'b@x.io']}):
            _unwrap(delete_cached_user)()

        assert 'Evicted 1 of 2 requested cached users' in caplog.text

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
        cached_user_manager.delete_multiple_cached_users.side_effect = RuntimeError('boom')

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
        A KeyError from the manager is a 500, not a 400

        The 'email' lookup and the manager calls must not share one try/except KeyError, or a KeyError
        raised inside the manager is answered with "'email' key not provided in the request payload!"
        """
        cached_user_manager.delete_multiple_cached_users.side_effect = KeyError('subscriptions')

        with flask_app.test_request_context(CACHE_USER_ROUTE, method=DELETE_METHOD, json={'email': 'a@x.io'}):
            with pytest.raises(HTTPException) as exc_info:
                _unwrap(delete_cached_user)()

        assert exc_info.value.code == 500


class TestDeleteAllCachedUsers:
    """delete_all_cached_users empties the whole cloud user cache."""

    def test_clears_the_cache(self, flask_app: Flask, cached_user_manager: MagicMock) -> None:
        """The cache is cleared and True is answered."""
        cached_user_manager.clear_cache.return_value = 0

        with flask_app.test_request_context(CACHE_USER_ALL_ROUTE, method=DELETE_METHOD):
            response = _unwrap(delete_all_cached_users)()

        cached_user_manager.clear_cache.assert_called_once_with()
        assert response.status_code == OK_STATUS
        assert response.get_json() is True

    def test_the_count_is_logged(
            self, flask_app: Flask, cached_user_manager: MagicMock, caplog: pytest.LogCaptureFixture) -> None:
        """The number removed reaches the log, not the body"""
        cached_user_manager.clear_cache.return_value = 40

        with caplog.at_level(logging.INFO, logger=ROUTE_PATH), \
             flask_app.test_request_context(CACHE_USER_ALL_ROUTE, method=DELETE_METHOD):
            _unwrap(delete_all_cached_users)()

        assert 'Cleared 40 cached users' in caplog.text

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
