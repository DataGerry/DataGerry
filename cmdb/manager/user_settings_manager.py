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
Implementation of UserSettingsManager

Identity here is `(user_id, resource)` rather than a public_id, so every method filters on that pair
instead of using the public_id-keyed CRUD of its GenericManager base - see `CmdbUserSetting`.

`get_user_settings` is deliberately the one read that does NOT build models: it normalises each
document and **skips** the ones it cannot read (reporting them), because it answers a whole user's
settings at once, and one unreadable record must not fail all of them
"""
from logging import Logger, getLogger
from typing import Any

from cmdb.database import MongoDatabaseManager

from cmdb.manager.generic_manager import GenericManager

from cmdb.models.settings_model import (
    CmdbUserSetting,
    UserSettingKey,
    UserSettingType,
    normalize_user_setting_document,
)

from cmdb.errors.manager import (
    BaseManagerDeleteError,
    BaseManagerGetError,
    BaseManagerUpdateError,
)
from cmdb.errors.manager.user_settings_manager import (
    USER_SETTINGS_MANAGER_ERRORS,
    UserSettingsManagerGetError,
    UserSettingsManagerIterationError,
    UserSettingsManagerUpdateError,
    UserSettingsManagerDeleteError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                              UserSettingsManager - CLASS                                             #
# -------------------------------------------------------------------------------------------------------------------- #
class UserSettingsManager(GenericManager):
    """
    The UserSettingsManager manages the interaction between CmdbUserSettings and the database

    Extends: GenericManager
    """
    def __init__(self, dbm: MongoDatabaseManager, database: str | None = None) -> None:
        """
        Initialises the UserSettingsManager

        Args:
            dbm (MongoDatabaseManager): Database interaction manager
            database (str | None): Target database name, used in cloud mode. Defaults to None
        """
        super().__init__(dbm, CmdbUserSetting, USER_SETTINGS_MANAGER_ERRORS, database)

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

    def get_user_setting(self, user_id: int, resource: str) -> dict[str, Any] | None:
        """
        Get a single CmdbUserSetting from a user by the identifier

        Args:
            user_id (int): public_id of the CmdbUser
            resource (str): name of the CmdbSetting

        Raises:
            UserSettingsManagerGetError: If the read fails (BaseManagerGetError); a programming error propagates
                unwrapped

        Returns:
            dict | None: A dictionary representation of the CmdbUserSetting if successful, otherwise None
        """
        try:
            return self.get_one_by(criteria={
                UserSettingKey.USER_ID.value: user_id,
                UserSettingKey.RESOURCE.value: resource,
            })
        except BaseManagerGetError as err:
            LOGGER.error("[get_user_setting] Exception: %s. Type: %s", err, type(err))
            raise UserSettingsManagerGetError(err) from err


    def get_user_settings(
            self,
            user_id: int,
            setting_type: UserSettingType | None = None) -> list[dict[str, Any]]:
        """
        Get all CmdbUserSettings of a CmdbUser by the user_id

        Answers normalised documents rather than model instances: the four keys, with an absent
        payload list reported as an empty one. Building a `CmdbUserSetting` per document and
        the caller immediately converted each back into a dict, which cost two objects per setting
        plus one per payload entry for a payload that is handed straight back.

        **A document that cannot be read is skipped, not fatal.** Reading one resolves its stored
        scope, and an unresolvable value must not fail the whole call - a single bad
        record answered 400 for every setting the user had, and the frontend (which syncs these on
        login and only logs a failure) silently stopped restoring any of them. The skipped record is
        logged with its resource by `normalize_user_setting_document`

        Args:
            user_id (int): public_id of the CmdbUser
            setting_type (UserSettingType, optional): UserSettingType to filter by. No route passes
                one; the scope is a label the frontend maintains for itself

        Raises:
            UserSettingsManagerIterationError: If the read fails (BaseManagerGetError); a programming error
                propagates unwrapped

        Returns:
            list[dict[str, Any]]: The user's readable settings, in the shape the list route answers
        """
        query: dict[str, Any] = {UserSettingKey.USER_ID.value: user_id}

        if setting_type:
            query[UserSettingKey.SETTING_TYPE.value] = setting_type.value

        try:
            stored: list[dict[str, Any]] = self.find(criteria=query)
        except BaseManagerGetError as err:
            LOGGER.error("[get_user_settings] Exception: %s. Type: %s", err, type(err))
            raise UserSettingsManagerIterationError(err) from err

        normalized: list[dict[str, Any] | None] = [normalize_user_setting_document(setting) for setting in stored]

        return [setting for setting in normalized if setting is not None]

# --------------------------------------------------- CRUD - UPDATE -------------------------------------------------- #

    def update_user_setting(self, user_id: int, resource: str, setting: dict[str, Any] | CmdbUserSetting) -> None:
        """
        Updates an existing CmdbUserSetting in the database

        Args:
            setting (dict | CmdbUserSetting): Settings data
            user_id (int): User of this setting
            resource (str): Identifier of the setting

        Raises:
            UserSettingsManagerUpdateError: If the write fails (BaseManagerUpdateError) or the setting cannot be
                serialised (CmdbUserSettingToJsonError); a programming error propagates unwrapped
        """
        try:
            if isinstance(setting, CmdbUserSetting):
                setting = CmdbUserSetting.to_json(setting)

            self.update(
                criteria={
                    UserSettingKey.RESOURCE.value: resource,
                    UserSettingKey.USER_ID.value: user_id,
                },
                data=setting,
            )
        except (BaseManagerUpdateError, *self._model_errors()) as err:
            LOGGER.error("[update_user_setting] Exception: %s. Type: %s", err, type(err))
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
            return self.delete(criteria={
                UserSettingKey.USER_ID.value: user_id,
                UserSettingKey.RESOURCE.value: resource,
            })
        except BaseManagerDeleteError as err:
            raise UserSettingsManagerDeleteError(err) from err
