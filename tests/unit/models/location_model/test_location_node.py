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
Unit tests for cmdb.models.location_model.location_node.LocationNode

Pure tests: no Mongo, no Flask. Exercise ``__init__`` (field population + the
``LocationNodeInitError`` raised on a malformed dict) and the tree-assembly logic that the
``/locations/tree`` route delegates to - ``get_children`` (parent-index build + recursion),
the cycle guard that protects against malformed parent chains, and ``to_json`` (nested
serialization, children key only emitted when present). The one-line accessors
(``get_public_id``, ``__repr__``) are out of scope as trivial.
"""
from typing import Any

import pytest

from cmdb.models.location_model.location_node import LocationNode
from cmdb.errors.models.cmdb_location import LocationNodeInitError
# -------------------------------------------------------------------------------------------------------------------- #

ROOT_PUBLIC_ID: int = 1

PARENT_ID: int = 10
CHILD_A_ID: int = 11
CHILD_B_ID: int = 12
GRANDCHILD_ID: int = 13
SECOND_ROOT_ID: int = 20

TYPE_ICON: str = 'fas fa-cube'


def _location(public_id: int, parent: int, name: str | None = None) -> dict[str, Any]:
    """Builds a minimal CmdbLocation dict accepted by ``LocationNode``."""
    return {
        'public_id': public_id,
        'name': name if name is not None else f'loc-{public_id}',
        'parent': parent,
        'type_icon': TYPE_ICON,
        'object_id': public_id + 100,
    }


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       __init__                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
class TestInit:
    """``__init__`` copies the location fields and raises a specific error on a malformed dict."""

    def test_populates_fields_from_params(self) -> None:
        """A complete location dict populates every node attribute and starts with no children."""
        node = LocationNode(_location(PARENT_ID, ROOT_PUBLIC_ID))

        assert node.public_id == PARENT_ID
        assert node.parent == ROOT_PUBLIC_ID
        assert node.object_id == PARENT_ID + 100
        assert node.children == []

    def test_missing_key_raises_location_node_init_error(self) -> None:
        """A location dict missing a required key is rejected with ``LocationNodeInitError``."""
        incomplete = _location(PARENT_ID, ROOT_PUBLIC_ID)
        del incomplete['object_id']

        with pytest.raises(LocationNodeInitError):
            LocationNode(incomplete)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                     get_children                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
class TestGetChildren:
    """``get_children`` attaches descendants to a parent using a parent->children index."""

    def test_empty_locations_yields_no_children(self) -> None:
        """A parent with an empty candidate list has no children."""
        parent = LocationNode(_location(PARENT_ID, ROOT_PUBLIC_ID))

        assert parent.get_children(PARENT_ID, []) == []

    def test_only_direct_children_are_returned_at_top_level(self) -> None:
        """The returned list holds exactly the direct children of the requested public_id."""
        parent = LocationNode(_location(PARENT_ID, ROOT_PUBLIC_ID))
        candidates = [
            _location(CHILD_A_ID, PARENT_ID),
            _location(CHILD_B_ID, PARENT_ID),
            _location(SECOND_ROOT_ID, ROOT_PUBLIC_ID),  # not a child of PARENT_ID
        ]

        children = parent.get_children(PARENT_ID, candidates)

        assert sorted(child.public_id for child in children) == [CHILD_A_ID, CHILD_B_ID]

    def test_nested_children_are_attached_recursively(self) -> None:
        """A grandchild is attached beneath its parent child, not at the top level."""
        parent = LocationNode(_location(PARENT_ID, ROOT_PUBLIC_ID))
        candidates = [
            _location(CHILD_A_ID, PARENT_ID),
            _location(GRANDCHILD_ID, CHILD_A_ID),
        ]

        children = parent.get_children(PARENT_ID, candidates)

        assert [child.public_id for child in children] == [CHILD_A_ID]
        assert [grandchild.public_id for grandchild in children[0].children] == [GRANDCHILD_ID]

    def test_unrelated_branches_are_not_attached(self) -> None:
        """Locations under a different parent never leak into the requested subtree."""
        parent = LocationNode(_location(PARENT_ID, ROOT_PUBLIC_ID))
        candidates = [
            _location(CHILD_A_ID, PARENT_ID),
            _location(GRANDCHILD_ID, SECOND_ROOT_ID),  # belongs to a different parent
        ]

        children = parent.get_children(PARENT_ID, candidates)

        assert [child.public_id for child in children] == [CHILD_A_ID]
        assert children[0].children == []

    def test_parent_cycle_does_not_recurse_infinitely(self) -> None:
        """A duplicated id that points back up the chain is dropped by the visited guard."""
        parent = LocationNode(_location(PARENT_ID, ROOT_PUBLIC_ID))
        # PARENT -> CHILD_A -> (node re-using PARENT_ID) would close a cycle; the guard cuts it.
        candidates = [
            _location(CHILD_A_ID, PARENT_ID),
            _location(PARENT_ID, CHILD_A_ID),  # cycle: PARENT_ID reachable again under CHILD_A
        ]

        children = parent.get_children(PARENT_ID, candidates)

        assert [child.public_id for child in children] == [CHILD_A_ID]
        # The cycle-closing node is filtered out, so CHILD_A has no children
        assert children[0].children == []


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       to_json                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
class TestToJson:
    """``to_json`` serializes a node and only emits a ``children`` key when children exist."""

    def test_leaf_node_has_no_children_key(self) -> None:
        """A node without children serializes without the optional ``children`` key."""
        node = LocationNode(_location(PARENT_ID, ROOT_PUBLIC_ID))

        result = LocationNode.to_json(node)

        assert 'children' not in result
        assert result['public_id'] == PARENT_ID
        assert result['object_id'] == PARENT_ID + 100

    def test_nested_children_are_serialized_recursively(self) -> None:
        """A populated subtree is serialized with nested ``children`` arrays."""
        parent = LocationNode(_location(PARENT_ID, ROOT_PUBLIC_ID))
        candidates = [
            _location(CHILD_A_ID, PARENT_ID),
            _location(GRANDCHILD_ID, CHILD_A_ID),
        ]
        parent.children = parent.get_children(PARENT_ID, candidates)

        result = LocationNode.to_json(parent)

        assert [child['public_id'] for child in result['children']] == [CHILD_A_ID]
        assert [gc['public_id'] for gc in result['children'][0]['children']] == [GRANDCHILD_ID]
