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
Functional smoke for the ``/special`` DataGerry Assistant routes.

Covers /special/intro (True on an empty DB, False when data exists) and /special/profiles (happy path
with a mocked assistant, the DB-not-empty 400, the missing-'data'-param 400, and the error -> 500
mappings). The 'DB empty' gate reads the shared session DB, so count_documents is monkeypatched, and
the assistant itself is mocked so no real types are created.
"""
from http import HTTPStatus

from cmdb.manager.base_manager import BaseManager
from cmdb.framework.datagerry_assistant.profile_assistant import ProfileAssistant
from cmdb.errors.dg_assistant.dg_assistant_errors import ProfileCreationError
from cmdb.errors.manager.categories_manager import CategoriesManagerGetError
# -------------------------------------------------------------------------------------------------------------------- #

INTRO_URL: str = '/special/intro'
PROFILES_URL: str = '/special/profiles'


def _raiser(exc: Exception):
    """Returns a function that ignores its args and raises the given exception."""
    def _fail(*_args, **_kwargs):
        raise exc
    return _fail


class TestIntro:
    """GET /special/intro reports whether the assistant should be shown."""

    def test_true_when_database_empty(self, rest_api, monkeypatch) -> None:
        """An empty database (all counts 0) reports show_assistant = True."""
        monkeypatch.setattr(BaseManager, 'count_documents', lambda _self, *_a, **_k: 0)

        response = rest_api.get(INTRO_URL)

        assert response.status_code == HTTPStatus.OK
        assert response.get_json() is True

    def test_false_when_data_exists(self, rest_api, monkeypatch) -> None:
        """A non-empty database reports show_assistant = False."""
        monkeypatch.setattr(BaseManager, 'count_documents', lambda _self, *_a, **_k: 1)

        response = rest_api.get(INTRO_URL)

        assert response.status_code == HTTPStatus.OK
        assert response.get_json() is False

    def test_manager_error_returns_500(self, rest_api, monkeypatch) -> None:
        """A manager error while counting surfaces as 500."""
        monkeypatch.setattr(BaseManager, 'count_documents', _raiser(CategoriesManagerGetError('boom')))

        assert rest_api.get(INTRO_URL).status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error while counting surfaces as 500."""
        monkeypatch.setattr(BaseManager, 'count_documents', _raiser(RuntimeError('boom')))

        assert rest_api.get(INTRO_URL).status_code == HTTPStatus.INTERNAL_SERVER_ERROR


class TestCreateProfiles:
    """POST /special/profiles creates the selected profiles when the database is empty."""

    def test_creates_profiles_on_empty_database(self, rest_api, monkeypatch) -> None:
        """With an empty DB the assistant runs and the created type ids are returned."""
        monkeypatch.setattr(BaseManager, 'count_documents', lambda _self, *_a, **_k: 0)
        monkeypatch.setattr(ProfileAssistant, 'create_profiles', lambda _self, _profiles: [100, 101])

        response = rest_api.post(PROFILES_URL, query_string={'data': 'SERVER#CLIENT'})

        assert response.status_code == HTTPStatus.OK
        assert response.get_json() == [100, 101]

    def test_non_empty_database_returns_400(self, rest_api, monkeypatch) -> None:
        """If the database already has data, profile creation is rejected with 400."""
        monkeypatch.setattr(BaseManager, 'count_documents', lambda _self, *_a, **_k: 1)

        response = rest_api.post(PROFILES_URL, query_string={'data': 'SERVER'})

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_missing_data_param_returns_400(self, rest_api) -> None:
        """A request without the 'data' query param is rejected with 400 (regression)."""
        assert rest_api.post(PROFILES_URL).status_code == HTTPStatus.BAD_REQUEST

    def test_profile_creation_error_returns_500(self, rest_api, monkeypatch) -> None:
        """A ProfileCreationError from the assistant surfaces as 500."""
        monkeypatch.setattr(BaseManager, 'count_documents', lambda _self, *_a, **_k: 0)
        monkeypatch.setattr(ProfileAssistant, 'create_profiles', _raiser(ProfileCreationError('boom')))

        response = rest_api.post(PROFILES_URL, query_string={'data': 'SERVER'})

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_manager_error_returns_500(self, rest_api, monkeypatch) -> None:
        """A manager error while checking prerequisites surfaces as 500."""
        monkeypatch.setattr(BaseManager, 'count_documents', _raiser(CategoriesManagerGetError('boom')))

        response = rest_api.post(PROFILES_URL, query_string={'data': 'SERVER'})

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error while creating profiles surfaces as 500."""
        monkeypatch.setattr(BaseManager, 'count_documents', lambda _self, *_a, **_k: 0)
        monkeypatch.setattr(ProfileAssistant, 'create_profiles', _raiser(RuntimeError('boom')))

        response = rest_api.post(PROFILES_URL, query_string={'data': 'SERVER'})

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
