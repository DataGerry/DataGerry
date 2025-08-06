# DataGerry - OpenSource Enterprise CMDB
# Copyright (C) 2025 becon GmbH
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
Implementation of UserSettingsManager
"""
import logging

from cmdb.database import MongoDatabaseManager

from cmdb.manager.generic_manager import GenericManager

from cmdb.models.settings_model import CmdbUserSetting, UserSettingType

from cmdb.errors.manager import (
    BaseManagerDeleteError,
)
from cmdb.errors.manager.user_settings_manager import (
    USER_SETTINGS_MANAGER_ERRORS,
    UserSettingsManagerGetError,
    UserSettingsManagerIterationError,
    UserSettingsManagerUpdateError,
    UserSettingsManagerDeleteError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER = logging.getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                GenericManager - CLASS                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class UserSettingsManager(GenericManager):
    """
    The UserSettingsManager manages the interaction between CmdbUserSettings and the database

    Extends: GenericManager
    """
    def __init__(self, dbm: MongoDatabaseManager, database: str = None):
        super().__init__(dbm, CmdbUserSetting, USER_SETTINGS_MANAGER_ERRORS, database)

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

    def get_user_setting(self, user_id: int, resource: str) -> dict | None:
        """
        Get a single CmdbUserSetting from a user by the identifier

        Args:
            user_id (int): public_id of the CmdbUser
            resource (str): name of the CmdbSetting

        Raises:
            UserSettingsManagerGetError: If an CmdbUserSetting could not be retrieved

        Returns:
            dict | None: A dictionary representation of the CmdbUserSetting if successful, otherwise None
        """
        try:
            return self.get_one_by(criteria={'user_id': user_id, 'resource': resource})
        except Exception as err:
            LOGGER.error("[get_user_setting] Exception: %s. Type: %s", err, type(err))
            raise UserSettingsManagerGetError(err) from err


    def get_user_settings(self, user_id: int, setting_type: UserSettingType = None) -> list[CmdbUserSetting]:
        """
        Get all CmdbUserSettings from a CmdbUser by the user_id

        Args:
            user_id (int): public_id of the CmdbUser
            setting_type(UserSettingType, optional): UserSettingType for filtering

        Raises:
            UserSettingsManagerIterationError:

        Returns:
            (list[CmdbUserSetting]): List of CmdbUserSetting instances
        """
        try:
            query = {'user_id': user_id}

            if setting_type:
                query.update({'setting_type': setting_type.value})

            user_settings = self.find(criteria=query)

            return [CmdbUserSetting.from_data(setting) for setting in user_settings]
        except Exception as err:
            LOGGER.error("[get_user_settings] Exception: %s. Type: %s", err, type(err))
            raise UserSettingsManagerIterationError(err) from err

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

    def update_user_setting(self, user_id: int, resource: str, setting: dict | CmdbUserSetting) -> None:
        """
        Updates an existing CmdbUserSetting in the database

        Args:
            setting (dict | CmdbUserSetting): Settings data
            user_id (int): User of this setting
            resource (str): Identifier of the setting

        Raises:
            UserSettingsManagerUpdateError: If the update operation fails
        """
        try:
            if isinstance(setting, CmdbUserSetting):
                setting = CmdbUserSetting.to_json(setting)

            return self.update(criteria={'resource': resource, 'user_id': user_id}, data=setting)
        except Exception as err:
            LOGGER.error("[update_setting] Exception: %s. Type: %s", err, type(err))
            raise UserSettingsManagerUpdateError(err) from err

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

    def delete_user_setting(self, user_id: int, resource: str) -> bool:
        """
        Deletes an CmdbUserSetting from the database

        Args:
            user_id (int): public_id of the CmdbUser
            resource (str): Identifier of the setting

        Raises:
            UserSettingsManagerDeleteError: If the delete operation fails

        Returns:
            bool: True if deletion was successful
        """
        try:
            return self.delete(criteria={'user_id': user_id, 'resource': resource})
        except BaseManagerDeleteError as err:
            raise UserSettingsManagerDeleteError(err) from err
