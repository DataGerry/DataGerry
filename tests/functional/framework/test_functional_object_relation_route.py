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
Functional smoke for the ``/object_relations`` REST routes

Covers the route-layer contract: the create round-trip (with server-stamped author/creation time),
the missing-relation and parent==child guards, the list envelope, the 404 on a missing id, the
update round-trip with creation_time preservation, the public_id-pin regression, the delete +
404-after-delete, the bulk delete, and the manager-error -> HTTP-status mapping. CRUD behavior
itself is asserted at the manager layer; these tests verify the route wraps it correctly.
"""
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import ObjectRelationsManager
from cmdb.models.relation_model import CmdbRelation
from cmdb.models.object_relation_model import CmdbObjectRelation
from cmdb.errors.manager.object_relations_manager import (
    ObjectRelationsManagerInsertError,
    ObjectRelationsManagerIterationError,
)
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_URL: str = '/object_relations'

RELATION_ID: int = 77001
MISSING_RELATION_ID: int = 77999

PARENT_TYPE_ID: int = 1
CHILD_TYPE_ID: int = 2
PARENT_OBJECT_ID: int = 600
CHILD_OBJECT_ID: int = 700

ADMIN_PUBLIC_ID: int = 1

OR_ID_FOR_GET: int = 77101
OR_ID_FOR_UPDATE: int = 77102
OR_ID_FOR_PIN: int = 77103
OR_ID_FOR_DELETE: int = 77104
OR_ID_FOR_BULK_A: int = 77105
OR_ID_FOR_BULK_B: int = 77106
FORGED_PUBLIC_ID: int = 77900
MISSING_OR_ID: int = 77800

SEEDED_CREATION_TIME: datetime = datetime(2020, 1, 1, tzinfo=timezone.utc)

ALL_OR_IDS: list[int] = [
    OR_ID_FOR_GET, OR_ID_FOR_UPDATE, OR_ID_FOR_PIN, OR_ID_FOR_DELETE,
    OR_ID_FOR_BULK_A, OR_ID_FOR_BULK_B, FORGED_PUBLIC_ID,
]


def _object_relation_payload(public_id: int | None = None,
                             relation_id: int = RELATION_ID,
                             parent_id: int = PARENT_OBJECT_ID,
                             child_id: int = CHILD_OBJECT_ID,
                             field_values: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Builds a CmdbObjectRelation payload acceptable to POST/PUT (public_id optional)."""
    payload: dict[str, Any] = {
        'relation_id': relation_id,
        'relation_parent_id': parent_id,
        'relation_parent_type_id': PARENT_TYPE_ID,
        'relation_child_id': child_id,
        'relation_child_type_id': CHILD_TYPE_ID,
        'field_values': field_values if field_values is not None else [],
    }

    if public_id is not None:
        payload['public_id'] = public_id

    return payload


def _insert_object_relation_doc(database_manager: MongoDatabaseManager, database_name: str, public_id: int,
                                creation_time: datetime | None = None) -> None:
    """Inserts a CmdbObjectRelation doc directly via the collection, bypassing POST validation."""
    doc = _object_relation_payload(public_id)
    doc['author_id'] = ADMIN_PUBLIC_ID
    doc['creation_time'] = creation_time or SEEDED_CREATION_TIME
    database_manager.get_collection(CmdbObjectRelation.COLLECTION, database_name).insert_one(doc)


