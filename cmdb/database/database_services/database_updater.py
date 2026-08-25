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
Implementation of DatabaseUpdater
"""
from logging import Logger, getLogger
from typing import Any
import time

from cmdb.database.database_constants import BASELINE_UPDATER_VERSION
from cmdb.database.database_services.database_services_constants import UpdaterSetting, Updater
from cmdb.database.mongo_database_manager import MongoDatabaseManager

from cmdb.manager import SettingsManager

from cmdb.utils.helpers import process_bar, load_class

from cmdb.errors.system_config import SectionError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #

class DatabaseUpdater:
    """
    Applies the versioned schema/data migrations a database is missing

    Each migration is a dated module under cmdb.database.updater.versions (updater_<YYYYMMDD>) whose
    version int is registered in __UPDATE_VERSIONS__. The updater reads the version last applied to
    the database (stored in the 'updater' settings section), then runs every registered migration
    newer than it, in ascending order, recording progress as it goes. The run is idempotent: on a
    database already at the highest version nothing is executed.

    Note: __UPDATE_VERSIONS__ is maintained by hand and must list every updater module; a new
    migration also needs a PyInstaller --hidden-import entry (see the Makefile) to ship in the binary.
    """
    # Registry of every available migration version; keep in sync with cmdb.database.updater.versions
    __UPDATE_VERSIONS__: list[int] = [
        20250619,
        20251203,
        20260225,
        20260226,
        20260417,
        20260604,
        20260720,
        20260731,
        20260804,
        20260824,
    ]


    def __init__(self, dbm: MongoDatabaseManager, db_name: str | None = None) -> None:
        """
        Initialises the DatabaseUpdater

        Args:
            dbm (MongoDatabaseManager): The database operations manager for MongoDB
            db_name (str | None): Name of the database to update; None targets the manager default
        """
        self.dbm: MongoDatabaseManager = dbm
        self.db_name: str | None = db_name
        self.settings_manager: SettingsManager = SettingsManager(dbm, db_name)

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
        Runs every registered migration newer than the database's current version

        Walks the registered versions in ascending order; for each version above the current one it
        dynamically loads the matching cmdb.database.updater.versions.updater_<version>.Update<version>
        class, runs its start_update, and reports progress. A short delay between migrations avoids
        throttling. Does nothing when the database is already at the highest version.
        """
        all_versions: list[int] = self.get_updater_versions()
        current_version: int = self.get_current_update_version()

        for index, update_version in enumerate(sorted(all_versions)):
            if current_version < update_version:
                process_bar(Updater.PROCESS_BAR_LABEL, len(all_versions), index + 1)
                updater_class: type = load_class(Updater.CLASS_PATH_TEMPLATE.format(version=update_version))
                updater_instance = updater_class(self.dbm, self.db_name)
                updater_instance.start_update()

                # Small delay to avoid throttling
                time.sleep(Updater.THROTTLE_SECONDS)


    def set_update_version(self, version: int) -> None:
        """
        Sets the update version of the database to the provided version

        Args:
            version (int): The new value for the update version of the database
        """
        new_version: dict[str, Any] = {
            UpdaterSetting.ID: UpdaterSetting.SECTION,
            UpdaterSetting.VERSION: version
        }

        self.settings_manager.write(_id=UpdaterSetting.SECTION, data=new_version)


    def get_current_update_version(self) -> int:
        """
        Retrieves the current update version stored in the database

        Falls back to BASELINE_UPDATER_VERSION when no 'updater' section exists yet (seeding it)
        or when the stored section carries no 'version', so the return value is always an int. Every
        registered migration at or below that baseline is therefore never applied to such a database.

        Returns:
            int: The current update version stored in the database
        """
        # First check if there is any Updater-Version
        default_version: dict[str, Any] = {
            UpdaterSetting.ID: UpdaterSetting.SECTION,
            UpdaterSetting.VERSION: BASELINE_UPDATER_VERSION
        }

        try:
            current_version: dict[str, Any] = self.settings_manager.get_all_values_from_section(
                UpdaterSetting.SECTION
            )
            return current_version.get(UpdaterSetting.VERSION, BASELINE_UPDATER_VERSION)
        except SectionError:
            # No Updater Version => Set it
            self.settings_manager.write(_id=UpdaterSetting.SECTION, data=default_version)

            return default_version[UpdaterSetting.VERSION]


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
