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
Functional smoke for the ``/objects`` REST routes

Covers the route-layer concerns that the ObjectsManager integration suite cannot:
HTTP status codes, the duplicate-insert 400, the not-found 404 on a missing id, the
JSON envelope returned by GET-list, the PUT update round-trip, the DELETE 200 +
follow-up 404, and the bulk-update flow via the ``objectIDs`` query param. The CRUD
behavior itself is asserted at the manager layer; these tests only verify the route
wraps it correctly
"""
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import ObjectsManager, TypesManager
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType
from cmdb.models.location_model.cmdb_location import CmdbLocation
from cmdb.errors.manager.objects_manager import (
    ObjectsManagerGetError,
    ObjectsManagerIterationError,
    ObjectsManagerDeleteError,
    ObjectsManagerUpdateError,
    ObjectsManagerInsertError,
)
from cmdb.errors.manager.types_manager import TypesManagerGetError
from cmdb.errors.security import AccessDeniedError
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_URL: str = '/objects'

TYPE_ID: int = 9401
TYPE_NAME: str = 'route-smoke-type'
NAME_FIELD: str = 'name-field'

OBJECT_ID_FOR_CREATE: int = 9411
OBJECT_ID_FOR_GET: int = 9412
OBJECT_ID_FOR_UPDATE: int = 9413
OBJECT_ID_FOR_DELETE: int = 9414
OBJECT_ID_FOR_PATCH: int = 9415
BULK_OBJECT_IDS: list[int] = [9421, 9422, 9423]
MISSING_OBJECT_ID: int = 9499

ALL_OBJECT_IDS: list[int] = [
    OBJECT_ID_FOR_CREATE,
    OBJECT_ID_FOR_GET,
    OBJECT_ID_FOR_UPDATE,
    OBJECT_ID_FOR_DELETE,
    OBJECT_ID_FOR_PATCH,
] + BULK_OBJECT_IDS

ORIGINAL_VALUE: str = 'original'
UPDATED_VALUE: str = 'updated'
BULK_UPDATED_VALUE: str = 'bulk-updated'

SEED_VERSION: str = '1.0.0'
UPDATE_VERSION: str = '1.0.1'
SEED_AUTHOR_ID: int = 1
# public_id of the authenticated user behind the rest_api fixture (full_access_user); the update
# pipeline stamps this as the object's editor_id
REQUEST_USER_ID: int = 1


def _type_doc() -> dict[str, Any]:
    """Builds an active CmdbType doc whose presence the route insert/update paths require.

    The section referencing NAME_FIELD is required: the PUT route reconstructs the
    object's field list from the render result, which itself walks the type's
    render_meta.sections — fields not surfaced by a section are silently dropped.
    """
    return {
        'public_id': TYPE_ID,
        'name': TYPE_NAME,
        'label': 'Route Smoke Type',
        'author_id': SEED_AUTHOR_ID,
        'creation_time': datetime.now(timezone.utc),
        'active': True,
        'fields': [{'type': 'text', 'name': NAME_FIELD, 'label': 'Name'}],
        'render_meta': {
            'icon': 'fa-cube',
            'sections': [{'type': 'section', 'name': 'main', 'label': 'Main', 'fields': [NAME_FIELD]}],
            'summary': {'fields': [NAME_FIELD]},
        },
        'acl': {'activated': False, 'groups': {'includes': None}},
        'version': SEED_VERSION,
    }


def _object_payload(public_id: int, value: str) -> dict[str, Any]:
    """Builds a CmdbObject-shaped payload acceptable to POST /objects/ and PUT /objects/<id>."""
    return {
        'public_id': public_id,
        'type_id': TYPE_ID,
        'active': True,
        'author_id': SEED_AUTHOR_ID,
        'version': SEED_VERSION,
        'fields': [{'type': 'text', 'name': NAME_FIELD, 'value': value}],
    }


def _object_doc(public_id: int, value: str) -> dict[str, Any]:
    """Builds a complete CmdbObject doc for direct DB insertion (bypasses route validation)."""
    payload = _object_payload(public_id, value)
    payload['creation_time'] = datetime.now(timezone.utc)
    return payload


@pytest.fixture(scope='module', autouse=True)
def _seed_type_and_cleanup(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds the CmdbType used by every test and removes the type + all test objects after."""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    types.insert_one(_type_doc())
    yield
    types.delete_one({'public_id': TYPE_ID})
    objects.delete_many({'public_id': {'$in': ALL_OBJECT_IDS}})


def _drop_object(database_manager: MongoDatabaseManager, database_name: str, public_id: int) -> None:
    """Removes a single CmdbObject doc directly via the collection, for per-test cleanup."""
    database_manager.get_collection(CmdbObject.COLLECTION, database_name).delete_one({'public_id': public_id})


