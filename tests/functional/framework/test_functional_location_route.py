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
Functional smoke for the ``/locations`` REST routes

End-to-end coverage that the LocationsManager integration suite cannot give: HTTP status
codes and the JSON envelopes for the CmdbLocation routes - GET-list, GET-single + 404, the
object-scoped ``/<id>/object`` + ``/parent`` + ``/children`` lookups, and the one-object move
``PATCH /<id>/parent`` placing, moving and removing a placement (node and object field alike). The
create, update and delete routes are retired and answer no write. CRUD correctness itself is
asserted at the manager layer; these tests only verify the routes wrap it correctly.

Also covered: the per-route error tails (the ``/tree/search`` 500 and the two
move routes' manager-error and unexpected-error arms), the HTTPException pass-throughs the five read
routes were missing, and the ``/<id>/parent`` route answering 200 with ``null`` for a dangling parent
instead of 404.

And: the root document (object_id sentinel 0) is unreachable through the move, and one tree level
answers in name order rather than in the read's insertion order.
"""
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any

import pytest
from werkzeug.exceptions import NotFound

from cmdb.database import MongoDatabaseManager
from cmdb.models.type_model import CmdbType
from cmdb.models.object_model import CmdbObject
from cmdb.models.location_model.cmdb_location import CmdbLocation
from cmdb.models.location_model.location_constants import CmdbLocationDefault, LocationKey
from cmdb.manager import LocationsManager
from cmdb.errors.manager.objects_manager import ObjectsManagerGetError, ObjectsManagerUpdateError
from cmdb.errors.manager.locations_manager import LocationsManagerGetError, LocationsManagerUpdateError
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_URL: str = '/locations'

TYPE_ID: int = 9790
TYPE_NAME: str = 'location-smoke-type'
NAME_FIELD: str = 'name-field'
LOCATION_FIELD: str = 'location-field'
ROOT_PARENT_ID: int = 1
SEED_AUTHOR_ID: int = 1
SEED_VERSION: str = '1.0.0'
SUMMARY_NAME: str = 'Derived Summary Name'

OBJECT_ID_FOR_CREATE: int = 9881

LOCATION_ID_FOR_GET: int = 9882
OBJECT_ID_FOR_GET: int = 9882

ROOT_LOCATION_ID: int = 9883
ROOT_OBJECT_ID: int = 9883
CHILD_LOCATION_ID: int = 9884
CHILD_OBJECT_ID: int = 9884

LOCATION_ID_FOR_UPDATE: int = 9885

DANGLING_LOCATION_ID: int = 9895
DANGLING_OBJECT_ID: int = 9895
MISSING_PARENT_ID: int = 9899
OBJECT_ID_FOR_UPDATE: int = 9885

LOCATION_ID_FOR_DELETE: int = 9886
OBJECT_ID_FOR_DELETE: int = 9886

NON_SELECTABLE_PARENT_LOC: int = 9887

DERIVE_POST_OBJECT_ID: int = 9890

MISSING_LOCATION_ID: int = 9898
MISSING_OBJECT_ID: int = 9899

ROOT_OBJECT_ID_SENTINEL: int = 0

# level-ordering fixtures: two children whose names are the reverse of their public_id order
LEVEL_PARENT_LOC: int = 9860
LEVEL_PARENT_OBJECT: int = 9860
LEVEL_FIRST_LOC: int = 9861
LEVEL_FIRST_OBJECT: int = 9861
LEVEL_SECOND_LOC: int = 9862
LEVEL_SECOND_OBJECT: int = 9862
LEVEL_FIRST_NAME: str = 'zeta'
LEVEL_SECOND_NAME: str = 'Alpha'

# path tree fixtures: DC <- {Rack, Rack2}; Rack <- {target, target-sibling}; target <- child; Office <- child.
# Expanding to the target returns every sibling level down to it, excluding the target's child and
# the off-path Office branch.
PATH_DC_LOC: int = 9870
PATH_OFFICE_LOC: int = 9871
PATH_RACK_LOC: int = 9872
PATH_RACK2_LOC: int = 9873
PATH_TARGET_LOC: int = 9874
PATH_TARGET_SIBLING_LOC: int = 9875
PATH_TARGET_CHILD_LOC: int = 9876
PATH_OFFICE_CHILD_LOC: int = 9877

# search tree fixtures: Datacenter <- Rack-01 <- Server-alpha, plus an unrelated Office root
SEARCH_DC_LOC: int = 9893
SEARCH_RACK_LOC: int = 9894
SEARCH_SRV_LOC: int = 9895
SEARCH_OFFICE_LOC: int = 9896
SEARCH_DC_NAME: str = 'Datacenter'
SEARCH_RACK_NAME: str = 'Rack-01'
SEARCH_SRV_NAME: str = 'Server-alpha'
SEARCH_OFFICE_NAME: str = 'Office'

ORIGINAL_NAME: str = 'Original Location'

ALL_LOCATION_IDS: list[int] = [
    LOCATION_ID_FOR_GET, ROOT_LOCATION_ID, CHILD_LOCATION_ID,
    LOCATION_ID_FOR_UPDATE, LOCATION_ID_FOR_DELETE,
    SEARCH_DC_LOC, SEARCH_RACK_LOC, SEARCH_SRV_LOC, SEARCH_OFFICE_LOC,
    NON_SELECTABLE_PARENT_LOC,
    PATH_DC_LOC, PATH_OFFICE_LOC, PATH_RACK_LOC, PATH_RACK2_LOC, PATH_TARGET_LOC,
    PATH_TARGET_SIBLING_LOC, PATH_TARGET_CHILD_LOC, PATH_OFFICE_CHILD_LOC,
]
ALL_OBJECT_IDS: list[int] = [
    OBJECT_ID_FOR_CREATE, OBJECT_ID_FOR_GET, ROOT_OBJECT_ID, CHILD_OBJECT_ID,
    OBJECT_ID_FOR_UPDATE, OBJECT_ID_FOR_DELETE, DERIVE_POST_OBJECT_ID,
]
# CmdbObjects seeded as real documents: the move reads the object (and derives a summary line)
REAL_OBJECT_IDS: list[int] = [
    DERIVE_POST_OBJECT_ID, OBJECT_ID_FOR_CREATE, OBJECT_ID_FOR_UPDATE, OBJECT_ID_FOR_DELETE,
    ROOT_OBJECT_ID, CHILD_OBJECT_ID,
]


def _type_doc() -> dict[str, Any]:
    """Builds an active CmdbType doc with a location field, so its objects can be placed."""
    return {
        'public_id': TYPE_ID,
        'name': TYPE_NAME,
        'label': 'Location Smoke Type',
        'author_id': SEED_AUTHOR_ID,
        'creation_time': datetime.now(timezone.utc),
        'active': True,
        'selectable_as_parent': True,
        'fields': [{'type': 'text', 'name': NAME_FIELD, 'label': 'Name'},
                   {'type': 'location', 'name': LOCATION_FIELD, 'label': 'Location'}],
        'render_meta': {
            'icon': 'fa-cube',
            'sections': [{'type': 'section', 'name': 'main', 'label': 'Main', 'fields': [NAME_FIELD, LOCATION_FIELD]}],
            'summary': {'fields': [NAME_FIELD]},
        },
        'acl': {'activated': False, 'groups': {'includes': None}},
        'version': SEED_VERSION,
    }


def _object_doc(public_id: int, value: str, placement: int | None = None) -> dict[str, Any]:
    """Builds a complete CmdbObject doc whose ``NAME_FIELD`` value drives the rendered summary line."""
    return {
        'public_id': public_id,
        'type_id': TYPE_ID,
        'active': True,
        'author_id': SEED_AUTHOR_ID,
        'version': SEED_VERSION,
        'fields': [{'type': 'text', 'name': NAME_FIELD, 'value': value},
                   {'type': 'location', 'name': LOCATION_FIELD, 'value': placement}],
        'creation_time': datetime.now(timezone.utc),
    }


def _insert_object(database_manager: MongoDatabaseManager, database_name: str, public_id: int, value: str,
                   placement: int | None = None) -> None:
    """Inserts a CmdbObject doc directly via the collection, placed under ``placement`` when one is given."""
    database_manager.get_collection(CmdbObject.COLLECTION, database_name)\
        .insert_one(_object_doc(public_id, value, placement))


def _location_field_value(database_manager: MongoDatabaseManager, database_name: str, public_id: int) -> Any:
    """Reads the stored value of the object's location field - the other side of the mirror."""
    stored: dict[str, Any] = database_manager.get_collection(CmdbObject.COLLECTION, database_name)\
        .find_one({'public_id': public_id})

    return next(field['value'] for field in stored['fields'] if field['name'] == LOCATION_FIELD)


def _drop_objects(database_manager: MongoDatabaseManager, database_name: str, public_ids: list[int]) -> None:
    """Removes CmdbObject docs by public_id directly via the collection."""
    database_manager.get_collection(CmdbObject.COLLECTION, database_name)\
        .delete_many({'public_id': {'$in': public_ids}})


def _location_doc(public_id: int, object_id: int, parent: int, name: str = ORIGINAL_NAME) -> dict[str, Any]:
    """Builds a complete CmdbLocation doc for direct DB insertion (bypasses the mirror)."""
    return {
        'public_id': public_id,
        'name': name,
        'parent': parent,
        'object_id': object_id,
        'type_id': TYPE_ID,
        'type_label': 'Location Smoke Type',
        'type_icon': 'fas fa-cube',
        'type_selectable': True,
    }


def _insert_location(database_manager: MongoDatabaseManager, database_name: str, doc: dict[str, Any]) -> None:
    """Inserts a CmdbLocation doc directly via the collection."""
    database_manager.get_collection(CmdbLocation.COLLECTION, database_name).insert_one(doc)


def _drop_locations_by_ids(database_manager: MongoDatabaseManager, database_name: str, public_ids: list[int]) -> None:
    """Removes CmdbLocation docs by public_id directly via the collection."""
    database_manager.get_collection(CmdbLocation.COLLECTION, database_name)\
        .delete_many({'public_id': {'$in': public_ids}})


def _drop_locations_by_objects(
    database_manager: MongoDatabaseManager, database_name: str, object_ids: list[int],
) -> None:
    """Removes CmdbLocation docs by object_id directly via the collection (a placed node gets an auto public_id)."""
    database_manager.get_collection(CmdbLocation.COLLECTION, database_name)\
        .delete_many({'object_id': {'$in': object_ids}})


@pytest.fixture(scope='module', autouse=True)
def _seed_type_and_cleanup(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds the CmdbType the placed objects use and removes the type + all test locations and objects after."""
    database_manager.get_collection(CmdbType.COLLECTION, database_name).insert_one(_type_doc())
    yield
    database_manager.get_collection(CmdbType.COLLECTION, database_name).delete_one({'public_id': TYPE_ID})
    _drop_locations_by_ids(database_manager, database_name, ALL_LOCATION_IDS)
    _drop_locations_by_objects(database_manager, database_name, ALL_OBJECT_IDS)
    _drop_objects(database_manager, database_name, REAL_OBJECT_IDS)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                        PLACE                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
class TestPlaceObject:
    """PATCH /locations/<object_id>/parent on an unplaced object creates its CmdbLocation."""

    def test_places_an_unplaced_object(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """The node is created under the parent and the object's location field mirrors it."""
        _insert_object(database_manager, database_name, OBJECT_ID_FOR_CREATE, ORIGINAL_NAME)
        try:
            response = rest_api.patch(f'{ROUTE_URL}/{OBJECT_ID_FOR_CREATE}/parent', json={'parent': ROOT_PARENT_ID})

            assert response.status_code == HTTPStatus.OK
            follow_up = rest_api.get(f'{ROUTE_URL}/{OBJECT_ID_FOR_CREATE}/object')
            assert follow_up.status_code == HTTPStatus.OK
            # The object-scoped GET uses DefaultResponse - the body is the bare location dict
            assert follow_up.get_json()['object_id'] == OBJECT_ID_FOR_CREATE
            assert follow_up.get_json()['parent'] == ROOT_PARENT_ID
            assert _location_field_value(database_manager, database_name, OBJECT_ID_FOR_CREATE) == ROOT_PARENT_ID
        finally:
            _drop_locations_by_objects(database_manager, database_name, [OBJECT_ID_FOR_CREATE])
            _drop_objects(database_manager, database_name, [OBJECT_ID_FOR_CREATE])

    def test_a_missing_object_is_404(self, rest_api) -> None:
        """No object, nothing to place"""
        response = rest_api.patch(f'{ROUTE_URL}/{MISSING_OBJECT_ID}/parent', json={'parent': ROOT_PARENT_ID})

        assert response.status_code == HTTPStatus.NOT_FOUND


class TestRetiredWriteRoutes:
    """The create, update and delete routes are gone: the two moves are the only placement writes."""

    @pytest.mark.parametrize('method, url', [
        ('post', f'{ROUTE_URL}/'),
        ('put', f'{ROUTE_URL}/update_location'),
        ('patch', f'{ROUTE_URL}/update_location'),
        ('delete', f'{ROUTE_URL}/{OBJECT_ID_FOR_GET}/object'),
    ], ids=['create', 'update-put', 'update-patch', 'delete'])
    def test_the_route_does_not_answer(self, rest_api, method: str, url: str) -> None:
        """No route by that method and path: 404 or 405, never a write"""
        response = getattr(rest_api, method)(url, json={'object_id': OBJECT_ID_FOR_GET, 'parent': ROOT_PARENT_ID})

        assert response.status_code in (HTTPStatus.NOT_FOUND, HTTPStatus.METHOD_NOT_ALLOWED)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                         READ                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
class TestGetLocation:
    """GET /locations/ and GET /locations/<id> return the expected envelopes."""

    @pytest.fixture(autouse=True)
    def _seed(self, database_manager: MongoDatabaseManager, database_name: str):
        """Inserts one location directly before each test and removes it after."""
        _insert_location(database_manager, database_name, _location_doc(
            LOCATION_ID_FOR_GET, OBJECT_ID_FOR_GET, ROOT_PARENT_ID,
        ))
        yield
        _drop_locations_by_ids(database_manager, database_name, [LOCATION_ID_FOR_GET])

    def test_get_single_returns_location(self, rest_api) -> None:
        """GET /locations/<id> for a seeded location returns 200 with the document."""
        response = rest_api.get(f'{ROUTE_URL}/{LOCATION_ID_FOR_GET}')

        assert response.status_code == HTTPStatus.OK
        # GET /locations/<id> uses DefaultResponse - the body is the bare location dict
        assert response.get_json()['public_id'] == LOCATION_ID_FOR_GET

    def test_get_single_missing_returns_404(self, rest_api) -> None:
        """GET /locations/<id> for a missing id returns 404."""
        response = rest_api.get(f'{ROUTE_URL}/{MISSING_LOCATION_ID}')

        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_get_list_returns_results_envelope(self, rest_api) -> None:
        """GET /locations/ returns a JSON envelope whose results length matches X-Total-Count."""
        response = rest_api.get(f'{ROUTE_URL}/')

        assert response.status_code == HTTPStatus.OK
        body = response.get_json()
        assert 'results' in body
        assert len(body['results']) == int(response.headers['X-Total-Count'])

    def test_list_rows_carry_exactly_the_payload_keys(self, rest_api) -> None:
        """
        The eight LocationKey keys and nothing else - '_id' above all

        The rows are answered as they are read now (no model per row), so the canonical
        normalisation is what keeps the Mongo id out of a response the Angular tree consumes.
        """
        response = rest_api.get(f'{ROUTE_URL}/', query_string={'filter': '{"public_id": %s}' % LOCATION_ID_FOR_GET})

        assert response.status_code == HTTPStatus.OK
        rows = response.get_json()['results']
        assert [row['public_id'] for row in rows] == [LOCATION_ID_FOR_GET]
        assert set(rows[0]) == {key.value for key in LocationKey}

    def test_list_defaults_the_optional_render_keys(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """A document written without the render snapshot still answers a complete node"""
        bare_document = _location_doc(DANGLING_LOCATION_ID, DANGLING_OBJECT_ID, ROOT_PARENT_ID)
        del bare_document['type_icon']
        del bare_document['type_selectable']
        _insert_location(database_manager, database_name, bare_document)

        try:
            response = rest_api.get(
                f'{ROUTE_URL}/', query_string={'filter': '{"public_id": %s}' % DANGLING_LOCATION_ID},
            )

            assert response.status_code == HTTPStatus.OK
            row = response.get_json()['results'][0]
            assert row['type_icon'] == CmdbLocationDefault.TYPE_ICON
            assert row['type_selectable'] is CmdbLocationDefault.TYPE_SELECTABLE
        finally:
            _drop_locations_by_ids(database_manager, database_name, [DANGLING_LOCATION_ID])

    def test_get_location_for_object_missing_returns_404(self, rest_api) -> None:
        """GET /locations/<object_id>/object for an object with no location returns 404."""
        response = rest_api.get(f'{ROUTE_URL}/{MISSING_OBJECT_ID}/object')

        assert response.status_code == HTTPStatus.NOT_FOUND


class TestGetLocationTreeAndRelations:
    """The retired /tree forest view and the object-scoped parent/children lookups."""

    @pytest.fixture(autouse=True)
    def _seed_parent_and_child(self, database_manager: MongoDatabaseManager, database_name: str):
        """Seeds a root location (parent == root id) and a child beneath it."""
        _insert_location(database_manager, database_name, _location_doc(
            ROOT_LOCATION_ID, ROOT_OBJECT_ID, ROOT_PARENT_ID,
        ))
        _insert_location(database_manager, database_name, _location_doc(
            CHILD_LOCATION_ID, CHILD_OBJECT_ID, ROOT_LOCATION_ID,
        ))
        yield
        _drop_locations_by_ids(database_manager, database_name, [ROOT_LOCATION_ID, CHILD_LOCATION_ID])

    def test_the_retired_eager_tree_route_is_gone(self, rest_api) -> None:
        """
        The whole forest in one response is not served; the lazy tree routes read it level by level

        A location exists, so a 404 here is the missing route and not an empty collection.
        """
        response = rest_api.get(f'{ROUTE_URL}/tree')

        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_parent_lookup_returns_root_location(self, rest_api) -> None:
        """GET /locations/<child_object_id>/parent returns the parent (root) location."""
        response = rest_api.get(f'{ROUTE_URL}/{CHILD_OBJECT_ID}/parent')

        assert response.status_code == HTTPStatus.OK
        # The parent lookup uses DefaultResponse - the body is the bare parent location dict
        assert response.get_json()['public_id'] == ROOT_LOCATION_ID

    def test_children_lookup_returns_direct_children(self, rest_api) -> None:
        """GET /locations/<root_object_id>/children returns the direct child location."""
        response = rest_api.get(f'{ROUTE_URL}/{ROOT_OBJECT_ID}/children')

        assert response.status_code == HTTPStatus.OK
        # The children lookup uses DefaultResponse - the body is the bare list of location dicts
        child_ids = [child['public_id'] for child in response.get_json()]
        assert CHILD_LOCATION_ID in child_ids

    def test_tree_roots_returns_root_children_flagged_has_children(self, rest_api) -> None:
        """GET /locations/tree/roots returns the root's direct children, flagging those with children."""
        response = rest_api.get(f'{ROUTE_URL}/tree/roots')

        assert response.status_code == HTTPStatus.OK
        root_node = next(node for node in response.get_json() if node['public_id'] == ROOT_LOCATION_ID)
        assert root_node['has_children'] is True  # it has CHILD_LOCATION_ID beneath it

    def test_tree_children_returns_one_level_flagged(self, rest_api) -> None:
        """GET /locations/tree/<id>/children returns the next level with has_children flags."""
        response = rest_api.get(f'{ROUTE_URL}/tree/{ROOT_LOCATION_ID}/children')

        assert response.status_code == HTTPStatus.OK
        nodes = {node['public_id']: node for node in response.get_json()}
        assert CHILD_LOCATION_ID in nodes
        assert nodes[CHILD_LOCATION_ID]['has_children'] is False  # leaf node
        # Unused type metadata is trimmed from tree nodes, but type_selectable is kept for drag-drop
        assert 'type_id' not in nodes[CHILD_LOCATION_ID]
        assert 'type_label' not in nodes[CHILD_LOCATION_ID]
        assert 'type_selectable' in nodes[CHILD_LOCATION_ID]

    def test_tree_children_of_leaf_is_empty(self, rest_api) -> None:
        """A leaf location returns an empty children level."""
        response = rest_api.get(f'{ROUTE_URL}/tree/{CHILD_LOCATION_ID}/children')

        assert response.status_code == HTTPStatus.OK
        assert response.get_json() == []


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  TREE LEVEL ORDER                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
class TestTreeLevelOrdering:
    """One level of the tree answers in name order, not in the order the documents were written."""

    @pytest.fixture(autouse=True)
    def _seed_level(self, database_manager: MongoDatabaseManager, database_name: str):
        """A parent with two children whose names run counter to their public_ids."""
        _insert_location(database_manager, database_name, _location_doc(
            LEVEL_PARENT_LOC, LEVEL_PARENT_OBJECT, ROOT_PARENT_ID,
        ))
        _insert_location(database_manager, database_name, _location_doc(
            LEVEL_FIRST_LOC, LEVEL_FIRST_OBJECT, LEVEL_PARENT_LOC, name=LEVEL_FIRST_NAME,
        ))
        _insert_location(database_manager, database_name, _location_doc(
            LEVEL_SECOND_LOC, LEVEL_SECOND_OBJECT, LEVEL_PARENT_LOC, name=LEVEL_SECOND_NAME,
        ))
        yield
        _drop_locations_by_ids(database_manager, database_name,
                               [LEVEL_PARENT_LOC, LEVEL_FIRST_LOC, LEVEL_SECOND_LOC])

    def test_tree_children_are_name_ordered(self, rest_api) -> None:
        """GET /locations/tree/<id>/children sorts case-insensitively by name."""
        response = rest_api.get(f'{ROUTE_URL}/tree/{LEVEL_PARENT_LOC}/children')

        assert response.status_code == HTTPStatus.OK
        assert [node['name'] for node in response.get_json()] == [LEVEL_SECOND_NAME, LEVEL_FIRST_NAME]

    def test_object_children_lookup_is_name_ordered(self, rest_api) -> None:
        """The object-scoped ``/<id>/children`` lookup shares the same ordering."""
        response = rest_api.get(f'{ROUTE_URL}/{LEVEL_PARENT_OBJECT}/children')

        assert response.status_code == HTTPStatus.OK
        assert [child['name'] for child in response.get_json()] == [LEVEL_SECOND_NAME, LEVEL_FIRST_NAME]


# -------------------------------------------------------------------------------------------------------------------- #
#                                                   TREE SEARCH                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
class TestSearchLocationTree:
    """GET /locations/tree/search returns a pruned nested forest of matches + their ancestor paths."""

    @pytest.fixture(autouse=True)
    def _seed(self, database_manager: MongoDatabaseManager, database_name: str):
        """Seeds Datacenter <- Rack-01 <- Server-alpha plus an unrelated Office root."""
        _insert_location(database_manager, database_name,
                         _location_doc(SEARCH_DC_LOC, SEARCH_DC_LOC, ROOT_PARENT_ID, name=SEARCH_DC_NAME))
        _insert_location(database_manager, database_name,
                         _location_doc(SEARCH_RACK_LOC, SEARCH_RACK_LOC, SEARCH_DC_LOC, name=SEARCH_RACK_NAME))
        _insert_location(database_manager, database_name,
                         _location_doc(SEARCH_SRV_LOC, SEARCH_SRV_LOC, SEARCH_RACK_LOC, name=SEARCH_SRV_NAME))
        _insert_location(database_manager, database_name,
                         _location_doc(SEARCH_OFFICE_LOC, SEARCH_OFFICE_LOC, ROOT_PARENT_ID, name=SEARCH_OFFICE_NAME))
        yield
        _drop_locations_by_ids(database_manager, database_name,
                               [SEARCH_DC_LOC, SEARCH_RACK_LOC, SEARCH_SRV_LOC, SEARCH_OFFICE_LOC])

    def test_search_returns_match_nested_under_its_ancestors(self, rest_api) -> None:
        """A match is returned nested under its full ancestor path; the unrelated root is excluded."""
        response = rest_api.get(f'{ROUTE_URL}/tree/search', query_string={'query': 'alpha'})

        assert response.status_code == HTTPStatus.OK
        forest = response.get_json()
        # only the Datacenter branch is present (Office excluded)
        assert [node['public_id'] for node in forest] == [SEARCH_DC_LOC]
        rack_level = forest[0]['children']
        assert [node['public_id'] for node in rack_level] == [SEARCH_RACK_LOC]
        server_level = rack_level[0]['children']
        assert [node['public_id'] for node in server_level] == [SEARCH_SRV_LOC]
        # each node carries has_children reflecting real direct children in the full tree
        assert forest[0]['has_children'] is True       # Datacenter has Rack-01
        assert rack_level[0]['has_children'] is True    # Rack-01 has Server-alpha
        assert server_level[0]['has_children'] is False  # Server-alpha is a leaf
        # and type_selectable is present on search nodes too (for drag-drop drop targets)
        assert forest[0]['type_selectable'] is True
        assert server_level[0]['type_selectable'] is True

    def test_search_no_match_returns_empty_forest(self, rest_api) -> None:
        """A query matching no location name returns an empty forest."""
        response = rest_api.get(f'{ROUTE_URL}/tree/search', query_string={'query': 'nonexistent-xyz'})

        assert response.status_code == HTTPStatus.OK
        assert response.get_json() == []

    def test_search_empty_query_returns_empty_forest(self, rest_api) -> None:
        """An empty query yields an empty forest rather than the whole tree."""
        response = rest_api.get(f'{ROUTE_URL}/tree/search', query_string={'query': ''})

        assert response.status_code == HTTPStatus.OK
        assert response.get_json() == []


# -------------------------------------------------------------------------------------------------------------------- #
#                                              TREE PATH (open to selection)                                          #
# -------------------------------------------------------------------------------------------------------------------- #
class TestGetLocationTreePath:
    """GET /locations/tree/path/<id> returns the tree pre-expanded down to one selected location."""

    @pytest.fixture(autouse=True)
    def _seed(self, database_manager: MongoDatabaseManager, database_name: str):
        """Seeds DC <- {Rack <- {target, sibling} <- target-child, Rack2} and an off-path Office <- child."""
        for public_id, parent in [
            (PATH_DC_LOC, ROOT_PARENT_ID),
            (PATH_OFFICE_LOC, ROOT_PARENT_ID),
            (PATH_RACK_LOC, PATH_DC_LOC),
            (PATH_RACK2_LOC, PATH_DC_LOC),
            (PATH_TARGET_LOC, PATH_RACK_LOC),
            (PATH_TARGET_SIBLING_LOC, PATH_RACK_LOC),
            (PATH_TARGET_CHILD_LOC, PATH_TARGET_LOC),
            (PATH_OFFICE_CHILD_LOC, PATH_OFFICE_LOC),
        ]:
            _insert_location(database_manager, database_name, _location_doc(public_id, public_id, parent))
        yield
        _drop_locations_by_ids(database_manager, database_name, [
            PATH_DC_LOC, PATH_OFFICE_LOC, PATH_RACK_LOC, PATH_RACK2_LOC, PATH_TARGET_LOC,
            PATH_TARGET_SIBLING_LOC, PATH_TARGET_CHILD_LOC, PATH_OFFICE_CHILD_LOC,
        ])

    @staticmethod
    def _by_id(nodes: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
        """Indexes a level of forest nodes by public_id for order-independent assertions."""
        return {node['public_id']: node for node in nodes}

    def test_path_expands_every_sibling_level_to_the_target(self, rest_api) -> None:
        """The forest opens down to the target: full siblings per level, deeper levels stay lazy."""
        response = rest_api.get(f'{ROUTE_URL}/tree/path/{PATH_TARGET_LOC}')

        assert response.status_code == HTTPStatus.OK
        roots = self._by_id(response.get_json())
        # both roots are present (full sibling context at level 1)
        assert set(roots) == {PATH_DC_LOC, PATH_OFFICE_LOC}

        # the on-path root is expanded to its children; the off-path root is not, but is flagged expandable
        assert 'children' not in roots[PATH_OFFICE_LOC]
        assert roots[PATH_OFFICE_LOC]['has_children'] is True

        dc_children = self._by_id(roots[PATH_DC_LOC]['children'])
        assert set(dc_children) == {PATH_RACK_LOC, PATH_RACK2_LOC}
        assert dc_children[PATH_RACK2_LOC]['has_children'] is False  # off-path leaf

        rack_children = self._by_id(dc_children[PATH_RACK_LOC]['children'])
        assert set(rack_children) == {PATH_TARGET_LOC, PATH_TARGET_SIBLING_LOC}

        # the target reports it still has children (loaded lazily, not inlined here)
        target = rack_children[PATH_TARGET_LOC]
        assert target['has_children'] is True
        assert 'children' not in target
        # its sibling is (here) a leaf
        assert rack_children[PATH_TARGET_SIBLING_LOC]['has_children'] is False
        # every node carries type_selectable (drives drag-drop drop-target enablement)
        assert target['type_selectable'] is True
        assert roots[PATH_DC_LOC]['type_selectable'] is True

    def test_path_to_root_level_target_returns_the_roots(self, rest_api) -> None:
        """Opening to a root-level location returns just the root level (its children load lazily)."""
        response = rest_api.get(f'{ROUTE_URL}/tree/path/{PATH_DC_LOC}')

        assert response.status_code == HTTPStatus.OK
        roots = self._by_id(response.get_json())
        assert set(roots) == {PATH_DC_LOC, PATH_OFFICE_LOC}
        # the root level is the deepest expanded level; children load lazily
        assert 'children' not in roots[PATH_DC_LOC]
        assert roots[PATH_DC_LOC]['has_children'] is True

    def test_path_to_missing_location_returns_404(self, rest_api) -> None:
        """Opening to a non-existent location returns 404."""
        response = rest_api.get(f'{ROUTE_URL}/tree/path/{MISSING_LOCATION_ID}')

        assert response.status_code == HTTPStatus.NOT_FOUND


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  NAME DERIVATION                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
class TestLocationNameDerivation:
    """A placed object's node is named after the object's rendered summary line."""

    def test_place_derives_the_name_from_object_summary(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """The move carries no name: the new node takes the summary line"""
        _insert_object(database_manager, database_name, DERIVE_POST_OBJECT_ID, SUMMARY_NAME)
        try:
            response = rest_api.patch(f'{ROUTE_URL}/{DERIVE_POST_OBJECT_ID}/parent', json={'parent': ROOT_PARENT_ID})

            assert response.status_code == HTTPStatus.OK
            stored = rest_api.get(f'{ROUTE_URL}/{DERIVE_POST_OBJECT_ID}/object').get_json()
            assert stored['name'] == SUMMARY_NAME
        finally:
            _drop_locations_by_objects(database_manager, database_name, [DERIVE_POST_OBJECT_ID])
            _drop_objects(database_manager, database_name, [DERIVE_POST_OBJECT_ID])


# -------------------------------------------------------------------------------------------------------------------- #
#                                                        MOVE                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class TestMoveObject:
    """PATCH /locations/<object_id>/parent validates the new parent before it writes."""

    def test_move_to_non_selectable_parent_rejected(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """A parent whose type is not selectable-as-parent is 400, and nothing moves"""
        _insert_object(database_manager, database_name, OBJECT_ID_FOR_UPDATE, ORIGINAL_NAME, ROOT_PARENT_ID)
        _insert_location(database_manager, database_name, _location_doc(
            LOCATION_ID_FOR_UPDATE, OBJECT_ID_FOR_UPDATE, ROOT_PARENT_ID,
        ))
        non_selectable = _location_doc(NON_SELECTABLE_PARENT_LOC, NON_SELECTABLE_PARENT_LOC, ROOT_PARENT_ID)
        non_selectable['type_selectable'] = False
        _insert_location(database_manager, database_name, non_selectable)
        try:
            response = rest_api.patch(
                f'{ROUTE_URL}/{OBJECT_ID_FOR_UPDATE}/parent', json={'parent': NON_SELECTABLE_PARENT_LOC},
            )

            assert response.status_code == HTTPStatus.BAD_REQUEST
            assert rest_api.get(f'{ROUTE_URL}/{LOCATION_ID_FOR_UPDATE}').get_json()['parent'] == ROOT_PARENT_ID
            assert _location_field_value(database_manager, database_name, OBJECT_ID_FOR_UPDATE) == ROOT_PARENT_ID
        finally:
            _drop_locations_by_ids(database_manager, database_name,
                                   [LOCATION_ID_FOR_UPDATE, NON_SELECTABLE_PARENT_LOC])
            _drop_objects(database_manager, database_name, [OBJECT_ID_FOR_UPDATE])


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       REMOVE                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
class TestRemovePlacement:
    """PATCH /locations/<object_id>/parent with a null parent removes the placement on both sides."""

    def test_remove_clears_node_and_field(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """The node is gone and the object's location field is null - the mirror holds"""
        _insert_object(database_manager, database_name, OBJECT_ID_FOR_DELETE, ORIGINAL_NAME, ROOT_PARENT_ID)
        _insert_location(database_manager, database_name, _location_doc(
            LOCATION_ID_FOR_DELETE, OBJECT_ID_FOR_DELETE, ROOT_PARENT_ID,
        ))
        try:
            response = rest_api.patch(f'{ROUTE_URL}/{OBJECT_ID_FOR_DELETE}/parent', json={'parent': None})

            assert response.status_code == HTTPStatus.OK
            follow_up = rest_api.get(f'{ROUTE_URL}/{OBJECT_ID_FOR_DELETE}/object')
            assert follow_up.status_code == HTTPStatus.NOT_FOUND
            assert _location_field_value(database_manager, database_name, OBJECT_ID_FOR_DELETE) is None
        finally:
            _drop_locations_by_ids(database_manager, database_name, [LOCATION_ID_FOR_DELETE])
            _drop_objects(database_manager, database_name, [OBJECT_ID_FOR_DELETE])

    def test_the_root_document_is_unreachable(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """The root carries object_id 0, which names no object - so no write reaches it"""
        _insert_location(database_manager, database_name, _location_doc(
            ROOT_LOCATION_ID, ROOT_OBJECT_ID, ROOT_PARENT_ID,
        ))
        try:
            response = rest_api.patch(f'{ROUTE_URL}/{ROOT_OBJECT_ID_SENTINEL}/parent', json={'parent': None})

            assert response.status_code == HTTPStatus.NOT_FOUND
            # the root is untouched and the top-level location still hangs off it
            assert rest_api.get(f'{ROUTE_URL}/{ROOT_PARENT_ID}').status_code == HTTPStatus.OK
            assert rest_api.get(f'{ROUTE_URL}/{ROOT_LOCATION_ID}').get_json()['parent'] == ROOT_PARENT_ID
        finally:
            _drop_locations_by_ids(database_manager, database_name, [ROOT_LOCATION_ID])

    def test_remove_with_children_promotes_them_to_grandparent(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """The children are re-parented onto the removed node's own parent, node and object field alike"""
        _insert_object(database_manager, database_name, ROOT_OBJECT_ID, ORIGINAL_NAME, ROOT_PARENT_ID)
        _insert_object(database_manager, database_name, CHILD_OBJECT_ID, ORIGINAL_NAME, ROOT_LOCATION_ID)
        _insert_location(database_manager, database_name, _location_doc(
            ROOT_LOCATION_ID, ROOT_OBJECT_ID, ROOT_PARENT_ID,
        ))
        _insert_location(database_manager, database_name, _location_doc(
            CHILD_LOCATION_ID, CHILD_OBJECT_ID, ROOT_LOCATION_ID,
        ))
        try:
            response = rest_api.patch(f'{ROUTE_URL}/{ROOT_OBJECT_ID}/parent', json={'parent': None})

            assert response.status_code == HTTPStatus.OK
            # the removed parent location is gone, and its object no longer names a placement
            assert rest_api.get(f'{ROUTE_URL}/{ROOT_OBJECT_ID}/object').status_code == HTTPStatus.NOT_FOUND
            assert _location_field_value(database_manager, database_name, ROOT_OBJECT_ID) is None
            # the child survives, re-parented onto the removed node's own parent (the root)
            child = rest_api.get(f'{ROUTE_URL}/{CHILD_LOCATION_ID}').get_json()
            assert child['parent'] == ROOT_PARENT_ID
            assert _location_field_value(database_manager, database_name, CHILD_OBJECT_ID) == ROOT_PARENT_ID
        finally:
            _drop_locations_by_ids(database_manager, database_name, [ROOT_LOCATION_ID, CHILD_LOCATION_ID])
            _drop_objects(database_manager, database_name, [ROOT_OBJECT_ID, CHILD_OBJECT_ID])


def _raiser(exc: Exception):
    """Returns a function that ignores its args and raises the given exception."""
    def _fail(*_args, **_kwargs):
        raise exc

    return _fail


class TestReadRouteErrorTails:
    """The read routes map an unmapped failure to a 500 rather than letting it escape."""

    def test_tree_search_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unmapped failure while searching the tree."""
        monkeypatch.setattr(LocationsManager, 'search_locations_with_ancestors', _raiser(RuntimeError('boom')))

        response = rest_api.get(f'{ROUTE_URL}/tree/search?query=anything')

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR


class TestReadRouteHttpExceptionPassThrough:
    """
    An HTTPException raised by a collaborator keeps its own status on every read route

    Five of them had no re-raise arm, so an abort from inside would have become a 500. Two of the arms
    are ONLY reachable this way - ``/<id>/children`` never aborts in its own body, and neither does
    ``/<id>/parent`` since a dangling parent stopped being a 404.
    """

    @pytest.mark.parametrize('url, manager_method', [
        ('/', 'iterate_location_documents'),
        ('/tree', 'iterate_location_documents'),
        ('/tree/roots', 'get_child_location_documents'),
        ('/tree/search?query=x', 'search_locations_with_ancestors'),
        ('/tree/1/children', 'get_child_location_documents'),
        (f'/{OBJECT_ID_FOR_GET}/children', 'get_location_for_object'),
        (f'/{OBJECT_ID_FOR_GET}/parent', 'get_location_for_object'),
    ], ids=['list', 'tree', 'tree-roots', 'tree-search', 'tree-children', 'object-children',
            'object-parent'])
    def test_route_keeps_the_status(self, rest_api, monkeypatch, url: str, manager_method: str) -> None:
        """Each route re-raises the HTTPException instead of wrapping it in its own 500."""
        monkeypatch.setattr(LocationsManager, manager_method, _raiser(NotFound()))

        assert rest_api.get(f'{ROUTE_URL}{url}').status_code == HTTPStatus.NOT_FOUND


class TestMoveRouteErrorTails:
    """The two move routes map manager failures and unmapped failures to 400 / 500."""

    def test_move_one_objects_manager_error_returns_400(self, rest_api, monkeypatch) -> None:
        """An ObjectsManagerUpdateError while moving one placement surfaces as 400 (raised by its first step)."""
        monkeypatch.setattr(
            'cmdb.interface.rest_api.routes.framework_routes.cmdb_locations.location_routes'
            '.validate_object_location_move',
            _raiser(ObjectsManagerUpdateError('boom')),
        )

        response = rest_api.patch(f'{ROUTE_URL}/{OBJECT_ID_FOR_GET}/parent', json={'parent': ROOT_PARENT_ID})

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_move_one_locations_manager_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A LocationsManagerUpdateError while moving one placement surfaces as 400."""
        monkeypatch.setattr(
            'cmdb.interface.rest_api.routes.framework_routes.cmdb_locations.location_routes'
            '.validate_object_location_move',
            _raiser(LocationsManagerUpdateError('boom')),
        )

        response = rest_api.patch(f'{ROUTE_URL}/{OBJECT_ID_FOR_GET}/parent', json={'parent': ROOT_PARENT_ID})

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_move_one_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unmapped failure while moving one placement."""
        monkeypatch.setattr(
            'cmdb.interface.rest_api.routes.framework_routes.cmdb_locations.location_routes'
            '.validate_object_location_move',
            _raiser(RuntimeError('boom')),
        )

        response = rest_api.patch(f'{ROUTE_URL}/{OBJECT_ID_FOR_GET}/parent', json={'parent': ROOT_PARENT_ID})

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    @pytest.mark.parametrize('error, expected', [
        (ObjectsManagerGetError('boom'), HTTPStatus.BAD_REQUEST),
        (LocationsManagerGetError('boom'), HTTPStatus.BAD_REQUEST),
        (RuntimeError('boom'), HTTPStatus.INTERNAL_SERVER_ERROR),
    ], ids=['objects-error', 'locations-error', 'unexpected'])
    def test_bulk_move_error_mapping(self, rest_api, monkeypatch, error: Exception, expected: int) -> None:
        """The bulk move maps the same error families as the single move."""
        monkeypatch.setattr(
            'cmdb.interface.rest_api.routes.framework_routes.cmdb_locations.location_routes'
            '.validate_object_location_moves',
            _raiser(error),
        )

        response = rest_api.patch(f'{ROUTE_URL}/parents',
                                  json={'object_ids': [OBJECT_ID_FOR_GET], 'parent': ROOT_PARENT_ID})

        assert response.status_code == expected


class TestParentOfDanglingLocation:
    """"There is no parent" is one answer, so it has one encoding."""

    def test_dangling_parent_answers_200_with_null(self, rest_api, database_manager: MongoDatabaseManager,
                                                   database_name: str) -> None:
        """
        A location whose parent id resolves to nothing answers 200 + null (regression)

        A 404 here, while an object with no location at all answers 200 + null, is the same outcome
        with two encodings, and a data-integrity problem reported as a missing resource.
        """
        collection = database_manager.get_collection(CmdbLocation.COLLECTION, database_name)
        collection.insert_one({
            'public_id': DANGLING_LOCATION_ID, 'object_id': DANGLING_OBJECT_ID,
            'parent': MISSING_PARENT_ID, 'name': 'Dangling', 'type_id': TYPE_ID,
            'type_label': 'T', 'type_icon': 'fas fa-cube', 'type_selectable': True,
        })
        try:
            response = rest_api.get(f'{ROUTE_URL}/{DANGLING_OBJECT_ID}/parent')

            assert response.status_code == HTTPStatus.OK
            assert response.get_json() is None
        finally:
            collection.delete_one({'public_id': DANGLING_LOCATION_ID})
