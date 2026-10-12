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
Functional tests for what a reader of the location tree may see

The location editor holds every location right but may not READ the HIDDEN type (the shared ``location_acl_seed``).
A HIDDEN node sits under the root, a VISIBLE node below it, and a second VISIBLE node beside it. For that reader a
hidden node - and its whole branch - is absent from every level, the search and the flat list, a read naming it or a
node below it is 403, and a node whose only children are hidden shows no expand control. The admin sees everything
"""
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.interface.rest_api.routes.framework_routes.cmdb_locations.location_constants import (
    LOCATION_NOT_READABLE_MSG,
)
from cmdb.models.location_model.cmdb_location import CmdbLocation
from cmdb.models.location_model.location_constants import RootLocationDefault
from tests.utils import location_acl_seed as seed
# -------------------------------------------------------------------------------------------------------------------- #

URL: str = '/locations'
HIDDEN_NODE: int = 89601
BRANCH_NODE: int = 89602
BESIDE_NODE: int = 89603
HIDDEN_NAME: str = 'scope-hidden-node'
BRANCH_NAME: str = 'scope-visible-below-hidden'
BESIDE_NAME: str = 'scope-visible-beside'
NODE_IDS: list[int] = [HIDDEN_NODE, BRANCH_NODE, BESIDE_NODE]
ROOT: int = RootLocationDefault.PUBLIC_ID


def _node(public_id: int, name: str, parent: int, object_id: int, type_id: int) -> dict[str, Any]:
    """A stored location node."""
    return {'public_id': public_id, 'name': name, 'parent': parent, 'object_id': object_id, 'type_id': type_id,
            'type_label': seed.type_label(type_id), 'type_icon': 'fas fa-cube', 'type_selectable': True}


@pytest.fixture(autouse=True)
def _seeded(database_manager: MongoDatabaseManager, database_name: str):
    """The location seed, plus a hidden node with a readable node below it and one beside it"""
    seed.seed(database_manager, database_name, ROOT)
    nodes = database_manager.get_collection(CmdbLocation.COLLECTION, database_name)
    nodes.delete_many({'public_id': {'$in': NODE_IDS}})
    nodes.insert_many([
        _node(HIDDEN_NODE, HIDDEN_NAME, ROOT, seed.HIDDEN_ID, seed.HIDDEN_TYPE_ID),
        _node(BRANCH_NODE, BRANCH_NAME, HIDDEN_NODE, seed.VISIBLE_ID, seed.VISIBLE_TYPE_ID),
        _node(BESIDE_NODE, BESIDE_NAME, ROOT, seed.READ_ONLY_ID, seed.READ_ONLY_TYPE_ID),
    ])
    yield nodes
    nodes.delete_many({'public_id': {'$in': NODE_IDS}})
    seed.purge(database_manager, database_name)


def _get(rest_api, path: str, as_editor: bool = True):
    """GETs a location read, as the location editor or as the admin."""
    kwargs: dict[str, Any] = {'user': seed.location_editor()} if as_editor else {}

    return rest_api.get(f'{URL}{path}', **kwargs)


def _ids(nodes: Any) -> set[int]:
    """Every public_id in a level, a forest (nested children) or a flat list."""
    found: set[int] = set()

    for node in nodes or []:
        found.add(node['public_id'])
        found |= _ids(node.get('children'))

    return found


def _assert_refused(response, public_id: int) -> None:
    """The 403 naming the node."""
    assert response.status_code == HTTPStatus.FORBIDDEN
    assert response.get_json()['message'] == LOCATION_NOT_READABLE_MSG.format(public_id=public_id)


class TestLevelsAndSearch:
    """What the reader is shown"""

    def test_the_roots_leave_the_hidden_node_out(self, rest_api) -> None:
        """The node beside it stays"""
        found = _ids(_get(rest_api, '/tree/roots').get_json())

        assert HIDDEN_NODE not in found and BESIDE_NODE in found

    def test_the_search_finds_no_hidden_node(self, rest_api) -> None:
        """By its own name"""
        assert not _ids(_get(rest_api, f'/tree/search?query={HIDDEN_NAME}').get_json())

    def test_the_search_finds_no_node_below_a_hidden_one(self, rest_api) -> None:
        """The whole branch is hidden"""
        assert not _ids(_get(rest_api, f'/tree/search?query={BRANCH_NAME}').get_json())

    def test_the_search_still_finds_a_readable_node(self, rest_api) -> None:
        """The control"""
        assert _ids(_get(rest_api, f'/tree/search?query={BESIDE_NAME}').get_json()) == {BESIDE_NODE}

    def test_the_flat_list_leaves_the_hidden_node_out(self, rest_api) -> None:
        """Rows and total alike"""
        body = _get(rest_api, '/?limit=0').get_json()
        found = {row['public_id'] for row in body['results']}

        assert HIDDEN_NODE not in found and BESIDE_NODE in found
        assert body['total'] == len(body['results'])

    @pytest.mark.parametrize('as_editor, expected', [(True, False), (False, True)], ids=['editor', 'admin'])
    def test_a_node_whose_only_child_is_hidden_shows_no_expander(self, rest_api, _seeded, as_editor: bool,
                                                                 expected: bool) -> None:
        """has_children counts what the reader may see - the admin sees the hidden child"""
        _seeded.delete_one({'public_id': BRANCH_NODE})
        _seeded.update_one({'public_id': HIDDEN_NODE}, {'$set': {'parent': BESIDE_NODE}})

        level = _get(rest_api, '/tree/roots', as_editor=as_editor).get_json()

        assert next(node for node in level if node['public_id'] == BESIDE_NODE)['has_children'] is expected


class TestReadsNamingANode:
    """A read naming a hidden node, or one below it"""

    @pytest.mark.parametrize('path, refused', [
        (f'/tree/path/{HIDDEN_NODE}', HIDDEN_NODE), (f'/tree/path/{BRANCH_NODE}', BRANCH_NODE),
        (f'/tree/{HIDDEN_NODE}/children', HIDDEN_NODE), (f'/{HIDDEN_NODE}', HIDDEN_NODE),
        (f'/{BRANCH_NODE}', BRANCH_NODE),
    ], ids=['path-to-hidden', 'path-below-hidden', 'children-of-hidden', 'single-hidden', 'single-below-hidden'])
    def test_by_node_id_is_a_403(self, rest_api, path: str, refused: int) -> None:
        """The answer GET /objects/<id> gives"""
        _assert_refused(_get(rest_api, path), refused)

    @pytest.mark.parametrize('path, refused', [
        (f'/{seed.HIDDEN_ID}/object', HIDDEN_NODE), (f'/{seed.VISIBLE_ID}/object', BRANCH_NODE),
        (f'/{seed.VISIBLE_ID}/parent', BRANCH_NODE), (f'/{seed.HIDDEN_ID}/children', HIDDEN_NODE),
    ], ids=['object-hidden', 'object-below-hidden', 'parent-is-hidden', 'children-of-hidden'])
    def test_by_object_id_is_a_403(self, rest_api, path: str, refused: int) -> None:
        """Judged on the object's node"""
        _assert_refused(_get(rest_api, path), refused)

    def test_the_path_to_a_readable_node_leaves_hidden_siblings_out(self, rest_api) -> None:
        """The root level of the path omits the hidden node"""
        response = _get(rest_api, f'/tree/path/{BESIDE_NODE}')

        assert response.status_code == HTTPStatus.OK
        found = _ids(response.get_json())
        assert BESIDE_NODE in found and HIDDEN_NODE not in found


class TestTheAdminSeesEverything:
    """The control: nothing is denied to the admin group"""

    def test_the_roots_and_the_search(self, rest_api) -> None:
        """Every seeded node"""
        assert {HIDDEN_NODE, BESIDE_NODE} <= _ids(_get(rest_api, '/tree/roots', as_editor=False).get_json())
        assert _ids(_get(rest_api, f'/tree/search?query={BRANCH_NAME}', as_editor=False).get_json()) == {
            HIDDEN_NODE, BRANCH_NODE}

    @pytest.mark.parametrize('path', [f'/tree/path/{BRANCH_NODE}', f'/{HIDDEN_NODE}', f'/{seed.VISIBLE_ID}/parent'],
                             ids=['path', 'single', 'parent'])
    def test_the_reads_naming_a_node(self, rest_api, path: str) -> None:
        """No 403"""
        assert _get(rest_api, path, as_editor=False).status_code == HTTPStatus.OK
