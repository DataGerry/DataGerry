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
Functional smoke for the ``/objects`` CRUD routes

The create / read-one / update / patch / delete round trips, the bulk update and the bulk delete,
plus the activation toggle - the route-layer concerns the ObjectsManager integration suite cannot
reach: status codes, the duplicate-insert 400, the 404 on a missing id, and what the routes own
rather than accept from the payload.

The presentation reads (the rendered payloads, the value view, the listing filters) are in
``test_functional_objects_read``; anything that turns a manager error into a status code is in
``test_functional_objects_error_mapping``
"""
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.object_model import CmdbObject
from cmdb.models.log_model.cmdb_meta_log import CmdbMetaLog
from cmdb.models.location_model.cmdb_location import CmdbLocation

from tests.functional.framework.objects.objects_route_helpers import (
    BULK_OBJECT_IDS,
    BULK_UPDATED_VALUE,
    MISSING_OBJECT_ID,
    NAME_FIELD,
    OBJECT_ID_FOR_CREATE,
    OBJECT_ID_FOR_DELETE,
    OBJECT_ID_FOR_GET,
    OBJECT_ID_FOR_PATCH,
    OBJECT_ID_FOR_UPDATE,
    ORIGINAL_VALUE,
    REQUEST_USER_ID,
    ROOT_LOCATION_ID,
    ROUTE_URL,
    TYPE_ID,
    TYPE_NAME,
    UPDATED_VALUE,
    UPDATE_VERSION,
    drop_object,
    insert_object_doc,
    object_doc,
    object_payload,
)
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
            response = rest_api.post(f'{ROUTE_URL}/', json=object_payload(OBJECT_ID_FOR_CREATE, ORIGINAL_VALUE))

            assert response.status_code == HTTPStatus.OK
            follow_up = rest_api.get(f'{ROUTE_URL}/native/{OBJECT_ID_FOR_CREATE}')
            assert follow_up.status_code == HTTPStatus.OK
        finally:
            drop_object(database_manager, database_name, OBJECT_ID_FOR_CREATE)

    def test_the_frontend_payload_shape_is_accepted(
        self,
        rest_api,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """
        The exact shape `new CmdbObject()` serialises to in object-add.component.ts

        Pinned because the create route carries `@validate(CmdbObject.SCHEMA)` and the validator
        purges unknown keys: the frontend class initialises `status`, which the schema does not
        declare. It is not stored either way - `CmdbObject.from_data`/`to_json` drop it - so purging
        changes nothing, and this test is what keeps that true.
        """
        try:
            response = rest_api.post(f'{ROUTE_URL}/', json={
                'public_id': OBJECT_ID_FOR_CREATE,
                'type_id': TYPE_ID,
                'status': True,                       # sent by the frontend, absent from the schema
                'version': '1.0.0',
                'author_id': 1,
                'ci_explorer_tooltip': None,
                'active': True,
                'fields': [{'name': NAME_FIELD, 'value': ORIGINAL_VALUE}],
                'multi_data_sections': [],
            })

            assert response.status_code == HTTPStatus.OK
            stored = database_manager.get_collection(CmdbObject.COLLECTION, database_name)\
                .find_one({'public_id': OBJECT_ID_FOR_CREATE})
            assert stored['fields'][0]['value'] == ORIGINAL_VALUE
            assert 'status' not in stored
        finally:
            drop_object(database_manager, database_name, OBJECT_ID_FOR_CREATE)

    def test_a_payload_without_an_author_is_refused(self, rest_api) -> None:
        """
        `author_id` is required by the schema - and was already required by the model

        `CmdbObject.REQUIRED_INIT_KEYS` demands it, so this was always refused; the schema only moves
        where it is reported, from deep in the insert pipeline to a clean 400 at the boundary.
        """
        response = rest_api.post(f'{ROUTE_URL}/', json={'type_id': TYPE_ID, 'fields': []})

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_a_misTyped_field_list_is_refused_at_the_boundary(self, rest_api) -> None:
        """`fields` must be a list; a string used to travel further into the pipeline before failing."""
        response = rest_api.post(f'{ROUTE_URL}/', json={
            'type_id': TYPE_ID, 'author_id': 1, 'fields': 'not-a-list',
        })

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_duplicate_public_id_returns_400(
        self,
        rest_api,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """A POST whose public_id already exists is rejected with 400."""
        try:
            first = rest_api.post(f'{ROUTE_URL}/', json=object_payload(OBJECT_ID_FOR_CREATE, ORIGINAL_VALUE))
            assert first.status_code == HTTPStatus.OK

            duplicate = rest_api.post(f'{ROUTE_URL}/', json=object_payload(OBJECT_ID_FOR_CREATE, ORIGINAL_VALUE))

            assert duplicate.status_code == HTTPStatus.BAD_REQUEST
        finally:
            drop_object(database_manager, database_name, OBJECT_ID_FOR_CREATE)


class TestGetObject:
    """GET /objects/native/<id> and GET /objects/ return the expected envelopes."""

    @pytest.fixture(autouse=True)
    def _seed(self, database_manager: MongoDatabaseManager, database_name: str):
        """Inserts one object directly via the DB before each test and removes it after."""
        insert_object_doc(database_manager, database_name, OBJECT_ID_FOR_GET, ORIGINAL_VALUE)
        yield
        drop_object(database_manager, database_name, OBJECT_ID_FOR_GET)

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


class TestPutObject:
    """PUT /objects/<id> updates the doc and stamps last_edit_time / editor_id."""

    def test_update_persists_changes_and_sets_last_edit_time(
        self,
        rest_api,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """After PUT, the object's field value reflects the new payload and last_edit_time is populated."""
        insert_object_doc(database_manager, database_name, OBJECT_ID_FOR_UPDATE, ORIGINAL_VALUE)
        try:
            updated_payload = object_payload(OBJECT_ID_FOR_UPDATE, UPDATED_VALUE)
            updated_payload['version'] = UPDATE_VERSION

            response = rest_api.put(f'{ROUTE_URL}/{OBJECT_ID_FOR_UPDATE}', json=updated_payload)
            assert response.status_code == HTTPStatus.ACCEPTED

            follow_up = rest_api.get(f'{ROUTE_URL}/native/{OBJECT_ID_FOR_UPDATE}')
            stored = CmdbObject.from_data(follow_up.get_json())
            assert stored.last_edit_time is not None
            stored_value = next(field['value'] for field in stored.fields if field['name'] == NAME_FIELD)
            assert stored_value == UPDATED_VALUE
        finally:
            drop_object(database_manager, database_name, OBJECT_ID_FOR_UPDATE)


