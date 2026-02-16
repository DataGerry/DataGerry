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
Represents a CategoryTree of CmdbCategories in DataGerry
"""
from logging import Logger, getLogger

from cmdb.models.type_model import CmdbType
from cmdb.models.category_model.cmdb_category import CmdbCategory
from cmdb.models.category_model.category_node import CategoryNode
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                 CategoryTree - CLASS                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
class CategoryTree:
    """
    Implementation of a CategoryTree build with CmdbCategories
    """
    MODEL = 'CategoryTree'

    def __init__(self, categories: list[CmdbCategory], types: list[CmdbType] = None):
        """
        Initializes the CategoryTree with the given CmdbCategories and CmdbTypes. Builds a sorted tree structure 
        based on the CmdbCategories' order

        Args:
            categories (list[CmdbCategory]): A list of CmdbCategories to create the CategoryTree
            types (list[CmdbType], optional): A list of CmdbTypes to associate with the CmdbCategories.
                                              Defaults to None
        """
        self.categories = categories
        self.types = types
        self._tree: list[CategoryNode] = sorted(
            self.__create_tree(self.categories, types=self.types),
            key=lambda node: (node.get_order() is None, node.get_order())
        )


    def __len__(self) -> int:
        """
        Returns the number of root CmdbCategories in the CategoryTree.
        The root CmdbCategories are the top-level CategoryNodes in the hierarchy.

        Returns:
            int: The number of root CmdbCategories (top-level CategoryNodes)
        """
        return len(self._tree)


    @property
    def tree(self) -> list[CategoryNode]:
        """
        Returns the CategoryTree
        """
        return self._tree


    @tree.setter
    def tree(self, value):
        """
        Sets the CategoryTree
        """
        self._tree = value

# --------------------------------------------------- CLASS METHODS -------------------------------------------------- #

    @classmethod
    def __create_tree(
            cls,
            categories: list[CmdbCategory],
            parent: int = None, types: list[CmdbType] = None) -> list[CategoryNode]:
        """
        Recursively generate a CmdbCategory tree from a list of CmdbCategories

        Args:
            categories list[CmdbCategory]: list of root/child CmdbCategories
            parent (int, optional): The parent public_id of the CmdbCategory for the current subset of CmdbCategories.
                    Defaults to None (for root CmdbCategories)
            types (list[CmdbType], optional): A list of all available CmdbTypes to associate with the CmdbCategories.
                                              Defaults to None

        Returns:
            list[CategoryNode]: A list of CategoryNodes representing the CmdbCategory hierarchy
        """
        # Avoid infinite recursion by filtering out categories already in the tree
        child_categories = [
            category for category in categories if category.parent == parent
        ]

        if not child_categories:
            return []  # Base case: return empty if no children for this parent

        # Recursively create nodes for each child category
        nodes = []
        for category in child_categories:
            # Avoid adding categories already in the tree to prevent circular references
            if category not in [node.category for node in nodes]:  # Check if category is already in the nodes list
                node = CategoryNode(
                    category,
                    cls.__create_tree(categories, category.get_public_id(), types),
                    types
                )
                nodes.append(node)

        return nodes


    @classmethod
    def from_data(cls, raw_categories: list[dict]) -> "CategoryTree":
        """
        Initialises a CategoryTree from a dict

        Args:
            data (dict): Data with which the CategoryTree should be initialised

        Returns:
            CategoryTree: CategoryTree with the given data
        """
        categories: list[CmdbCategory] = [CmdbCategory.from_data(category) for category in raw_categories]

        return cls(categories=categories)


    @classmethod
    def to_json(cls, instance: "CategoryTree"):
        """
        Converts a CategoryTree into a json compatible dict

        Args:
            instance (CategoryTree): The CategoryTree which should be converted

        Returns:
            dict: Json compatible dict of the CategoryTree values
        """
        return [CategoryNode.to_json(node) for node in instance.tree]

# -------------------------------------------------- HELPER METHODS -------------------------------------------------- #

    def flatten(self) -> list[CmdbCategory]:
        """
        Flattens the CategoryTree into a list of CmdbCategories, maintaining the hierarchy order
        
        Returns:
            list[CmdbCategory]: A list of CmdbCategories representing the flattened CategoryTree
        """
        return [category for node in self.tree for category in node.flatten()]
