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
Functional tests for the Service-Portal setup / teardown routes (/setup)

Proves the three DELETE routes are mounted where the Service Portal calls them and answers end to
end. DELETE /setup/subscriptions runs for real against a throwaway database created by the test; the
two cache routes are driven with a stubbed CachedUserManager, because the real one always targets the
shared dg_caches database (the collection it would empty is not the test database's)
"""
from http import HTTPStatus
from typing import Iterator
from unittest.mock import MagicMock

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.interface.rest_api.routes.setup_routes import setup_routes as setup_routes_module
# -------------------------------------------------------------------------------------------------------------------- #

SUBSCRIPTIONS_ROUTE: str = '/setup/subscriptions'
CACHE_USER_ROUTE: str = '/setup/cache/user'
CACHE_USER_ALL_ROUTE: str = '/setup/cache/user/all'
THROWAWAY_DB: str = 'cmdb-test-setup-route-drop'
UNKNOWN_DB: str = 'cmdb-test-setup-route-unknown'
PROBE_COLLECTION: str = 'probe'
EMAIL: str = 'ftest@acme.com'


@pytest.fixture(name='throwaway_database')
def fixture_throwaway_database(database_manager: MongoDatabaseManager) -> Iterator[str]:
    """Creates a database the test may drop, and removes it again if the drop did not happen."""
    database_manager.get_collection(PROBE_COLLECTION, THROWAWAY_DB).insert_one({'seeded': True})

    yield THROWAWAY_DB

    database_manager.connector.client.drop_database(THROWAWAY_DB)


@pytest.fixture(name='cached_user_manager')
def fixture_cached_user_manager(monkeypatch) -> MagicMock:
    """Stubs CachedUserManager in the route module so the shared cache database is not touched."""
    manager = MagicMock()
    monkeypatch.setattr(setup_routes_module, 'CachedUserManager', MagicMock(return_value=manager))

    return manager


class TestDeleteSubscription:
    """DELETE /setup/subscriptions drops the database named by the query parameter."""

    def test_drops_the_database(
        self,
        rest_api,
        database_manager: MongoDatabaseManager,
        throwaway_database: str,
    ) -> None:
        """The named database is really gone afterwards."""
        response = rest_api.delete(f'{SUBSCRIPTIONS_ROUTE}?database={throwaway_database}')

        assert response.status_code == HTTPStatus.OK
        assert response.get_json() is True
        assert throwaway_database not in database_manager.connector.client.list_database_names()

    def test_missing_database_parameter_returns_400(self, rest_api) -> None:
        """A call without the 'database' query parameter is refused."""
        assert rest_api.delete(SUBSCRIPTIONS_ROUTE).status_code == HTTPStatus.BAD_REQUEST

    def test_unknown_database_returns_400(self, rest_api) -> None:
        """Naming a database that does not exist is a client error."""
        response = rest_api.delete(f'{SUBSCRIPTIONS_ROUTE}?database={UNKNOWN_DB}')

        assert response.status_code == HTTPStatus.BAD_REQUEST


class TestDeleteCachedUser:
    """DELETE /setup/cache/user evicts cached cloud users."""

    def test_single_email_is_evicted(self, rest_api, cached_user_manager: MagicMock) -> None:
        """A string payload reaches delete_cached_user."""
        response = rest_api.delete(CACHE_USER_ROUTE, json={'email': EMAIL})

        assert response.status_code == HTTPStatus.OK
        cached_user_manager.delete_cached_user.assert_called_once_with(EMAIL)

    def test_email_list_is_evicted(self, rest_api, cached_user_manager: MagicMock) -> None:
        """A list payload reaches delete_multiple_cached_users."""
        emails = [EMAIL, 'ftest2@acme.com']

        response = rest_api.delete(CACHE_USER_ROUTE, json={'email': emails})

        assert response.status_code == HTTPStatus.OK
        cached_user_manager.delete_multiple_cached_users.assert_called_once_with(emails)

    def test_payload_without_email_returns_400(self, rest_api, cached_user_manager: MagicMock) -> None:
        """A payload missing the 'email' key is refused before the manager is used."""
        response = rest_api.delete(CACHE_USER_ROUTE, json={'other': 'x'})

        assert response.status_code == HTTPStatus.BAD_REQUEST
        cached_user_manager.delete_cached_user.assert_not_called()


class TestDeleteAllCachedUsers:
    """DELETE /setup/cache/user/all clears the whole cloud user cache."""

    def test_clears_the_cache(self, rest_api, cached_user_manager: MagicMock) -> None:
        """The route answers True and the cache is cleared."""
        response = rest_api.delete(CACHE_USER_ALL_ROUTE)

        assert response.status_code == HTTPStatus.OK
        assert response.get_json() is True
        cached_user_manager.clear_cache.assert_called_once_with()
