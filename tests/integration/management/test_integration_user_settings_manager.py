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
Integration tests for the UserSettingsManager database-backed methods.

Covers get_user_setting / get_user_settings (including the setting_type filter branch),
update_user_setting (both the dict and CmdbUserSetting-instance inputs), delete_user_setting, and the
error-wrapping of each method: the database failure of its call (and a model that cannot serialise) becomes the
manager-specific exception, while a programming error propagates as itself.
"""
from typing import Any, Callable

import pytest
from pymongo.errors import DuplicateKeyError

from cmdb.database import MongoDatabaseManager
from cmdb.manager.user_settings_manager import UserSettingsManager
from cmdb.models.settings_model import CmdbUserSetting, UserSettingType
from cmdb.errors.manager import BaseManagerDeleteError, BaseManagerGetError, BaseManagerUpdateError
from cmdb.errors.manager.user_settings_manager import (
    UserSettingsManagerGetError,
    UserSettingsManagerIterationError,
    UserSettingsManagerUpdateError,
    UserSettingsManagerDeleteError,
)
# -------------------------------------------------------------------------------------------------------------------- #

OTHER_USER_ID: int = 96702
USER_ID: int = 96701
RESOURCE_GLOBAL: str = 'dashboard'
RESOURCE_SERVER: str = 'sync-job'
DB_FAILURE: str = 'db down'


def _raising(error: Exception) -> Callable[..., Any]:
    """A stand-in for a manager method that raises the given error"""
    def _raise(*_args: Any, **_kwargs: Any) -> Any:
        raise error

    return _raise


@pytest.fixture(name='user_settings_manager')
def fixture_user_settings_manager(database_manager: MongoDatabaseManager) -> UserSettingsManager:
    """Provides a UserSettingsManager wired to the test database."""
    return UserSettingsManager(database_manager)


@pytest.fixture(autouse=True)
def _cleanup(database_manager: MongoDatabaseManager, database_name: str):
    """Removes any settings seeded by a test, before and after each test."""
    def _purge() -> None:
        database_manager.get_collection(CmdbUserSetting.COLLECTION, database_name)\
            .delete_many({'user_id': USER_ID})

    _purge()
    yield
    _purge()


def _seed(database_manager: MongoDatabaseManager, database_name: str,
          resource: str, setting_type: str = 'GLOBAL') -> None:
    """Inserts a CmdbUserSetting document directly via the collection."""
    database_manager.get_collection(CmdbUserSetting.COLLECTION, database_name).insert_one(
        {'resource': resource, 'user_id': USER_ID, 'payloads': [], 'setting_type': setting_type}
    )


class TestGetUserSetting:
    """get_user_setting returns the matching setting or None."""

    def test_returns_matching_setting(self, user_settings_manager: UserSettingsManager,
                                     database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A seeded (user_id, resource) pair is returned."""
        _seed(database_manager, database_name, RESOURCE_GLOBAL)

        result = user_settings_manager.get_user_setting(USER_ID, RESOURCE_GLOBAL)

        assert result is not None
        assert result['resource'] == RESOURCE_GLOBAL

    def test_returns_none_when_absent(self, user_settings_manager: UserSettingsManager) -> None:
        """A missing setting returns None."""
        assert user_settings_manager.get_user_setting(USER_ID, RESOURCE_GLOBAL) is None

    def test_wraps_a_read_failure(self, user_settings_manager: UserSettingsManager, monkeypatch) -> None:
        """The lookup's BaseManagerGetError is wrapped as UserSettingsManagerGetError, carrying it"""
        failure = BaseManagerGetError(DB_FAILURE)
        monkeypatch.setattr(UserSettingsManager, 'get_one_by', _raising(failure))

        with pytest.raises(UserSettingsManagerGetError) as caught:
            user_settings_manager.get_user_setting(USER_ID, RESOURCE_GLOBAL)

        assert caught.value.args[0] is failure

    def test_a_programming_error_propagates(self, user_settings_manager: UserSettingsManager, monkeypatch) -> None:
        """A bug in the lookup is not reported as a failed read"""
        monkeypatch.setattr(UserSettingsManager, 'get_one_by', _raising(RuntimeError(DB_FAILURE)))

        with pytest.raises(RuntimeError):
            user_settings_manager.get_user_setting(USER_ID, RESOURCE_GLOBAL)


