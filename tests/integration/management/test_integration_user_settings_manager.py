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
error-wrapping of each method into its manager-specific exception.
"""
import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.user_settings_manager import UserSettingsManager
from cmdb.models.settings_model import CmdbUserSetting, UserSettingType
from cmdb.errors.manager import BaseManagerDeleteError
from cmdb.errors.manager.user_settings_manager import (
    UserSettingsManagerGetError,
    UserSettingsManagerIterationError,
    UserSettingsManagerUpdateError,
    UserSettingsManagerDeleteError,
)
# -------------------------------------------------------------------------------------------------------------------- #

USER_ID: int = 96701
RESOURCE_GLOBAL: str = 'dashboard'
RESOURCE_SERVER: str = 'sync-job'


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

    def test_wraps_unexpected_error(self, user_settings_manager: UserSettingsManager, monkeypatch) -> None:
        """An unexpected lookup error is wrapped as UserSettingsManagerGetError."""
        def _boom(*_args, **_kwargs):
            raise RuntimeError('db down')

        monkeypatch.setattr(UserSettingsManager, 'get_one_by', _boom)

        with pytest.raises(UserSettingsManagerGetError):
            user_settings_manager.get_user_setting(USER_ID, RESOURCE_GLOBAL)


class TestGetUserSettings:
    """get_user_settings returns all settings for a user, optionally filtered by setting_type."""

    def test_returns_all_for_user(self, user_settings_manager: UserSettingsManager,
                                 database_manager: MongoDatabaseManager, database_name: str) -> None:
        """Without a filter all of the user's settings are returned."""
        _seed(database_manager, database_name, RESOURCE_GLOBAL, 'GLOBAL')
        _seed(database_manager, database_name, RESOURCE_SERVER, 'SERVER')

        results = user_settings_manager.get_user_settings(USER_ID)

        assert {setting.resource for setting in results} == {RESOURCE_GLOBAL, RESOURCE_SERVER}

    def test_filters_by_setting_type(self, user_settings_manager: UserSettingsManager,
                                    database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A setting_type filter returns only the settings of that scope."""
        _seed(database_manager, database_name, RESOURCE_GLOBAL, 'GLOBAL')
        _seed(database_manager, database_name, RESOURCE_SERVER, 'SERVER')

        results = user_settings_manager.get_user_settings(USER_ID, UserSettingType.SERVER)

        assert [setting.resource for setting in results] == [RESOURCE_SERVER]

    def test_wraps_unexpected_error(self, user_settings_manager: UserSettingsManager, monkeypatch) -> None:
        """An unexpected iteration error is wrapped as UserSettingsManagerIterationError."""
        def _boom(*_args, **_kwargs):
            raise RuntimeError('db down')

        monkeypatch.setattr(UserSettingsManager, 'find', _boom)

        with pytest.raises(UserSettingsManagerIterationError):
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

    def test_wraps_unexpected_error(self, user_settings_manager: UserSettingsManager, monkeypatch) -> None:
        """An unexpected update error is wrapped as UserSettingsManagerUpdateError."""
        def _boom(*_args, **_kwargs):
            raise RuntimeError('db down')

        monkeypatch.setattr(UserSettingsManager, 'update', _boom)

        with pytest.raises(UserSettingsManagerUpdateError):
            user_settings_manager.update_user_setting(
                USER_ID, RESOURCE_GLOBAL,
                {'resource': RESOURCE_GLOBAL, 'user_id': USER_ID, 'payloads': [], 'setting_type': 'GLOBAL'}
            )


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
