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
Represents a CategoryNode of a CategoryTree in DataGerry
"""
from logging import Logger, getLogger
from itertools import chain

from cmdb.models.type_model import CmdbType
from cmdb.models.category_model.cmdb_category import CmdbCategory
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                 CategoryNode - CLASS                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
class CategoryNode:
    """
    Represents a CategoryNode in a CategoryTree
    """
    def __init__(
            self,
            category: CmdbCategory,
            children: list["CategoryNode"] = None,
            types: list[CmdbType] = None):
        """
        Initializes a CategoryNode

        Args:
            category (CmdbCategory): The CmdbCategory associated with this node
            children (list[CategoryNode], optional): A list of child CategoryNodes, sorted by their order.
                                                     Defaults to None
            types (list[CmdbType], optional): A list of CmdbType instances to filter based on the CmdbCategory's types.
                                              Defaults to None
        """
        try:
            self.category = category
            self.node_order = self.category.get_meta().get_order()

            self.children: list["CategoryNode"] = sorted(
                children or [], key=lambda node: (node.get_order() is None, node.get_order())
            )

            # Filter and maintain correct type order
            self.types = [
                a_type for type_id in self.category.types for a_type in (types or []) if type_id == a_type.public_id
            ]
        except Exception as err:
            LOGGER.debug("CategoryNode Exception: %s", err)
            raise err


    def __repr__(self):
        """
        String representation of the CategoryNode for debugging and logging

        Returns:
            str: A string representation of the CategoryNode
        """
        return f"CategoryNode(CategoryID={self.category.public_id}, " \
               f"NodeOrder={self.node_order}, " \
               f"ChildrenCount={len(self.children)})"

# --------------------------------------------------- CLASS METHODS -------------------------------------------------- #

    @classmethod
    def to_json(cls, instance: "CategoryNode"):
        """
        Converts a CategoryNode into a json compatible dict

        Args:
            instance (CategoryNode): The CategoryNode which should be converted

        Returns:
            dict: Json compatible dict of the CategoryNode values
        """
        return {
            'category': CmdbCategory.to_json(instance.category),
            'node_order': instance.node_order,
            'children': [CategoryNode.to_json(child_node) for child_node in instance.children],
            'types': [CmdbType.to_json(type) for type in instance.types]
        }

# -------------------------------------------------- HELPER METHODS -------------------------------------------------- #

    def get_order(self) -> int:
        """
        Returns the order value from the CmdbCategory associated with this CategoryNode
        
        Returns:
            int: The order value of the CategoryNode
        """
        return self.node_order


    def flatten(self) -> list[CmdbCategory]:
        """
        Flattens this CategoryNode and its children into a single list

        Returns:
            list[CmdbCategory]: A flat list of CmdbCategories
        """
        return [self.category] + list(chain.from_iterable(c.flatten() for c in self.children))
