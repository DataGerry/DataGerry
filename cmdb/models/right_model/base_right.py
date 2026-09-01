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
Implementation of BaseRight, the single node type of DataGerry's static rights tree

Every right in the product is an instance of this class or of one of its `PREFIX`-specialising
subclasses (see `all_rights.py` for the tree they are assembled into). A right is immutable
configuration, not persisted data: the tree is built at import time and served from memory, so the
only validation that ever runs is the one in the `level` setter below.

Two invariants are worth knowing before touching this class:

* the **name is fully qualified** - `__init__` prefixes the caller's `name` with the subclass
  `PREFIX`, so `ObjectRight('view')` becomes `base.framework.object.view`. `CmdbUserGroup` stores and
  compares those qualified names, and `has_extended_right` walks them segment by segment, so the
  prefixing is part of the authorisation contract and not a display concern
* the **level is bounded per subclass** - `MIN_LEVEL` / `MAX_LEVEL` are class attributes a subclass
  may narrow, and the setter refuses anything outside them
"""
from typing import Any

from cmdb.models.right_model.levels_enum import Levels
from cmdb.models.right_model.constants import GLOBAL_RIGHT_IDENTIFIER

from cmdb.errors.security import InvalidLevelRightError, MinLevelRightError, MaxLevelRightError
# -------------------------------------------------------------------------------------------------------------------- #

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

        The stored `name` is the fully qualified one (`PREFIX` + '.' + the given name), and `label`
        defaults to the last segment of the PREFIX joined with the last segment of the name - so
        `ObjectRight('view')` is named `base.framework.object.view` and labelled `object.view`

        Args:
            level (Levels): The permission level assigned to the right
            name (str): The internal name of the right, without the PREFIX
            label (str, optional): A human-readable label for the right. Defaults to a generated label
            description (str, optional): A description of what the right permits or controls

        Raises:
            InvalidLevelRightError: If the provided level is not a Levels member
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


    def __getitem__(self, item: str) -> Any:
        """
        Enables dictionary-style access to attributes

        This is not a convenience: `RightsManager.iterate_rights` sorts the flattened tree with
        `key=lambda right: right[sort]`, where `sort` is the caller's `?sort=` query value. An
        attribute name that does not exist therefore raises AttributeError from here, which the
        manager wraps into `RightsManagerIterationError` and the route reports as a 500

        Args:
            item (str): The attribute name

        Returns:
            Any: The value of the requested attribute

        Raises:
            AttributeError: If the instance has no attribute of that name
        """
        return self.__getattribute__(item)


    @property
    def level(self) -> Levels:
        """
        The permission level of the right

        Returns:
            Levels: The current level assigned
        """
        return self._level


    @level.setter
    def level(self, level: Levels) -> None:
        """
        Sets the permission level with validation against min and max thresholds

        The type check is an `isinstance` and deliberately not `level not in Levels`: since Python
        3.12 `Enum.__contains__` also answers value lookups, so `50 in Levels` is True and a raw int
        equal to a level's value would pass the membership test and then fail on `level.value` with
        an AttributeError instead of the InvalidLevelRightError documented here

        Args:
            level (Levels): The level to assign

        Raises:
            InvalidLevelRightError: If the input is not a Levels member
            MinLevelRightError: If the level is too low
            MaxLevelRightError: If the level is too high
        """
        if not isinstance(level, Levels):
            raise InvalidLevelRightError(level)

        if level.value < self.MIN_LEVEL.value:
            raise MinLevelRightError(f"Level was {level}, expected at least {self.MIN_LEVEL}")

        if level.value > self.MAX_LEVEL.value:
            raise MaxLevelRightError(f"Level was {level}, expected at most {self.MAX_LEVEL}")

        self._level = level


    @classmethod
    def to_dict(cls, instance: "BaseRight") -> dict[str, Any]:
        """
        Serializes a BaseRight instance into a dictionary

        Args:
            instance (BaseRight): The instance to serialize

        Returns:
            dict[str, Any]: Dictionary containing the right's data
        """
        return {
            'level': instance.level,
            'name': instance.name,
            'label': instance.label,
            'description': instance.description,
            'is_master': instance.is_master
        }
