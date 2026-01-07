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
Implementation of BaseUpdate
"""
import logging
from abc import abstractmethod

import cmdb
from cmdb.database import MongoDatabaseManager

from cmdb.manager import (
    TypesManager,
    CategoriesManager,
    ObjectsManager,
    SettingsManager,
)

from cmdb.manager.system_manager.system_config_reader import SystemConfigReader
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER = logging.getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                              BaseDatabaseUpdate - CLASS                                              #
# -------------------------------------------------------------------------------------------------------------------- #
class BaseDatabaseUpdate:
    """
    Base class for database updates
    """
    def __init__(self, dbm:MongoDatabaseManager, db_name: str) -> None:
        scr = SystemConfigReader()
        mode = 'cloud' if cmdb.__CLOUD_MODE__ and not cmdb.__LOCAL_MODE__ else 'local'
        self.dbm: MongoDatabaseManager = dbm if dbm else MongoDatabaseManager(
                                                            **scr.get_all_values_from_section('Database'),
                                                            mode=mode
                                                         )
        self.db_name: str = db_name if db_name else self.dbm.db_name

        self.categories_manager = CategoriesManager(self.dbm, self.db_name)
        self.objects_manager = ObjectsManager(self.dbm, self.db_name)
        self.types_manager = TypesManager(self.dbm, self.db_name)
        self.settings_manager = SettingsManager(self.dbm, self.db_name)


    @abstractmethod
    def creation_date(self) -> int:
        """
        Returns the creation date of the update
        
        Returns:
            int: The update creation date as a single interger in format {year}{month}{day}
        """
        return NotImplementedError


    @abstractmethod
    def description(self) -> str:
        """
        Provides a brief description of the update
        
        Returns:
            str: A description of the update
        """
        return NotImplementedError


    @abstractmethod
    def start_update(self) -> None:
        """
        Starts the update process. This method should be implemented in subclasses to define specific update logic
        """
        return NotImplementedError


    def increase_updater_version(self, value: int):
        """
        Increments the updater version number in the database
        
        Args:
            value (int): The new version number to be set
        """
        self.settings_manager.write(_id='updater', data={'_id':'updater', 'version': value})
