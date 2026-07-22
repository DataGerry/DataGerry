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
<<<<<<< HEAD
=======


# -------------------------------------------------------------------------------------------------------------------- #
#                                                    INDEX HELPERS                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
def index_types_by_id(types: list[CmdbType] | None) -> dict[int, CmdbType]:
    """
    Builds a {public_id: CmdbType} lookup so a CategoryNode resolves its types in O(1) per id

    Args:
        types (list[CmdbType] | None): All available CmdbTypes, or None

    Returns:
        dict[int, CmdbType]: Mapping of every CmdbType's public_id to the CmdbType
    """
    return {a_type.public_id: a_type for a_type in types or []}


def group_categories_by_parent(
        categories: list[CmdbCategory]) -> dict[int | None, list[CmdbCategory]]:
    """
    Groups CmdbCategories by their parent public_id so the tree build never re-scans the full list

    The per-parent lists keep the input order, so the resulting tree preserves the original
    CmdbCategory ordering before each node's children are sorted by their own order value

    Args:
        categories (list[CmdbCategory]): The CmdbCategories to group

    Returns:
        dict[int | None, list[CmdbCategory]]: Mapping of parent public_id (None for roots) to its
            direct child CmdbCategories
    """
    grouped: dict[int | None, list[CmdbCategory]] = {}

    for category in categories:
        grouped.setdefault(category.parent, []).append(category)

    return grouped

>>>>>>> origin/version-3.2

# -------------------------------------------------------------------------------------------------------------------- #
#                                                 CategoryTree - CLASS                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
class CategoryTree:
    """
    Implementation of a CategoryTree build with CmdbCategories
    """
    MODEL = 'CategoryTree'

    def __init__(self, categories: list[CmdbCategory], types: list[CmdbType] | None = None) -> None:
        """
        Initializes the CategoryTree with the given CmdbCategories and CmdbTypes. Builds a sorted tree structure
        based on the CmdbCategories' order

        Args:
            categories (list[CmdbCategory]): A list of CmdbCategories to create the CategoryTree
            types (list[CmdbType] | None, optional): A list of CmdbTypes to associate with the CmdbCategories.
                                                     Defaults to None
        """
        self.categories = categories
        self.types = types
        types_by_id: dict[int, CmdbType] = index_types_by_id(types)
        children_by_parent: dict[int | None, list[CmdbCategory]] = group_categories_by_parent(categories)
        self._tree: list[CategoryNode] = sorted(
            self.__create_tree(children_by_parent, types_by_id),
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

        Returns:
            list[CategoryNode]: The root CategoryNodes in display order
        """
        return self._tree

# --------------------------------------------------- CLASS METHODS -------------------------------------------------- #

    @classmethod
    def __create_tree(
            cls,
            children_by_parent: dict[int | None, list[CmdbCategory]],
            types_by_id: dict[int, CmdbType],
            parent: int | None = None,
            visited: set[int] | None = None) -> list[CategoryNode]:
        """
        Recursively generate a CmdbCategory tree from a parent-grouped CmdbCategory index

        Linear in the number of CmdbCategories: each level reads only its direct children from
        ``children_by_parent`` instead of re-scanning the full list, and every CategoryNode
        resolves its types through the shared ``types_by_id`` lookup.

        Cycle-safe: every CmdbCategory is placed into the tree at most once, tracked via the
        shared ``visited`` set. Stored data containing a self-parent or a parent cycle (the
        write path rejects these, but legacy / hand-edited documents may still carry them)
        therefore cannot recurse infinitely - the offending CmdbCategories are simply not
        re-entered

        Args:
            children_by_parent (dict[int | None, list[CmdbCategory]]): CmdbCategories grouped by
                    their parent public_id (None for roots), as built by group_categories_by_parent
            types_by_id (dict[int, CmdbType]): {public_id: CmdbType} lookup of all available CmdbTypes
            parent (int | None, optional): The parent public_id for the current subset of
                    CmdbCategories. Defaults to None (for root CmdbCategories)
            visited (set[int] | None, optional): public_ids already placed in the tree; shared
                    across the recursion. Defaults to None (a fresh set at the root call)

        Returns:
            list[CategoryNode]: A list of CategoryNodes representing the CmdbCategory hierarchy
        """
        placed: set[int] = set() if visited is None else visited
        nodes: list[CategoryNode] = []

        for category in children_by_parent.get(parent, []):
            public_id: int = category.get_public_id()

            if public_id in placed:
                continue

            placed.add(public_id)
            nodes.append(CategoryNode(
                category,
                cls.__create_tree(children_by_parent, types_by_id, public_id, placed),
                types_by_id
            ))

        return nodes


    @classmethod
    def to_json(cls, instance: "CategoryTree") -> list[dict]:
        """
        Converts a CategoryTree into a json compatible list of dicts

        Args:
            instance (CategoryTree): The CategoryTree which should be converted

        Returns:
            list[dict]: Json compatible list of the CategoryTree's root nodes
        """
        return [CategoryNode.to_json(node) for node in instance.tree]
