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

Pure tests: no Mongo. RightsManager is not database-backed - it serves the static ``ALL_RIGHTS`` tree,
flattened once at import (``ALL_RIGHTS_FLAT``), from memory - so every method is exercised directly against
hand-built ``BaseRight`` fixtures (or a manager whose ``rights`` are replaced with a
deterministic list) to keep ordering independent of the real rights tree.
"""
from typing import Any

import pytest

from cmdb.manager.rights_manager import RIGHT_SORTABLE_FIELDS, RightsManager
from cmdb.models.right_model.all_rights import ALL_RIGHTS, ALL_RIGHT_NAMES, ALL_RIGHTS_FLAT, flat_rights_tree
from cmdb.models.right_model.base_right import BaseRight
from cmdb.models.right_model.levels_enum import Levels
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

    def test_deep_nesting_keeps_the_tree_order(self) -> None:
        """Every leaf once, in the order a depth-first walk meets it"""
        leaves: list[BaseRight] = [_make_right(name) for name in SORTED_LEAF_NAMES]
        tree: tuple[Any, ...] = (leaves[0], (leaves[1], (leaves[2], [leaves[3]])), leaves[4])

        assert flat_rights_tree(tree) == leaves


class TestFlattenedCatalogue:
    """The catalogue is flattened once, at import, and shared"""

    def test_the_cache_is_the_flattened_tree(self) -> None:
        """Same rights, same order as a fresh flattening"""
        assert ALL_RIGHTS_FLAT == flat_rights_tree(ALL_RIGHTS)

    def test_the_name_set_holds_every_right_name(self) -> None:
        """What a group's rights may carry"""
        assert ALL_RIGHT_NAMES == frozenset(right.name for right in ALL_RIGHTS_FLAT)

    def test_every_manager_shares_the_one_list(self) -> None:
        """Building a manager flattens nothing"""
        assert RightsManager().rights is ALL_RIGHTS_FLAT


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

    def test_building_one_does_not_flatten_the_tree(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The shared list is taken as it is - no flattening runs, so nothing can fail here"""
        def _fail(*_args: Any) -> None:
            raise AssertionError('flattened again')

        monkeypatch.setattr(RightsManager, 'flat_tree', _fail)

        assert RightsManager().rights is ALL_RIGHTS_FLAT

    @pytest.mark.parametrize('right_name', [
        'base.framework.report.view',
        'base.framework.report.add',
        'base.framework.report.edit',
        'base.framework.report.delete',
        'base.framework.ipam.view',
        'base.framework.ipam.add',
        'base.framework.ipam.edit',
        'base.framework.ipam.delete',
        'base.framework.location.view',
        'base.framework.location.add',
        'base.framework.location.edit',
        'base.framework.location.delete',
        'base.isms.import.add',
    ])
    def test_new_rights_are_registered(self, right_name: str) -> None:
        """The Report / IPAM / Location / ISMS-import rights resolve."""
        manager = RightsManager()

        assert manager.get_right(right_name) is not None


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

    def test_a_programming_error_propagates_as_itself(self, manager: RightsManager) -> None:
        """Nothing is wrapped: an in-memory scan has no failure of its own"""
        manager.rights = None  # iterating None raises TypeError inside get_right

        with pytest.raises(TypeError):
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
        """A skip beyond the end yields an empty page, not an IndexError surfacing as a 500"""
        result = manager.iterate_rights(limit=PAGE_LIMIT, skip=OUT_OF_RANGE_SKIP, sort='name', order=ORDER_ASC)

        assert result.results == []
        assert result.total == TOTAL_FIXTURE_RIGHTS

    def test_a_search_narrows_the_results(self, manager: RightsManager) -> None:
        """The term is matched against name, label and description"""
        result = manager.iterate_rights(limit=NO_LIMIT, skip=0, sort='name', order=ORDER_ASC, search='.a')

        assert [right.name for right in result.results] == [f'{RIGHT_PREFIX}a']

    def test_a_searched_total_counts_matches_not_the_catalogue(self, manager: RightsManager) -> None:
        """A pager built on the total has to offer the pages that exist"""
        result = manager.iterate_rights(limit=NO_LIMIT, skip=0, sort='name', order=ORDER_ASC, search='.a')

        assert result.total == 1

    def test_a_search_is_applied_before_the_page_is_cut(self, manager: RightsManager) -> None:
        """Narrow first, then sort, then slice - otherwise a page could come back empty by accident"""
        result = manager.iterate_rights(limit=1, skip=0, sort='name', order=ORDER_ASC, search=RIGHT_PREFIX)

        assert len(result.results) == 1
        assert result.total == TOTAL_FIXTURE_RIGHTS

    @pytest.mark.parametrize('search', [None, '', '   '])
    def test_a_blank_search_returns_every_right(self, manager: RightsManager, search) -> None:
        """An unsearched listing is the full, unfiltered list"""
        result = manager.iterate_rights(limit=NO_LIMIT, skip=0, sort='name', order=ORDER_ASC, search=search)

        assert result.total == TOTAL_FIXTURE_RIGHTS

    def test_a_search_matching_nothing_is_an_empty_page(self, manager: RightsManager) -> None:
        """Not an error, and the total says so too"""
        result = manager.iterate_rights(limit=NO_LIMIT, skip=0, sort='name', order=ORDER_ASC, search='zzz')

        assert result.results == []
        assert result.total == 0

    def test_total_is_always_the_full_count(self, manager: RightsManager) -> None:
        """The reported total reflects all rights, not just the returned page"""
        result = manager.iterate_rights(limit=PAGE_LIMIT, skip=0, sort='name', order=ORDER_ASC)

        assert len(result.results) == PAGE_LIMIT
        assert result.total == TOTAL_FIXTURE_RIGHTS

    def test_an_unchecked_unknown_sort_key_raises_as_itself(self, manager: RightsManager) -> None:
        """The routes check the key first; a caller that skips the check gets the AttributeError, unwrapped"""
        with pytest.raises(AttributeError):
            manager.iterate_rights(limit=NO_LIMIT, skip=0, sort=UNKNOWN_SORT_KEY, order=ORDER_ASC)

    @pytest.mark.parametrize('sort', RIGHT_SORTABLE_FIELDS)
    @pytest.mark.parametrize('order', [ORDER_ASC, ORDER_DESC])
    def test_every_sortable_field_sorts_the_real_catalogue(self, sort: str, order: int) -> None:
        """Each field every right sets to one comparable type - a sort over the catalogue cannot fail"""
        result = RightsManager().iterate_rights(limit=NO_LIMIT, skip=0, sort=sort, order=order)

        assert result.total == len(ALL_RIGHTS_FLAT)


class TestIsSortableRightField:
    """Which ?sort= values the routes accept"""

    @pytest.mark.parametrize('sort', RIGHT_SORTABLE_FIELDS)
    def test_the_serialised_keys_are_sortable(self, sort: str) -> None:
        """The keys a serialised right carries"""
        assert RightsManager.is_sortable_right_field(sort)

    @pytest.mark.parametrize('sort', [UNKNOWN_SORT_KEY, '_level', '__class__', ''])
    def test_anything_else_is_not(self, sort: str) -> None:
        """An unknown, private or dunder attribute is refused"""
        assert not RightsManager.is_sortable_right_field(sort)

    def test_the_sortable_fields_are_the_serialised_keys(self) -> None:
        """A client sorts by the columns it is shown"""
        assert set(RIGHT_SORTABLE_FIELDS) == set(BaseRight.to_dict(_make_right('a')))
