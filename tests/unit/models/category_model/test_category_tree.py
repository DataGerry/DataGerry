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
Unit tests for cmdb.models.category_model.category_tree

Covers the CategoryTree composition (nesting, root collection) and - most importantly -
its cycle safety: the write path rejects self-parents and ancestor cycles, but legacy /
hand-edited documents may still carry them, and the tree build must never recurse
infinitely on such data (it used to RecursionError and 500 the tree view)
"""
from types import SimpleNamespace
from typing import Any

from cmdb.models.category_model import CategoryTree, CmdbCategory
from cmdb.models.category_model.category_tree import index_types_by_id, group_categories_by_parent
# -------------------------------------------------------------------------------------------------------------------- #


ROOT_ID: int = 1
CHILD_ID: int = 2
GRANDCHILD_ID: int = 3
CYCLE_A_ID: int = 10
CYCLE_B_ID: int = 11

TYPE_A_ID: int = 100
TYPE_B_ID: int = 200
TYPE_C_ID: int = 300
UNLOADED_TYPE_ID: int = 999


def _category(public_id: int, parent: int | None = None, types: list[int] | None = None) -> CmdbCategory:
    """Builds a minimal CmdbCategory instance with the given identity, parent and type ids."""
    category = CmdbCategory(public_id=public_id, name=f'cat-{public_id}', parent=parent)
    category.types = types or []

    return category


def _type(public_id: int) -> Any:
    """Builds a lightweight CmdbType stand-in; the tree build only reads its public_id."""
    return SimpleNamespace(public_id=public_id)


def _self_parent_category(public_id: int) -> CmdbCategory:
    """Builds a CmdbCategory whose stored parent is its own id, bypassing the model guard.

    The constructor rejects self-parents, so the corrupted state is forced onto the
    attribute afterwards - exactly the shape a legacy / hand-edited document would load as
    """
    category = _category(public_id)
    category.parent = public_id

    return category


def _tree_ids(tree: CategoryTree) -> list[int]:
    """Returns the public_ids of the tree's root nodes."""
    return [node.category.get_public_id() for node in tree.tree]


def test_builds_nested_tree_from_parent_links() -> None:
    """Root / child / grandchild parent links produce the matching nesting."""
    tree = CategoryTree([
        _category(ROOT_ID),
        _category(CHILD_ID, parent=ROOT_ID),
        _category(GRANDCHILD_ID, parent=CHILD_ID),
    ])

    assert _tree_ids(tree) == [ROOT_ID]
    root_node = tree.tree[0]
    assert [c.category.get_public_id() for c in root_node.children] == [CHILD_ID]
    assert [c.category.get_public_id() for c in root_node.children[0].children] == [GRANDCHILD_ID]


def test_len_counts_root_nodes_only() -> None:
    """len() reports the number of top-level nodes, not the total category count."""
    tree = CategoryTree([
        _category(ROOT_ID),
        _category(CHILD_ID, parent=ROOT_ID),
    ])

    assert len(tree) == 1


def test_self_parent_category_does_not_recurse_infinitely() -> None:
    """A stored self-parent must not RecursionError the build; the node is simply not re-entered.

    This was the pre-guard failure mode: one corrupted document made every tree view 500
    """
    tree = CategoryTree([
        _category(ROOT_ID),
        _self_parent_category(CYCLE_A_ID),
    ])

    assert _tree_ids(tree) == [ROOT_ID]


def test_two_node_cycle_does_not_break_the_build() -> None:
    """A stored A -> B -> A cycle builds without error; healthy roots are unaffected."""
    cycle_a = _category(CYCLE_A_ID, parent=CYCLE_B_ID)
    cycle_b = _category(CYCLE_B_ID, parent=CYCLE_A_ID)

    tree = CategoryTree([
        _category(ROOT_ID),
        cycle_a,
        cycle_b,
    ])

    assert _tree_ids(tree) == [ROOT_ID]


def test_each_category_is_placed_at_most_once() -> None:
    """The shared visited set guarantees no category appears twice in the built tree."""
    tree = CategoryTree([
        _category(ROOT_ID),
        _category(CHILD_ID, parent=ROOT_ID),
        _category(GRANDCHILD_ID, parent=CHILD_ID),
    ])

    seen: list[int] = []

    def _collect(nodes) -> None:
        for node in nodes:
            seen.append(node.category.get_public_id())
            _collect(node.children)

    _collect(tree.tree)

    assert sorted(seen) == [ROOT_ID, CHILD_ID, GRANDCHILD_ID]
    assert len(seen) == len(set(seen))