class TestPatchObject:
    """PATCH /objects/<id> partially updates a single object and rejects disallowed keys."""

    def test_patch_updates_listed_field(
        self,
        rest_api,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """A PATCH with a fields subset changes that value and stamps last_edit_time."""
        insert_object_doc(database_manager, database_name, OBJECT_ID_FOR_PATCH, ORIGINAL_VALUE)
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
            drop_object(database_manager, database_name, OBJECT_ID_FOR_PATCH)

    def test_patch_rejects_immutable_key_and_leaves_object_unchanged(
        self,
        rest_api,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """A PATCH carrying an immutable key (type_id) is rejected 400 and nothing is written."""
        insert_object_doc(database_manager, database_name, OBJECT_ID_FOR_PATCH, ORIGINAL_VALUE)
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
            drop_object(database_manager, database_name, OBJECT_ID_FOR_PATCH)

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
        insert_object_doc(database_manager, database_name, OBJECT_ID_FOR_PATCH, ORIGINAL_VALUE)
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
            drop_object(database_manager, database_name, OBJECT_ID_FOR_PATCH)

    def test_the_edit_log_records_the_version_the_object_now_carries(
        self,
        rest_api,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """
        The log and the document agree on the version

        ``update_version`` returning the new version without storing it would make the update write
        the bumped string into the document while the edit log read the un-bumped one off the model
        instance - every object's history one bump behind the object it describes.
        """
        insert_object_doc(database_manager, database_name, OBJECT_ID_FOR_PATCH, ORIGINAL_VALUE)
        logs = database_manager.get_collection(CmdbMetaLog.COLLECTION, database_name)
        logs.delete_many({'object_id': OBJECT_ID_FOR_PATCH})

        try:
            rest_api.patch(
                f'{ROUTE_URL}/{OBJECT_ID_FOR_PATCH}',
                json={'fields': [{'name': NAME_FIELD, 'value': UPDATED_VALUE}]},
            )

            stored = CmdbObject.from_data(
                rest_api.get(f'{ROUTE_URL}/native/{OBJECT_ID_FOR_PATCH}').get_json()
            )
            edit_log = logs.find_one({'object_id': OBJECT_ID_FOR_PATCH, 'action_name': 'EDIT'})

            assert edit_log is not None
            assert edit_log['version'] == stored.version == UPDATE_VERSION
        finally:
            logs.delete_many({'object_id': OBJECT_ID_FOR_PATCH})
            drop_object(database_manager, database_name, OBJECT_ID_FOR_PATCH)

    def test_patch_stamps_editor_id_to_request_user(
        self,
        rest_api,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """PATCH stamps editor_id with the requesting user, exactly like the PUT pipeline."""
        insert_object_doc(database_manager, database_name, OBJECT_ID_FOR_PATCH, ORIGINAL_VALUE)
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
            drop_object(database_manager, database_name, OBJECT_ID_FOR_PATCH)

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


class TestDeleteObject:
    """DELETE /objects/<id> removes the doc; a follow-up GET reports 404."""

    def test_delete_removes_object(
        self,
        rest_api,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """A DELETE succeeds, and a subsequent GET for the same id returns 404."""
        insert_object_doc(database_manager, database_name, OBJECT_ID_FOR_DELETE, ORIGINAL_VALUE)
        try:
            response = rest_api.delete(f'{ROUTE_URL}/{OBJECT_ID_FOR_DELETE}')

            assert response.status_code == HTTPStatus.OK
            follow_up = rest_api.get(f'{ROUTE_URL}/native/{OBJECT_ID_FOR_DELETE}')
            assert follow_up.status_code == HTTPStatus.NOT_FOUND
        finally:
            drop_object(database_manager, database_name, OBJECT_ID_FOR_DELETE)


class TestBulkUpdateObjects:
    """PUT /objects/<id>?objectIDs=… applies the payload to every listed object."""

    @pytest.fixture(autouse=True)
    def _seed_three(self, database_manager: MongoDatabaseManager, database_name: str):
        """Inserts three objects with distinct values and removes them after the test."""
        for public_id in BULK_OBJECT_IDS:
            insert_object_doc(database_manager, database_name, public_id, f'initial-{public_id}')
        yield
        for public_id in BULK_OBJECT_IDS:
            drop_object(database_manager, database_name, public_id)

    def test_bulk_update_writes_payload_to_each_target(self, rest_api) -> None:
        """Each id listed in ``objectIDs`` ends up with the field value from the request body."""
        payload = object_payload(BULK_OBJECT_IDS[0], BULK_UPDATED_VALUE)
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


STATE_TOGGLE_ID: int = 9447

STATE_NOOP_ID: int = 9448

STATE_NONBOOL_ID: int = 9449

STATE_GET_ACTIVE_ID: int = 9450

STATE_GET_INACTIVE_ID: int = 9451

DELETE_MANY_IDS: list[int] = [9455, 9456]

DELETE_MANY_LOCATED_ID: int = 9457

DELETE_MANY_CHILD_OBJECT_ID: int = 9458

DELETE_MANY_CHILD_LOCATION_ID: int = 9459

DELETE_MANY_LOCATION_ID: int = 9483


def _inactive_object_doc(public_id: int) -> dict[str, Any]:
    """A CmdbObject doc with active=False, for the state read/toggle tests."""
    doc = object_doc(public_id, ORIGINAL_VALUE)
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


class TestObjectState:
    """GET/PUT /objects/state/<id> read and toggle the active flag."""

    def test_get_state_reflects_active_flag(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """The state GET returns True for an active object and False for an inactive one."""
        insert_object_doc(database_manager, database_name, STATE_GET_ACTIVE_ID, ORIGINAL_VALUE)
        database_manager.get_collection(CmdbObject.COLLECTION, database_name).insert_one(
            _inactive_object_doc(STATE_GET_INACTIVE_ID)
        )
        try:
            assert rest_api.get(f'{ROUTE_URL}/state/{STATE_GET_ACTIVE_ID}').get_json() is True
            assert rest_api.get(f'{ROUTE_URL}/state/{STATE_GET_INACTIVE_ID}').get_json() is False
        finally:
            drop_object(database_manager, database_name, STATE_GET_ACTIVE_ID)
            drop_object(database_manager, database_name, STATE_GET_INACTIVE_ID)

    def test_put_state_toggles_active_flag(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """Toggling an active object to False is accepted (202) and reflected on a follow-up read."""
        insert_object_doc(database_manager, database_name, STATE_TOGGLE_ID, ORIGINAL_VALUE)
        try:
            response = rest_api.put(f'{ROUTE_URL}/state/{STATE_TOGGLE_ID}', json=False)

            assert response.status_code == HTTPStatus.ACCEPTED
            assert rest_api.get(f'{ROUTE_URL}/state/{STATE_TOGGLE_ID}').get_json() is False
        finally:
            drop_object(database_manager, database_name, STATE_TOGGLE_ID)

    def test_put_state_unchanged_returns_the_object(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """A no-op state change writes nothing but answers in the SAME shape as a real change."""
        insert_object_doc(database_manager, database_name, STATE_NOOP_ID, ORIGINAL_VALUE)
        try:
            response = rest_api.put(f'{ROUTE_URL}/state/{STATE_NOOP_ID}', json=True)

            assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
            result = response.get_json()['result']
            assert result['public_id'] == STATE_NOOP_ID
            assert result['active'] is True
        finally:
            drop_object(database_manager, database_name, STATE_NOOP_ID)

    def test_put_state_non_boolean_returns_400(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """A non-boolean state body is rejected with 400."""
        insert_object_doc(database_manager, database_name, STATE_NONBOOL_ID, ORIGINAL_VALUE)
        try:
            response = rest_api.put(f'{ROUTE_URL}/state/{STATE_NONBOOL_ID}', json='not-a-bool')

            assert response.status_code == HTTPStatus.BAD_REQUEST
        finally:
            drop_object(database_manager, database_name, STATE_NONBOOL_ID)


class TestDeleteManyObjects:
    """DELETE /objects/delete/<ids> bulk-deletes objects, re-parenting the children of located ones."""

    def test_bulk_delete_removes_all_targets(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """Every listed (location-free) object is deleted and reported under 'successfully'."""
        for public_id in DELETE_MANY_IDS:
            insert_object_doc(database_manager, database_name, public_id, ORIGINAL_VALUE)
        try:
            ids = ','.join(str(public_id) for public_id in DELETE_MANY_IDS)
            response = rest_api.delete(f'{ROUTE_URL}/delete/{ids}')

            assert response.status_code == HTTPStatus.OK
            assert sorted(response.get_json()['successfully']) == sorted(DELETE_MANY_IDS)
            for public_id in DELETE_MANY_IDS:
                assert rest_api.get(f'{ROUTE_URL}/native/{public_id}').status_code == HTTPStatus.NOT_FOUND
        finally:
            for public_id in DELETE_MANY_IDS:
                drop_object(database_manager, database_name, public_id)

    def test_bulk_delete_reparents_children_of_located_targets(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """A located target is deleted and its location's children are promoted onto the grandparent."""
        insert_object_doc(database_manager, database_name, DELETE_MANY_LOCATED_ID, ORIGINAL_VALUE)
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
            drop_object(database_manager, database_name, DELETE_MANY_LOCATED_ID)
            database_manager.get_collection(CmdbLocation.COLLECTION, database_name).delete_many(
                {'public_id': {'$in': [DELETE_MANY_LOCATION_ID, DELETE_MANY_CHILD_LOCATION_ID]}}
            )


class TestBulkDeleteIsAtomic:
    """A target whose CmdbType is gone refuses the whole selection instead of deleting part of it."""

    ORPHAN_ID: int = 9432

    @pytest.fixture(autouse=True)
    def _seed(self, database_manager: MongoDatabaseManager, database_name: str):
        """Seeds one healthy object and one whose type_id points at no CmdbType."""
        objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
        insert_object_doc(database_manager, database_name, OBJECT_ID_FOR_DELETE, ORIGINAL_VALUE)
        orphan = object_doc(self.ORPHAN_ID, ORIGINAL_VALUE)
        orphan['type_id'] = 9998  # no such CmdbType
        objects.insert_one(orphan)
        yield
        objects.delete_many({'public_id': {'$in': [OBJECT_ID_FOR_DELETE, self.ORPHAN_ID]}})

    def test_nothing_is_deleted_when_one_type_is_missing(self, rest_api, database_manager, database_name) -> None:
        """The type check now runs in the up-front guard; it used to abort mid-loop (regression)."""
        response = rest_api.delete(f'{ROUTE_URL}/delete/{OBJECT_ID_FOR_DELETE},{self.ORPHAN_ID}')

        assert response.status_code == HTTPStatus.NOT_FOUND
        objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
        # the healthy target - listed FIRST, so the old mid-loop abort had already deleted it - survives
        assert objects.count_documents({'public_id': OBJECT_ID_FOR_DELETE}) == 1
        assert objects.count_documents({'public_id': self.ORPHAN_ID}) == 1
