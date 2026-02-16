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
Implementation of BaseRight
"""
from logging import Logger, getLogger
from cmdb.models.right_model.levels_enum import Levels
from cmdb.models.right_model.constants import GLOBAL_RIGHT_IDENTIFIER, LEVEL_TO_NAME

from cmdb.errors.security import InvalidLevelRightError, MinLevelRightError, MaxLevelRightError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                   BaseRight - CLASS                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
class BaseRight:
    """
    Base class for Rights in DataGerry.

    Handles the definition and validation of rights, including 
    level boundaries, labels, descriptions, and serialization.
    """
    MIN_LEVEL = Levels.NOTSET
    MAX_LEVEL = Levels.CRITICAL

    DEFAULT_MASTER: bool = False
    PREFIX: str = 'base'

    def __init__(self, level: Levels, name: str, label: str = None, description: str = None):
        """
        Initializes a BaseRight instance

        Args:
            level (Levels): The permission level assigned to the right
            name (str): The internal name of the right
            label (str, optional): A human-readable label for the right. Defaults to a generated label
            description (str, optional): A description of what the right permits or controls

        Raises:
            InvalidLevelRightError: If the provided level is not a valid Levels member
            MinLevelRightError: If the level is lower than the minimum allowed level
            MaxLevelRightError: If the level is higher than the maximum allowed level
        """
        self.level = level
        self.name = f'{self.PREFIX}.{name}'
        self.label = label or f'{self.get_prefix()}.{self.name.rsplit(".", maxsplit=1)[-1]}'
        self.description = description
        self.is_master = name == GLOBAL_RIGHT_IDENTIFIER


    def get_prefix(self) -> str:
        """
        Retrieves the last segment of the PREFIX, used for label generation

        Returns:
            str: The simplified prefix
        """
        return self.PREFIX.rsplit('.', maxsplit=1)[-1]


    def get_label(self) -> str:
        """
        Retrieves the label for the right. If not explicitly set, it generates one

        Returns:
            str: The label of the right
        """
        return self.label or f'{self.get_prefix()}.{self.name.rsplit(".", maxsplit=1)[-1]}'


    def __getitem__(self, item):
        """
        Enables dictionary-style access to attributes

        Args:
            item (str): The attribute name

        Returns:
            Any: The value of the requested attribute
        """
        return self.__getattribute__(item)


    @classmethod
    def get_levels(cls) -> dict:
        """
        Retrieves the mapping of levels to their human-readable names

        Returns:
            dict: Mapping of Levels to names
        """
        return LEVEL_TO_NAME


    @property
    def level(self) -> Levels:
        """
        The permission level of the right

        Returns:
            Levels: The current level assigned
        """
        return self._level


    @level.setter
    def level(self, level: Levels):
        """
        Sets the permission level with validation against min and max thresholds

        Args:
            level (Levels): The level to assign

        Raises:
            InvalidLevelRightError: If the input is not a valid Levels member
            MinLevelRightError: If the level is too low
            MaxLevelRightError: If the level is too high
        """
        if level not in Levels:
            raise InvalidLevelRightError(level)

        if level.value < self.MIN_LEVEL.value:
            raise MinLevelRightError(f"Level was {level}, expected at least {self.MIN_LEVEL}")

        if level.value > self.MAX_LEVEL.value:
            raise MaxLevelRightError(f"Level was {level}, expected at most {self.MAX_LEVEL}")

        self._level = level


    @classmethod
    def to_dict(cls, instance: "BaseRight") -> dict:
        """
        Serializes a BaseRight instance into a dictionary

        Args:
            instance (BaseRight): The instance to serialize

        Returns:
            dict: Dictionary containing the right's data
        """
        return {
            'level': instance.level,
            'name': instance.name,
            'label': instance.label,
            'description': instance.description,
            'is_master': instance.is_master
        }
