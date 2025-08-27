# DATAGERRY - OpenSource Enterprise CMDB
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
Module for reading and managing system configuration files
"""
import os
import logging
from typing import Any

import configparser
from cmdb.utils.cast import auto_cast
from cmdb.manager.system_manager.system_env_reader import SystemEnvironmentReader
from cmdb.manager.system_manager.system_reader import SystemReader

from cmdb.errors.system_config import (
    ConfigFileModificationError,
    ConfigFileNotFound,
    ConfigNotLoaded,
    SectionError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER = logging.getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                               ConfigFileReader - CLASS                                               #
# -------------------------------------------------------------------------------------------------------------------- #
class ConfigFileReader(SystemReader):
    """
    Configuration file reader for handling system settings.

    This class loads configuration files and retrieves values. If a configuration 
    file is unavailable, it falls back to environment variables.
    """
    DEFAULT_CONFIG_FILE_LESS = False
    CONFIG_LOADED = True
    CONFIG_NOT_LOADED = False


    def __init__(self, config_name: str | None, config_location: str) -> None:
        """
        Initializes the configuration reader

        Args:
            config_name (str): The name of the configuration file (including extension)
            config_location (str): The directory where the configuration file is stored

        Raises:
            ConfigFileNotFound: If the configuration file is not found
        """
        self.config = configparser.ConfigParser()

        if config_name is None:
            self.config_file_less = True
            self.config_status = self.CONFIG_LOADED
        else:
            self.config_file_less = self.DEFAULT_CONFIG_FILE_LESS
            self.config_status = self.CONFIG_NOT_LOADED
            self.config_name = config_name
            self.config_location = config_location
            self.config_file = self.config_location + self.config_name
            self.config_status = self.setup()

        if self.config_status == self.CONFIG_NOT_LOADED:
            raise ConfigFileNotFound(f"Config file: {self.config_name} was not found!")
        # load environment variables
        self.__envvars = SystemEnvironmentReader()


    def add_section(self, section: str) -> None:
        """
        Adds a new section to the configuration

        Notes:
            This is only allowed when no configuration file is loaded

        Args:
            section (str): The name of the section to be added

        Raises:
            ConfigFileModificationError: If a configuration file is loaded, manual changes are restricted
        """
        if not self.config_file_less:
            raise ConfigFileModificationError(f"Config file '{self.config_file}' is loaded. "
                                     "Manual modifications are not allowed!")

        self.config.add_section(section)


    def set(self, section: str, option: str, value: str) -> None:
        """
        Sets a configuration value

        Notes:
            This is only allowed when no configuration file is loaded

        Args:
            section (str): The section where the key-value pair is added
            option (str): The configuration key
            value (str): The configuration value

        Raises:
            ConfigFileModificationError: If a configuration file is loaded, manual changes are restricted
        """
        if not self.config_file_less:
            raise ConfigFileModificationError(f"Config file '{self.config_file}' is loaded. "
                                     "Manual modifications are not allowed!")

        self.config.set(section, option, value)


    def setup(self) -> bool:
        """
        Initializes the configuration file

        Returns:
            bool: True if the configuration was loaded successfully, otherwise False
        """
        try:
            self.read_config_file(self.config_file)
            return self.CONFIG_LOADED
        except ConfigFileNotFound:
            return self.CONFIG_NOT_LOADED


    def read_config_file(self, file: str):
        """
        Reads the configuration file

        Args:
            file (str): The path to the configuration file

        Raises:
            ConfigFileNotFound: If the file does not exist
        """
        if os.path.isfile(file):
            self.config.read(file)
        else:
            raise ConfigFileNotFound(f"Config file '{self.config_name}' was not found!")


    def get_value(self, name: str, section: str, default: Any = None) -> Any:
        """
        Retrieves a configuration value from a specified section

        Args:
            name (str): The key of the configuration value
            section (str): The section where the key resides
            default (Any, optional): A default value if the key is not found

        Returns:
            Any: The retrieved value, cast to the appropriate type

        Raises:
            SectionError: If the section does not exist
            KeyError: If the key is missing and no default is provided
            ConfigNotLoaded: If the configuration is not loaded
        """
        try:
            return self.__envvars.get_value(name, section)
        except KeyError:
            pass

        if self.config_status == self.CONFIG_LOADED:
            if self.config.has_section(section):
                if name not in self.config[section]:
                    if default is not None:
                        return default
                    raise KeyError(name)
                return auto_cast(self.config[section][name])

            raise SectionError(f"The section '{section}' does not exist!")

        raise ConfigNotLoaded(f"Config file '{self.config_name}' was not loaded correctly!")


    def get_sections(self) -> list[str]:
        """
        Retrieves all sections from the configuration

        Returns:
            list: A list of section names

        Raises:
            ConfigNotLoaded: If the configuration is not loaded
        """
        if self.config_status == self.CONFIG_LOADED:
            return self.config.sections()

        raise ConfigNotLoaded(f"Config file '{self.config_name}' was not loaded correctly!")


    def get_all_values_from_section(self, section: str) -> dict:
        """
        Retrieves all key-value pairs from a given section

        Args:
            section (str): The section name

        Returns:
            dict: A dictionary containing all key-value pairs in the section

        Raises:
            SectionError: If the section does not exist
            ConfigNotLoaded: If the configuration is not loaded
        """
        section_envvars = {}
        try:
            section_envvars = self.__envvars.get_all_values_from_section(section)
        except Exception:
            pass

        section_conffile = {}
        if self.config_status == self.CONFIG_LOADED:
            if self.config.has_section(section):
                section_conffile = dict(self.config.items(section))
            else:
                raise SectionError(f"The section '{section}' does not exist!")
        else:
            raise ConfigNotLoaded(f"Config file '{self.config_name}' was not loaded correctly!")

        section_merged = section_conffile.copy()
        section_merged.update(section_envvars)

        return section_merged


    def status(self) -> bool:
        """
        Checks if the configuration was successfully loaded

        Returns:
            bool: True if loaded, False otherwise
        """
        return self.CONFIG_LOADED if self.config_status else self.CONFIG_NOT_LOADED