class TestGetUserSettings:
    """get_user_settings returns all settings for a user, optionally filtered by setting_type."""

    def test_returns_all_for_user(self, user_settings_manager: UserSettingsManager,
                                 database_manager: MongoDatabaseManager, database_name: str) -> None:
        """Without a filter all of the user's settings are returned."""
        _seed(database_manager, database_name, RESOURCE_GLOBAL, 'GLOBAL')
        _seed(database_manager, database_name, RESOURCE_SERVER, 'SERVER')

        results = user_settings_manager.get_user_settings(USER_ID)

        assert {setting['resource'] for setting in results} == {RESOURCE_GLOBAL, RESOURCE_SERVER}

    def test_filters_by_setting_type(self, user_settings_manager: UserSettingsManager,
                                    database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A setting_type filter returns only the settings of that scope."""
        _seed(database_manager, database_name, RESOURCE_GLOBAL, 'GLOBAL')
        _seed(database_manager, database_name, RESOURCE_SERVER, 'SERVER')

        results = user_settings_manager.get_user_settings(USER_ID, UserSettingType.SERVER)

        assert [setting['resource'] for setting in results] == [RESOURCE_SERVER]

    def test_wraps_a_read_failure(self, user_settings_manager: UserSettingsManager, monkeypatch) -> None:
        """The read's BaseManagerGetError is wrapped as UserSettingsManagerIterationError, carrying it"""
        failure = BaseManagerGetError(DB_FAILURE)
        monkeypatch.setattr(UserSettingsManager, 'find', _raising(failure))

        with pytest.raises(UserSettingsManagerIterationError) as caught:
            user_settings_manager.get_user_settings(USER_ID)

        assert caught.value.args[0] is failure

    def test_a_programming_error_propagates(self, user_settings_manager: UserSettingsManager, monkeypatch) -> None:
        """A bug in the read is not reported as a failed read"""
        monkeypatch.setattr(UserSettingsManager, 'find', _raising(RuntimeError(DB_FAILURE)))

        with pytest.raises(RuntimeError):
            user_settings_manager.get_user_settings(USER_ID)


class TestUpdateUserSetting:
    """update_user_setting persists changes from a dict or a CmdbUserSetting instance."""

    def test_updates_from_dict(self, user_settings_manager: UserSettingsManager,
                              database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A dict payload updates the stored setting_type."""
        _seed(database_manager, database_name, RESOURCE_GLOBAL, 'GLOBAL')

        user_settings_manager.update_user_setting(
            USER_ID, RESOURCE_GLOBAL,
            {'resource': RESOURCE_GLOBAL, 'user_id': USER_ID, 'payloads': [], 'setting_type': 'SERVER'}
        )

        assert user_settings_manager.get_user_setting(USER_ID, RESOURCE_GLOBAL)['setting_type'] == 'SERVER'

    def test_updates_from_instance(self, user_settings_manager: UserSettingsManager,
                                  database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A CmdbUserSetting instance is serialised and persisted."""
        _seed(database_manager, database_name, RESOURCE_GLOBAL, 'GLOBAL')

        setting = CmdbUserSetting(resource=RESOURCE_GLOBAL, user_id=USER_ID,
                                  payloads=[], setting_type=UserSettingType.APPLICATION)

        user_settings_manager.update_user_setting(USER_ID, RESOURCE_GLOBAL, setting)

        assert user_settings_manager.get_user_setting(USER_ID, RESOURCE_GLOBAL)['setting_type'] == 'APPLICATION'

    def test_wraps_a_write_failure(self, user_settings_manager: UserSettingsManager, monkeypatch) -> None:
        """The write's BaseManagerUpdateError is wrapped as UserSettingsManagerUpdateError, carrying it"""
        failure = BaseManagerUpdateError(DB_FAILURE)
        monkeypatch.setattr(UserSettingsManager, 'update', _raising(failure))

        with pytest.raises(UserSettingsManagerUpdateError) as caught:
            user_settings_manager.update_user_setting(
                USER_ID, RESOURCE_GLOBAL,
                {'resource': RESOURCE_GLOBAL, 'user_id': USER_ID, 'payloads': [], 'setting_type': 'GLOBAL'}
            )

        assert caught.value.args[0] is failure

    def test_wraps_an_unserialisable_setting(self, user_settings_manager: UserSettingsManager) -> None:
        """A setting the model cannot serialise is the update's error, carrying the model's"""
        setting = CmdbUserSetting(resource=RESOURCE_GLOBAL, user_id=USER_ID,
                                  payloads=[], setting_type=UserSettingType.APPLICATION)
        setting.setting_type = None

        with pytest.raises(UserSettingsManagerUpdateError) as caught:
            user_settings_manager.update_user_setting(USER_ID, RESOURCE_GLOBAL, setting)

        assert isinstance(caught.value.args[0], CmdbUserSetting.TO_JSON_ERROR)

    def test_a_programming_error_propagates(self, user_settings_manager: UserSettingsManager, monkeypatch) -> None:
        """A bug in the write is not reported as a failed update"""
        monkeypatch.setattr(UserSettingsManager, 'update', _raising(RuntimeError(DB_FAILURE)))

        with pytest.raises(RuntimeError):
            user_settings_manager.update_user_setting(
                USER_ID, RESOURCE_GLOBAL,
                {'resource': RESOURCE_GLOBAL, 'user_id': USER_ID, 'payloads': [], 'setting_type': 'GLOBAL'}
            )

    def test_answers_nothing(self, user_settings_manager: UserSettingsManager,
                             database_manager: MongoDatabaseManager, database_name: str) -> None:
        """The update is declared to answer None, and does"""
        _seed(database_manager, database_name, RESOURCE_GLOBAL, 'GLOBAL')

        assert user_settings_manager.update_user_setting(
            USER_ID, RESOURCE_GLOBAL,
            {'resource': RESOURCE_GLOBAL, 'user_id': USER_ID, 'payloads': [], 'setting_type': 'SERVER'}
        ) is None


class TestDeleteUserSetting:
    """delete_user_setting removes a setting and wraps failures."""

    def test_deletes_setting(self, user_settings_manager: UserSettingsManager,
                            database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A seeded setting is removed."""
        _seed(database_manager, database_name, RESOURCE_GLOBAL)

        result = user_settings_manager.delete_user_setting(USER_ID, RESOURCE_GLOBAL)

        assert result is True
        assert user_settings_manager.get_user_setting(USER_ID, RESOURCE_GLOBAL) is None

    def test_wraps_delete_error(self, user_settings_manager: UserSettingsManager, monkeypatch) -> None:
        """A BaseManagerDeleteError is wrapped as UserSettingsManagerDeleteError."""
        def _boom(*_args, **_kwargs):
            raise BaseManagerDeleteError('db down')

        monkeypatch.setattr(UserSettingsManager, 'delete', _boom)

        with pytest.raises(UserSettingsManagerDeleteError):
            user_settings_manager.delete_user_setting(USER_ID, RESOURCE_GLOBAL)


# -------------------------------------------------------------------------------------------------------------------- #
#                                   the index, and a document that cannot be read                                      #
# -------------------------------------------------------------------------------------------------------------------- #
class TestIdentityIndex:
    """(resource, user_id) is enforced by the database, and only a real index can show it.

    The create route rejects a duplicate itself, so the index is never reached through the API - which
    is exactly why it is measured here. It exists in production because `CmdbUserSetting` is registered
    in `user_management_constants.__COLLECTIONS__`; the test database never runs CollectionValidator,
    so the index is built here the way the application builds it at startup.
    """

    @staticmethod
    def _with_index(database_manager: MongoDatabaseManager, database_name: str):
        """The settings collection with the model's declared index built."""
        database_manager.create_indexes(
            CmdbUserSetting.COLLECTION, database_name, CmdbUserSetting.get_index_keys(),
        )

        return database_manager.get_collection(CmdbUserSetting.COLLECTION, database_name)

    def test_the_same_resource_twice_for_one_user_is_refused(
        self, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """One document per user and resource - the guarantee the routes rely on"""
        collection = self._with_index(database_manager, database_name)
        collection.insert_one({'resource': RESOURCE_GLOBAL, 'user_id': USER_ID,
                               'payloads': [], 'setting_type': 'GLOBAL', 'public_id': 8001})

        with pytest.raises(DuplicateKeyError):
            collection.insert_one({'resource': RESOURCE_GLOBAL, 'user_id': USER_ID,
                                   'payloads': [], 'setting_type': 'SERVER', 'public_id': 8002})

    def test_the_same_resource_for_another_user_is_accepted(
        self, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """The index is compound: every user has their own 'dashboard'"""
        collection = self._with_index(database_manager, database_name)
        collection.insert_one({'resource': RESOURCE_GLOBAL, 'user_id': USER_ID,
                               'payloads': [], 'setting_type': 'GLOBAL', 'public_id': 8003})
        collection.insert_one({'resource': RESOURCE_GLOBAL, 'user_id': OTHER_USER_ID,
                               'payloads': [], 'setting_type': 'GLOBAL', 'public_id': 8004})

        assert collection.count_documents({'resource': RESOURCE_GLOBAL}) == 2

        collection.delete_many({'user_id': OTHER_USER_ID})


class TestUnreadableDocuments:
    """One document that cannot be read may not cost the user the rest of their settings."""

    def test_a_bad_scope_is_skipped_and_the_others_survive(
        self, user_settings_manager: UserSettingsManager,
        database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """
        Against a real collection, which is where such a document comes from

        A failure here raises UserSettingsManagerIterationError - a 400 answering for every setting
        the user has.
        """
        _seed(database_manager, database_name, RESOURCE_GLOBAL, 'GLOBAL')
        database_manager.get_collection(CmdbUserSetting.COLLECTION, database_name).insert_one(
            {'resource': RESOURCE_SERVER, 'user_id': USER_ID, 'payloads': [],
             'setting_type': 'NOT_A_TYPE', 'public_id': 8010},
        )

        results = user_settings_manager.get_user_settings(USER_ID)

        assert [setting['resource'] for setting in results] == [RESOURCE_GLOBAL]

    def test_the_skipped_document_is_reported(
        self, user_settings_manager: UserSettingsManager,
        database_manager: MongoDatabaseManager, database_name: str, caplog,
    ) -> None:
        """Silently dropping a stored record would be worse than the 400 it replaces"""
        database_manager.get_collection(CmdbUserSetting.COLLECTION, database_name).insert_one(
            {'resource': RESOURCE_SERVER, 'user_id': USER_ID, 'payloads': [],
             'setting_type': 'NOT_A_TYPE', 'public_id': 8011},
        )

        with caplog.at_level('WARNING'):
            user_settings_manager.get_user_settings(USER_ID)

        assert RESOURCE_SERVER in caplog.text

    def test_a_stored_payload_list_survives_the_read(
        self, user_settings_manager: UserSettingsManager,
        database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """The content is what a setting is for"""
        payloads = [{'id': 'objects-table', 'columns': ['public_id', 'name']}]
        database_manager.get_collection(CmdbUserSetting.COLLECTION, database_name).insert_one(
            {'resource': RESOURCE_GLOBAL, 'user_id': USER_ID, 'payloads': payloads,
             'setting_type': 'APPLICATION', 'public_id': 8012},
        )

        results = user_settings_manager.get_user_settings(USER_ID)

        assert results[0]['payloads'] == payloads

    def test_a_document_without_a_payload_list_reads_as_empty(
        self, user_settings_manager: UserSettingsManager,
        database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """The key is optional, and the read normalises rather than answering a missing key"""
        database_manager.get_collection(CmdbUserSetting.COLLECTION, database_name).insert_one(
            {'resource': RESOURCE_GLOBAL, 'user_id': USER_ID, 'setting_type': 'GLOBAL',
             'public_id': 8013},
        )

        assert user_settings_manager.get_user_settings(USER_ID)[0]['payloads'] == []

    def test_the_public_id_is_not_part_of_the_answer(
        self, user_settings_manager: UserSettingsManager,
        database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """It is stamped in the collection but not in this shape"""
        _seed(database_manager, database_name, RESOURCE_GLOBAL)

        assert 'public_id' not in user_settings_manager.get_user_settings(USER_ID)[0]
