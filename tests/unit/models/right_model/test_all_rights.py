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
Unit tests for cmdb.models.right_model.all_rights

Pure: no Mongo, no Flask. Two things are pinned here.

`flat_rights_tree` is now the single implementation of the flattening - `RightsManager.flat_tree`
delegates to it and `GroupsManager` calls it directly - so its recursion is tested on its own.

The rest are **invariants of the declared tree itself**, which no other test covers: the tree is
authorisation configuration, and a duplicate name, an unqualified name or a missing description are
the kind of copy-paste slip a 200-line declaration invites. They fail loudly here rather than turning
into a route that can never be granted.
"""
from typing import Any

from cmdb.models.right_model.all_rights import ALL_RIGHTS, flat_rights_tree
from cmdb.models.right_model.base_right import BaseRight
from cmdb.models.right_model.levels_enum import Levels
from cmdb.models.right_model.constants import GLOBAL_RIGHT_IDENTIFIER
# -------------------------------------------------------------------------------------------------------------------- #

# The root PREFIX every qualified right name has to start with
ROOT_PREFIX: str = 'base'

# The master right, which grants every other right through CmdbUserGroup.has_extended_right
MASTER_NAME: str = f'{ROOT_PREFIX}.{GLOBAL_RIGHT_IDENTIFIER}'

# A right guaranteed to exist, used to pin that the flattening really reaches the leaves
KNOWN_LEAF_NAME: str = 'base.framework.type.view'


def _make_right(name: str) -> BaseRight:
    """Builds a plain BaseRight leaf for the flattening tests."""
    return BaseRight(Levels.PERMISSION, name)


class TestFlatRightsTree:
    """Tests for flat_rights_tree"""

    def test_flattens_nested_levels(self) -> None:
        """Rights at any nesting depth end up in one flat list, in tree order."""
        deep = _make_right('deep')
        shallow = _make_right('shallow')
        tree: tuple = (shallow, ((deep,),))

        assert flat_rights_tree(tree) == [shallow, deep]

    def test_keeps_an_already_flat_tuple(self) -> None:
        """A flat tuple of rights comes back as the equivalent list."""
        leaves: list[BaseRight] = [_make_right('a'), _make_right('b')]

        assert flat_rights_tree(tuple(leaves)) == leaves

    def test_empty_tree_yields_empty_list(self) -> None:
        """An empty tree flattens to an empty list rather than raising."""
        assert flat_rights_tree(()) == []

    def test_accepts_lists_as_branches(self) -> None:
        """Branches may be lists as well as tuples, which the annotation allows."""
        leaf = _make_right('in_a_list')

        assert flat_rights_tree([[leaf]]) == [leaf]


class TestDeclaredTreeInvariants:
    """Invariants of the ALL_RIGHTS declaration itself"""

    def test_every_leaf_is_a_base_right(self) -> None:
        """Nothing but rights survives the flattening."""
        assert all(isinstance(right, BaseRight) for right in flat_rights_tree(ALL_RIGHTS))

    def test_right_names_are_unique(self) -> None:
        """A duplicate name would make one of the two rights ungrantable."""
        names: list[str] = [right.name for right in flat_rights_tree(ALL_RIGHTS)]

        assert len(names) == len(set(names))

    def test_every_name_is_qualified_from_the_root(self) -> None:
        """has_extended_right walks up to 'base', so every name must be rooted there."""
        for right in flat_rights_tree(ALL_RIGHTS):
            assert right.name == ROOT_PREFIX or right.name.startswith(f'{ROOT_PREFIX}.')

    def test_every_right_has_a_description(self) -> None:
        """Descriptions reach the UI, and a None would also break ?sort=description."""
        assert [right.name for right in flat_rights_tree(ALL_RIGHTS) if not right.description] == []

    def test_every_right_has_a_label(self) -> None:
        """Either an explicit or a generated label, never an empty one."""
        assert [right.name for right in flat_rights_tree(ALL_RIGHTS) if not right.label] == []

    def test_master_right_is_present_and_flagged(self) -> None:
        """The master right exists exactly once and is the only right named 'base.*'."""
        masters: list[BaseRight] = [
            right for right in flat_rights_tree(ALL_RIGHTS) if right.name == MASTER_NAME
        ]

        assert len(masters) == 1
        assert masters[0].is_master is True

    def test_flattening_reaches_the_leaves(self) -> None:
        """A known leaf is found, so the tree is not merely returning its top-level groups."""
        names: list[str] = [right.name for right in flat_rights_tree(ALL_RIGHTS)]

        assert KNOWN_LEAF_NAME in names
        assert len(names) > len(ALL_RIGHTS)

    def test_wildcard_rights_are_the_only_masters(self) -> None:
        """is_master is derived from the name, so the two must agree for every right."""
        for right in flat_rights_tree(ALL_RIGHTS):
            expected: bool = right.name.rsplit('.', maxsplit=1)[-1] == GLOBAL_RIGHT_IDENTIFIER
            assert right.is_master is expected, right.name
