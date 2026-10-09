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
Functional tests for the ``/special`` DataGerry Assistant routes

The "database is empty" gate reads the shared session database, so the counts are patched to 0 where a test needs
an empty installation; the seeding itself is real where the test is about what it stores, and every type and
category it creates is deleted afterwards, together with the one-time marker. Pinned:

  - /intro answers true only to a caller holding type.add + category.add, on an empty database, before the
    assistant ran; the seeded ``user`` group is not offered it. A failed read is a 400
  - /profiles asks for both rights (403 naming the missing one), refuses no / unknown profiles, a non-empty
    database and a second run (400); a real run stores the types and categories with the caller as author
  - a run that fails part-way deletes what it created and releases the marker, so the next run works
"""
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import CategoriesManager, SettingsManager
from cmdb.manager.base_manager import BaseManager
from cmdb.models.category_model import CmdbCategory
from cmdb.models.group_model import CmdbUserGroup
from cmdb.models.group_model.group_constants import USER_GROUP_ID
from cmdb.models.type_model import CmdbType
from cmdb.models.user_model import CmdbUser
from cmdb.framework.datagerry_assistant.profile_assistant import ProfileAssistant
from cmdb.framework.datagerry_assistant.profile_name import ProfileName
from cmdb.framework.write_ledger import LedgerResidue, WriteLedger
from cmdb.framework.write_ledger_constants import WriteKind
from cmdb.interface.rest_api.routes.framework_routes.special_constants import (
    ASSISTANT_ALREADY_RAN_MESSAGE,
    ASSISTANT_READ_FAILED_MESSAGE,
    ASSISTANT_RESIDUE_MESSAGE,
    ASSISTANT_RIGHTS,
    ASSISTANT_SETTINGS_SECTION,
    FRAMEWORK_DATA_EXISTS_MESSAGE,
    NO_PROFILES_MESSAGE,
    UNKNOWN_PROFILES_MESSAGE,
)
from cmdb.errors.dg_assistant.dg_assistant_errors import ProfileCreationError
from cmdb.errors.manager.categories_manager import CategoriesManagerGetError, CategoriesManagerInsertError
# -------------------------------------------------------------------------------------------------------------------- #

INTRO_URL: str = '/special/intro'
PROFILES_URL: str = '/special/profiles'
RIGHT_REFUSAL: str = 'User has not the required right {right}'
PROFILE: str = ProfileName.USER_MANAGEMENT.value
ADMIN_USER_ID: int = 1

TYPE_ONLY_GROUP_ID: int = 88701
BOTH_GROUP_ID: int = 88702
TYPE_ONLY_USER_ID: int = 88711
BOTH_USER_ID: int = 88712
DEFAULT_USER_ID: int = 88713


def _raiser(exc: Exception):
    """Returns a function that ignores its args and raises the given exception."""
    def _fail(*_args, **_kwargs):
        raise exc
    return _fail


def _empty(monkeypatch: pytest.MonkeyPatch) -> None:
    """Makes the 'database is empty' gate see an empty installation"""
    monkeypatch.setattr(BaseManager, 'count_documents', lambda _self, *_a, **_k: 0)


@pytest.fixture(name='settings', autouse=True)
def fixture_settings(database_manager: MongoDatabaseManager, database_name: str):
    """The one-time marker removed before and after every test"""
    settings = database_manager.get_collection(SettingsManager.COLLECTION, database_name)
    settings.delete_one({'_id': ASSISTANT_SETTINGS_SECTION})
    yield settings
    settings.delete_one({'_id': ASSISTANT_SETTINGS_SECTION})


@pytest.fixture(name='created')
def fixture_created(database_manager: MongoDatabaseManager, database_name: str):
    """Records the type and category ids that exist before a real run, and deletes every newer one after it"""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    categories = database_manager.get_collection(CmdbCategory.COLLECTION, database_name)
    before: dict[str, set[int]] = {
        'types': {doc['public_id'] for doc in types.find({}, {'public_id': 1})},
        'categories': {doc['public_id'] for doc in categories.find({}, {'public_id': 1})},
    }

    def _new() -> dict[str, list[dict[str, Any]]]:
        return {
            'types': list(types.find({'public_id': {'$nin': list(before['types'])}})),
            'categories': list(categories.find({'public_id': {'$nin': list(before['categories'])}})),
        }

    yield _new
    types.delete_many({'public_id': {'$nin': list(before['types'])}})
    categories.delete_many({'public_id': {'$nin': list(before['categories'])}})


def _insert_user(database_manager: MongoDatabaseManager, database_name: str, user_id: int,
                 group_id: int) -> CmdbUser:
    """Stores an active user in ``group_id`` and answers the model the test client sends as"""
    user_name: str = f'assistant-{user_id}'
    database_manager.get_collection(CmdbUser.COLLECTION, database_name).insert_one({
        'public_id': user_id, 'user_name': user_name, 'active': True, 'group_id': group_id,
        'registration_time': datetime.now(timezone.utc),
    })

    return CmdbUser(public_id=user_id, user_name=user_name, active=True, group_id=group_id)


@pytest.fixture(name='users')
def fixture_users(database_manager: MongoDatabaseManager, database_name: str):
    """A group holding type.add only, one holding both rights, and a member of the seeded user group"""
    groups = database_manager.get_collection(CmdbUserGroup.COLLECTION, database_name)
    users = database_manager.get_collection(CmdbUser.COLLECTION, database_name)

    def _purge() -> None:
        groups.delete_many({'public_id': {'$in': [TYPE_ONLY_GROUP_ID, BOTH_GROUP_ID]}})
        users.delete_many({'public_id': {'$in': [TYPE_ONLY_USER_ID, BOTH_USER_ID, DEFAULT_USER_ID]}})

    _purge()
    groups.insert_many([
        {'public_id': TYPE_ONLY_GROUP_ID, 'name': 'assistant-type', 'label': 'T', 'rights': [ASSISTANT_RIGHTS[0]]},
        {'public_id': BOTH_GROUP_ID, 'name': 'assistant-both', 'label': 'B', 'rights': list(ASSISTANT_RIGHTS)},
    ])
    yield {
        'type-only': _insert_user(database_manager, database_name, TYPE_ONLY_USER_ID, TYPE_ONLY_GROUP_ID),
        'both': _insert_user(database_manager, database_name, BOTH_USER_ID, BOTH_GROUP_ID),
        'default': _insert_user(database_manager, database_name, DEFAULT_USER_ID, USER_GROUP_ID),
    }
    _purge()


class TestIntro:
    """GET /special/intro: whether to offer the assistant to the caller"""

    def test_true_for_a_caller_who_may_run_it_on_an_empty_database(self, rest_api, monkeypatch) -> None:
        """Both rights, nothing stored, never run"""
        _empty(monkeypatch)

        response = rest_api.get(INTRO_URL)

        assert response.status_code == HTTPStatus.OK
        assert response.get_json() is True

    def test_false_when_data_exists(self, rest_api, monkeypatch) -> None:
        """A non-empty database"""
        monkeypatch.setattr(BaseManager, 'count_documents', lambda _self, *_a, **_k: 1)

        assert rest_api.get(INTRO_URL).get_json() is False

    def test_false_once_the_assistant_ran(self, rest_api, monkeypatch, settings) -> None:
        """The marker section exists"""
        _empty(monkeypatch)
        settings.insert_one({'_id': ASSISTANT_SETTINGS_SECTION, 'claimed_by': ADMIN_USER_ID})

        assert rest_api.get(INTRO_URL).get_json() is False

    @pytest.mark.parametrize('who', ['type-only', 'default'])
    def test_false_for_a_caller_who_may_not_run_it(self, rest_api, monkeypatch, users: dict[str, CmdbUser],
                                                   who: str) -> None:
        """No 403 - the frontend asks it after every login; the caller is simply not offered it"""
        _empty(monkeypatch)

        response = rest_api.get(INTRO_URL, user=users[who])

        assert response.status_code == HTTPStatus.OK
        assert response.get_json() is False

    def test_true_for_a_custom_group_holding_both_rights(self, rest_api, monkeypatch,
                                                          users: dict[str, CmdbUser]) -> None:
        """The two rights are enough"""
        _empty(monkeypatch)

        assert rest_api.get(INTRO_URL, user=users['both']).get_json() is True

    def test_a_failed_read_is_a_400(self, rest_api, monkeypatch) -> None:
        """Named, not a 500"""
        monkeypatch.setattr(BaseManager, 'count_documents', _raiser(CategoriesManagerGetError('boom')))

        response = rest_api.get(INTRO_URL)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'] == ASSISTANT_READ_FAILED_MESSAGE

    def test_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """Anything else is the tail's 500"""
        monkeypatch.setattr(BaseManager, 'count_documents', _raiser(RuntimeError('boom')))

        assert rest_api.get(INTRO_URL).status_code == HTTPStatus.INTERNAL_SERVER_ERROR


