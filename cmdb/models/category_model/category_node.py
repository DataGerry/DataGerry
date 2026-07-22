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
<<<<<<< HEAD
from itertools import chain
=======
from typing import Any
>>>>>>> origin/version-3.2

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
            children: list["CategoryNode"] | None = None,
            types_by_id: dict[int, CmdbType] | None = None) -> None:
        """
        Initializes a CategoryNode

        Args:
            category (CmdbCategory): The CmdbCategory associated with this node
            children (list[CategoryNode] | None, optional): A list of child CategoryNodes, sorted by their
                                                            order. Defaults to None
            types_by_id (dict[int, CmdbType] | None, optional): A {public_id: CmdbType} lookup of all
                                                                available CmdbTypes; the node selects the
                                                                ones referenced by the CmdbCategory.
                                                                Defaults to None
        """
        self.category = category
        self.node_order: int | None = self.category.get_meta().get_order()

        self.children: list["CategoryNode"] = sorted(
            children or [], key=lambda node: (node.get_order() is None, node.get_order())
        )

        # Resolve the referenced CmdbTypes via the lookup, preserving the CmdbCategory's declared
        # type order and skipping ids without a loaded CmdbType (O(referenced ids) per node)
        lookup: dict[int, CmdbType] = types_by_id or {}
        self.types: list[CmdbType] = [
            lookup[type_id] for type_id in self.category.types if type_id in lookup
        ]


    def __repr__(self) -> str:
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
    def to_json(cls, instance: "CategoryNode") -> dict[str, Any]:
        """
        Converts a CategoryNode into a json compatible dict

        Args:
            instance (CategoryNode): The CategoryNode which should be converted

        Returns:
            dict[str, Any]: Json compatible dict of the CategoryNode values
        """
        return {
            'category': CmdbCategory.to_json(instance.category),
            'node_order': instance.node_order,
            'children': [CategoryNode.to_json(child_node) for child_node in instance.children],
            'types': [CmdbType.to_json(a_type) for a_type in instance.types]
        }

# -------------------------------------------------- HELPER METHODS -------------------------------------------------- #

    def get_order(self) -> int | None:
        """
        Returns the order value from the CmdbCategory associated with this CategoryNode

        Returns:
            int | None: The order value of the CategoryNode, or None when no order is set
        """
        return self.node_order
