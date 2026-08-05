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
Implementation of BaseMediaFile
"""
from logging import Logger, getLogger
from typing import Any

from pymongo import IndexModel
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                 BaseMediaFile - CLASS                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class BaseMediaFile:
    """
    Base class representing a media file in a database

    This class provides foundational attributes and methods for handling media file metadata
    It defines indexing structures for MongoDB and initializes object attributes dynamically
    """
    ASCENDING = 1
    DESCENDING = -1
    COLLECTION = 'media.*'

    SUPER_INDEX_KEYS: list[dict[str, Any]] = [
        {'keys': [('public_id', ASCENDING)], 'name': 'public_id', 'unique': True}
    ]

    REQUIRED_INIT_KEYS = []
    INDEX_KEYS = []


    def __init__(self, **kwargs) -> None:
        """
        Initialize a BaseMediaFile instance with dynamic attributes

        Args:
            **kwargs: Arbitrary keyword arguments representing attributes to be set on the instance
        """
        self.public_id = None

        for key, value in kwargs.items():
            setattr(self, key, value)


    @classmethod
    def get_index_keys(cls) -> list[IndexModel]:
        """
        Return a list of MongoDB index models for the collection

        Combines class-defined index keys with the predefined `SUPER_INDEX_KEYS`

        Returns:
            list[IndexModel]: A list of `IndexModel` objects representing database indexes
        """
        index_list = [IndexModel(**index) for index in cls.INDEX_KEYS + cls.SUPER_INDEX_KEYS]

        return index_list
