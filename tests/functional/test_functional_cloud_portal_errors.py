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
Functional coverage of what the cloud entry points answer when the Service Portal check fails underneath

`check_user_in_service_portal` no longer wraps an unexpected error in a bare `Exception`: each error reaches its
caller as itself, and both entry points let a database failure through to the app's handlers: a lost connection is
the 503 (also inside the connector's own `DatabaseConnectionError`), a lock timeout the 423, any other connector
failure the 500 *"A database operation failed!"*, and a bug the app's 500 - the login's own outage message, its
catch-all and the API-key channel's blanket 400 are gone
"""
import base64
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from pymongo.errors import ConnectionFailure

from cmdb.errors.database import DatabaseConnectionError, DocumentLockTimeoutError, DocumentNetworkError
from cmdb.interface.rest_api.responses.error_handlers import (
    DATABASE_LOCKED_MSG,
    DATABASE_OPERATION_FAILED_MSG,
    DATABASE_UNAVAILABLE_MSG,
)
from cmdb.interface import cloud_user_helper, route_utils
from tests.utils.cloud_mode import AUTHORIZATION_ENVIRON_KEY, enable_hosted_cloud_mode
# -------------------------------------------------------------------------------------------------------------------- #

LOGIN_URL: str = '/auth/login'
PROTECTED_URL: str = '/types/?limit=1'
EMAIL: str = 'portal-errors@x.io'
PASSWORD: str = 'portal-password'
API_KEY: str = 'the-api-key'

OLD_DATABASE_DOWN_MSG: str = 'Failed to establish a connection to the database!'
OLD_LOGIN_INTERNAL_ERROR_MSG: str = 'An internal server error occured while trying to login!'
API_ACCESS_FAILED_MSG: str = 'Failed to verify API access!'


class _FailingCache:
    """A user cache whose first read fails with the given error"""

    def __init__(self, failure: Exception) -> None:
        """Keeps the error to raise"""
        self.failure = failure

    def cached_user_exists(self, _email: str) -> bool:
        """The read every portal check starts with"""
        raise self.failure


@pytest.fixture(name='cache_fails_with')
def fixture_cache_fails_with(rest_api, monkeypatch: pytest.MonkeyPatch, database_manager: MongoDatabaseManager):
    """Hosted cloud mode, with the user cache failing as the test asks"""
    enable_hosted_cloud_mode(rest_api, monkeypatch, database_manager)

    def _install(failure: Exception) -> None:
        monkeypatch.setattr(cloud_user_helper, 'get_cached_user_manager', lambda: _FailingCache(failure))

    return _install


def _connector_error(lost: bool) -> DatabaseConnectionError:
    """The connector's error - wrapping a lost connection, or not"""
    error = DatabaseConnectionError('cache down')

    if lost:
        error.__cause__ = ConnectionFailure('server gone')

    return error


def _login(rest_api) -> Any:
    """POSTs the cloud login"""
    return rest_api.post(LOGIN_URL, json={'user_name': EMAIL, 'password': PASSWORD})


def _api_key_request(rest_api) -> Any:
    """GETs a protected route on the API-key channel"""
    credentials: str = base64.b64encode(f'{EMAIL}:{PASSWORD}'.encode()).decode('ascii')

    return rest_api.get(
        PROTECTED_URL,
        headers={route_utils.API_KEY_HEADER: API_KEY},
        environ_overrides={AUTHORIZATION_ENVIRON_KEY: f'Basic {credentials}'},
    )


ENTRY_POINTS: list[Any] = [pytest.param(_login, id='login'), pytest.param(_api_key_request, id='api-key')]


@pytest.mark.parametrize('send', ENTRY_POINTS)
class TestADatabaseFailureReachesTheAppHandlers:
    """The real portal check failing at its user-cache read, on both cloud entry points"""

    @pytest.mark.parametrize('failure, status, message', [
        (DocumentNetworkError('lost'), HTTPStatus.SERVICE_UNAVAILABLE, DATABASE_UNAVAILABLE_MSG),
        (DocumentLockTimeoutError('locked'), HTTPStatus.LOCKED, DATABASE_LOCKED_MSG),
    ], ids=['network', 'lock'])
    def test_a_transient_failure_says_try_again(self, rest_api, cache_fails_with, send: Any, failure: Exception,
                                                status: HTTPStatus, message: str) -> None:
        """503 / 423 - the login answered both with its generic 500, the API-key channel with 400"""
        cache_fails_with(failure)

        response = send(rest_api)

        assert (response.status_code, response.get_json()['message']) == (status, message)

    @pytest.mark.parametrize('lost, status, message', [
        (True, HTTPStatus.SERVICE_UNAVAILABLE, DATABASE_UNAVAILABLE_MSG),
        (False, HTTPStatus.INTERNAL_SERVER_ERROR, DATABASE_OPERATION_FAILED_MSG),
    ], ids=['lost-connection', 'other-failure'])
    def test_the_connectors_error_is_judged_by_its_cause(self, rest_api, cache_fails_with, send: Any, lost: bool,
                                                         status: HTTPStatus, message: str) -> None:
        """One app handler: a lost connection inside it is the 503, anything else the 500"""
        cache_fails_with(_connector_error(lost))

        response = send(rest_api)

        assert (response.status_code, response.get_json()['message']) == (status, message)
        assert response.get_json()['message'] not in (OLD_DATABASE_DOWN_MSG, API_ACCESS_FAILED_MSG)

    def test_a_bug_is_the_apps_500(self, rest_api, cache_fails_with, monkeypatch, send: Any) -> None:
        """No entry point catches it wholesale any more - answered as production does"""
        monkeypatch.setitem(rest_api.application.config, 'PROPAGATE_EXCEPTIONS', False)
        cache_fails_with(RuntimeError('bug'))

        response = send(rest_api)

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert OLD_LOGIN_INTERNAL_ERROR_MSG not in response.get_data(as_text=True)
        assert API_ACCESS_FAILED_MSG not in response.get_data(as_text=True)


def test_an_on_premise_bearer_request_is_still_served(rest_api) -> None:
    """The decorators no longer push an application context of their own; the frontend's channel is unaffected"""
    assert rest_api.get(PROTECTED_URL).status_code == HTTPStatus.OK