# -------------------------------------------------------------------------------------------------------------------- #
#                                              group_categories_by_parent                                              #
# -------------------------------------------------------------------------------------------------------------------- #
def test_group_categories_by_parent_buckets_roots_under_none_and_children_under_parent() -> None:
    """Roots land in the None bucket; children land under their parent's public_id."""
    root = _category(ROOT_ID)
    child = _category(CHILD_ID, parent=ROOT_ID)
    grandchild = _category(GRANDCHILD_ID, parent=CHILD_ID)

    grouped = group_categories_by_parent([root, child, grandchild])

    assert grouped == {None: [root], ROOT_ID: [child], CHILD_ID: [grandchild]}


def test_group_categories_by_parent_preserves_input_order_within_a_bucket() -> None:
    """Siblings keep their input order so the built tree's ordering stays deterministic."""
    first = _category(CHILD_ID, parent=ROOT_ID)
    second = _category(GRANDCHILD_ID, parent=ROOT_ID)

    grouped = group_categories_by_parent([_category(ROOT_ID), first, second])

    assert grouped[ROOT_ID] == [first, second]


def test_group_categories_by_parent_returns_empty_dict_for_no_categories() -> None:
    """An empty category list groups to an empty dict (no root bucket)."""
    assert group_categories_by_parent([]) == {}


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  index_types_by_id                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
def test_index_types_by_id_keys_each_type_by_its_public_id() -> None:
    """Every CmdbType is reachable under its own public_id."""
    type_a = _type(TYPE_A_ID)
    type_b = _type(TYPE_B_ID)

    assert index_types_by_id([type_a, type_b]) == {TYPE_A_ID: type_a, TYPE_B_ID: type_b}


def test_index_types_by_id_returns_empty_dict_for_none() -> None:
    """A None type list (the unset default) maps to an empty lookup."""
    assert index_types_by_id(None) == {}


# -------------------------------------------------------------------------------------------------------------------- #
#                                            CategoryNode type resolution                                              #
# -------------------------------------------------------------------------------------------------------------------- #
def test_node_types_follow_the_categorys_declared_order() -> None:
    """node.types is ordered by the category's 'types' list, not by the input type list."""
    category = _category(ROOT_ID, types=[TYPE_C_ID, TYPE_A_ID, TYPE_B_ID])
    types = [_type(TYPE_A_ID), _type(TYPE_B_ID), _type(TYPE_C_ID)]

    tree = CategoryTree([category], types)

    assert [a_type.public_id for a_type in tree.tree[0].types] == [TYPE_C_ID, TYPE_A_ID, TYPE_B_ID]


def test_node_types_skip_referenced_ids_without_a_loaded_type() -> None:
    """A type id referenced by the category but absent from the loaded types is dropped."""
    category = _category(ROOT_ID, types=[TYPE_A_ID, UNLOADED_TYPE_ID, TYPE_B_ID])
    types = [_type(TYPE_A_ID), _type(TYPE_B_ID)]

    tree = CategoryTree([category], types)

    assert [a_type.public_id for a_type in tree.tree[0].types] == [TYPE_A_ID, TYPE_B_ID]


def test_node_types_is_empty_when_no_types_are_provided() -> None:
    """With no loaded types, a category that references some resolves to an empty type list."""
    category = _category(ROOT_ID, types=[TYPE_A_ID])

    tree = CategoryTree([category])

    assert tree.tree[0].types == []


def test_nested_nodes_resolve_their_own_types() -> None:
    """Type resolution reaches child nodes, not just the roots."""
    root = _category(ROOT_ID, types=[TYPE_A_ID])
    child = _category(CHILD_ID, parent=ROOT_ID, types=[TYPE_B_ID])
    types = [_type(TYPE_A_ID), _type(TYPE_B_ID)]

    tree = CategoryTree([root, child], types)
    root_node = tree.tree[0]

    assert [a_type.public_id for a_type in root_node.types] == [TYPE_A_ID]
    assert [a_type.public_id for a_type in root_node.children[0].types] == [TYPE_B_ID]
