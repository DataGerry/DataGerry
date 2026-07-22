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
Unit tests for cmdb.manager.rights_manager.RightsManager

Pure tests: no Mongo. RightsManager is not database-backed - it flattens the static
``ALL_RIGHTS`` tree into an in-memory list - so every method is exercised directly against
hand-built ``BaseRight`` fixtures (or a manager whose ``rights`` are replaced with a
deterministic list) to keep ordering independent of the real rights tree.
"""
from typing import Any
from unittest.mock import patch

import pytest

from cmdb.manager.rights_manager import RightsManager
from cmdb.models.right_model.base_right import BaseRight
from cmdb.models.right_model.levels_enum import Levels

from cmdb.errors.manager.rights_manager import (
    RightsManagerInitError,
    RightsManagerGetError,
    RightsManagerIterationError,
)
# -------------------------------------------------------------------------------------------------------------------- #

MODULE_PATH: str = 'cmdb.manager.rights_manager'

# BaseRight prefixes every name with 'base.', so a fixture built as 'a' is queried as 'base.a'
RIGHT_PREFIX: str = 'base.'
SORTED_LEAF_NAMES: list[str] = ['a', 'b', 'c', 'd', 'e']
TOTAL_FIXTURE_RIGHTS: int = len(SORTED_LEAF_NAMES)

MASTER_RIGHT_NAME: str = 'base.*'
MISSING_RIGHT_NAME: str = 'base.does.not.exist'
UNKNOWN_SORT_KEY: str = 'this_attribute_does_not_exist'

ORDER_ASC: int = 1
ORDER_DESC: int = -1

PAGE_LIMIT: int = 2
NO_LIMIT: int = 0
OUT_OF_RANGE_SKIP: int = 10_000


def _make_right(leaf_name: str) -> BaseRight:
    """Builds a BaseRight fixture; its public name becomes ``base.<leaf_name>``"""
    return BaseRight(Levels.PERMISSION, leaf_name)


@pytest.fixture(name="manager")
def fixture_manager() -> RightsManager:
    """A RightsManager whose rights are replaced with a deterministic, unsorted fixture list"""
    manager = RightsManager()
    # Deliberately out of order so the sorting in iterate_rights is actually observable
    manager.rights = [_make_right(name) for name in ['c', 'a', 'e', 'b', 'd']]

    return manager


# -------------------------------------------------------------- flat_tree ------------------------------------------- #

class TestFlatTree:
    """Tests for RightsManager.flat_tree"""

    def test_flattens_nested_tuples_and_lists(self) -> None:
        """A nested tree of tuples/lists collapses to a flat list of every leaf right"""
        leaf_a, leaf_b, leaf_c = _make_right('a'), _make_right('b'), _make_right('c')
        tree: tuple[Any, ...] = (leaf_a, (leaf_b, [leaf_c]))

        result: list[BaseRight] = RightsManager.flat_tree(tree)

        assert result == [leaf_a, leaf_b, leaf_c]

    def test_already_flat_input_is_returned_unchanged(self) -> None:
        """A flat tree of leaves is returned as-is"""
        leaves: list[BaseRight] = [_make_right('a'), _make_right('b')]

        assert RightsManager.flat_tree(tuple(leaves)) == leaves

    def test_empty_tree_yields_empty_list(self) -> None:
        """An empty tree flattens to an empty list"""
        assert RightsManager.flat_tree(()) == []


# ------------------------------------------------------------- tree_to_json ----------------------------------------- #

class TestTreeToJson:
    """Tests for RightsManager.tree_to_json"""

    def test_preserves_nesting_and_serializes_leaves(self) -> None:
        """Branches stay nested lists while leaves become their to_dict representation"""
        leaf_a, leaf_b = _make_right('a'), _make_right('b')
        tree: tuple[Any, ...] = (leaf_a, (leaf_b,))

        result: list[Any] = RightsManager.tree_to_json(tree)

        assert result == [BaseRight.to_dict(leaf_a), [BaseRight.to_dict(leaf_b)]]

    def test_leaves_are_dicts_not_objects(self) -> None:
        """Every serialized leaf is a plain dict carrying the right's name"""
        result: list[Any] = RightsManager.tree_to_json((_make_right('a'),))

        assert isinstance(result[0], dict)
        assert result[0]['name'] == f'{RIGHT_PREFIX}a'


# ---------------------------------------------------------------- __init__ ------------------------------------------ #