@pytest.fixture(scope='module', autouse=True)
def _seed_relation_and_cleanup(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds the referenced CmdbRelation for the module and cleans up all test docs afterwards."""
    database_manager.get_collection(CmdbRelation.COLLECTION, database_name).insert_one({
        'public_id': RELATION_ID,
        'relation_name': 'functional-object-relation-test',
        'parent_type_ids': [PARENT_TYPE_ID],
        'child_type_ids': [CHILD_TYPE_ID],
    })
    yield
    database_manager.get_collection(CmdbRelation.COLLECTION, database_name)\
        .delete_one({'public_id': RELATION_ID})
    database_manager.get_collection(CmdbObjectRelation.COLLECTION, database_name)\
        .delete_many({'public_id': {'$in': ALL_OR_IDS}})


class TestPostObjectRelation:
    """POST /object_relations/ creates a new CmdbObjectRelation."""

    def test_creates_and_stamps_author_and_creation_time(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """A POST returns 200/201, stamps the author + creation time, and is retrievable."""
        response = rest_api.post(f'{ROUTE_URL}/', json=_object_relation_payload())

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.CREATED)
        created = response.get_json()['raw']
        created_id = response.get_json()['result_id']
        try:
            assert created['author_id'] == ADMIN_PUBLIC_ID
            assert created['creation_time'] is not None
            assert rest_api.get(f'{ROUTE_URL}/{created_id}').status_code == HTTPStatus.OK
        finally:
            database_manager.get_collection(CmdbObjectRelation.COLLECTION, database_name)\
                .delete_one({'public_id': created_id})

    def test_missing_relation_returns_400(self, rest_api) -> None:
        """A POST referencing a non-existent CmdbRelation returns 400."""
        response = rest_api.post(f'{ROUTE_URL}/', json=_object_relation_payload(relation_id=MISSING_RELATION_ID))

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_parent_equals_child_returns_400(self, rest_api) -> None:
        """A POST where parent and child are the same object returns 400."""
        response = rest_api.post(f'{ROUTE_URL}/',
                                 json=_object_relation_payload(parent_id=PARENT_OBJECT_ID, child_id=PARENT_OBJECT_ID))

        assert response.status_code == HTTPStatus.BAD_REQUEST


class TestGetObjectRelation:
    """GET /object_relations/<id> and GET /object_relations/ envelopes."""

    @pytest.fixture(autouse=True)
    def _seed(self, database_manager: MongoDatabaseManager, database_name: str):
        _insert_object_relation_doc(database_manager, database_name, OR_ID_FOR_GET)
        yield
        database_manager.get_collection(CmdbObjectRelation.COLLECTION, database_name)\
            .delete_one({'public_id': OR_ID_FOR_GET})

    def test_get_single_returns_object_relation(self, rest_api) -> None:
        """A known id returns 200 with the matching object relation."""
        response = rest_api.get(f'{ROUTE_URL}/{OR_ID_FOR_GET}')

        assert response.status_code == HTTPStatus.OK
        assert response.get_json()['result']['public_id'] == OR_ID_FOR_GET

    def test_get_single_missing_returns_404(self, rest_api) -> None:
        """A missing id returns 404."""
        assert rest_api.get(f'{ROUTE_URL}/{MISSING_OR_ID}').status_code == HTTPStatus.NOT_FOUND

    def test_get_list_returns_results_envelope(self, rest_api) -> None:
        """GET /object_relations/ returns a results envelope matching X-Total-Count."""
        response = rest_api.get(f'{ROUTE_URL}/')

        assert response.status_code == HTTPStatus.OK
        body = response.get_json()
        assert 'results' in body
        assert len(body['results']) == int(response.headers['X-Total-Count'])


class TestUpdateObjectRelation:
    """PUT /object_relations/<id> updates a CmdbObjectRelation."""

    def test_update_persists_field_values(self, rest_api,
                                          database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A PUT updates the field values and the change is retrievable."""
        _insert_object_relation_doc(database_manager, database_name, OR_ID_FOR_UPDATE)
        try:
            payload = _object_relation_payload(OR_ID_FOR_UPDATE, field_values=[{'name': 'a', 'value': 'b'}])

            response = rest_api.put(f'{ROUTE_URL}/{OR_ID_FOR_UPDATE}', json=payload)

            assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
            follow_up = rest_api.get(f'{ROUTE_URL}/{OR_ID_FOR_UPDATE}')
            assert follow_up.get_json()['result']['field_values'] == [{'name': 'a', 'value': 'b'}]
        finally:
            database_manager.get_collection(CmdbObjectRelation.COLLECTION, database_name)\
                .delete_one({'public_id': OR_ID_FOR_UPDATE})

    def test_update_preserves_creation_time(self, rest_api,
                                            database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A PUT omitting creation_time must not reset the stored original creation time (regression)."""
        _insert_object_relation_doc(database_manager, database_name, OR_ID_FOR_UPDATE,
                                    creation_time=SEEDED_CREATION_TIME)
        try:
            rest_api.put(f'{ROUTE_URL}/{OR_ID_FOR_UPDATE}', json=_object_relation_payload(OR_ID_FOR_UPDATE))

            stored = database_manager.get_collection(CmdbObjectRelation.COLLECTION, database_name)\
                .find_one({'public_id': OR_ID_FOR_UPDATE})
            assert stored is not None
            creation_time = stored['creation_time']
            assert (creation_time.year, creation_time.month, creation_time.day) == (2020, 1, 1)
        finally:
            database_manager.get_collection(CmdbObjectRelation.COLLECTION, database_name)\
                .delete_one({'public_id': OR_ID_FOR_UPDATE})

    def test_update_missing_returns_404(self, rest_api) -> None:
        """A PUT against a missing object relation returns 404."""
        response = rest_api.put(f'{ROUTE_URL}/{MISSING_OR_ID}', json=_object_relation_payload(MISSING_OR_ID))

        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_update_pins_public_id_to_the_url(self, rest_api,
                                              database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A forged body public_id must not rewrite the document identity (regression)."""
        _insert_object_relation_doc(database_manager, database_name, OR_ID_FOR_PIN)
        try:
            payload = _object_relation_payload(FORGED_PUBLIC_ID)  # body carries a different public_id

            response = rest_api.put(f'{ROUTE_URL}/{OR_ID_FOR_PIN}', json=payload)

            assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
            assert rest_api.get(f'{ROUTE_URL}/{OR_ID_FOR_PIN}').status_code == HTTPStatus.OK
            assert rest_api.get(f'{ROUTE_URL}/{FORGED_PUBLIC_ID}').status_code == HTTPStatus.NOT_FOUND
        finally:
            database_manager.get_collection(CmdbObjectRelation.COLLECTION, database_name)\
                .delete_many({'public_id': {'$in': [OR_ID_FOR_PIN, FORGED_PUBLIC_ID]}})


class TestDeleteObjectRelation:
    """DELETE /object_relations/<id> and POST /object_relations/delete/many."""

    def test_delete_removes_object_relation(self, rest_api,
                                            database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A DELETE removes the object relation and a subsequent GET returns 404."""
        _insert_object_relation_doc(database_manager, database_name, OR_ID_FOR_DELETE)
        try:
            response = rest_api.delete(f'{ROUTE_URL}/{OR_ID_FOR_DELETE}')

            assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
            assert rest_api.get(f'{ROUTE_URL}/{OR_ID_FOR_DELETE}').status_code == HTTPStatus.NOT_FOUND
        finally:
            database_manager.get_collection(CmdbObjectRelation.COLLECTION, database_name)\
                .delete_one({'public_id': OR_ID_FOR_DELETE})

    def test_delete_missing_returns_404(self, rest_api) -> None:
        """Deleting a non-existent object relation returns 404."""
        assert rest_api.delete(f'{ROUTE_URL}/{MISSING_OR_ID}').status_code == HTTPStatus.NOT_FOUND

    def test_delete_many_removes_all_targets(self, rest_api,
                                             database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A bulk delete removes every targeted object relation."""
        _insert_object_relation_doc(database_manager, database_name, OR_ID_FOR_BULK_A)
        _insert_object_relation_doc(database_manager, database_name, OR_ID_FOR_BULK_B)
        try:
            response = rest_api.post(f'{ROUTE_URL}/delete/many',
                                     json={'target_ids': [OR_ID_FOR_BULK_A, OR_ID_FOR_BULK_B]})

            assert response.status_code == HTTPStatus.OK
            assert rest_api.get(f'{ROUTE_URL}/{OR_ID_FOR_BULK_A}').status_code == HTTPStatus.NOT_FOUND
            assert rest_api.get(f'{ROUTE_URL}/{OR_ID_FOR_BULK_B}').status_code == HTTPStatus.NOT_FOUND
        finally:
            database_manager.get_collection(CmdbObjectRelation.COLLECTION, database_name)\
                .delete_many({'public_id': {'$in': [OR_ID_FOR_BULK_A, OR_ID_FOR_BULK_B]}})

    def test_delete_many_without_ids_returns_400(self, rest_api) -> None:
        """A bulk delete with no target_ids returns 400."""
        assert rest_api.post(f'{ROUTE_URL}/delete/many', json={}).status_code == HTTPStatus.BAD_REQUEST


def _raise(exc: Exception):
    """Returns a function that ignores its args and raises the given exception."""
    def _fail(*_args, **_kwargs):
        raise exc
    return _fail


class TestErrorMapping:
    """The routes map manager failures to the documented HTTP statuses."""

    def test_insert_error_returns_400(self, rest_api, monkeypatch) -> None:
        """An ObjectRelationsManagerInsertError on create surfaces as 400."""
        monkeypatch.setattr(
            ObjectRelationsManager, 'insert_object_relation', _raise(ObjectRelationsManagerInsertError('boom')),
        )

        response = rest_api.post(f'{ROUTE_URL}/', json=_object_relation_payload())

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_list_iteration_error_returns_400(self, rest_api, monkeypatch) -> None:
        """An ObjectRelationsManagerIterationError on list surfaces as 400."""
        monkeypatch.setattr(
            ObjectRelationsManager, 'iterate', _raise(ObjectRelationsManagerIterationError('boom')),
        )

        assert rest_api.get(f'{ROUTE_URL}/').status_code == HTTPStatus.BAD_REQUEST
