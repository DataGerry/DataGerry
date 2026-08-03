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
the missing-relation and parent==child guards on BOTH write verbs, the list envelope, the 404 on a
missing id, the update round-trip with creation_time preservation, the public_id-pin regression, the
stored-document response, the delete + 404-after-delete, the bulk delete with its id validation, the
history side effects (written only after a successful write, best-effort), and the manager-error ->
HTTP-status mapping of every handler. CRUD behavior itself is asserted at the manager layer; these
tests verify the route wraps it correctly.
"""
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any

import pytest

from flask import abort

from cmdb.database import MongoDatabaseManager
from cmdb.manager import ObjectRelationsManager, ObjectRelationLogsManager
from cmdb.models.log_model import CmdbObjectRelationLog
from cmdb.models.relation_model import CmdbRelation
from cmdb.models.object_relation_model import CmdbObjectRelation
from cmdb.errors.manager.object_relation_logs_manager import ObjectRelationLogsManagerBuildError
from cmdb.errors.manager.object_relations_manager import (
    ObjectRelationsManagerInsertError,
    ObjectRelationsManagerIterationError,
    ObjectRelationsManagerGetError,
    ObjectRelationsManagerUpdateError,
    ObjectRelationsManagerDeleteError,
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

OR_ID_FOR_LOGS: int = 77107
OR_ID_FOR_MOVE: int = 77108
OTHER_CHILD_OBJECT_ID: int = 701

ALL_OR_IDS: list[int] = [
    OR_ID_FOR_GET, OR_ID_FOR_UPDATE, OR_ID_FOR_PIN, OR_ID_FOR_DELETE,
    OR_ID_FOR_BULK_A, OR_ID_FOR_BULK_B, FORGED_PUBLIC_ID,
    OR_ID_FOR_LOGS, OR_ID_FOR_MOVE,
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
    """Inserts a CmdbObjectRelation doc directly via the collection, bypassing POST validation.

    Any history a previous test wrote for the same public_id is dropped first, so a test asserting the
    log entries of its relation sees only its own.
    """
    database_manager.get_collection(CmdbObjectRelationLog.COLLECTION, database_name)\
        .delete_many({'object_relation_id': public_id})

    doc = _object_relation_payload(public_id)
    doc['author_id'] = ADMIN_PUBLIC_ID
    doc['creation_time'] = creation_time or SEEDED_CREATION_TIME
    database_manager.get_collection(CmdbObjectRelation.COLLECTION, database_name).insert_one(doc)


def _purge_object_relation(database_manager: MongoDatabaseManager, database_name: str, public_id: int) -> None:
    """Removes a CmdbObjectRelation and every log written for it."""
    database_manager.get_collection(CmdbObjectRelation.COLLECTION, database_name)\
        .delete_one({'public_id': public_id})
    database_manager.get_collection(CmdbObjectRelationLog.COLLECTION, database_name)\
        .delete_many({'object_relation_id': public_id})


def _object_relation_logs(database_manager: MongoDatabaseManager, database_name: str,
                          public_id: int) -> list[str]:
    """Returns the recorded log actions of one CmdbObjectRelation, oldest first."""
    logs = database_manager.get_collection(CmdbObjectRelationLog.COLLECTION, database_name)\
        .find({'object_relation_id': public_id}).sort('public_id', 1)

    return [log['action'] for log in logs]


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
    database_manager.get_collection(CmdbObjectRelationLog.COLLECTION, database_name)\
        .delete_many({'object_relation_id': {'$in': ALL_OR_IDS}})


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

    def test_created_relation_is_logged(self, rest_api, database_manager: MongoDatabaseManager,
                                        database_name: str) -> None:
        """A successful create writes exactly one CREATE entry into the relation's history."""
        response = rest_api.post(f'{ROUTE_URL}/', json=_object_relation_payload())
        created_id = response.get_json()['result_id']
        try:
            assert _object_relation_logs(database_manager, database_name, created_id) == ['CREATE']
        finally:
            _purge_object_relation(database_manager, database_name, created_id)

    def test_a_failing_log_does_not_fail_the_create(self, rest_api, monkeypatch,
                                                    database_manager: MongoDatabaseManager,
                                                    database_name: str) -> None:
        """The history is best-effort: a log failure must not lose the created relation."""
        monkeypatch.setattr(
            ObjectRelationLogsManager, 'build_object_relation_log',
            _raise(ObjectRelationLogsManagerBuildError('boom')),
        )

        response = rest_api.post(f'{ROUTE_URL}/', json=_object_relation_payload())

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.CREATED)
        _purge_object_relation(database_manager, database_name, response.get_json()['result_id'])


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

    def test_update_parent_equals_child_returns_400(self, rest_api,
                                                    database_manager: MongoDatabaseManager,
                                                    database_name: str) -> None:
        """An update may not turn a relation into a self-relation the create route refuses (regression)."""
        _insert_object_relation_doc(database_manager, database_name, OR_ID_FOR_UPDATE)
        try:
            payload = _object_relation_payload(OR_ID_FOR_UPDATE, parent_id=PARENT_OBJECT_ID,
                                               child_id=PARENT_OBJECT_ID)

            response = rest_api.put(f'{ROUTE_URL}/{OR_ID_FOR_UPDATE}', json=payload)

            assert response.status_code == HTTPStatus.BAD_REQUEST
        finally:
            _purge_object_relation(database_manager, database_name, OR_ID_FOR_UPDATE)

    def test_update_missing_relation_returns_400(self, rest_api,
                                                 database_manager: MongoDatabaseManager,
                                                 database_name: str) -> None:
        """An update referencing a CmdbRelation that no longer exists returns 400."""
        _insert_object_relation_doc(database_manager, database_name, OR_ID_FOR_UPDATE)
        try:
            payload = _object_relation_payload(OR_ID_FOR_UPDATE, relation_id=MISSING_RELATION_ID)

            assert rest_api.put(f'{ROUTE_URL}/{OR_ID_FOR_UPDATE}',
                                json=payload).status_code == HTTPStatus.BAD_REQUEST
        finally:
            _purge_object_relation(database_manager, database_name, OR_ID_FOR_UPDATE)

    def test_update_returns_the_stored_document(self, rest_api,
                                                database_manager: MongoDatabaseManager,
                                                database_name: str) -> None:
        """The response is the stored document: the pinned public_id, not the forged body one."""
        _insert_object_relation_doc(database_manager, database_name, OR_ID_FOR_PIN)
        try:
            payload = _object_relation_payload(FORGED_PUBLIC_ID)

            response = rest_api.put(f'{ROUTE_URL}/{OR_ID_FOR_PIN}', json=payload)
            result = response.get_json()['result']

            assert result['public_id'] == OR_ID_FOR_PIN
            assert result['last_edit_time'] is not None
            assert result == rest_api.get(f'{ROUTE_URL}/{OR_ID_FOR_PIN}').get_json()['result']
        finally:
            database_manager.get_collection(CmdbObjectRelation.COLLECTION, database_name)\
                .delete_many({'public_id': {'$in': [OR_ID_FOR_PIN, FORGED_PUBLIC_ID]}})

    def test_update_records_the_editing_user_as_author(self, rest_api,
                                                      database_manager: MongoDatabaseManager,
                                                      database_name: str) -> None:
        """`author_id` doubles as 'who last touched this' - a CmdbObjectRelation has no editor field."""
        _insert_object_relation_doc(database_manager, database_name, OR_ID_FOR_UPDATE)
        try:
            rest_api.put(f'{ROUTE_URL}/{OR_ID_FOR_UPDATE}', json=_object_relation_payload(OR_ID_FOR_UPDATE))

            stored = database_manager.get_collection(CmdbObjectRelation.COLLECTION, database_name)\
                .find_one({'public_id': OR_ID_FOR_UPDATE})
            assert stored['author_id'] == ADMIN_PUBLIC_ID
            assert stored['last_edit_time'] is not None
        finally:
            _purge_object_relation(database_manager, database_name, OR_ID_FOR_UPDATE)

    def test_field_only_update_is_logged_as_one_edit(self, rest_api,
                                                     database_manager: MongoDatabaseManager,
                                                     database_name: str) -> None:
        """Changing only the field values yields a single EDIT entry."""
        _insert_object_relation_doc(database_manager, database_name, OR_ID_FOR_LOGS)
        try:
            payload = _object_relation_payload(OR_ID_FOR_LOGS, field_values=[{'name': 'a', 'value': 'b'}])

            rest_api.put(f'{ROUTE_URL}/{OR_ID_FOR_LOGS}', json=payload)

            assert _object_relation_logs(database_manager, database_name, OR_ID_FOR_LOGS) == ['EDIT']
        finally:
            _purge_object_relation(database_manager, database_name, OR_ID_FOR_LOGS)

    def test_moving_the_relation_is_logged_as_delete_plus_create(self, rest_api,
                                                                 database_manager: MongoDatabaseManager,
                                                                 database_name: str) -> None:
        """Repointing an endpoint is recorded as the old relation's DELETE plus the new one's CREATE."""
        _insert_object_relation_doc(database_manager, database_name, OR_ID_FOR_MOVE)
        try:
            payload = _object_relation_payload(OR_ID_FOR_MOVE, child_id=OTHER_CHILD_OBJECT_ID)

            rest_api.put(f'{ROUTE_URL}/{OR_ID_FOR_MOVE}', json=payload)

            assert sorted(_object_relation_logs(database_manager, database_name, OR_ID_FOR_MOVE)) == [
                'CREATE', 'DELETE',
            ]
        finally:
            _purge_object_relation(database_manager, database_name, OR_ID_FOR_MOVE)

    def test_a_failed_update_writes_no_log(self, rest_api, monkeypatch,
                                           database_manager: MongoDatabaseManager,
                                           database_name: str) -> None:
        """A write that fails must not leave a history entry claiming it happened (regression)."""
        _insert_object_relation_doc(database_manager, database_name, OR_ID_FOR_LOGS)
        monkeypatch.setattr(
            ObjectRelationsManager, 'update_object_relation',
            _raise(ObjectRelationsManagerUpdateError('boom')),
        )
        try:
            response = rest_api.put(f'{ROUTE_URL}/{OR_ID_FOR_LOGS}',
                                    json=_object_relation_payload(OR_ID_FOR_LOGS))

            assert response.status_code == HTTPStatus.BAD_REQUEST
            assert _object_relation_logs(database_manager, database_name, OR_ID_FOR_LOGS) == []
        finally:
            _purge_object_relation(database_manager, database_name, OR_ID_FOR_LOGS)

    def test_a_failing_log_does_not_fail_the_update(self, rest_api, monkeypatch,
                                                    database_manager: MongoDatabaseManager,
                                                    database_name: str) -> None:
        """The history is best-effort on the update path too."""
        _insert_object_relation_doc(database_manager, database_name, OR_ID_FOR_LOGS)
        monkeypatch.setattr(
            ObjectRelationLogsManager, 'build_object_relation_log',
            _raise(ObjectRelationLogsManagerBuildError('boom')),
        )
        try:
            response = rest_api.put(f'{ROUTE_URL}/{OR_ID_FOR_LOGS}',
                                    json=_object_relation_payload(OR_ID_FOR_LOGS))

            assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
        finally:
            _purge_object_relation(database_manager, database_name, OR_ID_FOR_LOGS)

    def test_unusable_data_returns_400(self, rest_api, monkeypatch,
                                       database_manager: MongoDatabaseManager,
                                       database_name: str) -> None:
        """Data the model refuses is a bad request, not an internal error."""
        _insert_object_relation_doc(database_manager, database_name, OR_ID_FOR_UPDATE)
        monkeypatch.setattr(CmdbObjectRelation, 'from_data', staticmethod(_raise(ValueError('boom'))))
        try:
            response = rest_api.put(f'{ROUTE_URL}/{OR_ID_FOR_UPDATE}',
                                    json=_object_relation_payload(OR_ID_FOR_UPDATE))

            assert response.status_code == HTTPStatus.BAD_REQUEST
        finally:
            _purge_object_relation(database_manager, database_name, OR_ID_FOR_UPDATE)

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

    def test_delete_many_accepts_digit_strings(self, rest_api,
                                               database_manager: MongoDatabaseManager,
                                               database_name: str) -> None:
        """A selection sent as strings addresses the same relations as one sent as numbers."""
        _insert_object_relation_doc(database_manager, database_name, OR_ID_FOR_BULK_A)
        try:
            response = rest_api.post(f'{ROUTE_URL}/delete/many', json={'target_ids': [str(OR_ID_FOR_BULK_A)]})

            assert response.status_code == HTTPStatus.OK
            assert rest_api.get(f'{ROUTE_URL}/{OR_ID_FOR_BULK_A}').status_code == HTTPStatus.NOT_FOUND
        finally:
            _purge_object_relation(database_manager, database_name, OR_ID_FOR_BULK_A)

    @pytest.mark.parametrize('target_ids', [[True], [0], [-1], ['abc'], [None], [1.5]],
                             ids=['bool', 'zero', 'negative', 'text', 'none', 'float'])
    def test_delete_many_rejects_unusable_ids(self, rest_api, target_ids: list[Any],
                                              database_manager: MongoDatabaseManager,
                                              database_name: str) -> None:
        """A JSON `true` used to normalise to public_id 1 and delete a relation (regression)."""
        _insert_object_relation_doc(database_manager, database_name, OR_ID_FOR_BULK_A)
        try:
            response = rest_api.post(f'{ROUTE_URL}/delete/many', json={'target_ids': target_ids})

            assert response.status_code == HTTPStatus.BAD_REQUEST
            assert rest_api.get(f'{ROUTE_URL}/{OR_ID_FOR_BULK_A}').status_code == HTTPStatus.OK
        finally:
            _purge_object_relation(database_manager, database_name, OR_ID_FOR_BULK_A)

    def test_delete_many_unknown_ids_returns_400(self, rest_api) -> None:
        """A selection that matches nothing is reported instead of answering 'deleted'."""
        response = rest_api.post(f'{ROUTE_URL}/delete/many', json={'target_ids': [MISSING_OR_ID]})

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_delete_many_logs_every_deletion(self, rest_api,
                                             database_manager: MongoDatabaseManager,
                                             database_name: str) -> None:
        """Each deleted relation gets its own DELETE entry, written in one batch."""
        _insert_object_relation_doc(database_manager, database_name, OR_ID_FOR_BULK_A)
        _insert_object_relation_doc(database_manager, database_name, OR_ID_FOR_BULK_B)
        try:
            rest_api.post(f'{ROUTE_URL}/delete/many',
                          json={'target_ids': [OR_ID_FOR_BULK_A, OR_ID_FOR_BULK_B]})

            assert _object_relation_logs(database_manager, database_name, OR_ID_FOR_BULK_A) == ['DELETE']
            assert _object_relation_logs(database_manager, database_name, OR_ID_FOR_BULK_B) == ['DELETE']
        finally:
            _purge_object_relation(database_manager, database_name, OR_ID_FOR_BULK_A)
            _purge_object_relation(database_manager, database_name, OR_ID_FOR_BULK_B)

    def test_a_failing_log_does_not_fail_the_delete(self, rest_api, monkeypatch,
                                                    database_manager: MongoDatabaseManager,
                                                    database_name: str) -> None:
        """The history is best-effort on the delete path too."""
        _insert_object_relation_doc(database_manager, database_name, OR_ID_FOR_DELETE)
        monkeypatch.setattr(
            ObjectRelationLogsManager, 'build_object_relation_log',
            _raise(ObjectRelationLogsManagerBuildError('boom')),
        )
        try:
            response = rest_api.delete(f'{ROUTE_URL}/{OR_ID_FOR_DELETE}')

            assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
        finally:
            _purge_object_relation(database_manager, database_name, OR_ID_FOR_DELETE)

    def test_a_failing_bulk_log_does_not_fail_the_delete(self, rest_api, monkeypatch,
                                                         database_manager: MongoDatabaseManager,
                                                         database_name: str) -> None:
        """A failure while batching the bulk logs must not fail the deletion that happened."""
        _insert_object_relation_doc(database_manager, database_name, OR_ID_FOR_BULK_A)
        monkeypatch.setattr(
            ObjectRelationLogsManager, 'format_object_relation_log_data',
            _raise(ObjectRelationLogsManagerBuildError('boom')),
        )
        try:
            response = rest_api.post(f'{ROUTE_URL}/delete/many', json={'target_ids': [OR_ID_FOR_BULK_A]})

            assert response.status_code == HTTPStatus.OK
            assert rest_api.get(f'{ROUTE_URL}/{OR_ID_FOR_BULK_A}').status_code == HTTPStatus.NOT_FOUND
        finally:
            _purge_object_relation(database_manager, database_name, OR_ID_FOR_BULK_A)


