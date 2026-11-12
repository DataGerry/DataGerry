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
from logging import Logger, getLogger
from abc import abstractmethod

from cmdb.database import MongoDatabaseManager

from cmdb.manager import (
    TypesManager,
    CategoriesManager,
    ObjectsManager,
    SettingsManager,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# Refusal of an update constructed without the caller's database manager
MISSING_DATABASE_MANAGER_MESSAGE: str = (
    "A database update runs on the caller's database manager and builds none of its own"
)

# -------------------------------------------------------------------------------------------------------------------- #
#                                              BaseDatabaseUpdate - CLASS                                              #
# -------------------------------------------------------------------------------------------------------------------- #
class BaseDatabaseUpdate:
    """
    Base class for database updates
    """
    def __init__(self, dbm: MongoDatabaseManager, db_name: str | None) -> None:
        """
        Initialises the update with a database manager, target database and the domain managers

        The update runs on the caller's manager and never builds its own: a second manager would open a second
        client and start a keep-alive thread that nothing closes. Both callers - `DatabaseUpdater.run_updates` and
        the configuration import's staging migration - hand theirs in

        Args:
            dbm (MongoDatabaseManager): Database manager to run the update on
            db_name (str | None): Target database name; falls back to the manager's default when falsy - the
                                  updater passes None for the default database

        Raises:
            ValueError: If no database manager is given
        """
        if dbm is None:
            raise ValueError(MISSING_DATABASE_MANAGER_MESSAGE)

        self.dbm: MongoDatabaseManager = dbm
        self.db_name: str = db_name if db_name else self.dbm.db_name

        self.categories_manager: CategoriesManager = CategoriesManager(self.dbm, self.db_name)
        self.objects_manager: ObjectsManager = ObjectsManager(self.dbm, self.db_name)
        self.types_manager: TypesManager = TypesManager(self.dbm, self.db_name)
        self.settings_manager: SettingsManager = SettingsManager(self.dbm, self.db_name)


    @abstractmethod
    def creation_date(self) -> int:
        """
        Returns the creation date of the update

        Returns:
            int: The update creation date as a single integer in format {year}{month}{day}
        """
        raise NotImplementedError


    @abstractmethod
    def description(self) -> str:
        """
        Provides a brief description of the update

        Returns:
            str: A description of the update
        """
        raise NotImplementedError


    @abstractmethod
    def start_update(self) -> None:
        """
        Starts the update process. Subclasses implement this to define their specific update logic
        """
        raise NotImplementedError


    def increase_updater_version(self, value: int) -> None:
        """
        Persists the updater version number in the database

        Args:
            value (int): The new version number to set (typically an update's creation_date)
        """
        self.settings_manager.write(_id='updater', data={'_id':'updater', 'version': value})
