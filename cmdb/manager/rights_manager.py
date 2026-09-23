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
from typing import Any

from cmdb.models.right_model.base_right import BaseRight
from cmdb.models.right_model.all_rights import ALL_RIGHTS, flat_rights_tree
from cmdb.framework.results import IterationResult
from cmdb.framework.search.list_search import matches_search_term

from cmdb.errors.manager.rights_manager import (
    RightsManagerInitError,
    RightsManagerGetError,
    RightsManagerIterationError,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# The fields a `?search=` term is matched against. `name` is the identifier a caller filters by,
# `label` and `description` are what a human reads in the table - the same three the rights list
# shows as columns
RIGHT_SEARCHABLE_FIELDS: tuple[str, ...] = ('name', 'label', 'description')

# -------------------------------------------------------------------------------------------------------------------- #
#                                                 RightsManager - CLASS                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class RightsManager:
    """
    Manages the static collection of DataGerry rights defined in the `ALL_RIGHTS` tree.

    Unlike the other managers, `RightsManager` is not database-backed: the rights are a
    compile-time tree, so this class only flattens that tree once and serves it in-memory.
    It deliberately does not extend `BaseManager` (there is no collection or `MongoDatabaseManager`)
    and is not registered with `ManagerProvider`. It provides functionality to flatten the tree,
    retrieve a single right, iterate over the rights with pagination/sorting, and serialize the
    tree to JSON.
    """

    def __init__(self) -> None:
        """
        Initializes the RightsManager with a flattened version of the `ALL_RIGHTS` tree

        Raises:
            RightsManagerInitError: If the RightsManager could not be initialised
        """
        try:
            self.rights: list[BaseRight] = RightsManager.flat_tree(ALL_RIGHTS)
        except Exception as err:
            raise RightsManagerInitError(err) from err

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

    def iterate_rights(
            self,
            limit: int,
            skip: int,
            sort: str,
            order: int,
            search: str | None = None,
        ) -> IterationResult[BaseRight]:
        """
        Iterates over the rights with optional searching, pagination and sorting.

        A `search` term narrows the set FIRST, so the reported total is the number of matches and a
        pager built on it offers the pages that actually exist. Sorting is applied next, then a
        single `skip`/`limit` window is sliced out. A `skip` beyond the end yields an empty page
        rather than raising.

        The term is matched the way every other list route matches `?search=` - as literal text,
        case-insensitively, against the fields `RIGHT_SEARCHABLE_FIELDS` declares - through the
        shared `matches_search_term`. An absent or blank term narrows nothing, so an unsearched
        listing is exactly what it was.

        Args:
            limit (int): Maximum number of rights to return in one page. If <= 0, returns all
            skip (int): Number of rights to skip before starting the page
            sort (str): Attribute name to sort by
            order (int): Sorting order, 1 for ascending, -1 for descending
            search (str | None): Free-text term; None or blank returns every right

        Returns:
            IterationResult[BaseRight]: Paginated and sorted result of the matching rights

        Raises:
            RightsManagerIterationError: If retrieving the rights failed
        """
        try:
            matching_rights: list[BaseRight] = [
                right for right in self.rights
                if matches_search_term((right[field] for field in RIGHT_SEARCHABLE_FIELDS), search)
            ]

            sorted_rights: list[BaseRight] = sorted(matching_rights,
                                                    key=lambda right: right[sort],
                                                    reverse=order == -1)

            spliced_rights: list[BaseRight] = sorted_rights[skip:skip + limit] if limit > 0 else sorted_rights

            return IterationResult(spliced_rights, len(matching_rights))
        except Exception as err:
            raise RightsManagerIterationError(err) from err


    def get_right(self, name: str) -> BaseRight | None:
        """
        Retrieves a right by its name

        Args:
            name (str): Name of the right to retrieve

        Returns:
            BaseRight | None: The right matching the given name, or None when no right matches

        Raises:
            RightsManagerGetError: If retrieval fails unexpectedly
        """
        try:
            return next((right for right in self.rights if right.name == name), None)
        except Exception as err:
            raise RightsManagerGetError(err) from err

# -------------------------------------------------- HELPER METHODS -------------------------------------------------- #

    @staticmethod
    def flat_tree(right_tree: tuple | list) -> list[BaseRight]:
        """
        Flattens a nested right tree into a flat list of rights

        Kept as the manager-side entry point, but the recursion itself lives once in
        `cmdb.models.right_model.all_rights.flat_rights_tree`, which `GroupsManager` also uses - the
        two had byte-identical bodies before

        Args:
            right_tree (tuple | list): A nested structure containing rights

        Returns:
            list[BaseRight]: A flat list containing all rights
        """
        return flat_rights_tree(right_tree)


    @staticmethod
    def tree_to_json(right_tree: tuple | list) -> list[Any]:
        """
        Converts a nested rights tree into a JSON-serializable structure

        Preserves the nesting: each branch becomes a nested list and each leaf `BaseRight`
        becomes its `to_dict` representation.

        Args:
            right_tree (tuple | list): A nested structure containing rights

        Returns:
            list[Any]: A JSON-serializable, nesting-preserving representation of the rights tree
                (each element is either a right dict or a nested list of the same shape)
        """
        raw_tree: list[Any] = []

        for node in right_tree:
            if isinstance(node, (tuple, list)):
                raw_tree.append(RightsManager.tree_to_json(node))
            else:
                raw_tree.append(BaseRight.to_dict(node))

        return raw_tree