def _raise(exc: Exception):
    """Returns a function that ignores its args and raises the given exception."""
    def _fail(*_args, **_kwargs):
        raise exc
    return _fail


def _abort_418(*_args, **_kwargs):
    """Aborts with a status no handler maps, to prove HTTPExceptions pass through untouched."""
    abort(HTTPStatus.IM_A_TEAPOT)


class TestErrorMapping:
    """The routes map manager failures to the documented HTTP statuses."""

    def test_insert_error_returns_400(self, rest_api, monkeypatch) -> None:
        """An ObjectRelationsManagerInsertError on create surfaces as 400."""
        monkeypatch.setattr(
            ObjectRelationsManager, 'insert_object_relation', _raise(ObjectRelationsManagerInsertError('boom')),
        )

        response = rest_api.post(f'{ROUTE_URL}/', json=_object_relation_payload())

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_insert_read_back_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A failing read-back of the created relation surfaces as 400."""
        monkeypatch.setattr(
            ObjectRelationsManager, 'get_object_relation', _raise(ObjectRelationsManagerGetError('boom')),
        )

        assert rest_api.post(f'{ROUTE_URL}/',
                             json=_object_relation_payload()).status_code == HTTPStatus.BAD_REQUEST

    def test_insert_unreadable_creation_returns_404(self, rest_api, monkeypatch,
                                                    database_manager: MongoDatabaseManager,
                                                    database_name: str) -> None:
        """A created relation that cannot be read back is reported as 404, not as a success."""
        monkeypatch.setattr(ObjectRelationsManager, 'get_object_relation', lambda *_args, **_kwargs: None)

        response = rest_api.post(f'{ROUTE_URL}/', json=_object_relation_payload())

        assert response.status_code == HTTPStatus.NOT_FOUND
        database_manager.get_collection(CmdbObjectRelation.COLLECTION, database_name)\
            .delete_many({'relation_id': RELATION_ID, 'public_id': {'$nin': ALL_OR_IDS}})

    def test_insert_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An error nobody anticipated on create surfaces as 500."""
        monkeypatch.setattr(ObjectRelationsManager, 'insert_object_relation', _raise(RuntimeError('boom')))

        assert rest_api.post(f'{ROUTE_URL}/',
                             json=_object_relation_payload()).status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_list_iteration_error_returns_400(self, rest_api, monkeypatch) -> None:
        """An ObjectRelationsManagerIterationError on list surfaces as 400."""
        monkeypatch.setattr(
            ObjectRelationsManager, 'iterate', _raise(ObjectRelationsManagerIterationError('boom')),
        )

        assert rest_api.get(f'{ROUTE_URL}/').status_code == HTTPStatus.BAD_REQUEST

    def test_list_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An error nobody anticipated on list surfaces as 500."""
        monkeypatch.setattr(ObjectRelationsManager, 'iterate', _raise(RuntimeError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/').status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_list_passes_an_http_exception_through(self, rest_api, monkeypatch) -> None:
        """An HTTPException raised inside the handler keeps its status instead of becoming a 500."""
        monkeypatch.setattr(ObjectRelationsManager, 'iterate', _abort_418)

        assert rest_api.get(f'{ROUTE_URL}/').status_code == HTTPStatus.IM_A_TEAPOT

    def test_get_single_error_returns_400(self, rest_api, monkeypatch) -> None:
        """An ObjectRelationsManagerGetError on the single read surfaces as 400."""
        monkeypatch.setattr(
            ObjectRelationsManager, 'get_object_relation', _raise(ObjectRelationsManagerGetError('boom')),
        )

        assert rest_api.get(f'{ROUTE_URL}/{MISSING_OR_ID}').status_code == HTTPStatus.BAD_REQUEST

    def test_get_single_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An error nobody anticipated on the single read surfaces as 500."""
        monkeypatch.setattr(ObjectRelationsManager, 'get_object_relation', _raise(RuntimeError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/{MISSING_OR_ID}').status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_update_read_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A failing read of the relation to update surfaces as 400."""
        monkeypatch.setattr(
            ObjectRelationsManager, 'get_object_relation', _raise(ObjectRelationsManagerGetError('boom')),
        )

        assert rest_api.put(f'{ROUTE_URL}/{MISSING_OR_ID}',
                            json=_object_relation_payload(MISSING_OR_ID)).status_code == HTTPStatus.BAD_REQUEST

    def test_update_error_returns_400(self, rest_api, monkeypatch,
                                      database_manager: MongoDatabaseManager, database_name: str) -> None:
        """An ObjectRelationsManagerUpdateError surfaces as 400."""
        _insert_object_relation_doc(database_manager, database_name, OR_ID_FOR_UPDATE)
        monkeypatch.setattr(
            ObjectRelationsManager, 'update_object_relation', _raise(ObjectRelationsManagerUpdateError('boom')),
        )
        try:
            assert rest_api.put(f'{ROUTE_URL}/{OR_ID_FOR_UPDATE}',
                                json=_object_relation_payload(OR_ID_FOR_UPDATE)).status_code \
                == HTTPStatus.BAD_REQUEST
        finally:
            _purge_object_relation(database_manager, database_name, OR_ID_FOR_UPDATE)

    def test_update_unexpected_error_returns_500(self, rest_api, monkeypatch,
                                                 database_manager: MongoDatabaseManager,
                                                 database_name: str) -> None:
        """An error nobody anticipated on update surfaces as 500."""
        _insert_object_relation_doc(database_manager, database_name, OR_ID_FOR_UPDATE)
        monkeypatch.setattr(ObjectRelationsManager, 'update_object_relation', _raise(RuntimeError('boom')))
        try:
            assert rest_api.put(f'{ROUTE_URL}/{OR_ID_FOR_UPDATE}',
                                json=_object_relation_payload(OR_ID_FOR_UPDATE)).status_code \
                == HTTPStatus.INTERNAL_SERVER_ERROR
        finally:
            _purge_object_relation(database_manager, database_name, OR_ID_FOR_UPDATE)

    def test_delete_error_returns_400(self, rest_api, monkeypatch,
                                      database_manager: MongoDatabaseManager, database_name: str) -> None:
        """An ObjectRelationsManagerDeleteError on the single delete surfaces as 400."""
        _insert_object_relation_doc(database_manager, database_name, OR_ID_FOR_DELETE)
        monkeypatch.setattr(
            ObjectRelationsManager, 'delete_object_relation', _raise(ObjectRelationsManagerDeleteError('boom')),
        )
        try:
            assert rest_api.delete(f'{ROUTE_URL}/{OR_ID_FOR_DELETE}').status_code == HTTPStatus.BAD_REQUEST
        finally:
            _purge_object_relation(database_manager, database_name, OR_ID_FOR_DELETE)

    def test_delete_read_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A failing read of the relation to delete surfaces as 400."""
        monkeypatch.setattr(
            ObjectRelationsManager, 'get_object_relation', _raise(ObjectRelationsManagerGetError('boom')),
        )

        assert rest_api.delete(f'{ROUTE_URL}/{MISSING_OR_ID}').status_code == HTTPStatus.BAD_REQUEST

    def test_delete_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An error nobody anticipated on the single delete surfaces as 500."""
        monkeypatch.setattr(ObjectRelationsManager, 'get_object_relation', _raise(RuntimeError('boom')))

        assert rest_api.delete(f'{ROUTE_URL}/{MISSING_OR_ID}').status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_delete_many_error_returns_400(self, rest_api, monkeypatch,
                                           database_manager: MongoDatabaseManager, database_name: str) -> None:
        """An ObjectRelationsManagerDeleteError on the bulk delete surfaces as 400, like the single one."""
        _insert_object_relation_doc(database_manager, database_name, OR_ID_FOR_BULK_A)
        monkeypatch.setattr(
            ObjectRelationsManager, 'delete_many', _raise(ObjectRelationsManagerDeleteError('boom')),
        )
        try:
            assert rest_api.post(f'{ROUTE_URL}/delete/many',
                                 json={'target_ids': [OR_ID_FOR_BULK_A]}).status_code == HTTPStatus.BAD_REQUEST
        finally:
            _purge_object_relation(database_manager, database_name, OR_ID_FOR_BULK_A)

    def test_delete_many_unexpected_error_returns_500(self, rest_api, monkeypatch,
                                                      database_manager: MongoDatabaseManager,
                                                      database_name: str) -> None:
        """An error nobody anticipated on the bulk delete surfaces as 500."""
        _insert_object_relation_doc(database_manager, database_name, OR_ID_FOR_BULK_A)
        monkeypatch.setattr(ObjectRelationsManager, 'find', _raise(RuntimeError('boom')))
        try:
            assert rest_api.post(f'{ROUTE_URL}/delete/many',
                                 json={'target_ids': [OR_ID_FOR_BULK_A]}).status_code \
                == HTTPStatus.INTERNAL_SERVER_ERROR
        finally:
            _purge_object_relation(database_manager, database_name, OR_ID_FOR_BULK_A)