class TestInit:
    """Tests for RightsManager.__init__"""

    def test_builds_flat_rights_from_all_rights(self) -> None:
        """The real ALL_RIGHTS tree is flattened into a non-empty list of BaseRight"""
        manager = RightsManager()

        assert len(manager.rights) > 0
        assert all(isinstance(right, BaseRight) for right in manager.rights)

    def test_wraps_failure_in_init_error(self) -> None:
        """A failure while flattening the tree surfaces as RightsManagerInitError"""
        with patch.object(RightsManager, 'flat_tree', side_effect=RuntimeError("boom")):
            with pytest.raises(RightsManagerInitError):
                RightsManager()


# --------------------------------------------------------------- get_right ------------------------------------------ #

class TestGetRight:
    """Tests for RightsManager.get_right"""

    def test_returns_matching_right(self, manager: RightsManager) -> None:
        """A known name returns the matching right"""
        right: BaseRight | None = manager.get_right(f'{RIGHT_PREFIX}a')

        assert right is not None
        assert right.name == f'{RIGHT_PREFIX}a'

    def test_returns_none_when_not_found(self, manager: RightsManager) -> None:
        """A name that matches nothing returns None (so the route can map it to a 404)"""
        assert manager.get_right(MISSING_RIGHT_NAME) is None

    def test_wraps_unexpected_failure_in_get_error(self, manager: RightsManager) -> None:
        """An unexpected failure while scanning the rights surfaces as RightsManagerGetError"""
        manager.rights = None  # iterating None raises TypeError inside get_right

        with pytest.raises(RightsManagerGetError):
            manager.get_right(f'{RIGHT_PREFIX}a')


# ------------------------------------------------------------- iterate_rights --------------------------------------- #

class TestIterateRights:
    """Tests for RightsManager.iterate_rights"""

    def test_sorts_ascending_by_name(self, manager: RightsManager) -> None:
        """Ascending order returns the rights sorted by name"""
        result = manager.iterate_rights(limit=NO_LIMIT, skip=0, sort='name', order=ORDER_ASC)

        names: list[str] = [right.name for right in result.results]
        assert names == [f'{RIGHT_PREFIX}{name}' for name in SORTED_LEAF_NAMES]

    def test_sorts_descending_by_name(self, manager: RightsManager) -> None:
        """Descending order reverses the sort"""
        result = manager.iterate_rights(limit=NO_LIMIT, skip=0, sort='name', order=ORDER_DESC)

        names: list[str] = [right.name for right in result.results]
        assert names == [f'{RIGHT_PREFIX}{name}' for name in reversed(SORTED_LEAF_NAMES)]

    def test_applies_limit_and_skip_window(self, manager: RightsManager) -> None:
        """limit/skip slice out a single page of the sorted list"""
        result = manager.iterate_rights(limit=PAGE_LIMIT, skip=PAGE_LIMIT, sort='name', order=ORDER_ASC)

        names: list[str] = [right.name for right in result.results]
        assert names == [f'{RIGHT_PREFIX}c', f'{RIGHT_PREFIX}d']

    def test_non_positive_limit_returns_all(self, manager: RightsManager) -> None:
        """A limit <= 0 returns every right"""
        result = manager.iterate_rights(limit=NO_LIMIT, skip=0, sort='name', order=ORDER_ASC)

        assert len(result.results) == TOTAL_FIXTURE_RIGHTS

    def test_out_of_range_skip_returns_empty_page_without_error(self, manager: RightsManager) -> None:
        """A skip beyond the end yields an empty page (regression: used to raise IndexError -> 500)"""
        result = manager.iterate_rights(limit=PAGE_LIMIT, skip=OUT_OF_RANGE_SKIP, sort='name', order=ORDER_ASC)

        assert result.results == []
        assert result.total == TOTAL_FIXTURE_RIGHTS

    def test_total_is_always_the_full_count(self, manager: RightsManager) -> None:
        """The reported total reflects all rights, not just the returned page"""
        result = manager.iterate_rights(limit=PAGE_LIMIT, skip=0, sort='name', order=ORDER_ASC)

        assert len(result.results) == PAGE_LIMIT
        assert result.total == TOTAL_FIXTURE_RIGHTS

    def test_wraps_unknown_sort_key_in_iteration_error(self, manager: RightsManager) -> None:
        """Sorting by a non-existent attribute surfaces as RightsManagerIterationError"""
        with pytest.raises(RightsManagerIterationError):
            manager.iterate_rights(limit=NO_LIMIT, skip=0, sort=UNKNOWN_SORT_KEY, order=ORDER_ASC)
