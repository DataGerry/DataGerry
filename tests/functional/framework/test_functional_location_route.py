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
codes and the JSON envelopes for the CmdbLocation routes - POST create, GET-list, the
``/tree`` forest view, GET-single + 404, the object-scoped ``/<id>/object`` + ``/parent`` +
``/children`` lookups, the PUT update round-trip, and DELETE + follow-up 404. CRUD
correctness itself is asserted at the manager layer; these tests only verify the routes wrap
it correctly.
"""
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.type_model import CmdbType
from cmdb.models.object_model import CmdbObject
from cmdb.models.location_model.cmdb_location import CmdbLocation
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_URL: str = '/locations'

TYPE_ID: int = 9790
TYPE_NAME: str = 'location-smoke-type'
NAME_FIELD: str = 'name-field'
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
OBJECT_ID_FOR_UPDATE: int = 9885

LOCATION_ID_FOR_DELETE: int = 9886
OBJECT_ID_FOR_DELETE: int = 9886

DERIVE_POST_OBJECT_ID: int = 9890
DERIVE_PUT_OBJECT_ID: int = 9891
DERIVE_PUT_LOCATION_ID: int = 9892

MISSING_LOCATION_ID: int = 9898
MISSING_OBJECT_ID: int = 9899

ORIGINAL_NAME: str = 'Original Location'
UPDATED_NAME: str = 'Updated Location'

ALL_LOCATION_IDS: list[int] = [
    LOCATION_ID_FOR_GET, ROOT_LOCATION_ID, CHILD_LOCATION_ID,
    LOCATION_ID_FOR_UPDATE, LOCATION_ID_FOR_DELETE, DERIVE_PUT_LOCATION_ID,
]
ALL_OBJECT_IDS: list[int] = [
    OBJECT_ID_FOR_CREATE, OBJECT_ID_FOR_GET, ROOT_OBJECT_ID, CHILD_OBJECT_ID,
    OBJECT_ID_FOR_UPDATE, OBJECT_ID_FOR_DELETE, DERIVE_POST_OBJECT_ID, DERIVE_PUT_OBJECT_ID,
]
# CmdbObjects seeded as real documents (so the render pipeline can derive a summary line)
REAL_OBJECT_IDS: list[int] = [DERIVE_POST_OBJECT_ID, DERIVE_PUT_OBJECT_ID]


def _type_doc() -> dict[str, Any]:
    """Builds an active CmdbType doc whose presence the location insert route requires."""
    return {
        'public_id': TYPE_ID,
        'name': TYPE_NAME,
        'label': 'Location Smoke Type',
        'author_id': SEED_AUTHOR_ID,
        'creation_time': datetime.now(timezone.utc),
        'active': True,
        'selectable_as_parent': True,
        'fields': [{'type': 'text', 'name': NAME_FIELD, 'label': 'Name'}],
        'render_meta': {
            'icon': 'fa-cube',
            'sections': [{'type': 'section', 'name': 'main', 'label': 'Main', 'fields': [NAME_FIELD]}],
            'summary': {'fields': [NAME_FIELD]},
        },
        'acl': {'activated': False, 'groups': {'includes': None}},
        'version': SEED_VERSION,
    }


def _object_doc(public_id: int, value: str) -> dict[str, Any]:
    """Builds a complete CmdbObject doc whose ``NAME_FIELD`` value drives the rendered summary line."""
    return {
        'public_id': public_id,
        'type_id': TYPE_ID,
        'active': True,
        'author_id': SEED_AUTHOR_ID,
        'version': SEED_VERSION,
        'fields': [{'type': 'text', 'name': NAME_FIELD, 'value': value}],
        'creation_time': datetime.now(timezone.utc),
    }


def _insert_object(database_manager: MongoDatabaseManager, database_name: str, public_id: int, value: str) -> None:
    """Inserts a CmdbObject doc directly via the collection."""
    database_manager.get_collection(CmdbObject.COLLECTION, database_name).insert_one(_object_doc(public_id, value))


def _drop_objects(database_manager: MongoDatabaseManager, database_name: str, public_ids: list[int]) -> None:
    """Removes CmdbObject docs by public_id directly via the collection."""
    database_manager.get_collection(CmdbObject.COLLECTION, database_name)\
        .delete_many({'public_id': {'$in': public_ids}})


def _location_doc(public_id: int, object_id: int, parent: int, name: str = ORIGINAL_NAME) -> dict[str, Any]:
    """Builds a complete CmdbLocation doc for direct DB insertion (bypasses the POST route)."""
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


def _location_payload(object_id: int, parent: int, name: str = ORIGINAL_NAME) -> dict[str, Any]:
    """Builds a POST /locations/ payload (the route derives the rest from the type + object)."""
    return {'object_id': object_id, 'parent': parent, 'type_id': TYPE_ID, 'name': name}


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
    """Removes CmdbLocation docs by object_id directly via the collection (POST uses an auto public_id)."""
    database_manager.get_collection(CmdbLocation.COLLECTION, database_name)\
        .delete_many({'object_id': {'$in': object_ids}})


@pytest.fixture(scope='module', autouse=True)
def _seed_type_and_cleanup(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds the CmdbType used by the insert route and removes the type + all test locations after."""
    database_manager.get_collection(CmdbType.COLLECTION, database_name).insert_one(_type_doc())
    yield
    database_manager.get_collection(CmdbType.COLLECTION, database_name).delete_one({'public_id': TYPE_ID})
    _drop_locations_by_ids(database_manager, database_name, ALL_LOCATION_IDS)
    _drop_locations_by_objects(database_manager, database_name, ALL_OBJECT_IDS)
    _drop_objects(database_manager, database_name, REAL_OBJECT_IDS)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       CREATE                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
