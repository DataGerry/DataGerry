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
Integration tests for the reader-scoped location reads against a real MongoDB

Seeds root -> HIDDEN (denied type) -> BRANCH (readable type) and root -> BESIDE (readable type) and asserts what the
manager's reads answer for a reader denied the HIDDEN type: the chain read, the children and has-children grouping,
the search (a match below a hidden node is dropped with its chain) and the path's sibling levels
"""
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import LocationsManager
from cmdb.models.location_model.cmdb_location import CmdbLocation
from cmdb.models.location_model.location_constants import RootLocationDefault
# -------------------------------------------------------------------------------------------------------------------- #

ROOT: int = RootLocationDefault.PUBLIC_ID
DENIED_TYPE: int = 89701
READABLE_TYPE: int = 89702
HIDDEN_NODE: int = 89711
BRANCH_NODE: int = 89712
BESIDE_NODE: int = 89713
NODE_IDS: list[int] = [HIDDEN_NODE, BRANCH_NODE, BESIDE_NODE]
DENIED: list[int] = [DENIED_TYPE]
SEARCH_TERM: str = 'scope-int'


def _node(public_id: int, parent: int, type_id: int) -> dict[str, Any]:
    """A stored location node named after the search term."""
    return {'public_id': public_id, 'name': f'{SEARCH_TERM}-{public_id}', 'parent': parent, 'object_id': public_id,
            'type_id': type_id, 'type_label': 'T', 'type_icon': 'fas fa-cube', 'type_selectable': True}


@pytest.fixture(name='manager')
def fixture_manager(database_manager: MongoDatabaseManager, database_name: str):
    """The three nodes - removed after"""
    nodes = database_manager.get_collection(CmdbLocation.COLLECTION, database_name)
    nodes.delete_many({'public_id': {'$in': NODE_IDS}})
    nodes.insert_many([_node(HIDDEN_NODE, ROOT, DENIED_TYPE), _node(BRANCH_NODE, HIDDEN_NODE, READABLE_TYPE),
                       _node(BESIDE_NODE, ROOT, READABLE_TYPE)])
    yield LocationsManager(database_manager)
    nodes.delete_many({'public_id': {'$in': NODE_IDS}})


def _ids(documents: list[dict[str, Any]]) -> set[int]:
    """The public_ids of the seeded nodes among the documents"""
    return {document['public_id'] for document in documents} & set(NODE_IDS)


def test_the_chain_is_the_node_then_its_ancestors(manager) -> None:
    """Root included, two keys each"""
    chain = manager.get_location_chain(BRANCH_NODE)

    assert chain[0] == {'public_id': BRANCH_NODE, 'type_id': READABLE_TYPE}
    assert {node['public_id'] for node in chain[1:]} == {HIDDEN_NODE, ROOT}
    assert all(set(node) <= {'public_id', 'type_id'} for node in chain)


def test_a_missing_node_has_no_chain(manager) -> None:
    """Nothing to judge"""
    assert not manager.get_location_chain(max(NODE_IDS) + 1)


def test_the_root_level_leaves_the_hidden_node_out(manager) -> None:
    """Only for the reader it is denied to"""
    assert _ids(manager.get_child_location_documents(ROOT, DENIED)) == {BESIDE_NODE}
    assert _ids(manager.get_child_location_documents(ROOT)) == {HIDDEN_NODE, BESIDE_NODE}


def test_a_hidden_child_does_not_count(manager) -> None:
    """HIDDEN's only child is readable; ROOT's hidden child does not make it expandable on its own"""
    assert manager.get_parents_with_children([HIDDEN_NODE], DENIED) == {HIDDEN_NODE}
    assert manager.get_parents_with_children([BESIDE_NODE, HIDDEN_NODE], [READABLE_TYPE]) == set()


def test_the_search_drops_a_hidden_branch(manager) -> None:
    """Neither the hidden node nor the readable node below it; the readable node beside it stays"""
    assert _ids(manager.search_locations_with_ancestors(SEARCH_TERM, DENIED)) == {BESIDE_NODE}
    assert _ids(manager.search_locations_with_ancestors(SEARCH_TERM)) == set(NODE_IDS)


def test_the_path_levels_leave_hidden_siblings_out(manager) -> None:
    """The root level of the path to BESIDE omits HIDDEN"""
    assert _ids(manager.get_locations_on_path_to(BESIDE_NODE, DENIED)) == {BESIDE_NODE}
    assert _ids(manager.get_locations_on_path_to(BESIDE_NODE)) == {HIDDEN_NODE, BESIDE_NODE}