def _insert_object_doc(database_manager: MongoDatabaseManager, database_name: str, public_id: int, value: str) -> None:
    """Inserts a CmdbObject doc directly via the collection, bypassing the POST route validation."""
    database_manager.get_collection(CmdbObject.COLLECTION, database_name).insert_one(_object_doc(public_id, value))


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       CREATE                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class TestPostObject:
    """POST /objects/ creates a new CmdbObject and rejects a duplicate id with 400."""

    def test_creates_new_object(
        self,
        rest_api,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """A POST with a fresh public_id returns 200 and the object is queryable afterwards."""
        try:
            response = rest_api.post(f'{ROUTE_URL}/', json=_object_payload(OBJECT_ID_FOR_CREATE, ORIGINAL_VALUE))

            assert response.status_code == HTTPStatus.OK
            follow_up = rest_api.get(f'{ROUTE_URL}/native/{OBJECT_ID_FOR_CREATE}')
            assert follow_up.status_code == HTTPStatus.OK
        finally:
            _drop_object(database_manager, database_name, OBJECT_ID_FOR_CREATE)

    def test_duplicate_public_id_returns_400(
        self,
        rest_api,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """A POST whose public_id already exists is rejected with 400."""
        try:
            first = rest_api.post(f'{ROUTE_URL}/', json=_object_payload(OBJECT_ID_FOR_CREATE, ORIGINAL_VALUE))
            assert first.status_code == HTTPStatus.OK

            duplicate = rest_api.post(f'{ROUTE_URL}/', json=_object_payload(OBJECT_ID_FOR_CREATE, ORIGINAL_VALUE))

            assert duplicate.status_code == HTTPStatus.BAD_REQUEST
        finally:
            _drop_object(database_manager, database_name, OBJECT_ID_FOR_CREATE)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       READ                                                           #
# -------------------------------------------------------------------------------------------------------------------- #
class TestGetObject:
    """GET /objects/native/<id> and GET /objects/ return the expected envelopes."""

    @pytest.fixture(autouse=True)
    def _seed(self, database_manager: MongoDatabaseManager, database_name: str):
        """Inserts one object directly via the DB before each test and removes it after."""
        _insert_object_doc(database_manager, database_name, OBJECT_ID_FOR_GET, ORIGINAL_VALUE)
        yield
        _drop_object(database_manager, database_name, OBJECT_ID_FOR_GET)

    def test_get_single_returns_object(self, rest_api) -> None:
        """A GET /objects/native/<id> for a seeded object returns 200 and a parseable payload."""
        response = rest_api.get(f'{ROUTE_URL}/native/{OBJECT_ID_FOR_GET}')

        assert response.status_code == HTTPStatus.OK
        parsed = CmdbObject.from_data(response.get_json())
        assert parsed.public_id == OBJECT_ID_FOR_GET

    def test_get_single_missing_returns_404(self, rest_api) -> None:
        """A GET /objects/native/<id> for a missing id returns 404."""
        response = rest_api.get(f'{ROUTE_URL}/native/{MISSING_OBJECT_ID}')

        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_get_list_returns_results_and_total(self, rest_api) -> None:
        """A GET /objects/ returns a JSON envelope whose results length matches X-Total-Count."""
        response = rest_api.get(f'{ROUTE_URL}/')

        assert response.status_code == HTTPStatus.OK
        body = response.get_json()
        assert 'results' in body
        assert len(body['results']) == int(response.headers['X-Total-Count'])


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       UPDATE                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class TestPutObject:
    """PUT /objects/<id> updates the doc and stamps last_edit_time / editor_id."""

    def test_update_persists_changes_and_sets_last_edit_time(
        self,
        rest_api,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """After PUT, the object's field value reflects the new payload and last_edit_time is populated."""
        _insert_object_doc(database_manager, database_name, OBJECT_ID_FOR_UPDATE, ORIGINAL_VALUE)
        try:
            updated_payload = _object_payload(OBJECT_ID_FOR_UPDATE, UPDATED_VALUE)
            updated_payload['version'] = UPDATE_VERSION

            response = rest_api.put(f'{ROUTE_URL}/{OBJECT_ID_FOR_UPDATE}', json=updated_payload)
            assert response.status_code == HTTPStatus.ACCEPTED

            follow_up = rest_api.get(f'{ROUTE_URL}/native/{OBJECT_ID_FOR_UPDATE}')
            stored = CmdbObject.from_data(follow_up.get_json())
            assert stored.last_edit_time is not None
            stored_value = next(field['value'] for field in stored.fields if field['name'] == NAME_FIELD)
            assert stored_value == UPDATED_VALUE
        finally:
            _drop_object(database_manager, database_name, OBJECT_ID_FOR_UPDATE)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  PARTIAL UPDATE                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
class TestPatchObject:
    """PATCH /objects/<id> partially updates a single object and rejects disallowed keys."""

    def test_patch_updates_listed_field(
        self,
        rest_api,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """A PATCH with a fields subset changes that value and stamps last_edit_time."""
        _insert_object_doc(database_manager, database_name, OBJECT_ID_FOR_PATCH, ORIGINAL_VALUE)
        try:
            response = rest_api.patch(
                f'{ROUTE_URL}/{OBJECT_ID_FOR_PATCH}',
                json={'fields': [{'name': NAME_FIELD, 'value': UPDATED_VALUE}]},
            )
            assert response.status_code == HTTPStatus.ACCEPTED

            follow_up = rest_api.get(f'{ROUTE_URL}/native/{OBJECT_ID_FOR_PATCH}')
            stored = CmdbObject.from_data(follow_up.get_json())
            assert stored.last_edit_time is not None
            stored_value = next(field['value'] for field in stored.fields if field['name'] == NAME_FIELD)
            assert stored_value == UPDATED_VALUE
        finally:
            _drop_object(database_manager, database_name, OBJECT_ID_FOR_PATCH)

    def test_patch_rejects_immutable_key_and_leaves_object_unchanged(
        self,
        rest_api,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """A PATCH carrying an immutable key (type_id) is rejected 400 and nothing is written."""
        _insert_object_doc(database_manager, database_name, OBJECT_ID_FOR_PATCH, ORIGINAL_VALUE)
        try:
            response = rest_api.patch(
                f'{ROUTE_URL}/{OBJECT_ID_FOR_PATCH}',
                json={'type_id': 9999, 'fields': [{'name': NAME_FIELD, 'value': UPDATED_VALUE}]},
            )
            assert response.status_code == HTTPStatus.BAD_REQUEST

            follow_up = rest_api.get(f'{ROUTE_URL}/native/{OBJECT_ID_FOR_PATCH}')
            stored = CmdbObject.from_data(follow_up.get_json())
            stored_value = next(field['value'] for field in stored.fields if field['name'] == NAME_FIELD)
            assert stored_value == ORIGINAL_VALUE
        finally:
            _drop_object(database_manager, database_name, OBJECT_ID_FOR_PATCH)

    def test_patch_missing_object_returns_404(self, rest_api) -> None:
        """A PATCH for an unknown object id returns 404 after the payload validates."""
        response = rest_api.patch(
            f'{ROUTE_URL}/{MISSING_OBJECT_ID}',
            json={'fields': [{'name': NAME_FIELD, 'value': UPDATED_VALUE}]},
        )

        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_patch_bumps_version_from_field_diff(
        self,
        rest_api,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """Changing the single field of a one-field object bumps the version 1.0.0 -> 1.0.1 (patch)."""
        _insert_object_doc(database_manager, database_name, OBJECT_ID_FOR_PATCH, ORIGINAL_VALUE)
        try:
            response = rest_api.patch(
                f'{ROUTE_URL}/{OBJECT_ID_FOR_PATCH}',
                json={'fields': [{'name': NAME_FIELD, 'value': UPDATED_VALUE}]},
            )
            assert response.status_code == HTTPStatus.ACCEPTED

            follow_up = rest_api.get(f'{ROUTE_URL}/native/{OBJECT_ID_FOR_PATCH}')
            stored = CmdbObject.from_data(follow_up.get_json())
            assert stored.version == UPDATE_VERSION
        finally:
            _drop_object(database_manager, database_name, OBJECT_ID_FOR_PATCH)

    def test_patch_stamps_editor_id_to_request_user(
        self,
        rest_api,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """PATCH stamps editor_id with the requesting user, exactly like the PUT pipeline."""
        _insert_object_doc(database_manager, database_name, OBJECT_ID_FOR_PATCH, ORIGINAL_VALUE)
        try:
            response = rest_api.patch(
                f'{ROUTE_URL}/{OBJECT_ID_FOR_PATCH}',
                json={'fields': [{'name': NAME_FIELD, 'value': UPDATED_VALUE}]},
            )
            assert response.status_code == HTTPStatus.ACCEPTED

            follow_up = rest_api.get(f'{ROUTE_URL}/native/{OBJECT_ID_FOR_PATCH}')
            stored = CmdbObject.from_data(follow_up.get_json())
            assert stored.editor_id == REQUEST_USER_ID
        finally:
            _drop_object(database_manager, database_name, OBJECT_ID_FOR_PATCH)

    def test_patch_empty_payload_returns_400(self, rest_api) -> None:
        """A PATCH that carries no changing key is rejected 400 before any object is fetched."""
        response = rest_api.patch(f'{ROUTE_URL}/{OBJECT_ID_FOR_PATCH}', json={})

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_patch_comment_only_returns_400(self, rest_api) -> None:
        """A comment does not count as a change, so a comment-only PATCH is rejected 400."""
        response = rest_api.patch(f'{ROUTE_URL}/{OBJECT_ID_FOR_PATCH}', json={'comment': 'nothing to change'})

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_patch_non_object_body_returns_400(self, rest_api) -> None:
        """A PATCH body that is valid JSON but not an object (a list) is rejected 400."""
        response = rest_api.patch(f'{ROUTE_URL}/{OBJECT_ID_FOR_PATCH}', json=[{'name': NAME_FIELD, 'value': 1}])

        assert response.status_code == HTTPStatus.BAD_REQUEST


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       DELETE                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class TestDeleteObject:
    """DELETE /objects/<id> removes the doc; a follow-up GET reports 404."""

    def test_delete_removes_object(
        self,
        rest_api,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """A DELETE succeeds, and a subsequent GET for the same id returns 404."""
        _insert_object_doc(database_manager, database_name, OBJECT_ID_FOR_DELETE, ORIGINAL_VALUE)
        try:
            response = rest_api.delete(f'{ROUTE_URL}/{OBJECT_ID_FOR_DELETE}')

            assert response.status_code == HTTPStatus.OK
            follow_up = rest_api.get(f'{ROUTE_URL}/native/{OBJECT_ID_FOR_DELETE}')
            assert follow_up.status_code == HTTPStatus.NOT_FOUND
        finally:
            _drop_object(database_manager, database_name, OBJECT_ID_FOR_DELETE)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                BULK UPDATE                                                           #
# -------------------------------------------------------------------------------------------------------------------- #
class TestBulkUpdateObjects:
    """PUT /objects/<id>?objectIDs=… applies the payload to every listed object."""

    @pytest.fixture(autouse=True)
    def _seed_three(self, database_manager: MongoDatabaseManager, database_name: str):
        """Inserts three objects with distinct values and removes them after the test."""
        for public_id in BULK_OBJECT_IDS:
            _insert_object_doc(database_manager, database_name, public_id, f'initial-{public_id}')
        yield
        for public_id in BULK_OBJECT_IDS:
            _drop_object(database_manager, database_name, public_id)

    def test_bulk_update_writes_payload_to_each_target(self, rest_api) -> None:
        """Each id listed in ``objectIDs`` ends up with the field value from the request body."""
        payload = _object_payload(BULK_OBJECT_IDS[0], BULK_UPDATED_VALUE)
        payload['version'] = UPDATE_VERSION

        response = rest_api.put(
            f'{ROUTE_URL}/{BULK_OBJECT_IDS[0]}',
            json=payload,
            query_string={'objectIDs': BULK_OBJECT_IDS},
        )

        assert response.status_code == HTTPStatus.ACCEPTED
        for public_id in BULK_OBJECT_IDS:
            follow_up = rest_api.get(f'{ROUTE_URL}/native/{public_id}')
            assert follow_up.status_code == HTTPStatus.OK
            stored = CmdbObject.from_data(follow_up.get_json())
            stored_value = next(field['value'] for field in stored.fields if field['name'] == NAME_FIELD)
            assert stored_value == BULK_UPDATED_VALUE


# -------------------------------------------------------------------------------------------------------------------- #
#                                            MISSING-OBJECT 404s                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
class TestMissingObjectReturns404:
    """state and references routes must answer 404 (not 500) for an unknown object id."""

    def test_state_of_missing_object_returns_404(self, rest_api) -> None:
        """GET /objects/state/<missing> returns 404 instead of crashing into a 500."""
        response = rest_api.get(f'{ROUTE_URL}/state/{MISSING_OBJECT_ID}')

        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_references_of_missing_object_returns_404(self, rest_api) -> None:
        """GET /objects/references/<missing> returns 404 instead of passing None into from_data."""
        response = rest_api.get(f'{ROUTE_URL}/references/{MISSING_OBJECT_ID}')

        assert response.status_code == HTTPStatus.NOT_FOUND


# -------------------------------------------------------------------------------------------------------------------- #
#                                      DELETE WITH CHILD OBJECTS                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
PARENT_OBJECT_ID: int = 9425
CHILD_OBJECT_ID: int = 9426
PARENT_LOCATION_ID: int = 9431
CHILD_LOCATION_ID: int = 9432


# -------------------------------------------------------------------------------------------------------------------- #
#                                        GAP-FILL: shared helpers + ids                                               #
# -------------------------------------------------------------------------------------------------------------------- #
EXTRA_FIELD: str = 'extra-field'

RENDERED_GET_ID: int = 9440
COUNT_DELTA_ID: int = 9441
COUNT_TYPE_IDS: list[int] = [9442, 9443]
MDS_REF_ID: int = 9444
CLEAN_PROBE_CLEAN_ID: int = 9445
CLEAN_PROBE_DIRTY_ID: int = 9446
STATE_TOGGLE_ID: int = 9447
STATE_NOOP_ID: int = 9448
STATE_NONBOOL_ID: int = 9449
STATE_GET_ACTIVE_ID: int = 9450
STATE_GET_INACTIVE_ID: int = 9451
REFERENCES_HAPPY_ID: int = 9452
LOC_PARENT_OBJECT_ID: int = 9453
LOC_CHILD_OBJECT_ID: int = 9454
DELETE_MANY_IDS: list[int] = [9455, 9456]
DELETE_MANY_LOCATED_ID: int = 9457
DELETE_MANY_CHILD_OBJECT_ID: int = 9458
DELETE_MANY_CHILD_LOCATION_ID: int = 9459

ROOT_LOCATION_ID: int = 1  # the synthetic location-tree root; a top-level node's parent

LOCATIONS_KEEP_PARENT_LOC: int = 9481
LOCATIONS_KEEP_CHILD_LOC: int = 9482

# Dedicated ids for the "child object keeps but its dg_location reference is cleared" case
LOC_CLEAR_PARENT_OBJECT_ID: int = 9461
LOC_CLEAR_CHILD_OBJECT_ID: int = 9462
LOC_CLEAR_PARENT_LOC: int = 9483
LOC_CLEAR_CHILD_LOC: int = 9484
LOCATION_FIELD_NAME: str = 'dg_location'
DELETE_MANY_LOCATION_ID: int = 9483

# A second type carrying a ref field that points at TYPE_ID, used to exercise the references route
REF_TYPE_ID: int = 9402
REF_FIELD: str = 'ref-field'
REF_TARGET_OBJECT_ID: int = 9460
REF_SOURCE_OBJECT_ID: int = 9461


def _ref_type_doc() -> dict[str, Any]:
    """Builds a CmdbType doc whose single field is a ref pointing at TYPE_ID."""
    return {
        'public_id': REF_TYPE_ID,
        'name': f'ref-type-{REF_TYPE_ID}',
        'label': 'Ref Type',
        'author_id': SEED_AUTHOR_ID,
        'active': True,
        'fields': [{'type': 'ref', 'name': REF_FIELD, 'label': 'Ref', 'ref_types': [TYPE_ID]}],
        'render_meta': {
            'icon': 'fa-cube',
            'sections': [{'type': 'section', 'name': 'main', 'label': 'Main', 'fields': [REF_FIELD]}],
            'summary': {'fields': [REF_FIELD]},
        },
        'acl': {'activated': False, 'groups': {'includes': None}},
        'version': SEED_VERSION,
        'creation_time': datetime.now(timezone.utc),
    }


def _referencing_object_doc(public_id: int, target_id: int) -> dict[str, Any]:
    """Builds a CmdbObject of REF_TYPE_ID whose ref field points at the given target object id."""
    return {
        'public_id': public_id,
        'type_id': REF_TYPE_ID,
        'active': True,
        'author_id': SEED_AUTHOR_ID,
        'version': SEED_VERSION,
        'fields': [{'type': 'ref', 'name': REF_FIELD, 'value': target_id}],
        'creation_time': datetime.now(timezone.utc),
    }


# A type whose ref field lives inside a multi-data section, to exercise the MDS reference path
MDS_REF_TYPE_ID: int = 9403
MDS_REF_FIELD: str = 'mds-ref'
MDS_REF_TARGET_ID: int = 9462
MDS_REF_SOURCE_ID: int = 9463


def _mds_ref_type_doc() -> dict[str, Any]:
    """Builds a CmdbType whose ref field (pointing at TYPE_ID) is part of a multi-data section."""
    return {
        'public_id': MDS_REF_TYPE_ID,
        'name': f'mds-ref-type-{MDS_REF_TYPE_ID}',
        'label': 'MDS Ref Type',
        'author_id': SEED_AUTHOR_ID,
        'active': True,
        'fields': [{'type': 'ref', 'name': MDS_REF_FIELD, 'label': 'MDS Ref', 'ref_types': [TYPE_ID]}],
        'render_meta': {
            'icon': 'fa-cube',
            'sections': [{
                'type': 'multi-data-section', 'name': 'mds-section', 'label': 'MDS', 'fields': [MDS_REF_FIELD],
            }],
            'summary': {'fields': []},
        },
        'acl': {'activated': False, 'groups': {'includes': None}},
        'version': SEED_VERSION,
        'creation_time': datetime.now(timezone.utc),
    }


def _mds_referencing_object_doc(public_id: int, target_id: int) -> dict[str, Any]:
    """Builds a CmdbObject whose multi-data-section row holds a ref field pointing at target_id."""
    return {
        'public_id': public_id,
        'type_id': MDS_REF_TYPE_ID,
        'active': True,
        'author_id': SEED_AUTHOR_ID,
        'version': SEED_VERSION,
        'fields': [],
        'multi_data_sections': [{
            'section_id': 'mds-section',
            'values': [{
                'multi_data_id': 1,
                'data': [{'type': 'ref', 'name': MDS_REF_FIELD, 'value': target_id}],
            }],
        }],
        'creation_time': datetime.now(timezone.utc),
    }


def _dirty_object_doc(public_id: int) -> dict[str, Any]:
    """A CmdbObject doc carrying an extra field the type does not declare (structurally dirty)."""
    doc = _object_doc(public_id, ORIGINAL_VALUE)
    doc['fields'].append({'type': 'text', 'name': EXTRA_FIELD, 'value': 'x'})
    return doc


def _inactive_object_doc(public_id: int) -> dict[str, Any]:
    """A CmdbObject doc with active=False, for the state read/toggle tests."""
    doc = _object_doc(public_id, ORIGINAL_VALUE)
    doc['active'] = False
    return doc


def _insert_location(
    database_manager: MongoDatabaseManager,
    database_name: str,
    location_id: int,
    object_id: int,
    parent: int,
) -> None:
    """Inserts a CmdbLocation doc linking the given object under the given parent location id."""
    database_manager.get_collection(CmdbLocation.COLLECTION, database_name).insert_one({
        'public_id': location_id, 'name': f'loc-{location_id}', 'parent': parent,
        'object_id': object_id, 'type_id': TYPE_ID, 'type_label': TYPE_NAME,
    })


def _location_exists(database_manager: MongoDatabaseManager, database_name: str, location_id: int) -> bool:
    """True when a CmdbLocation with the given public_id is still present."""
    collection = database_manager.get_collection(CmdbLocation.COLLECTION, database_name)
    return collection.find_one({'public_id': location_id}) is not None


def _location_parent(database_manager: MongoDatabaseManager, database_name: str, location_id: int) -> int | None:
    """Returns the parent id of the CmdbLocation with the given public_id, or None when missing."""
    collection = database_manager.get_collection(CmdbLocation.COLLECTION, database_name)
    location = collection.find_one({'public_id': location_id})
    return location['parent'] if location else None


# -------------------------------------------------------------------------------------------------------------------- #
#                                        READ: rendered single + counts                                               #
# -------------------------------------------------------------------------------------------------------------------- #
class TestGetRenderedObject:
    """GET /objects/<id> returns the rendered single-object representation."""

    def test_get_rendered_single_object(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """A GET for a seeded object returns 200 and a body carrying its object_id."""
        _insert_object_doc(database_manager, database_name, RENDERED_GET_ID, ORIGINAL_VALUE)
        try:
            response = rest_api.get(f'{ROUTE_URL}/{RENDERED_GET_ID}')

            assert response.status_code == HTTPStatus.OK
            assert str(RENDERED_GET_ID) in response.get_data(as_text=True)
        finally:
            _drop_object(database_manager, database_name, RENDERED_GET_ID)

    def test_get_rendered_missing_returns_404(self, rest_api) -> None:
        """A GET for a missing id returns 404."""
        assert rest_api.get(f'{ROUTE_URL}/{MISSING_OBJECT_ID}').status_code == HTTPStatus.NOT_FOUND


class TestObjectCounts:
    """GET /objects/count and /objects/count/<type_id> return increasing integer counts."""

    def test_global_count_increases_after_insert(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """Inserting one object raises the global count by exactly one."""
        before = rest_api.get(f'{ROUTE_URL}/count').get_json()
        _insert_object_doc(database_manager, database_name, COUNT_DELTA_ID, ORIGINAL_VALUE)
        try:
            after = rest_api.get(f'{ROUTE_URL}/count')
            assert after.status_code == HTTPStatus.OK
            assert after.get_json() == before + 1
        finally:
            _drop_object(database_manager, database_name, COUNT_DELTA_ID)

    def test_count_for_type_increases_by_inserted(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """The per-type count rises by the number of objects inserted for that type."""
        before = rest_api.get(f'{ROUTE_URL}/count/{TYPE_ID}').get_json()
        for public_id in COUNT_TYPE_IDS:
            _insert_object_doc(database_manager, database_name, public_id, ORIGINAL_VALUE)
        try:
            after = rest_api.get(f'{ROUTE_URL}/count/{TYPE_ID}')
            assert after.status_code == HTTPStatus.OK
            assert after.get_json() == before + len(COUNT_TYPE_IDS)
        finally:
            for public_id in COUNT_TYPE_IDS:
                _drop_object(database_manager, database_name, public_id)


# -------------------------------------------------------------------------------------------------------------------- #
#                                        READ: MDS references + dirty probe                                            #
# -------------------------------------------------------------------------------------------------------------------- #
class TestMdsReferenceRoutes:
    """GET /objects/<id>/mds_reference[s] render the MDS reference summary for an object."""

    def test_single_mds_reference(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """A seeded object returns 200 for its MDS reference summary."""
        _insert_object_doc(database_manager, database_name, MDS_REF_ID, ORIGINAL_VALUE)
        try:
            assert rest_api.get(f'{ROUTE_URL}/{MDS_REF_ID}/mds_reference').status_code == HTTPStatus.OK
        finally:
            _drop_object(database_manager, database_name, MDS_REF_ID)

    def test_single_mds_reference_missing_returns_404(self, rest_api) -> None:
        """A missing object returns 404 for the MDS reference summary."""
        assert rest_api.get(f'{ROUTE_URL}/{MISSING_OBJECT_ID}/mds_reference').status_code == HTTPStatus.NOT_FOUND

    def test_multi_mds_references_keyed_by_id(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """The multi route returns 200 and a mapping that includes the requested id."""
        _insert_object_doc(database_manager, database_name, MDS_REF_ID, ORIGINAL_VALUE)
        try:
            response = rest_api.get(f'{ROUTE_URL}/{MDS_REF_ID}/mds_references')

            assert response.status_code == HTTPStatus.OK
            assert str(MDS_REF_ID) in response.get_json()
        finally:
            _drop_object(database_manager, database_name, MDS_REF_ID)


class TestUnstructuredObjectsProbe:
    """GET /objects/clean/<type_id> reports how many objects no longer match the type fields."""

    def test_probe_counts_only_dirty_objects(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """With one clean and one dirty object, the probe's X-Total-Count is 1."""
        _insert_object_doc(database_manager, database_name, CLEAN_PROBE_CLEAN_ID, ORIGINAL_VALUE)
        database_manager.get_collection(CmdbObject.COLLECTION, database_name).insert_one(
            _dirty_object_doc(CLEAN_PROBE_DIRTY_ID)
        )
        try:
            response = rest_api.get(f'{ROUTE_URL}/clean/{TYPE_ID}')

            assert response.status_code == HTTPStatus.OK
            assert int(response.headers['X-Total-Count']) == 1
        finally:
            _drop_object(database_manager, database_name, CLEAN_PROBE_CLEAN_ID)
            _drop_object(database_manager, database_name, CLEAN_PROBE_DIRTY_ID)


# -------------------------------------------------------------------------------------------------------------------- #
#                                        READ + UPDATE: active state                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
class TestObjectState:
    """GET/PUT /objects/state/<id> read and toggle the active flag."""

    def test_get_state_reflects_active_flag(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """The state GET returns True for an active object and False for an inactive one."""
        _insert_object_doc(database_manager, database_name, STATE_GET_ACTIVE_ID, ORIGINAL_VALUE)
        database_manager.get_collection(CmdbObject.COLLECTION, database_name).insert_one(
            _inactive_object_doc(STATE_GET_INACTIVE_ID)
        )
        try:
            assert rest_api.get(f'{ROUTE_URL}/state/{STATE_GET_ACTIVE_ID}').get_json() is True
            assert rest_api.get(f'{ROUTE_URL}/state/{STATE_GET_INACTIVE_ID}').get_json() is False
        finally:
            _drop_object(database_manager, database_name, STATE_GET_ACTIVE_ID)
            _drop_object(database_manager, database_name, STATE_GET_INACTIVE_ID)

    def test_put_state_toggles_active_flag(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """Toggling an active object to False is accepted (202) and reflected on a follow-up read."""
        _insert_object_doc(database_manager, database_name, STATE_TOGGLE_ID, ORIGINAL_VALUE)
        try:
            response = rest_api.put(f'{ROUTE_URL}/state/{STATE_TOGGLE_ID}', json=False)

            assert response.status_code == HTTPStatus.ACCEPTED
            assert rest_api.get(f'{ROUTE_URL}/state/{STATE_TOGGLE_ID}').get_json() is False
        finally:
            _drop_object(database_manager, database_name, STATE_TOGGLE_ID)

    def test_put_state_unchanged_returns_false(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """Setting the state to its current value is a no-op that returns False with 200."""
        _insert_object_doc(database_manager, database_name, STATE_NOOP_ID, ORIGINAL_VALUE)
        try:
            response = rest_api.put(f'{ROUTE_URL}/state/{STATE_NOOP_ID}', json=True)

            assert response.status_code == HTTPStatus.OK
            assert response.get_json() is False
        finally:
            _drop_object(database_manager, database_name, STATE_NOOP_ID)

    def test_put_state_non_boolean_returns_400(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """A non-boolean state body is rejected with 400."""
        _insert_object_doc(database_manager, database_name, STATE_NONBOOL_ID, ORIGINAL_VALUE)
        try:
            response = rest_api.put(f'{ROUTE_URL}/state/{STATE_NONBOOL_ID}', json='not-a-bool')

            assert response.status_code == HTTPStatus.BAD_REQUEST
        finally:
            _drop_object(database_manager, database_name, STATE_NONBOOL_ID)


# -------------------------------------------------------------------------------------------------------------------- #
#                                        READ: references happy path                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
class TestObjectReferencesHappyPath:
    """GET /objects/references/<id> returns a paged envelope for an existing object."""

    def test_references_of_existing_object_returns_envelope(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """An object with no referrers returns 200 and an empty results list (not a 500/404)."""
        _insert_object_doc(database_manager, database_name, REFERENCES_HAPPY_ID, ORIGINAL_VALUE)
        try:
            response = rest_api.get(f'{ROUTE_URL}/references/{REFERENCES_HAPPY_ID}')

            assert response.status_code == HTTPStatus.OK
            body = response.get_json()
            assert 'results' in body
            assert body['results'] == []
        finally:
            _drop_object(database_manager, database_name, REFERENCES_HAPPY_ID)

    def test_references_returns_referencing_object(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """An object pointed at by another object's ref field appears in its references list."""
        types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
        objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
        types.insert_one(_ref_type_doc())
        objects.insert_one(_object_doc(REF_TARGET_OBJECT_ID, ORIGINAL_VALUE))
        objects.insert_one(_referencing_object_doc(REF_SOURCE_OBJECT_ID, REF_TARGET_OBJECT_ID))
        try:
            response = rest_api.get(f'{ROUTE_URL}/references/{REF_TARGET_OBJECT_ID}')

            assert response.status_code == HTTPStatus.OK
            result_ids = [result['public_id'] for result in response.get_json()['results']]
            assert REF_SOURCE_OBJECT_ID in result_ids
        finally:
            objects.delete_many({'public_id': {'$in': [REF_TARGET_OBJECT_ID, REF_SOURCE_OBJECT_ID]}})
            types.delete_one({'public_id': REF_TYPE_ID})

    def test_references_returns_mds_referencing_object(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """An object referencing the target via a multi-data-section ref field is also returned."""
        types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
        objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
        types.insert_one(_mds_ref_type_doc())
        objects.insert_one(_object_doc(MDS_REF_TARGET_ID, ORIGINAL_VALUE))
        objects.insert_one(_mds_referencing_object_doc(MDS_REF_SOURCE_ID, MDS_REF_TARGET_ID))
        try:
            response = rest_api.get(f'{ROUTE_URL}/references/{MDS_REF_TARGET_ID}')

            assert response.status_code == HTTPStatus.OK
            result_ids = [result['public_id'] for result in response.get_json()['results']]
            assert MDS_REF_SOURCE_ID in result_ids
        finally:
            objects.delete_many({'public_id': {'$in': [MDS_REF_TARGET_ID, MDS_REF_SOURCE_ID]}})
            types.delete_one({'public_id': MDS_REF_TYPE_ID})


# -------------------------------------------------------------------------------------------------------------------- #
#                                                DELETE: bulk delete                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
class TestDeleteManyObjects:
    """DELETE /objects/delete/<ids> bulk-deletes objects, re-parenting the children of located ones."""

    def test_bulk_delete_removes_all_targets(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """Every listed (location-free) object is deleted and reported under 'successfully'."""
        for public_id in DELETE_MANY_IDS:
            _insert_object_doc(database_manager, database_name, public_id, ORIGINAL_VALUE)
        try:
            ids = ','.join(str(public_id) for public_id in DELETE_MANY_IDS)
            response = rest_api.delete(f'{ROUTE_URL}/delete/{ids}')

            assert response.status_code == HTTPStatus.OK
            assert sorted(response.get_json()['successfully']) == sorted(DELETE_MANY_IDS)
            for public_id in DELETE_MANY_IDS:
                assert rest_api.get(f'{ROUTE_URL}/native/{public_id}').status_code == HTTPStatus.NOT_FOUND
        finally:
            for public_id in DELETE_MANY_IDS:
                _drop_object(database_manager, database_name, public_id)

    def test_bulk_delete_reparents_children_of_located_targets(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """A located target is deleted and its location's children are promoted onto the grandparent."""
        _insert_object_doc(database_manager, database_name, DELETE_MANY_LOCATED_ID, ORIGINAL_VALUE)
        _insert_location(database_manager, database_name, DELETE_MANY_LOCATION_ID,
                         DELETE_MANY_LOCATED_ID, ROOT_LOCATION_ID)
        _insert_location(database_manager, database_name, DELETE_MANY_CHILD_LOCATION_ID,
                         DELETE_MANY_CHILD_OBJECT_ID, DELETE_MANY_LOCATION_ID)
        try:
            response = rest_api.delete(f'{ROUTE_URL}/delete/{DELETE_MANY_LOCATED_ID}')

            assert response.status_code == HTTPStatus.OK
            assert response.get_json()['successfully'] == [DELETE_MANY_LOCATED_ID]
            # target object + its own location node are gone
            assert rest_api.get(f'{ROUTE_URL}/native/{DELETE_MANY_LOCATED_ID}').status_code == HTTPStatus.NOT_FOUND
            assert _location_exists(database_manager, database_name, DELETE_MANY_LOCATION_ID) is False
            # the child location survives, promoted onto the deleted node's own parent (the root)
            assert _location_parent(
                database_manager, database_name, DELETE_MANY_CHILD_LOCATION_ID,
            ) == ROOT_LOCATION_ID
        finally:
            _drop_object(database_manager, database_name, DELETE_MANY_LOCATED_ID)
            database_manager.get_collection(CmdbLocation.COLLECTION, database_name).delete_many(
                {'public_id': {'$in': [DELETE_MANY_LOCATION_ID, DELETE_MANY_CHILD_LOCATION_ID]}}
            )


# -------------------------------------------------------------------------------------------------------------------- #
#                                     PATCH MDS ROWS (create / edit / delete)                                         #
# -------------------------------------------------------------------------------------------------------------------- #
MDS_ROWS_SOURCE_ID: int = 9466
MDS_ROWS_TARGET_ID: int = 9467
MDS_ROWS_TARGET_ID_2: int = 9468
MDS_EMPTY_SOURCE_ID: int = 9469
MDS_SECTION_ID: str = 'mds-section'


def _mds_object_two_rows(public_id: int, target_id: int) -> dict[str, Any]:
    """An MDS-ref object carrying two rows (multi_data_id 1 and 2), highest_id 2."""
    doc = _mds_referencing_object_doc(public_id, target_id)
    doc['multi_data_sections'][0]['highest_id'] = 2
    doc['multi_data_sections'][0]['values'].append({
        'multi_data_id': 2,
        'data': [{'type': 'ref', 'name': MDS_REF_FIELD, 'value': target_id}],
    })
    return doc


def _mds_object_no_rows(public_id: int) -> dict[str, Any]:
    """An object of the MDS-ref type that has no multi_data_sections container yet."""
    return {
        'public_id': public_id,
        'type_id': MDS_REF_TYPE_ID,
        'active': True,
        'author_id': SEED_AUTHOR_ID,
        'version': SEED_VERSION,
        'fields': [],
        'multi_data_sections': [],
        'creation_time': datetime.now(timezone.utc),
    }


class TestPatchMdsRows:
    """PATCH applies created/edited/deleted MDS rows in one call, with backend-assigned ids."""

    @pytest.fixture(autouse=True)
    def _seed(self, database_manager: MongoDatabaseManager, database_name: str):
        """Seeds the MDS-ref type, two ref targets, a source with two rows and one with no rows."""
        types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
        objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
        types.insert_one(_mds_ref_type_doc())
        objects.insert_one(_object_doc(MDS_ROWS_TARGET_ID, ORIGINAL_VALUE))
        objects.insert_one(_object_doc(MDS_ROWS_TARGET_ID_2, ORIGINAL_VALUE))
        objects.insert_one(_mds_object_two_rows(MDS_ROWS_SOURCE_ID, MDS_ROWS_TARGET_ID))
        objects.insert_one(_mds_object_no_rows(MDS_EMPTY_SOURCE_ID))
        yield
        objects.delete_many(
            {'public_id': {'$in': [
                MDS_ROWS_SOURCE_ID, MDS_ROWS_TARGET_ID, MDS_ROWS_TARGET_ID_2, MDS_EMPTY_SOURCE_ID,
            ]}}
        )
        types.delete_one({'public_id': MDS_REF_TYPE_ID})

    def test_patch_creates_edits_and_deletes_rows_in_one_call(self, rest_api) -> None:
        """Create appends a backend-numbered row (highest_id -> 3), edit updates row 1, delete drops row 2."""
        response = rest_api.patch(
            f'{ROUTE_URL}/{MDS_ROWS_SOURCE_ID}',
            json={
                'created_mds_rows': [
                    {'section_id': MDS_SECTION_ID, 'data': [{'name': MDS_REF_FIELD, 'value': MDS_ROWS_TARGET_ID}]},
                ],
                'edited_mds_rows': [
                    {'section_id': MDS_SECTION_ID, 'multi_data_id': 1,
                     'data': [{'name': MDS_REF_FIELD, 'value': MDS_ROWS_TARGET_ID_2}]},
                ],
                'deleted_mds_rows': [
                    {'section_id': MDS_SECTION_ID, 'multi_data_id': 2},
                ],
            },
        )

        assert response.status_code == HTTPStatus.ACCEPTED

        follow_up = rest_api.get(f'{ROUTE_URL}/native/{MDS_ROWS_SOURCE_ID}')
        stored = CmdbObject.from_data(follow_up.get_json())
        section = stored.multi_data_sections[0]

        # row 2 deleted, row 1 kept, a new row 3 created (highest_id was 2 -> assigned 3)
        assert {row['multi_data_id'] for row in section['values']} == {1, 3}
        assert section['highest_id'] == 3

        rows_by_id = {row['multi_data_id']: row for row in section['values']}
        edited_value = next(f['value'] for f in rows_by_id[1]['data'] if f['name'] == MDS_REF_FIELD)
        created_value = next(f['value'] for f in rows_by_id[3]['data'] if f['name'] == MDS_REF_FIELD)
        assert edited_value == MDS_ROWS_TARGET_ID_2
        assert created_value == MDS_ROWS_TARGET_ID

    def test_patch_first_row_add_seeds_section_container(self, rest_api) -> None:
        """Creating a row in a declared section the object lacks seeds the container with row 1."""
        response = rest_api.patch(
            f'{ROUTE_URL}/{MDS_EMPTY_SOURCE_ID}',
            json={'created_mds_rows': [
                {'section_id': MDS_SECTION_ID, 'data': [{'name': MDS_REF_FIELD, 'value': MDS_ROWS_TARGET_ID}]},
            ]},
        )

        assert response.status_code == HTTPStatus.ACCEPTED

        follow_up = rest_api.get(f'{ROUTE_URL}/native/{MDS_EMPTY_SOURCE_ID}')
        stored = CmdbObject.from_data(follow_up.get_json())
        section = next(s for s in stored.multi_data_sections if s['section_id'] == MDS_SECTION_ID)
        assert section['highest_id'] == 1
        assert section['values'][0]['multi_data_id'] == 1


# -------------------------------------------------------------------------------------------------------------------- #
#                                              ERROR MAPPING MATRIX                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
def _raiser(exc: Exception):
    """Returns a function that ignores its args and raises the given exception."""
    def _fail(*_args, **_kwargs):
        raise exc
    return _fail


class TestErrorMapping:
    """Each route maps its manager exceptions to the documented HTTP status codes."""

    # ---- READ ---- #
    def test_list_iteration_error_returns_400(self, rest_api, monkeypatch) -> None:
        """An ObjectsManagerIterationError from iterate maps the list route to 400."""
        monkeypatch.setattr(ObjectsManager, 'iterate', _raiser(ObjectsManagerIterationError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/').status_code == HTTPStatus.BAD_REQUEST

    def test_list_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error from iterate maps the list route to 500."""
        monkeypatch.setattr(ObjectsManager, 'iterate', _raiser(RuntimeError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/').status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_count_get_error_returns_400(self, rest_api, monkeypatch) -> None:
        """An ObjectsManagerGetError from count_documents maps the count route to 400."""
        monkeypatch.setattr(ObjectsManager, 'count_documents', _raiser(ObjectsManagerGetError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/count').status_code == HTTPStatus.BAD_REQUEST

    def test_count_for_type_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error from count_documents maps the count-for-type route to 500."""
        monkeypatch.setattr(ObjectsManager, 'count_documents', _raiser(RuntimeError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/count/{TYPE_ID}').status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_single_get_access_denied_returns_403(self, rest_api, monkeypatch) -> None:
        """An AccessDeniedError from get_object maps the single-get route to 403."""
        monkeypatch.setattr(ObjectsManager, 'get_object', _raiser(AccessDeniedError('nope')))

        assert rest_api.get(f'{ROUTE_URL}/{MISSING_OBJECT_ID}').status_code == HTTPStatus.FORBIDDEN

    def test_native_get_error_returns_400(self, rest_api, monkeypatch) -> None:
        """An ObjectsManagerGetError from get_object maps the native route to 400."""
        monkeypatch.setattr(ObjectsManager, 'get_object', _raiser(ObjectsManagerGetError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/native/{MISSING_OBJECT_ID}').status_code == HTTPStatus.BAD_REQUEST

    def test_state_get_error_returns_400(self, rest_api, monkeypatch) -> None:
        """An ObjectsManagerGetError from get_object maps the state-get route to 400."""
        monkeypatch.setattr(ObjectsManager, 'get_object', _raiser(ObjectsManagerGetError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/state/{MISSING_OBJECT_ID}').status_code == HTTPStatus.BAD_REQUEST

    def test_references_get_error_returns_400(self, rest_api, monkeypatch) -> None:
        """An ObjectsManagerGetError while resolving the referenced object maps to 400."""
        monkeypatch.setattr(ObjectsManager, 'get_object', _raiser(ObjectsManagerGetError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/references/{MISSING_OBJECT_ID}').status_code == HTTPStatus.BAD_REQUEST

    def test_mds_reference_access_denied_returns_403(self, rest_api, monkeypatch) -> None:
        """An AccessDeniedError from get_object maps the single MDS-reference route to 403."""
        monkeypatch.setattr(ObjectsManager, 'get_object', _raiser(AccessDeniedError('nope')))

        assert rest_api.get(f'{ROUTE_URL}/{MISSING_OBJECT_ID}/mds_reference').status_code == HTTPStatus.FORBIDDEN

    # ---- GROUP ---- #
    def test_group_iteration_error_returns_400(self, rest_api, monkeypatch) -> None:
        """An ObjectsManagerIterationError from group_objects_by_value maps the group route to 400."""
        monkeypatch.setattr(ObjectsManager, 'group_objects_by_value', _raiser(ObjectsManagerIterationError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/group/type_id').status_code == HTTPStatus.BAD_REQUEST

    def test_group_types_lookup_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A TypesManagerGetError while resolving the groups' types maps the group route to 400."""
        monkeypatch.setattr(
            ObjectsManager, 'group_objects_by_value', lambda *_a, **_k: [{'_id': TYPE_ID, 'count': 1, 'result': {}}]
        )
        monkeypatch.setattr(TypesManager, 'get_types_lookup', _raiser(TypesManagerGetError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/group/type_id').status_code == HTTPStatus.BAD_REQUEST

    # ---- WRITE / DELETE ---- #
    def test_update_get_error_returns_400(self, rest_api, monkeypatch) -> None:
        """An ObjectsManagerGetError raised inside the update pipeline maps PUT to 400."""
        monkeypatch.setattr(ObjectsManager, 'get_object', _raiser(ObjectsManagerGetError('boom')))

        response = rest_api.put(f'{ROUTE_URL}/{MISSING_OBJECT_ID}', json=_object_payload(MISSING_OBJECT_ID, 'x'))

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_delete_get_error_returns_400(self, rest_api, monkeypatch) -> None:
        """An ObjectsManagerGetError from the delete target lookup maps DELETE to 400."""
        monkeypatch.setattr(ObjectsManager, 'get_object', _raiser(ObjectsManagerGetError('boom')))

        assert rest_api.delete(f'{ROUTE_URL}/{MISSING_OBJECT_ID}').status_code == HTTPStatus.BAD_REQUEST

    def test_clean_probe_type_not_found_returns_404(self, rest_api, monkeypatch) -> None:
        """A missing type on the GET /clean probe returns 404."""
        monkeypatch.setattr(ObjectsManager, 'get_object_type', lambda *_a, **_k: None)

        assert rest_api.get(f'{ROUTE_URL}/clean/{MISSING_OBJECT_ID}').status_code == HTTPStatus.NOT_FOUND

    def test_clean_update_type_not_found_returns_500(self, rest_api, monkeypatch) -> None:
        """A missing type on the PUT /clean re-align returns 500."""
        monkeypatch.setattr(ObjectsManager, 'get_object_type', lambda *_a, **_k: None)

        assert rest_api.put(f'{ROUTE_URL}/clean/{MISSING_OBJECT_ID}').status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_delete_many_delete_error_returns_500(self, rest_api, monkeypatch, database_manager, database_name) -> None:
        """An ObjectsManagerDeleteError during a bulk delete maps to 500."""
        _insert_object_doc(database_manager, database_name, BULK_OBJECT_IDS[0], 'x')
        monkeypatch.setattr(ObjectsManager, 'delete_object', _raiser(ObjectsManagerDeleteError('boom')))
        monkeypatch.setattr(ObjectsManager, 'delete_objects_from_risk_assessment_cascade', lambda *_a, **_k: None)

        try:
            response = rest_api.delete(f'{ROUTE_URL}/delete/{BULK_OBJECT_IDS[0]}')
            assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        finally:
            _drop_object(database_manager, database_name, BULK_OBJECT_IDS[0])


class TestErrorMappingWriteAndDelete:
    """Per-route exception handlers for the write / delete routes map to the right status codes."""

    def test_insert_manager_error_returns_400(self, rest_api, monkeypatch) -> None:
        """An ObjectsManagerInsertError from insert_object maps POST to 400."""
        monkeypatch.setattr(ObjectsManager, 'insert_object', _raiser(ObjectsManagerInsertError('boom')))

        response = rest_api.post(f'{ROUTE_URL}/', json=_object_payload(MISSING_OBJECT_ID, 'x'))

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_insert_access_denied_returns_403(self, rest_api, monkeypatch) -> None:
        """An AccessDeniedError from insert_object maps POST to 403."""
        monkeypatch.setattr(ObjectsManager, 'insert_object', _raiser(AccessDeniedError('nope')))

        response = rest_api.post(f'{ROUTE_URL}/', json=_object_payload(MISSING_OBJECT_ID, 'x'))

        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_single_get_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error from get_object maps the single-get route to 500."""
        monkeypatch.setattr(ObjectsManager, 'get_object', _raiser(RuntimeError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/{MISSING_OBJECT_ID}').status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_mds_references_plural_get_error_returns_400(self, rest_api, monkeypatch) -> None:
        """An ObjectsManagerGetError maps the plural MDS-references route to 400."""
        monkeypatch.setattr(ObjectsManager, 'get_object', _raiser(ObjectsManagerGetError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/{MISSING_OBJECT_ID}/mds_references').status_code == HTTPStatus.BAD_REQUEST

    def test_references_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error while resolving references maps to 500."""
        monkeypatch.setattr(ObjectsManager, 'get_object', _raiser(RuntimeError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/references/{MISSING_OBJECT_ID}').status_code \
            == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_patch_get_error_returns_400(self, rest_api, monkeypatch) -> None:
        """An ObjectsManagerGetError from the patch object lookup maps PATCH to 400."""
        monkeypatch.setattr(ObjectsManager, 'get_object', _raiser(ObjectsManagerGetError('boom')))

        response = rest_api.patch(f'{ROUTE_URL}/{MISSING_OBJECT_ID}', json={'fields': [{'name': 'a', 'value': 1}]})

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_patch_access_denied_returns_403(self, rest_api, monkeypatch) -> None:
        """An AccessDeniedError during patch maps PATCH to 403."""
        monkeypatch.setattr(ObjectsManager, 'get_object', _raiser(AccessDeniedError('nope')))

        response = rest_api.patch(f'{ROUTE_URL}/{MISSING_OBJECT_ID}', json={'fields': [{'name': 'a', 'value': 1}]})

        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_delete_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error from the delete target lookup maps DELETE to 500."""
        monkeypatch.setattr(ObjectsManager, 'get_object', _raiser(RuntimeError('boom')))

        assert rest_api.delete(f'{ROUTE_URL}/{MISSING_OBJECT_ID}').status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_state_update_error_returns_400(self, rest_api, monkeypatch, database_manager, database_name) -> None:
        """An ObjectsManagerUpdateError while toggling the state maps PUT /state to 400."""
        _insert_object_doc(database_manager, database_name, OBJECT_ID_FOR_UPDATE, 'x')
        monkeypatch.setattr(ObjectsManager, 'update_object', _raiser(ObjectsManagerUpdateError('boom')))

        try:
            # seeded object is active=True, so sending False is a real state change that reaches update_object
            response = rest_api.put(f'{ROUTE_URL}/state/{OBJECT_ID_FOR_UPDATE}', json=False)
            assert response.status_code == HTTPStatus.BAD_REQUEST
        finally:
            _drop_object(database_manager, database_name, OBJECT_ID_FOR_UPDATE)


# -------------------------------------------------------------------------------------------------------------------- #
#                                    OBJECT-DRIVEN LOCATION SYNC (create/edit)                                        #
# -------------------------------------------------------------------------------------------------------------------- #
LSYNC_TYPE_ID: int = 9404
LSYNC_OBJECT_ID: int = 9470
LSYNC_CHILD_OBJECT_ID: int = 9471
LSYNC_PARENT_A: int = 9490
LSYNC_PARENT_B: int = 9491
LSYNC_OWN_LOCATION: int = 9492
LSYNC_CHILD_LOCATION: int = 9493
NONEXISTENT_PARENT: int = 88888
CUSTOM_LOCATION_NAME: str = 'Custom Location Name'


def _location_type_doc() -> dict[str, Any]:
    """A CmdbType carrying a location-typed field, so its objects mirror into the CmdbLocation tree."""
    return {
        'public_id': LSYNC_TYPE_ID,
        'name': f'loc-type-{LSYNC_TYPE_ID}',
        'label': 'Location Type',
        'author_id': SEED_AUTHOR_ID,
        'creation_time': datetime.now(timezone.utc),
        'active': True,
        'fields': [
            {'type': 'text', 'name': NAME_FIELD, 'label': 'Name'},
            {'type': 'location', 'name': LOCATION_FIELD_NAME, 'label': 'Location'},
        ],
        'render_meta': {
            'icon': 'fa-cube',
            'sections': [{'type': 'section', 'name': 'main', 'label': 'Main',
                          'fields': [NAME_FIELD, LOCATION_FIELD_NAME]}],
            'summary': {'fields': [NAME_FIELD]},
        },
        'acl': {'activated': False, 'groups': {'includes': None}},
        'version': SEED_VERSION,
    }


def _loc_object_payload(public_id: int, parent: int | None) -> dict[str, Any]:
    """POST/PUT body for a LOC_TYPE object placed under `parent` (0/None => no location)."""
    return {
        'public_id': public_id,
        'type_id': LSYNC_TYPE_ID,
        'active': True,
        'author_id': SEED_AUTHOR_ID,
        'version': SEED_VERSION,
        'fields': [
            {'type': 'text', 'name': NAME_FIELD, 'value': ORIGINAL_VALUE},
            {'type': 'location', 'name': LOCATION_FIELD_NAME, 'value': parent},
        ],
    }


def _loc_doc(public_id: int, object_id: int, parent: int) -> dict[str, Any]:
    """A CmdbLocation doc for direct insertion into the locations collection."""
    return {
        'public_id': public_id,
        'name': f'loc-{public_id}',
        'parent': parent,
        'object_id': object_id,
        'type_id': LSYNC_TYPE_ID,
        'type_label': 'Location Type',
        'type_icon': 'fa-cube',
        'type_selectable': True,
    }


class TestObjectLocationSync:
    """POST/PUT/PATCH mirror the object's location field into the CmdbLocation tree and validate it."""

    @pytest.fixture(autouse=True)
    def _seed(self, database_manager: MongoDatabaseManager, database_name: str):
        """Seeds the location-field type and two selectable parent locations; cleans everything after."""
        types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
        objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
        locations = database_manager.get_collection(CmdbLocation.COLLECTION, database_name)

        types.insert_one(_location_type_doc())
        locations.insert_many([
            _loc_doc(LSYNC_PARENT_A, 9480, ROOT_LOCATION_ID),
            _loc_doc(LSYNC_PARENT_B, 9481, ROOT_LOCATION_ID),
        ])
        yield
        types.delete_one({'public_id': LSYNC_TYPE_ID})
        objects.delete_many({'public_id': {'$in': [LSYNC_OBJECT_ID, LSYNC_CHILD_OBJECT_ID]}})
        locations.delete_many(
            {'public_id': {'$in': [LSYNC_PARENT_A, LSYNC_PARENT_B, LSYNC_OWN_LOCATION, LSYNC_CHILD_LOCATION]}}
        )
        locations.delete_many({'object_id': {'$in': [LSYNC_OBJECT_ID, LSYNC_CHILD_OBJECT_ID]}})

    @staticmethod
    def _location_of(database_manager: MongoDatabaseManager, database_name: str, object_id: int):
        """Returns the CmdbLocation doc linked to the given object, or None."""
        return database_manager.get_collection(CmdbLocation.COLLECTION, database_name)\
            .find_one({'object_id': object_id})

    # ---- CREATE ---- #
    def test_post_creates_location_for_new_object(self, rest_api, database_manager, database_name) -> None:
        """POSTing an object with a parent creates a mirrored CmdbLocation carrying that parent."""
        response = rest_api.post(f'{ROUTE_URL}/', json=_loc_object_payload(LSYNC_OBJECT_ID, LSYNC_PARENT_A))

        assert response.status_code == HTTPStatus.OK
        location = self._location_of(database_manager, database_name, LSYNC_OBJECT_ID)
        assert location is not None
        assert location['parent'] == LSYNC_PARENT_A

    def test_post_uses_custom_location_name(self, rest_api, database_manager, database_name) -> None:
        """A location_name in the POST body is used verbatim as the CmdbLocation tree name."""
        payload = _loc_object_payload(LSYNC_OBJECT_ID, LSYNC_PARENT_A)
        payload['location_name'] = CUSTOM_LOCATION_NAME

        response = rest_api.post(f'{ROUTE_URL}/', json=payload)

        assert response.status_code == HTTPStatus.OK
        location = self._location_of(database_manager, database_name, LSYNC_OBJECT_ID)
        assert location['name'] == CUSTOM_LOCATION_NAME

    def test_post_without_parent_creates_no_location(self, rest_api, database_manager, database_name) -> None:
        """POSTing an object with no parent leaves the location tree untouched."""
        response = rest_api.post(f'{ROUTE_URL}/', json=_loc_object_payload(LSYNC_OBJECT_ID, 0))

        assert response.status_code == HTTPStatus.OK
        assert self._location_of(database_manager, database_name, LSYNC_OBJECT_ID) is None

    def test_post_nonexistent_parent_rejected(self, rest_api) -> None:
        """POSTing under a parent location that does not exist is rejected 400 (object not created)."""
        response = rest_api.post(f'{ROUTE_URL}/', json=_loc_object_payload(LSYNC_OBJECT_ID, NONEXISTENT_PARENT))

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert rest_api.get(f'{ROUTE_URL}/native/{LSYNC_OBJECT_ID}').status_code == HTTPStatus.NOT_FOUND

    # ---- EDIT (PUT) ---- #
    def test_put_updates_location_parent(self, rest_api, database_manager, database_name) -> None:
        """Changing the object's location field via PUT moves its CmdbLocation to the new parent."""
        objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
        locations = database_manager.get_collection(CmdbLocation.COLLECTION, database_name)
        objects.insert_one({**_loc_object_payload(LSYNC_OBJECT_ID, LSYNC_PARENT_A),
                            'creation_time': datetime.now(timezone.utc)})
        locations.insert_one(_loc_doc(LSYNC_OWN_LOCATION, LSYNC_OBJECT_ID, LSYNC_PARENT_A))

        response = rest_api.put(f'{ROUTE_URL}/{LSYNC_OBJECT_ID}',
                                json=_loc_object_payload(LSYNC_OBJECT_ID, LSYNC_PARENT_B))

        assert response.status_code == HTTPStatus.ACCEPTED
        assert self._location_of(database_manager, database_name, LSYNC_OBJECT_ID)['parent'] == LSYNC_PARENT_B

    def test_put_removes_location_when_parent_cleared(self, rest_api, database_manager, database_name) -> None:
        """Clearing the location field via PUT deletes the object's (childless) CmdbLocation."""
        objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
        locations = database_manager.get_collection(CmdbLocation.COLLECTION, database_name)
        objects.insert_one({**_loc_object_payload(LSYNC_OBJECT_ID, LSYNC_PARENT_A),
                            'creation_time': datetime.now(timezone.utc)})
        locations.insert_one(_loc_doc(LSYNC_OWN_LOCATION, LSYNC_OBJECT_ID, LSYNC_PARENT_A))

        response = rest_api.put(f'{ROUTE_URL}/{LSYNC_OBJECT_ID}',
                                json=_loc_object_payload(LSYNC_OBJECT_ID, 0))

        assert response.status_code == HTTPStatus.ACCEPTED
        assert self._location_of(database_manager, database_name, LSYNC_OBJECT_ID) is None

    def test_put_nonexistent_parent_rejected(self, rest_api, database_manager, database_name) -> None:
        """Moving to a parent location that does not exist is rejected 400."""
        objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
        locations = database_manager.get_collection(CmdbLocation.COLLECTION, database_name)
        objects.insert_one({**_loc_object_payload(LSYNC_OBJECT_ID, LSYNC_PARENT_A),
                            'creation_time': datetime.now(timezone.utc)})
        locations.insert_one(_loc_doc(LSYNC_OWN_LOCATION, LSYNC_OBJECT_ID, LSYNC_PARENT_A))

        response = rest_api.put(f'{ROUTE_URL}/{LSYNC_OBJECT_ID}',
                                json=_loc_object_payload(LSYNC_OBJECT_ID, NONEXISTENT_PARENT))

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_put_cycle_rejected(self, rest_api, database_manager, database_name) -> None:
        """Setting the parent to a location inside the object's own subtree is rejected 400 (cycle)."""
        objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
        locations = database_manager.get_collection(CmdbLocation.COLLECTION, database_name)
        objects.insert_one({**_loc_object_payload(LSYNC_OBJECT_ID, ROOT_LOCATION_ID),
                            'creation_time': datetime.now(timezone.utc)})
        locations.insert_one(_loc_doc(LSYNC_OWN_LOCATION, LSYNC_OBJECT_ID, ROOT_LOCATION_ID))
        locations.insert_one(_loc_doc(LSYNC_CHILD_LOCATION, LSYNC_CHILD_OBJECT_ID, LSYNC_OWN_LOCATION))

        response = rest_api.put(f'{ROUTE_URL}/{LSYNC_OBJECT_ID}',
                                json=_loc_object_payload(LSYNC_OBJECT_ID, LSYNC_CHILD_LOCATION))

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_put_remove_with_children_promotes_them(self, rest_api, database_manager, database_name) -> None:
        """Clearing the location promotes children to the grandparent - both the child location NODE
        and the child OBJECT's mirrored location field (the two-collection mirror, end to end)."""
        objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
        locations = database_manager.get_collection(CmdbLocation.COLLECTION, database_name)
        objects.insert_one({**_loc_object_payload(LSYNC_OBJECT_ID, ROOT_LOCATION_ID),
                            'creation_time': datetime.now(timezone.utc)})
        # the child object is placed under the parent's location (its dg_location field points there)
        objects.insert_one({**_loc_object_payload(LSYNC_CHILD_OBJECT_ID, LSYNC_OWN_LOCATION),
                            'creation_time': datetime.now(timezone.utc)})
        locations.insert_one(_loc_doc(LSYNC_OWN_LOCATION, LSYNC_OBJECT_ID, ROOT_LOCATION_ID))
        locations.insert_one(_loc_doc(LSYNC_CHILD_LOCATION, LSYNC_CHILD_OBJECT_ID, LSYNC_OWN_LOCATION))

        response = rest_api.put(f'{ROUTE_URL}/{LSYNC_OBJECT_ID}',
                                json=_loc_object_payload(LSYNC_OBJECT_ID, 0))

        assert response.status_code == HTTPStatus.ACCEPTED
        # the object's own placement is removed
        assert self._location_of(database_manager, database_name, LSYNC_OBJECT_ID) is None
        # the child location NODE survives, promoted onto the removed node's own parent (the root)
        child_node = locations.find_one({'public_id': LSYNC_CHILD_LOCATION})
        assert child_node is not None and child_node['parent'] == ROOT_LOCATION_ID
        # and the child OBJECT's mirrored location field is re-pointed at the grandparent too
        child_object = objects.find_one({'public_id': LSYNC_CHILD_OBJECT_ID})
        location_field = next(f for f in child_object['fields'] if f['name'] == LOCATION_FIELD_NAME)
        assert location_field['value'] == ROOT_LOCATION_ID

    # ---- PATCH (name-only) ---- #
    def test_patch_location_name_only_renames_node(self, rest_api, database_manager, database_name) -> None:
        """A name-only PATCH renames the CmdbLocation without a field change and is not rejected as empty."""
        objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
        locations = database_manager.get_collection(CmdbLocation.COLLECTION, database_name)
        objects.insert_one({**_loc_object_payload(LSYNC_OBJECT_ID, LSYNC_PARENT_A),
                            'creation_time': datetime.now(timezone.utc)})
        locations.insert_one(_loc_doc(LSYNC_OWN_LOCATION, LSYNC_OBJECT_ID, LSYNC_PARENT_A))

        response = rest_api.patch(f'{ROUTE_URL}/{LSYNC_OBJECT_ID}', json={'location_name': CUSTOM_LOCATION_NAME})

        assert response.status_code == HTTPStatus.ACCEPTED
        location = self._location_of(database_manager, database_name, LSYNC_OBJECT_ID)
        assert location['name'] == CUSTOM_LOCATION_NAME
        assert location['parent'] == LSYNC_PARENT_A