class TestPostLocation:
    """POST /locations/ creates a CmdbLocation for the linked object."""

    def test_creates_location_for_object(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """A POST with a valid type + object creates a location retrievable via /<object_id>/object."""
        try:
            response = rest_api.post(
                f'{ROUTE_URL}/',
                json=_location_payload(OBJECT_ID_FOR_CREATE, ROOT_PARENT_ID),
            )

            assert response.status_code == HTTPStatus.OK
            follow_up = rest_api.get(f'{ROUTE_URL}/{OBJECT_ID_FOR_CREATE}/object')
            assert follow_up.status_code == HTTPStatus.OK
            # The object-scoped GET uses DefaultResponse - the body is the bare location dict
            assert follow_up.get_json()['object_id'] == OBJECT_ID_FOR_CREATE
        finally:
            _drop_locations_by_objects(database_manager, database_name, [OBJECT_ID_FOR_CREATE])


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

    def test_get_location_for_object_missing_returns_404(self, rest_api) -> None:
        """GET /locations/<object_id>/object for an object with no location returns 404."""
        response = rest_api.get(f'{ROUTE_URL}/{MISSING_OBJECT_ID}/object')

        assert response.status_code == HTTPStatus.NOT_FOUND


class TestGetLocationTreeAndRelations:
    """The /tree forest view and the object-scoped parent/children lookups."""

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

    def test_tree_view_returns_200_with_results(self, rest_api) -> None:
        """GET /locations/tree returns 200 and a non-empty forest."""
        response = rest_api.get(f'{ROUTE_URL}/tree')

        assert response.status_code == HTTPStatus.OK
        assert response.get_json()['results']

    def test_tree_view_nests_child_under_its_root(self, rest_api) -> None:
        """The seeded child appears nested under its root node in the forest, not at the top level."""
        response = rest_api.get(f'{ROUTE_URL}/tree')

        roots = response.get_json()['results']
        root_node = next(node for node in roots if node['public_id'] == ROOT_LOCATION_ID)
        child_ids = [child['public_id'] for child in root_node.get('children', [])]
        assert CHILD_LOCATION_ID in child_ids

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


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  NAME DERIVATION                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
class TestLocationNameDerivation:
    """An empty name is derived end-to-end from the linked object's rendered summary line."""

    def test_post_with_empty_name_derives_from_object_summary(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """POST with an empty name renders the linked object and stores its summary line as the name."""
        _insert_object(database_manager, database_name, DERIVE_POST_OBJECT_ID, SUMMARY_NAME)
        try:
            response = rest_api.post(
                f'{ROUTE_URL}/',
                json={'object_id': DERIVE_POST_OBJECT_ID, 'parent': ROOT_PARENT_ID, 'type_id': TYPE_ID, 'name': ''},
            )

            assert response.status_code == HTTPStatus.OK
            stored = rest_api.get(f'{ROUTE_URL}/{DERIVE_POST_OBJECT_ID}/object').get_json()
            assert stored['name'] == SUMMARY_NAME
        finally:
            _drop_locations_by_objects(database_manager, database_name, [DERIVE_POST_OBJECT_ID])
            _drop_objects(database_manager, database_name, [DERIVE_POST_OBJECT_ID])

    def test_put_with_empty_name_derives_from_object_summary(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """PUT with an empty name re-derives the name from the linked object's summary line."""
        _insert_object(database_manager, database_name, DERIVE_PUT_OBJECT_ID, SUMMARY_NAME)
        _insert_location(database_manager, database_name, _location_doc(
            DERIVE_PUT_LOCATION_ID, DERIVE_PUT_OBJECT_ID, ROOT_PARENT_ID, name=ORIGINAL_NAME,
        ))
        try:
            response = rest_api.put(
                f'{ROUTE_URL}/update_location',
                json={'object_id': DERIVE_PUT_OBJECT_ID, 'parent': ROOT_PARENT_ID, 'name': ''},
            )

            assert response.status_code == HTTPStatus.ACCEPTED
            stored = rest_api.get(f'{ROUTE_URL}/{DERIVE_PUT_LOCATION_ID}').get_json()
            assert stored['name'] == SUMMARY_NAME
        finally:
            _drop_locations_by_ids(database_manager, database_name, [DERIVE_PUT_LOCATION_ID])
            _drop_objects(database_manager, database_name, [DERIVE_PUT_OBJECT_ID])


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       UPDATE                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
class TestPutLocation:
    """PUT /locations/update_location writes the new params for the object's location."""

    def test_update_persists_new_name(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """After the update a follow-up GET reflects the new name."""
        _insert_location(database_manager, database_name, _location_doc(
            LOCATION_ID_FOR_UPDATE, OBJECT_ID_FOR_UPDATE, ROOT_PARENT_ID,
        ))
        try:
            response = rest_api.put(
                f'{ROUTE_URL}/update_location',
                json={'object_id': OBJECT_ID_FOR_UPDATE, 'parent': ROOT_PARENT_ID, 'name': UPDATED_NAME},
            )

            assert response.status_code == HTTPStatus.ACCEPTED
            # The follow-up GET uses DefaultResponse - the body is the bare location dict
            follow_up = rest_api.get(f'{ROUTE_URL}/{LOCATION_ID_FOR_UPDATE}')
            assert follow_up.get_json()['name'] == UPDATED_NAME
        finally:
            _drop_locations_by_ids(database_manager, database_name, [LOCATION_ID_FOR_UPDATE])


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       DELETE                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
class TestDeleteLocation:
    """DELETE /locations/<object_id>/object removes the location; a follow-up GET reports 404."""

    def test_delete_removes_location(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """A DELETE succeeds and the object's location is then unretrievable."""
        _insert_location(database_manager, database_name, _location_doc(
            LOCATION_ID_FOR_DELETE, OBJECT_ID_FOR_DELETE, ROOT_PARENT_ID,
        ))
        try:
            response = rest_api.delete(f'{ROUTE_URL}/{OBJECT_ID_FOR_DELETE}/object')

            assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED, HTTPStatus.NO_CONTENT)
            follow_up = rest_api.get(f'{ROUTE_URL}/{OBJECT_ID_FOR_DELETE}/object')
            assert follow_up.status_code == HTTPStatus.NOT_FOUND
        finally:
            _drop_locations_by_ids(database_manager, database_name, [LOCATION_ID_FOR_DELETE])

    def test_delete_missing_returns_404(self, rest_api) -> None:
        """A DELETE for an object with no location returns 404."""
        response = rest_api.delete(f'{ROUTE_URL}/{MISSING_OBJECT_ID}/object')

        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_delete_location_with_children_returns_403(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """A location that still has child locations cannot be deleted (403) and survives."""
        _insert_location(database_manager, database_name, _location_doc(
            ROOT_LOCATION_ID, ROOT_OBJECT_ID, ROOT_PARENT_ID,
        ))
        _insert_location(database_manager, database_name, _location_doc(
            CHILD_LOCATION_ID, CHILD_OBJECT_ID, ROOT_LOCATION_ID,
        ))
        try:
            response = rest_api.delete(f'{ROUTE_URL}/{ROOT_OBJECT_ID}/object')

            assert response.status_code == HTTPStatus.FORBIDDEN
            # the parent location still exists
            assert rest_api.get(f'{ROUTE_URL}/{ROOT_OBJECT_ID}/object').status_code == HTTPStatus.OK
        finally:
            _drop_locations_by_ids(database_manager, database_name, [ROOT_LOCATION_ID, CHILD_LOCATION_ID])
