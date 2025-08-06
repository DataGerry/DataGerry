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
Implementation of SettingsManager
"""
import logging

from pymongo.results import UpdateResult

from cmdb.database import MongoDatabaseManager

from cmdb.manager.system_manager.system_reader import SystemReader

from cmdb.errors.system_config import SectionError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER = logging.getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                SettingsManager - CLASS                                               #
# -------------------------------------------------------------------------------------------------------------------- #
class SettingsManager(SystemReader):
    """
    Settings reader loads settings from database
    """
    COLLECTION = 'settings.conf'

    def __init__(self, dbm: MongoDatabaseManager, database: str = None):
        """
        init system settings reader
        Args:
            database_manager: database managers
        """
        self.db_name = database
        self.dbm = dbm

        super().__init__()


    def get_value(self, name, section) -> dict:
        """
        Retrieve a value from a given section
        Args:
            name: key of value
            section: section of the value

        Returns:
            value
        """
        return self.dbm.find_one_by(
                            collection=SettingsManager.COLLECTION,
                            db_name=self.db_name,
                            filter={'_id': section})[name]


    def get_section(self, section_name: str) -> dict:
        """
        Retrieves a specific configuration section from the settings collection

        Args:
            section_name (str): The name of the configuration section to retrieve

        Returns:
            dict: The configuration section as a dictionary if found, otherwise None
        """
        query_filter = {'_id': section_name}

        return self.dbm.find_one_by(
                            collection=SettingsManager.COLLECTION,
                            db_name=self.db_name,
                            filter=query_filter
                        )


    def get_sections(self) -> list:
        """
        Retrieves all section names from the settings collection.

        Returns:
            list: A list of section names (as dictionaries containing '_id' keys).
        """
        return self.dbm.find_all(
                            collection=SettingsManager.COLLECTION,
                            db_name=self.db_name,
                            projection={'_id': 1}
                        )


    def get_all_values_from_section(self, section: str, default=None) -> dict:
        """
        Retrieve all key-value pairs from a specific configuration section

        Args:
            section (str): The name of the section to retrieve
            default (dict | None): The default dictionary to return if the section does not exist

        Raises:
            SectionError: If the section does not exist and no default is provided

        Returns:
            dict: A dictionary containing all key-value pairs from the specified section
        """

        section_values = self.dbm.find_one_by(
                                    collection=SettingsManager.COLLECTION,
                                    db_name=self.db_name,
                                    filter={'_id': section}
                                )

        if not section_values:
            if default:
                return default

            raise SectionError(f"The section '{section}' does not exist!")

        return section_values


    def write(self, _id: str, data: dict) -> UpdateResult:
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
                        criteria={'_id': _id},
                        data=data,
                        upsert=True
                    )
