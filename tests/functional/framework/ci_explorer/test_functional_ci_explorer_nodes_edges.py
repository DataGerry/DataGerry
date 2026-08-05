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
Golden-master functional tests for GET /ci_explorer/items

These tests pin the observable contract of the current route before the refactor:
top-level response keys per target_type, node/edge counts, edge directions, titles,
location-flip semantics, item_limit clipping and types_filter behaviour. They are
intentionally shape-focused (not byte-identical) so the refactor can normalise
internal inconsistencies without false-positive failures
"""
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any

import pytest
from pymongo.mongo_client import MongoClient

from cmdb.database.mongo_connector import MongoConnector
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType
from cmdb.models.relation_model import CmdbRelation
from cmdb.models.object_relation_model import CmdbObjectRelation
from cmdb.models.location_model.cmdb_location import CmdbLocation
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_URL: str = '/ci_explorer/items'

# Type ids
TYPE_SERVER: int = 10
TYPE_PRINTER: int = 11
TYPE_NETWORK: int = 12
TYPE_LOCATION: int = 13

# Object ids
OBJ_TARGET: int = 100              # Server, the focal object for non-location tests
OBJ_PARENT_SERVER: int = 101       # Server, parent of OBJ_TARGET in the relation graph
OBJ_CHILD_PRINTER: int = 102       # Printer, child of OBJ_TARGET
OBJ_CHILD_NETWORK: int = 103       # Network, child of OBJ_TARGET (used for types_filter test)
OBJ_EXTRA_1: int = 104             # Printer, extra child for the item_limit test
OBJ_EXTRA_2: int = 105
OBJ_EXTRA_3: int = 106

OBJ_LOC_PARENT: int = 200          # object that owns the parent location node in the location tree
OBJ_LOC_CHILD: int = 201           # object that owns the child location node in the location tree

# Relation + objectRelation ids
RELATION_CONNECTED: int = 500
OBJ_REL_PARENT_TO_TARGET: int = 600
OBJ_REL_TARGET_TO_PRINTER: int = 601
OBJ_REL_TARGET_TO_NETWORK: int = 602
OBJ_REL_TARGET_TO_EXTRA_1: int = 603
OBJ_REL_TARGET_TO_EXTRA_2: int = 604
OBJ_REL_TARGET_TO_EXTRA_3: int = 605

# Location ids (sentinel root = 1 per the route's special-case at line 416)
LOC_ROOT: int = 1
LOC_FOR_LOC_PARENT_OBJECT: int = 1000
LOC_FOR_TARGET_OBJECT: int = 1001
LOC_FOR_LOC_CHILD_OBJECT: int = 1002


def _make_type(public_id: int, name: str, label: str, color: str, icon: str) -> dict[str, Any]:
    """Builds a minimal CmdbType doc the CI-Explorer route reads from."""
    return {
        'public_id': public_id,
        'name': name,
        'label': label,
        'author_id': 1,
        'creation_time': datetime.now(timezone.utc),
        'active': True,
        'fields': [
            {'type': 'text', 'name': 'name', 'label': 'Name'},
        ],
        'render_meta': {
            'icon': icon,
            'sections': [],
            'summary': {'fields': ['name']},
        },
        'ci_explorer_label': 'name',
        'ci_explorer_color': color,
        'acl': {'activated': False, 'groups': {'includes': None}},
        'version': '1.0.0',
    }


def _make_object(public_id: int, type_id: int, display_name: str) -> dict[str, Any]:
    """Builds a minimal CmdbObject doc with one 'name' field used as the CI-Explorer title."""
    return {
        'public_id': public_id,
        'type_id': type_id,
        'status': True,
        'active': True,
        'author_id': 1,
        'creation_time': datetime.now(timezone.utc),
        'version': '1.0.0',
        'fields': [
            {'name': 'name', 'value': display_name},
        ],
    }


def _make_relation() -> dict[str, Any]:
    """Builds the single CmdbRelation used by every object-relation in the fixture."""
    return {
        'public_id': RELATION_CONNECTED,
        'relation_name': 'connected',
        'parent_type_ids': [TYPE_SERVER],
        'child_type_ids': [TYPE_SERVER, TYPE_PRINTER, TYPE_NETWORK],
        'relation_name_parent': 'hosts',
        'relation_name_child': 'hosted_by',
        'relation_icon_parent': 'fa-arrow-right',
        'relation_icon_child': 'fa-arrow-left',
        'relation_color_parent': '#33aa33',
        'relation_color_child': '#aa3333',
        'description': 'fixture relation',
        'sections': [],
        'fields': [],
    }


def _make_object_relation(
    public_id: int,
    parent_id: int,
    parent_type_id: int,
    child_id: int,
    child_type_id: int,
) -> dict[str, Any]:
    """Builds one objectRelation document linking parent_id → child_id via RELATION_CONNECTED."""
    return {
        'public_id': public_id,
        'relation_id': RELATION_CONNECTED,
        'relation_parent_id': parent_id,
        'relation_parent_type_id': parent_type_id,
        'relation_child_id': child_id,
        'relation_child_type_id': child_type_id,
        'author_id': 1,
        'creation_time': datetime.now(timezone.utc),
        'last_edit_time': None,
        'field_values': [],
    }


def _make_location(public_id: int, parent: int, object_id: int, name: str) -> dict[str, Any]:
    """Builds one location node in the dg_location tree."""
    return {
        'public_id': public_id,
        'name': name,
        'parent': parent,
        'object_id': object_id,
        'type_id': TYPE_LOCATION,
        'type_label': 'Location',
        'type_icon': 'fas fa-cube',
        'type_selectable': True,
    }


@pytest.fixture(scope='module', name='connector')
def fixture_connector(database_manager) -> MongoConnector:
    """Shortcut to the underlying MongoConnector for direct collection access."""
    return database_manager.connector


@pytest.fixture(scope='module', autouse=True)
def setup_ci_explorer_fixture(request, connector: MongoConnector, database_name):
    """
    Seeds types, objects, relations, object relations and locations once per test module
    and drops every touched collection at teardown
    """
    db = connector.client.get_database(database_name)
    types = db.get_collection(CmdbType.COLLECTION)
    objects = db.get_collection(CmdbObject.COLLECTION)
    relations = db.get_collection(CmdbRelation.COLLECTION)
    object_relations = db.get_collection(CmdbObjectRelation.COLLECTION)
    locations = db.get_collection(CmdbLocation.COLLECTION)

    types.insert_many([
        _make_type(TYPE_SERVER, 'server', 'Server', '#1f77b4', 'fa-server'),
        _make_type(TYPE_PRINTER, 'printer', 'Printer', '#ff7f0e', 'fa-print'),
        _make_type(TYPE_NETWORK, 'network', 'Network', '#2ca02c', 'fa-network-wired'),
        _make_type(TYPE_LOCATION, 'location', 'Location', '#888888', 'fas fa-cube'),
    ])

    objects.insert_many([
        _make_object(OBJ_TARGET, TYPE_SERVER, 'srv-target'),
        _make_object(OBJ_PARENT_SERVER, TYPE_SERVER, 'srv-parent'),
        _make_object(OBJ_CHILD_PRINTER, TYPE_PRINTER, 'prn-child'),
        _make_object(OBJ_CHILD_NETWORK, TYPE_NETWORK, 'net-child'),
        _make_object(OBJ_EXTRA_1, TYPE_PRINTER, 'prn-extra-1'),
        _make_object(OBJ_EXTRA_2, TYPE_PRINTER, 'prn-extra-2'),
        _make_object(OBJ_EXTRA_3, TYPE_PRINTER, 'prn-extra-3'),
        _make_object(OBJ_LOC_PARENT, TYPE_LOCATION, 'loc-parent'),
        _make_object(OBJ_LOC_CHILD, TYPE_LOCATION, 'loc-child'),
    ])

    relations.insert_one(_make_relation())

    object_relations.insert_many([
        # OBJ_PARENT_SERVER -> OBJ_TARGET (parent of the target)
        _make_object_relation(
            OBJ_REL_PARENT_TO_TARGET, OBJ_PARENT_SERVER, TYPE_SERVER, OBJ_TARGET, TYPE_SERVER,
        ),
        # OBJ_TARGET -> OBJ_CHILD_PRINTER (child of the target)
        _make_object_relation(
            OBJ_REL_TARGET_TO_PRINTER, OBJ_TARGET, TYPE_SERVER, OBJ_CHILD_PRINTER, TYPE_PRINTER,
        ),
        # OBJ_TARGET -> OBJ_CHILD_NETWORK (other-type child, used for types_filter test)
        _make_object_relation(
            OBJ_REL_TARGET_TO_NETWORK, OBJ_TARGET, TYPE_SERVER, OBJ_CHILD_NETWORK, TYPE_NETWORK,
        ),
        # Extra Printer children used by the item_limit test
        _make_object_relation(
            OBJ_REL_TARGET_TO_EXTRA_1, OBJ_TARGET, TYPE_SERVER, OBJ_EXTRA_1, TYPE_PRINTER,
        ),
        _make_object_relation(
            OBJ_REL_TARGET_TO_EXTRA_2, OBJ_TARGET, TYPE_SERVER, OBJ_EXTRA_2, TYPE_PRINTER,
        ),
        _make_object_relation(
            OBJ_REL_TARGET_TO_EXTRA_3, OBJ_TARGET, TYPE_SERVER, OBJ_EXTRA_3, TYPE_PRINTER,
        ),
    ])

    # Location tree:
    #   1000 (object=OBJ_LOC_PARENT, parent=root=1)
    #     └── 1001 (object=OBJ_TARGET, parent=1000)
    #           └── 1002 (object=OBJ_LOC_CHILD, parent=1001)
    locations.insert_many([
        _make_location(LOC_FOR_LOC_PARENT_OBJECT, LOC_ROOT, OBJ_LOC_PARENT, 'loc-parent'),
        _make_location(LOC_FOR_TARGET_OBJECT, LOC_FOR_LOC_PARENT_OBJECT, OBJ_TARGET, 'loc-target'),
        _make_location(LOC_FOR_LOC_CHILD_OBJECT, LOC_FOR_TARGET_OBJECT, OBJ_LOC_CHILD, 'loc-child'),
    ])

    def _drop_all():
        types.drop()
        objects.drop()
        relations.drop()
        object_relations.drop()
        locations.drop()

    request.addfinalizer(_drop_all)


# -------------------------------------------------------------------------------------------------------------------- #
#                                       Smoke tests for /ci_explorer/items                                             #
# -------------------------------------------------------------------------------------------------------------------- #
class TestCiExplorerNodesEdgesContract:
    """Pins the observable contract of the current route before the refactor."""

    def test_both_with_root_returns_root_plus_parent_and_child_neighbourhoods(self, rest_api):
        """target_type=BOTH&with_root=true returns root_node + populated parent and child sides"""
        response = rest_api.get(f'{ROUTE_URL}?target_id={OBJ_TARGET}&target_type=BOTH&with_root=true')

        assert response.status_code == HTTPStatus.OK
        body = response.get_json()

        assert 'root_node' in body
        assert body['root_node']['linked_object']['public_id'] == OBJ_TARGET
        assert body['root_node']['title'] == 'srv-target'
        assert body['root_node']['type_info']['type_id'] == TYPE_SERVER

        # Parents: the parent server (object 101) connects via OBJ_REL_PARENT_TO_TARGET
        parent_ids = {node['linked_object']['public_id'] for node in body['parent_nodes']}
        assert OBJ_PARENT_SERVER in parent_ids
        parent_edge = next(e for e in body['parent_edges'] if e['from'] == OBJ_PARENT_SERVER)
        assert parent_edge['to'] == OBJ_TARGET
        assert parent_edge['metadata']['relation_id'] == RELATION_CONNECTED

        # Children: the Printer + Network + 3 extras (6 total)
        child_ids = {node['linked_object']['public_id'] for node in body['children_nodes']}
        assert {OBJ_CHILD_PRINTER, OBJ_CHILD_NETWORK, OBJ_EXTRA_1, OBJ_EXTRA_2, OBJ_EXTRA_3}.issubset(child_ids)
        printer_edge = next(e for e in body['child_edges'] if e['to'] == OBJ_CHILD_PRINTER)
        assert printer_edge['from'] == OBJ_TARGET
        assert printer_edge['metadata']['relation_id'] == RELATION_CONNECTED


    def test_child_only_omits_parent_block(self, rest_api):
        """target_type=CHILD returns only the child side; parent_nodes / parent_edges are absent"""
        response = rest_api.get(f'{ROUTE_URL}?target_id={OBJ_TARGET}&target_type=CHILD')

        assert response.status_code == HTTPStatus.OK
        body = response.get_json()

        assert 'children_nodes' in body
        assert 'child_edges' in body
        assert 'parent_nodes' not in body
        assert 'parent_edges' not in body


    def test_parent_only_omits_child_block(self, rest_api):
        """target_type=PARENT returns only the parent side; children_nodes / child_edges are absent"""
        response = rest_api.get(f'{ROUTE_URL}?target_id={OBJ_TARGET}&target_type=PARENT')

        assert response.status_code == HTTPStatus.OK
        body = response.get_json()

        assert 'parent_nodes' in body
        assert 'parent_edges' in body
        assert 'children_nodes' not in body
        assert 'child_edges' not in body


    def test_types_filter_restricts_children_to_matching_type(self, rest_api):
        """types_filter=[TYPE_PRINTER] keeps only Printer children; Network and Server neighbours are dropped"""
        response = rest_api.get(
            f'{ROUTE_URL}?target_id={OBJ_TARGET}&target_type=CHILD&types_filter=[{TYPE_PRINTER}]'
        )

        assert response.status_code == HTTPStatus.OK
        body = response.get_json()

        child_type_ids = {node['type_info']['type_id'] for node in body['children_nodes']}
        assert child_type_ids == {TYPE_PRINTER}

        child_object_ids = {node['linked_object']['public_id'] for node in body['children_nodes']}
        assert OBJ_CHILD_NETWORK not in child_object_ids


    def test_item_limit_caps_returned_neighbours(self, rest_api):
        """item_limit=2 caps the linked-objects query so at most 2 distinct neighbours are returned"""
        response = rest_api.get(
            f'{ROUTE_URL}?target_id={OBJ_TARGET}&target_type=CHILD&item_limit=2'
        )

        assert response.status_code == HTTPStatus.OK
        body = response.get_json()

        # Pin only the upper bound: the Mongo-level limit caps raw documents, so the
        # visible count is <= item_limit. The lower bound is at least 1 (we have plenty).
        assert 1 <= len(body['children_nodes']) <= 2


    def test_with_locations_flips_location_semantics(self, rest_api):
        """
        with_locations=true grafts the dg_location hierarchy with INVERTED semantics:
        a location-parent appears in children_nodes (flipped) and a location-child appears
        in parent_nodes. Location edges carry no 'metadata' block, unlike relation edges
        """
        response = rest_api.get(
            f'{ROUTE_URL}?target_id={OBJ_TARGET}&target_type=BOTH&with_locations=true'
        )

        assert response.status_code == HTTPStatus.OK
        body = response.get_json()

        # OBJ_LOC_PARENT (the location-tree parent of the target) should appear in CHILDREN
        child_object_ids = {node['linked_object']['public_id'] for node in body['children_nodes']}
        assert OBJ_LOC_PARENT in child_object_ids

        # OBJ_LOC_CHILD (the location-tree child of the target) should appear in PARENTS
        parent_object_ids = {node['linked_object']['public_id'] for node in body['parent_nodes']}
        assert OBJ_LOC_CHILD in parent_object_ids

        # The location edge from the target to OBJ_LOC_PARENT lacks a 'metadata' key
        loc_edge_up = next(e for e in body['child_edges'] if e['to'] == OBJ_LOC_PARENT)
        assert loc_edge_up['from'] == OBJ_TARGET
        assert 'metadata' not in loc_edge_up

        # The location edge from OBJ_LOC_CHILD to the target also lacks 'metadata'
        loc_edge_down = next(e for e in body['parent_edges'] if e['from'] == OBJ_LOC_CHILD)
        assert loc_edge_down['to'] == OBJ_TARGET
        assert 'metadata' not in loc_edge_down
