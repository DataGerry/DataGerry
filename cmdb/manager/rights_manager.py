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
Implementation of RightsManager
"""
from logging import Logger, getLogger
from multiprocessing.managers import BaseManager

from cmdb.models.right_model.base_right import BaseRight
from cmdb.models.right_model.all_rights import ALL_RIGHTS
from cmdb.framework.results import IterationResult

from cmdb.errors.manager.rights_manager import (
    RightsManagerInitError,
    RightsManagerGetError,
    RightsManagerIterationError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                 RightsManager - CLASS                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class RightsManager(BaseManager):
    """
    Manages a collection of rights organized in a tree structure.
    Provides functionalities to flatten the tree, retrieve rights,
    and iterate over them with pagination and sorting.
    """

    def __init__(self):
        """
        Initializes the RightsManager with a flattened version of the provided rights tree

        Args:
            right_tree : A nested structure of rights

        Raises:
            RightsManagerInitError: If the RightsManager could not be initialised
        """
        try:
            self.rights = RightsManager.flat_tree(ALL_RIGHTS)

            super().__init__()
        except Exception as err:
            raise RightsManagerInitError(err) from err

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

    def iterate_rights(self, limit: int, skip: int, sort: str, order: int) -> IterationResult[BaseRight]:
        """
        Iterates over the rights with optional pagination and sorting.

        Args:
            limit (int): Maximum number of rights to return in one page. If <= 0, returns all
            skip (int): Number of rights to skip before starting the page
            sort (str): Attribute name to sort by
            order (int): Sorting order, 1 for ascending, -1 for descending

        Returns:
            IterationResult[BaseRight]: Paginated and sorted result of rights

        Raises:
            RightsManagerIterationError: If retrieving the rights failed
        """
        try:
            sorted_rights = sorted(self.rights, key=lambda right: right[sort], reverse=order == -1)

            if limit > 0:
                spliced_rights = [sorted_rights[i:i + limit] for i in range(0, len(sorted_rights),
                                  limit)][int(skip / limit)]
            else:
                spliced_rights = sorted_rights

            result: IterationResult[BaseRight] = IterationResult(spliced_rights, len(self.rights))

            return result
        except Exception as err:
            raise RightsManagerIterationError(err) from err


    def get_right(self, name: str) -> BaseRight:
        """
        Retrieves a right by its name

        Args:
            name (str): Name of the right to retrieve

        Returns:
            BaseRight: The right object matching the given name

        Raises:
            BaseManagerGetError: If no matching right is found or retrieval fails
        """
        try:
            return next(right for right in self.rights if right.name == name)
        except Exception as err:
            raise RightsManagerGetError(err) from err

# -------------------------------------------------- HELPER METHODS -------------------------------------------------- #

    @staticmethod
    def flat_tree(right_tree: tuple) -> list[BaseRight]:
        """
        Flattens a nested right tree into a flat list of rights

        Args:
            right_tree: A nested structure containing rights

        Returns:
            list[BaseRight]: A flat list containing all rights
        """
        rights: list[BaseRight] = []

        for right in right_tree:
            if isinstance(right, (tuple, list)):
                rights = rights + RightsManager.flat_tree(right)
            else:
                rights.append(right)

        return rights


    #TODO: ANNOTATION-FIX (get type of right_tree)
    @staticmethod
    def tree_to_json(right_tree) -> list:
        """
        Converts a nested rights tree into a JSON-serializable structure

        Args:
            right_tree: A nested structure containing rights

        Returns:
            list[dict]: A JSON-serializable list representing the rights tree
        """
        raw_tree = []

        for node in right_tree:
            if isinstance(node, (tuple, list)):
                raw_tree.append(RightsManager.tree_to_json(node))
            else:
                raw_tree.append(BaseRight.to_dict(node))

        return raw_tree
