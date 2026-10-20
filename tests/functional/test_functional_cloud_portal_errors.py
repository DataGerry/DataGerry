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
caller as itself. So the login's own arm for a database outage answers with its own message, a bug still gets the
generic 500, and the API-key channel answers as it always did
"""
import base64
from http import HTTPStatus

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.errors.database import DatabaseConnectionError
from cmdb.interface import route_utils
from tests.utils.cloud_mode import AUTHORIZATION_ENVIRON_KEY, enable_hosted_cloud_mode
# -------------------------------------------------------------------------------------------------------------------- #

LOGIN_URL: str = '/auth/login'
PROTECTED_URL: str = '/types/?limit=1'
EMAIL: str = 'portal-errors@x.io'
PASSWORD: str = 'portal-password'
API_KEY: str = 'the-api-key'

DATABASE_DOWN_MSG: str = 'Failed to establish a connection to the database!'
LOGIN_INTERNAL_ERROR_MSG: str = 'An internal server error occured while trying to login!'
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
        monkeypatch.setattr(route_utils, 'get_cached_user_manager', lambda: _FailingCache(failure))

    return _install


class TestCloudLogin:
    """POST /auth/login in hosted cloud mode, the real portal check failing at its cache read"""

    def test_a_database_outage_answers_with_its_own_message(self, rest_api, cache_fails_with) -> None:
        """cloud_login's DatabaseConnectionError arm is reachable: it used to see a bare Exception"""
        cache_fails_with(DatabaseConnectionError('cache down'))

        response = rest_api.post(LOGIN_URL, json={'user_name': EMAIL, 'password': PASSWORD})

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert response.get_json()['message'] == DATABASE_DOWN_MSG

    def test_a_bug_still_gets_the_generic_500(self, rest_api, cache_fails_with) -> None:
        """The contrast: nothing names a RuntimeError, so the login's catch-all answers"""
        cache_fails_with(RuntimeError('bug'))

        response = rest_api.post(LOGIN_URL, json={'user_name': EMAIL, 'password': PASSWORD})

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert response.get_json()['message'] == LOGIN_INTERNAL_ERROR_MSG


class TestApiKeyChannel:
    """A Basic + x-api-key request, whose check runs in verify_api_access"""

    def test_a_failed_check_still_answers_400(self, rest_api, cache_fails_with) -> None:
        """Unchanged: verify_api_access answers every failure of the check the same way"""
        cache_fails_with(DatabaseConnectionError('cache down'))
        credentials: str = base64.b64encode(f'{EMAIL}:{PASSWORD}'.encode()).decode('ascii')

        response = rest_api.get(
            PROTECTED_URL,
            headers={route_utils.API_KEY_HEADER: API_KEY},
            environ_overrides={AUTHORIZATION_ENVIRON_KEY: f'Basic {credentials}'},
        )

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'] == API_ACCESS_FAILED_MSG


def test_an_on_premise_bearer_request_is_still_served(rest_api) -> None:
    """The decorators no longer push an application context of their own; the frontend's channel is unaffected"""
    assert rest_api.get(PROTECTED_URL).status_code == HTTPStatus.OK
