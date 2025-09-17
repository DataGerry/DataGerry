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
Implementation of SystemConfigReader
"""
import os

from cmdb.manager.system_manager.config_file_reader import ConfigFileReader
# -------------------------------------------------------------------------------------------------------------------- #

# -------------------------------------------------------------------------------------------------------------------- #
#                                              SystemConfigReader - CLASS                                              #
# -------------------------------------------------------------------------------------------------------------------- #
class SystemConfigReader:
    """
    System reader for local config file
    Options from config file can be overwritten by environment vars
    """
    DEFAULT_CONFIG_LOCATION = os.path.join(os.path.dirname(__file__), '../../etc/')
    DEFAULT_CONFIG_NAME = 'cmdb.conf'
    RUNNING_CONFIG_LOCATION = DEFAULT_CONFIG_LOCATION
    RUNNING_CONFIG_NAME = DEFAULT_CONFIG_NAME
    CONFIG_LOADED = True
    CONFIG_NOT_LOADED = False
    instance = None


    def __new__(cls, config_name: str | None = None, config_location=None) -> ConfigFileReader:
        if not SystemConfigReader.instance:
            SystemConfigReader.instance = ConfigFileReader(config_name, config_location)

        return SystemConfigReader.instance


    def __getattr__(self, name):
        return getattr(self.instance, name)


    def __setattr__(self, name, value) -> None:
        return setattr(self.instance, name, value)
