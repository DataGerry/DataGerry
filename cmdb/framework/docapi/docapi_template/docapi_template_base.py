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
Implementation of TemplateManagementBase
"""
from logging import Logger, getLogger
from typing import Any

from pymongo import IndexModel
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                            TemplateManagementBase - CLASS                                            #
# -------------------------------------------------------------------------------------------------------------------- #
#TODO: REFACTOR-FIX (CmdbDAO as base for DocapiTemplates instead of this)
class TemplateManagementBase:
    """
    Base class for managing template-related database operations
    
    Attributes:
        ASCENDING (int): Constant representing ascending sort order
        DESCENDING (int): Constant representing descending sort order
        COLLECTION (str): Collection pattern for document storage
        SUPER_INDEX_KEYS (list): Default index keys for unique constraints
        IGNORED_INIT_KEYS (list): List of keys to be ignored during initialization
        REQUIRED_INIT_KEYS (list): List of keys that are required for initialization
        INDEX_KEYS (list): Custom index keys specific to derived classes
    """

    ASCENDING = 1
    DESCENDING = -1
    COLLECTION = "docapi.*"

    SUPER_INDEX_KEYS: list[dict[str, Any]] = [
        {
            "keys": [("public_id", ASCENDING)],
            "name": "public_id",
            "unique": True
        }
    ]
    IGNORED_INIT_KEYS: list[Any] = []
    REQUIRED_INIT_KEYS: list[Any] = []
    INDEX_KEYS: list[Any] = []

    def __init__(self, **kwargs: Any) -> None:
        """
        Initializes the TemplateManagementBase instance with given keyword arguments
        
        Args:
            **kwargs (Any): Arbitrary keyword arguments representing document fields
        """
        self.public_id: int | None = None

        for key, value in kwargs.items():
            setattr(self, key, value)


    @classmethod
    def get_index_keys(cls) -> list[IndexModel]:
        """
        Retrieves the list of index models for database indexing.
        
        Returns:
            list[IndexModel]: A list of pymongo IndexModel instances representing indexes.
        """
        return [IndexModel(**index) for index in cls.INDEX_KEYS + cls.SUPER_INDEX_KEYS]


    def to_database(self) -> dict[str, Any]:
        """
        Converts the TemplateManagementBase attributes to a dictionary for database storage
        
        Returns:
            dict[str, Any]: A dictionary representation of the TemplateManagementBase
        """
        return self.__dict__