class TestProfilesGate:
    """POST /special/profiles: who may run it, and when"""

    @pytest.mark.parametrize('who, missing', [('default', ASSISTANT_RIGHTS[0]), ('type-only', ASSISTANT_RIGHTS[1])],
                             ids=['default-group', 'type-add-only'])
    def test_without_both_rights_it_is_a_403(self, rest_api, users: dict[str, CmdbUser], who: str,
                                             missing: str) -> None:
        """Naming the right that is missing"""
        response = rest_api.post(PROFILES_URL, query_string={'data': PROFILE}, user=users[who])

        assert response.status_code == HTTPStatus.FORBIDDEN
        assert response.get_json()['message'] == RIGHT_REFUSAL.format(right=missing)

    @pytest.mark.parametrize('data', [None, '', '#'], ids=['missing', 'empty', 'separator-only'])
    def test_no_profile_is_a_400(self, rest_api, data: str | None) -> None:
        """Nothing to seed"""
        query: dict[str, str] = {} if data is None else {'data': data}

        response = rest_api.post(PROFILES_URL, query_string=query)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'] == NO_PROFILES_MESSAGE

    def test_an_unknown_profile_is_a_400_naming_it(self, rest_api, monkeypatch, settings) -> None:
        """Refused before anything is checked or written"""
        _empty(monkeypatch)

        response = rest_api.post(PROFILES_URL, query_string={'data': f'{PROFILE}#SERVER'})

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'] == UNKNOWN_PROFILES_MESSAGE.format(names='SERVER')
        assert settings.find_one({'_id': ASSISTANT_SETTINGS_SECTION}) is None

    def test_a_non_empty_database_is_a_400(self, rest_api, monkeypatch) -> None:
        """The assistant only seeds an empty installation"""
        monkeypatch.setattr(BaseManager, 'count_documents', lambda _self, *_a, **_k: 1)

        response = rest_api.post(PROFILES_URL, query_string={'data': PROFILE})

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'] == FRAMEWORK_DATA_EXISTS_MESSAGE

    def test_a_second_run_is_a_400(self, rest_api, monkeypatch, settings) -> None:
        """The marker is claimed atomically - also against a concurrent run"""
        _empty(monkeypatch)
        settings.insert_one({'_id': ASSISTANT_SETTINGS_SECTION, 'claimed_by': ADMIN_USER_ID})
        monkeypatch.setattr(ProfileAssistant, 'create_profiles', _raiser(AssertionError('must not run')))

        response = rest_api.post(PROFILES_URL, query_string={'data': PROFILE})

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'] == ASSISTANT_ALREADY_RAN_MESSAGE

    def test_a_failed_prerequisite_read_is_a_400(self, rest_api, monkeypatch) -> None:
        """Named, not a 500"""
        monkeypatch.setattr(BaseManager, 'count_documents', _raiser(CategoriesManagerGetError('boom')))

        response = rest_api.post(PROFILES_URL, query_string={'data': PROFILE})

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'] == ASSISTANT_READ_FAILED_MESSAGE


