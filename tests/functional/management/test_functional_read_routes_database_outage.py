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
Functional tests: five read routes answer a temporary database failure with the app's 503 / 423, never a 500

`GET /users/`, `/persons/`, `/person_groups/`, `/auth/settings` and `/auth/providers`. The failure is raised where it
really starts - the database manager's aggregation (the lists) or its read of the `auth` settings section - so the
managers in between are the real ones and must let it through unwrapped; the route's `handle_route_errors` then
leaves it to the app's handlers. An unexpected error still answers the route's own 500, worded as it always was
"""
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database.mongo_database_manager import MongoDatabaseManager
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.manager.system_manager.settings_manager import SettingsManager
from cmdb.models.security_models.auth_settings_constants import AUTH_SETTINGS_ID
from cmdb.errors.database import DocumentLockTimeoutError, DocumentNetworkError
# -------------------------------------------------------------------------------------------------------------------- #

LIST_URLS: list[str] = ['/users/', '/persons/', '/person_groups/']
AUTH_URLS: list[str] = ['/auth/settings', '/auth/providers']
TRANSIENT_ANSWERS: list[tuple[type[Exception], HTTPStatus]] = [
    (DocumentNetworkError, HTTPStatus.SERVICE_UNAVAILABLE),
    (DocumentLockTimeoutError, HTTPStatus.LOCKED),
]
TRANSIENT_IDS: list[str] = ['network-503', 'lock-423']
# The 500 each route answers for an unexpected error - its wording kept from before the decorator
UNEXPECTED_MESSAGES: dict[str, str] = {
    '/users/': 'An internal server error occured while iterating the requested Users!',
    '/persons/': 'An internal server error occured while retrieving Persons!',
    '/person_groups/': 'An internal server error occured while retrieving PersonGroups!',
    '/auth/settings': 'An internal server error occured while retrieving auth settings!',
    '/auth/providers': 'An internal server error occured while retrieving installed providers!',
}


@pytest.fixture(autouse=True)
def _licensed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Persons and person groups sit behind the ISMS licence - every feature licensed"""
    monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, _feature: True)


def _fail_lists(monkeypatch: pytest.MonkeyPatch, failure: Exception) -> None:
    """Every aggregation raises `failure` - the request's authentication reads no aggregation"""
    def _aggregate(*_args: Any, **_kwargs: Any) -> Any:
        raise failure

    monkeypatch.setattr(MongoDatabaseManager, 'aggregate_within_time_limit', _aggregate)


def _fail_auth_section(monkeypatch: pytest.MonkeyPatch, failure: Exception) -> None:
    """The read of the `auth` settings section raises `failure`; every other settings read goes through"""
    original = SettingsManager.get_all_values_from_section

    def _read(self: SettingsManager, section: str, *args: Any, **kwargs: Any) -> Any:
        if section == AUTH_SETTINGS_ID:
            raise failure

        return original(self, section, *args, **kwargs)

    monkeypatch.setattr(SettingsManager, 'get_all_values_from_section', _read)


def _message(response: Any) -> str:
    """The message of an error answer"""
    return response.get_json()['message']


class TestTheListsLetAnOutageThrough:
    """`GET /users/`, `/persons/`, `/person_groups/`"""

    @pytest.mark.parametrize('error, status', TRANSIENT_ANSWERS, ids=TRANSIENT_IDS)
    @pytest.mark.parametrize('url', LIST_URLS)
    def test_a_temporary_failure_is_the_apps_answer(self, rest_api, monkeypatch, url: str,
                                                    error: type[Exception], status: HTTPStatus) -> None:
        """Try again later - not an internal error"""
        _fail_lists(monkeypatch, error('database unavailable'))

        assert rest_api.get(url).status_code == status

    @pytest.mark.parametrize('url', LIST_URLS)
    def test_an_unexpected_error_keeps_its_500(self, rest_api, monkeypatch, url: str) -> None:
        """Worded as before"""
        _fail_lists(monkeypatch, RuntimeError('a bug'))

        response = rest_api.get(url)

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert _message(response) == UNEXPECTED_MESSAGES[url]


class TestTheAuthReadsLetAnOutageThrough:
    """`GET /auth/settings`, `/auth/providers`"""

    @pytest.mark.parametrize('error, status', TRANSIENT_ANSWERS, ids=TRANSIENT_IDS)
    @pytest.mark.parametrize('url', AUTH_URLS)
    def test_a_temporary_failure_is_the_apps_answer(self, rest_api, monkeypatch, url: str,
                                                    error: type[Exception], status: HTTPStatus) -> None:
        """Try again later - not an internal error"""
        _fail_auth_section(monkeypatch, error('database unavailable'))

        assert rest_api.get(url).status_code == status

    @pytest.mark.parametrize('url', AUTH_URLS)
    def test_an_unexpected_error_keeps_its_500(self, rest_api, monkeypatch, url: str) -> None:
        """Worded as before"""
        _fail_auth_section(monkeypatch, RuntimeError('a bug'))

        response = rest_api.get(url)

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert _message(response) == UNEXPECTED_MESSAGES[url]

    @pytest.mark.parametrize('url', AUTH_URLS)
    def test_without_a_failure_the_reads_answer(self, rest_api, url: str) -> None:
        """The shared AuthModule read changes nothing for a working database"""
        assert rest_api.get(url).status_code == HTTPStatus.OK
