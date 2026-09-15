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
Module for reading and managing system configuration files

A ConfigFileReader serves the values of an ini config file overlaid with the matching
``DATAGERRY_<SECTION>_<NAME>`` environment variables (collected by SystemEnvironmentReader):

* the **environment always wins** over a value of the same name in the file - it is an override, not
  just a fallback;
* a section that exists **only** in the environment is served as well, and is listed by
  ``get_sections``, so an installation can be configured entirely through environment variables -
  including with no config file at all (*file-less mode*, ``config_name=None``);
* every value is passed through ``auto_cast`` on **both** paths, so ``port = 27017`` is served as the
  int ``27017`` whether it came from the file or from ``DATAGERRY_Database_port``.

The reader is read-only: the config file (plus the overlay) is the single source of truth, and there is
no API to mutate the loaded configuration in memory.
"""
import os
from logging import Logger, getLogger
from typing import Any, Mapping

import configparser
from cmdb.utils import auto_cast
from cmdb.manager.system_manager.system_env_reader import SystemEnvironmentReader
from cmdb.manager.system_manager.system_reader import SystemReader

from cmdb.errors.system_config import (
    ConfigFileNotFound,
    ConfigFileParsingError,
    ConfigNotLoaded,
    SectionError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# Sentinel telling "the caller passed no default" apart from an explicit default of None, so
# get_value(..., default=None) can legitimately serve None instead of raising
_NO_DEFAULT: Any = object()

# Stand-in for the file name in error messages of a reader that has no config file (file-less mode)
_FILE_LESS_LABEL: str = '<file-less>'

# -------------------------------------------------------------------------------------------------------------------- #
#                                               ConfigFileReader - CLASS                                               #
# -------------------------------------------------------------------------------------------------------------------- #
class ConfigFileReader(SystemReader):
    """
    Configuration file reader for handling system settings

    Loads an ini config file (or none at all) and serves its values overlaid with the matching
    DATAGERRY_* environment variables, which take precedence - see the module docstring for the
    precedence, the env-only sections and the casting rules

    Extends: SystemReader
    """
    CONFIG_LOADED = True
    CONFIG_NOT_LOADED = False


    def __init__(self, config_name: str | None, config_location: str | None) -> None:
        """
        Initializes the configuration reader

        ``config_name=None`` selects file-less mode: no file is read and every value comes from the
        environment. ``config_name`` / ``config_location`` / ``config_file`` are always defined (all
        three are None in file-less mode, which is how a consumer recognises it)

        Args:
            config_name (str | None): Name of the configuration file including its extension; None
                                      selects file-less mode
            config_location (str | None): Directory holding the configuration file

        Raises:
            ConfigFileNotFound: If a configuration file was requested but does not exist
            ConfigFileParsingError: If the configuration file exists but is not valid ini content
        """
        self.config = configparser.ConfigParser()
        self.config_name: str | None = config_name
        self.config_location: str | None = config_location
        self.config_file: str | None = None

        if config_name is None:
            self.config_status = self.CONFIG_LOADED
        else:
            self.config_status = self.CONFIG_NOT_LOADED
            # os.path.join instead of concatenation: a location without a trailing separator used to
            # silently produce a wrong path, reported as "config file not found"
            self.config_file = os.path.join(config_location or '', config_name)
            self.config_status = self.setup()

        if self.config_status == self.CONFIG_NOT_LOADED:
            raise ConfigFileNotFound(f"Config file: {self.config_file} was not found!")

        # load environment variables
        self.__envvars = SystemEnvironmentReader()


    def setup(self) -> bool:
        """
        Initializes the configuration file

        A missing file is reported through the return value (the constructor turns it into a
        ConfigFileNotFound); a file that exists but cannot be parsed is a hard error and propagates

        Returns:
            bool: True if the configuration was loaded successfully, otherwise False

        Raises:
            ConfigFileParsingError: If the configuration file is not valid ini content
        """
        try:
            self.read_config_file(self.config_file)
            return self.CONFIG_LOADED
        except ConfigFileNotFound:
            return self.CONFIG_NOT_LOADED


    def read_config_file(self, file: str) -> None:
        """
        Reads the configuration file

        Args:
            file (str): The path to the configuration file

        Raises:
            ConfigFileNotFound: If the file does not exist
            ConfigFileParsingError: If the file is not valid ini content (the underlying configparser
                error is chained, never leaked to the caller)
        """
        if not os.path.isfile(file):
            raise ConfigFileNotFound(f"Config file '{file}' was not found!")

        try:
            self.config.read(file)
        except configparser.Error as err:
            raise ConfigFileParsingError(f"Config file '{file}' could not be parsed: {err}") from err


    def get_value(self, name: str, section: str, default: Any = _NO_DEFAULT) -> Any:
        """
        Retrieves a configuration value from a specified section

        The environment overlay is consulted first, then the config file; both results are cast with
        ``auto_cast``. A provided ``default`` is served whenever the value cannot be resolved - for a
        missing key *and* for a missing section - and is returned as-is (never cast). Passing
        ``default=None`` explicitly serves None instead of raising

        Args:
            name (str): The key of the configuration value
            section (str): The section where the key resides
            default (Any, optional): Value to serve when the key or its section does not exist

        Returns:
            Any: The retrieved value, cast to the appropriate type, or the default

        Raises:
            SectionError: If neither the environment nor the file knows the section and no default was given
            KeyError: If the section exists but not the key, and no default was given
            ConfigNotLoaded: If no config file is loaded and the environment does not serve the value
        """
        env_values: dict[str, str] = self._env_section_values(section)

        if name in env_values:
            return auto_cast(env_values[name])

        self._ensure_config_loaded()

        if self.config.has_section(section):
            if name in self.config[section]:
                return auto_cast(self.config[section][name])

            if default is not _NO_DEFAULT:
                return default

            raise KeyError(name)

        if default is not _NO_DEFAULT:
            return default

        if env_values:
            # The section exists in the environment overlay only, so this really is a missing key
            raise KeyError(name)

        raise SectionError(f"The section '{section}' does not exist!")


    def get_sections(self) -> list[str]:
        """
        Retrieves all sections from the configuration

        The config file's sections come first, in file order, followed by any section that only the
        environment overlay defines

        Returns:
            list[str]: A list of section names

        Raises:
            ConfigNotLoaded: If the configuration is not loaded
        """
        self._ensure_config_loaded()

        sections: list[str] = list(self.config.sections())
        sections.extend(section for section in self.__envvars.get_sections() if section not in sections)

        return sections


    def get_all_values_from_section(self, section: str) -> dict[str, Any]:
        """
        Retrieves all key-value pairs from a given section, cast to their appropriate types

        The file's values are merged with the environment overlay, which wins on a shared key. A
        section only the overlay defines is served as well, so an installation configured purely
        through environment variables (including file-less mode) resolves here too

        Args:
            section (str): The section name

        Returns:
            dict[str, Any]: All key-value pairs of the section, each value cast with ``auto_cast``

        Raises:
            SectionError: If neither the file nor the environment overlay knows the section
            ConfigNotLoaded: If no config file is loaded and the overlay does not know the section
        """
        env_values: dict[str, str] = self._env_section_values(section)
        file_values: dict[str, str] = {}

        if self.config_status == self.CONFIG_LOADED and self.config.has_section(section):
            file_values = dict(self.config.items(section))

        if not file_values and not env_values:
            self._ensure_config_loaded()

            raise SectionError(f"The section '{section}' does not exist!")

        section_values: dict[str, Any] = self._cast_values(file_values)
        section_values.update(self._cast_values(env_values))

        return section_values


# -------------------------------------------------- HELPER METHODS -------------------------------------------------- #

    def _ensure_config_loaded(self) -> None:
        """
        Guards the read methods against a reader whose configuration never loaded

        Raises:
            ConfigNotLoaded: If the configuration is not loaded
        """
        if self.config_status != self.CONFIG_LOADED:
            raise ConfigNotLoaded(
                f"Config file '{self.config_file or _FILE_LESS_LABEL}' was not loaded correctly!"
            )


    def _env_section_values(self, section: str) -> dict[str, str]:
        """
        Returns the environment overlay's values for a section, empty when it defines none

        Args:
            section (str): The section name

        Returns:
            dict[str, str]: The raw (uncast) DATAGERRY_<section>_* values, or {} when there are none
        """
        try:
            return dict(self.__envvars.get_all_values_from_section(section))
        except KeyError:
            return {}


    @staticmethod
    def _cast_values(values: Mapping[str, str]) -> dict[str, Any]:
        """
        Casts every value of a mapping with ``auto_cast``

        Args:
            values (Mapping[str, str]): The raw string values read from the file or the environment

        Returns:
            dict[str, Any]: The same keys with their values cast to bool / int / None / float / str
        """
        return {key: auto_cast(value) for key, value in values.items()}