class TestProfilesRun:
    """A real run - and one that fails part-way"""

    def test_a_run_stores_types_and_categories_by_the_caller(self, rest_api, monkeypatch, users: dict[str, CmdbUser],
                                                             created, settings) -> None:
        """The answered ids are the stored types; the caller is their author; the marker names the caller"""
        _empty(monkeypatch)

        response = rest_api.post(PROFILES_URL, query_string={'data': PROFILE}, user=users['both'])

        assert response.status_code == HTTPStatus.OK
        stored = created()
        assert sorted(response.get_json()) == sorted(doc['public_id'] for doc in stored['types'])
        assert stored['types'] and stored['categories']
        assert {doc['author_id'] for doc in stored['types']} == {BOTH_USER_ID}
        assert settings.find_one({'_id': ASSISTANT_SETTINGS_SECTION})['claimed_by'] == BOTH_USER_ID

    def test_a_failure_part_way_undoes_the_run_and_allows_another(self, rest_api, monkeypatch, created,
                                                                  settings) -> None:
        """The types made before the failing category insert are deleted; the marker is released"""
        _empty(monkeypatch)
        monkeypatch.setattr(CategoriesManager, 'insert_category', _raiser(CategoriesManagerInsertError('boom')))

        response = rest_api.post(PROFILES_URL, query_string={'data': PROFILE})

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert created() == {'types': [], 'categories': []}
        assert settings.find_one({'_id': ASSISTANT_SETTINGS_SECTION}) is None

        monkeypatch.undo()
        _empty(monkeypatch)

        assert rest_api.post(PROFILES_URL, query_string={'data': PROFILE}).status_code == HTTPStatus.OK

    def test_a_profile_creation_error_is_a_500(self, rest_api, monkeypatch, settings) -> None:
        """Nothing was written, so the marker is released"""
        _empty(monkeypatch)
        monkeypatch.setattr(ProfileAssistant, 'create_profiles', _raiser(ProfileCreationError('boom')))

        response = rest_api.post(PROFILES_URL, query_string={'data': PROFILE})

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert settings.find_one({'_id': ASSISTANT_SETTINGS_SECTION}) is None

    def test_an_undo_that_cannot_finish_keeps_the_marker(self, rest_api, monkeypatch, created, settings) -> None:
        """Something is left behind, so the installation is not empty and the assistant stays claimed"""
        _empty(monkeypatch)
        monkeypatch.setattr(CategoriesManager, 'insert_category', _raiser(CategoriesManagerInsertError('boom')))
        monkeypatch.setattr(WriteLedger, 'undo', lambda _self: [
            LedgerResidue(collection=CmdbType.COLLECTION, kind=WriteKind.INSERT, public_id=1),
        ])

        response = rest_api.post(PROFILES_URL, query_string={'data': PROFILE})

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert response.get_json()['message'].startswith(ASSISTANT_RESIDUE_MESSAGE.split('{', maxsplit=1)[0])
        assert settings.find_one({'_id': ASSISTANT_SETTINGS_SECTION}) is not None
        assert created()['types']

