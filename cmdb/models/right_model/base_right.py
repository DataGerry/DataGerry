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
configuration, not persisted data: the tree is built at import time and served from memory.

The invariant worth knowing before touching this class: the **name is fully qualified** - `__init__`
prefixes the caller's `name` with the subclass `PREFIX`, so `ObjectRight('view')` becomes
`base.framework.object.view`. `CmdbUserGroup` stores and compares those qualified names, and
`has_extended_right` walks them segment by segment, so the prefixing is part of the authorisation contract and
not a display concern. A right carries a name, a label and a description - nothing else decides what it grants
"""
from typing import Any

from cmdb.models.right_model.right_constants import GLOBAL_RIGHT_IDENTIFIER, RightKey
# -------------------------------------------------------------------------------------------------------------------- #

# -------------------------------------------------------------------------------------------------------------------- #
#                                                   BaseRight - CLASS                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
class BaseRight:
    """
    Base class for Rights in DataGerry - the single node type of the right tree

    Every right family (`FrameworkRight`, `IsmsRight`, `UserManagementRight`, ...) extends it and only sets its
    `PREFIX`, so a right is declared as `ObjectRight('view', description=...)`
    """
    PREFIX: str = 'base'

    def __init__(self, name: str, label: str | None = None, description: str | None = None) -> None:
        """
        Initializes a BaseRight instance

        The stored `name` is the fully qualified one (`PREFIX` + '.' + the given name), and `label`
        defaults to the last segment of the PREFIX joined with the last segment of the name - so
        `ObjectRight('view')` is named `base.framework.object.view` and labelled `object.view`

        Args:
            name (str): The internal name of the right, without the PREFIX
            label (str | None): A human-readable label for the right. Defaults to a generated label
            description (str | None): What holding the right lets a user do
        """
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
        `key=lambda right: right[sort]`, where `sort` is the caller's `?sort=` query value. The rights
        routes refuse a value outside `RIGHT_SORTABLE_FIELDS` with a 400 first; an attribute name that
        does not exist would otherwise raise AttributeError from here

        Args:
            item (str): The attribute name

        Returns:
            Any: The value of the requested attribute

        Raises:
            AttributeError: If the instance has no attribute of that name
        """
        return self.__getattribute__(item)


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
            RightKey.NAME.value: instance.name,
            RightKey.LABEL.value: instance.label,
            RightKey.DESCRIPTION.value: instance.description,
            RightKey.IS_MASTER.value: instance.is_master
        }
