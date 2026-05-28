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
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_URL: str = '/objects'

TYPE_ID: int = 9401
TYPE_NAME: str = 'route-smoke-type'
NAME_FIELD: str = 'name-field'

OBJECT_ID_FOR_CREATE: int = 9411
OBJECT_ID_FOR_GET: int = 9412
OBJECT_ID_FOR_UPDATE: int = 9413
OBJECT_ID_FOR_DELETE: int = 9414
BULK_OBJECT_IDS: list[int] = [9421, 9422, 9423]
MISSING_OBJECT_ID: int = 9499

ALL_OBJECT_IDS: list[int] = [
    OBJECT_ID_FOR_CREATE,
    OBJECT_ID_FOR_GET,
    OBJECT_ID_FOR_UPDATE,
    OBJECT_ID_FOR_DELETE,
] + BULK_OBJECT_IDS

ORIGINAL_VALUE: str = 'original'
UPDATED_VALUE: str = 'updated'
BULK_UPDATED_VALUE: str = 'bulk-updated'

SEED_VERSION: str = '1.0.0'
UPDATE_VERSION: str = '1.0.1'
SEED_AUTHOR_ID: int = 1


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
