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
Implementation of DatabaseUpdater
"""
import logging
from typing import Any

from cmdb.database.database_constants import MIN_CLOUD_UPDATER_VERSION
from cmdb.database.mongo_database_manager import MongoDatabaseManager

from cmdb.manager import SettingsManager

from cmdb.utils.helpers import process_bar, load_class

from cmdb.errors.system_config import SectionError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER = logging.getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #

class DatabaseUpdater:
    """
    The DatabaseUpdater applies required changes to the database
    """
    __UPDATE_VERSIONS__: list[int] = [
        20200512,
        20200513,
        20240603,
        20250619,
    ]


    def __init__(self, dbm: MongoDatabaseManager, db_name: str = None) -> None:
        """
        Initialises the DatabaseUpdater
        """
        self.dbm = dbm
        self.db_name = db_name
        self.settings_manager = SettingsManager(dbm, db_name)

# -------------------------------------------------------------------------------------------------------------------- #

    def is_update_available(self) -> bool:
        """
        Checks if a new database update is available

        Returns:
            bool: True if a newer version is available, else False
        """
        return self.get_highest_update_version() > self.get_current_update_version()


    def run_updates(self) -> None:
        """
        Executes updates if there are any
        """
        all_versions = self.get_updater_versions()
        current_version = self.get_current_update_version()

        for index, update_version in enumerate(sorted(all_versions)):
            if current_version < update_version:
                process_bar('Process', len(all_versions), index + 1)
                updater_class = load_class(
                    f'cmdb.database.updater.versions.updater_{update_version}.Update{update_version}'
                )
                updater_instance = updater_class(self.dbm, self.db_name)
                updater_instance.start_update()


    def set_update_version(self, version: int) -> None:
        """
        Sets the update version of the database to the provided version

        Args:
            version (int): The new value for the update version of the database
        """
        new_version: dict[str, Any] = {
            '_id': 'updater',
            'version': version
        }

        self.settings_manager.write(_id='updater', data=new_version)


    def get_current_update_version(self) -> int:
        """
        Retrieves the current update version stored in the database

        Returns:
            int: The current update version stored in the database
        """
            # First check if there is any Updater-Version
        default_version: dict[str, Any] = {
                            '_id': 'updater',
                            'version': MIN_CLOUD_UPDATER_VERSION
                        }

        try:
            current_version = self.settings_manager.get_all_values_from_section('updater')
            return current_version.get('version')
        except SectionError:
            # No Updater Version => Set it
            self.settings_manager.write(_id='updater', data=default_version)

            return default_version.get('version', 0)


    def get_updater_versions(self) -> list[int]:
        """
        Retrieve all available Updater versions

        Returns:
            list[int]: Sorted list of all updater versions
        """
        return sorted(DatabaseUpdater.__UPDATE_VERSIONS__)


    def get_highest_update_version(self) -> int:
        """
        Retrieves the highest available update version

        Returns:
            int: The highest update version
        """
        return sorted(DatabaseUpdater.__UPDATE_VERSIONS__)[-1]
