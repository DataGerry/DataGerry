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
Implementation of SystemEnvironmentReader
"""
import os
import re
from typing import Any

from cmdb.manager.system_manager.system_reader import SystemReader
# -------------------------------------------------------------------------------------------------------------------- #

class SystemEnvironmentReader(SystemReader):
    """
    Reads configuration settings from environment variables

    Extends: SystemReader
    """

    def __init__(self) -> None:
        """
        Initializes the SystemEnvironmentReader instance by loading environment variables
        that match the DATAGERRY_<SECTION>_<NAME> pattern
        """
        self.__config: dict[str, dict[str, str]] = {}
        pattern = re.compile("DATAGERRY_([a-zA-Z]*)_(.*)")

        for key, value in os.environ.items():
            match = pattern.fullmatch(key)

            if match:
                section = match.group(1)
                name = match.group(2)

                # save value in config dict
                if section not in self.__config:
                    self.__config[section] = {}

                self.__config[section][name] = value

        super().__init__()


    def get_value(self, name: str, section: str) -> str:
        """
        Retrieves a specific configuration value

        Args:
            name (str): The name of the configuration key
            section (str): The section under which the key is stored

        Returns:
            str: The corresponding configuration value
        """
        return self.__config[section][name]


    def get_sections(self) -> list[str]:
        """
        Retrieves all available configuration sections

        Returns:
            list[str]: The section names, as a new list (not a live view of the reader's state)
        """
        return list(self.__config.keys())


    def get_all_values_from_section(self, section: str) -> dict[str, Any]:
        """
        Retrieves all configuration values from a specific section

        Args:
            section (str): The section from which to retrieve values

        Returns:
            dict[str, Any]: A dictionary of key-value pairs from the specified section
        """
        return self.__config[section]


    def setup(self) -> None:
        """
        Placeholder method for setup functionality

        This method is intended to be overridden in subclasses where additional setup is required

        Raises:
            NotImplementedError: This method is not implemented
        """
        raise NotImplementedError
