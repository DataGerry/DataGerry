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
Implementation of SettingsManager
"""
from logging import Logger, getLogger
from typing import Any

from pymongo.results import UpdateResult

from cmdb.database import MongoDatabaseManager

from cmdb.manager.system_manager.system_reader import SystemReader

from cmdb.errors.system_config import SectionError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# A settings section is one document whose MongoDB '_id' is the section's name
SETTINGS_SECTION_ID_KEY: str = '_id'

# -------------------------------------------------------------------------------------------------------------------- #
#                                                SettingsManager - CLASS                                               #
# -------------------------------------------------------------------------------------------------------------------- #
class SettingsManager(SystemReader):
    """
    Settings reader loads settings from database
    """
    COLLECTION = 'settings.conf'

    def __init__(self, dbm: MongoDatabaseManager, database: str | None = None) -> None:
        """
        Initializes the SettingsManager

        Args:
            dbm (MongoDatabaseManager): The database manager used to read/write settings
            database (str | None): The target database name; None resolves to the default database
        """
        self.db_name: str | None = database
        self.dbm: MongoDatabaseManager = dbm

        super().__init__()


    def get_value(self, name: str, section: str) -> Any:
        """
        Retrieve a single value by key from a settings section

        Args:
            name (str): The key of the value within the section
            section (str): The identifier ('_id') of the settings section

        Returns:
            Any: The stored value, or None if the section or the key does not exist
        """
        section_values = self.dbm.find_one_by(
                                    collection=SettingsManager.COLLECTION,
                                    db_name=self.db_name,
                                    filter={SETTINGS_SECTION_ID_KEY: section}
                                )

        if not section_values:
            return None

        return section_values.get(name)


    def get_section(self, section_name: str) -> dict[str, Any] | None:
        """
        Retrieves a specific configuration section from the settings collection

        Args:
            section_name (str): The name of the configuration section to retrieve

        Returns:
            dict[str, Any] | None: The configuration section as a dictionary if found, otherwise None
        """
        query_filter = {SETTINGS_SECTION_ID_KEY: section_name}

        return self.dbm.find_one_by(
                            collection=SettingsManager.COLLECTION,
                            db_name=self.db_name,
                            filter=query_filter
                        )


    def get_sections(self) -> list[str]:
        """
        Retrieves the names of all sections stored in the settings collection

        The same answer every SystemReader gives - section names, like the config-file and environment
        readers - so a caller holding any reader can iterate them the same way. A settings section is
        one document whose '_id' is its name, so only that key is read

        Returns:
            list[str]: The section names
        """
        documents: list[dict[str, Any]] = self.dbm.find_all(
            collection=SettingsManager.COLLECTION,
            db_name=self.db_name,
            projection={SETTINGS_SECTION_ID_KEY: 1},
        )

        return [document[SETTINGS_SECTION_ID_KEY] for document in documents]


    def get_all_values_from_section(
            self,
            section: str,
            default: dict[str, Any] | None = None) -> dict[str, Any]:
        """
        Retrieve all key-value pairs from a specific configuration section

        Args:
            section (str): The name of the section to retrieve
            default (dict[str, Any] | None): The default dictionary to return if the section does not
                                             exist. An empty dictionary is a valid default and is
                                             returned as-is (only None means "no default").

        Raises:
            SectionError: If the section does not exist and no default is provided

        Returns:
            dict[str, Any]: A dictionary containing all key-value pairs from the specified section
        """

        section_values = self.dbm.find_one_by(
                                    collection=SettingsManager.COLLECTION,
                                    db_name=self.db_name,
                                    filter={SETTINGS_SECTION_ID_KEY: section}
                                )

        if not section_values:
            if default is not None:
                return default

            raise SectionError(f"The section '{section}' does not exist!")

        return section_values


    def write(self, _id: str, data: dict[str, Any]) -> UpdateResult:
        """
        Write or update a setting value in the database

        Args:
            _id (str): The unique identifier of the setting section
            data (dict): The key-value pairs to store or update in the section

        Returns:
            UpdateResult: The result object of the database update operation
        """
        return self.dbm.update(
                        collection=self.COLLECTION,
                        db_name=self.db_name,
                        criteria={SETTINGS_SECTION_ID_KEY: _id},
                        data=data,
                        upsert=True
                    )
