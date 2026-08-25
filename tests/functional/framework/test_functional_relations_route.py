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
Functional smoke for the ``/relations`` REST routes

Covers the route-layer contract: the create round-trip, the list envelope, the 404 on a missing
id, the update round-trip, the public_id-pin regression (a forged body public_id must not rewrite
the document identity), the server-owned public_id on create, the type-existence guard, the delete +
404-after-delete, and the in-use guard (deleting a relation referenced by a CmdbObjectRelation is
refused with 400). The error-mapping class drives every documented status of the five handlers,
including the two partial-application cases where the relation was written but its cascade failed.
CRUD behavior itself is asserted at the manager layer; these tests verify the route wraps it
correctly.
"""
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import RelationsManager, ObjectRelationsManager, CiExplorerProfileManager, TypesManager
from cmdb.models.relation_model import CmdbRelation
from cmdb.models.object_relation_model import CmdbObjectRelation
from cmdb.models.type_model.cmdb_type import CmdbType
from cmdb.errors.manager import BaseManagerGetError, BaseManagerUpdateError
from cmdb.errors.manager.ci_explorer_profile_manager import CiExplorerProfileManagerUpdateError
from cmdb.errors.manager.relations_manager import (
    RelationsManagerInsertError,
    RelationsManagerGetError,
    RelationsManagerIterationError,
    RelationsManagerUpdateError,
    RelationsManagerDeleteError,
)
from cmdb.errors.manager.types_manager import TypesManagerGetError
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_URL: str = '/relations'

# Dedicated type ids so seeding them cannot collide with the types other modules seed
PARENT_TYPE_ID: int = 79101
CHILD_TYPE_ID: int = 79102
REMOVED_CHILD_TYPE_ID: int = 79103
UNKNOWN_TYPE_ID: int = 79199

ALL_TYPE_IDS: list[int] = [PARENT_TYPE_ID, CHILD_TYPE_ID, REMOVED_CHILD_TYPE_ID]

REL_ID_FOR_CREATE: int = 79001
REL_ID_FOR_GET: int = 79002
REL_ID_FOR_UPDATE: int = 79003
REL_ID_FOR_PIN: int = 79004
REL_ID_FOR_DELETE: int = 79005
REL_ID_FOR_INUSE: int = 79006
FORGED_PUBLIC_ID: int = 79999
MISSING_REL_ID: int = 79900

OBJECT_RELATION_ID: int = 78001

ALL_REL_IDS: list[int] = [
    REL_ID_FOR_CREATE,
    REL_ID_FOR_GET,
    REL_ID_FOR_UPDATE,
    REL_ID_FOR_PIN,
    REL_ID_FOR_DELETE,
    REL_ID_FOR_INUSE,
    FORGED_PUBLIC_ID,
]


def _relation_payload(public_id: int | None = None,
                      parent_ids: list[int] | None = None,
                      child_ids: list[int] | None = None) -> dict[str, Any]:
    """Builds a CmdbRelation payload acceptable to POST/PUT (public_id optional)."""
    payload: dict[str, Any] = {
        'relation_name': f'rel-{public_id or "new"}',
        'relation_name_parent': 'is-parent-of',
        'relation_name_child': 'is-child-of',
        'parent_type_ids': parent_ids if parent_ids is not None else [PARENT_TYPE_ID],
        'child_type_ids': child_ids if child_ids is not None else [CHILD_TYPE_ID],
        'sections': [],
        'fields': [],
    }

    if public_id is not None:
        payload['public_id'] = public_id

    return payload


def _insert_relation_doc(database_manager: MongoDatabaseManager, database_name: str, public_id: int) -> None:
    """Inserts a CmdbRelation doc directly via the collection, bypassing POST validation."""
    database_manager.get_collection(CmdbRelation.COLLECTION, database_name)\
        .insert_one(_relation_payload(public_id))


@pytest.fixture(scope='module', autouse=True)
def _seed_referenced_types(database_manager: MongoDatabaseManager, database_name: str):
    """
    Seeds the CmdbTypes the relation payloads reference

    The routes refuse a relation whose parent / child types do not exist, so the ids used by these
    payloads must be backed by real type documents. Only the public_id is read (the existence check
    is a distinct on it), so a minimal document is enough.
    """
    types_collection = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    types_collection.insert_many([
        {'public_id': type_id, 'name': f'relation-test-type-{type_id}', 'label': f'Type {type_id}'}
        for type_id in ALL_TYPE_IDS
    ])
    yield
    types_collection.delete_many({'public_id': {'$in': ALL_TYPE_IDS}})


@pytest.fixture(scope='module', autouse=True)
def _cleanup_relations_after_module(database_manager: MongoDatabaseManager, database_name: str):
    """Removes any leftover test relations / object relations after the module's tests have run."""
    yield
    database_manager.get_collection(CmdbRelation.COLLECTION, database_name)\
        .delete_many({'public_id': {'$in': ALL_REL_IDS}})
    database_manager.get_collection(CmdbObjectRelation.COLLECTION, database_name)\
        .delete_many({'public_id': OBJECT_RELATION_ID})


class TestPostRelation:
    """POST /relations/ creates a new CmdbRelation."""

    def test_creates_and_is_retrievable(self, rest_api,
                                        database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A POST returns 200/201 and the created relation is then retrievable."""
        try:
            response = rest_api.post(f'{ROUTE_URL}/', json=_relation_payload(REL_ID_FOR_CREATE))

            assert response.status_code in (HTTPStatus.OK, HTTPStatus.CREATED)
            created_id = response.get_json()['result_id']
            follow_up = rest_api.get(f'{ROUTE_URL}/{created_id}')
            assert follow_up.status_code == HTTPStatus.OK
        finally:
            database_manager.get_collection(CmdbRelation.COLLECTION, database_name)\
                .delete_many({'relation_name': f'rel-{REL_ID_FOR_CREATE}'})

    def test_creates_without_fields(self, rest_api,
                                    database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A POST omitting the optional 'fields' succeeds (regression: schema 'default: None' rejected it)."""
        payload = _relation_payload(REL_ID_FOR_CREATE)
        payload.pop('fields')
        try:
            response = rest_api.post(f'{ROUTE_URL}/', json=payload)

            assert response.status_code in (HTTPStatus.OK, HTTPStatus.CREATED)
        finally:
            database_manager.get_collection(CmdbRelation.COLLECTION, database_name)\
                .delete_many({'relation_name': f'rel-{REL_ID_FOR_CREATE}'})

    def test_ignores_a_public_id_from_the_payload(self, rest_api,
                                                 database_manager: MongoDatabaseManager,
                                                 database_name: str) -> None:
        """The public_id is server-owned: a payload may not choose the new relation's id."""
        try:
            response = rest_api.post(f'{ROUTE_URL}/', json=_relation_payload(FORGED_PUBLIC_ID))

            assert response.status_code in (HTTPStatus.OK, HTTPStatus.CREATED)
            assert response.get_json()['result_id'] != FORGED_PUBLIC_ID
            assert rest_api.get(f'{ROUTE_URL}/{FORGED_PUBLIC_ID}').status_code == HTTPStatus.NOT_FOUND
        finally:
            database_manager.get_collection(CmdbRelation.COLLECTION, database_name)\
                .delete_many({'relation_name': f'rel-{FORGED_PUBLIC_ID}'})

    def test_unknown_parent_type_returns_400(self, rest_api) -> None:
        """A relation whose parent type does not exist is refused instead of stored."""
        payload = _relation_payload(parent_ids=[UNKNOWN_TYPE_ID])

        response = rest_api.post(f'{ROUTE_URL}/', json=payload)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert str(UNKNOWN_TYPE_ID) in response.get_json()['message']

    def test_unknown_child_type_returns_400(self, rest_api) -> None:
        """A relation whose child type does not exist is refused instead of stored."""
        response = rest_api.post(f'{ROUTE_URL}/', json=_relation_payload(child_ids=[UNKNOWN_TYPE_ID]))

        assert response.status_code == HTTPStatus.BAD_REQUEST


class TestGetRelation:
    """GET /relations/<id> and GET /relations/ envelopes."""

    @pytest.fixture(autouse=True)
    def _seed(self, database_manager: MongoDatabaseManager, database_name: str):
        _insert_relation_doc(database_manager, database_name, REL_ID_FOR_GET)
        yield
        database_manager.get_collection(CmdbRelation.COLLECTION, database_name)\
            .delete_one({'public_id': REL_ID_FOR_GET})

    def test_get_single_returns_relation(self, rest_api) -> None:
        """A known relation id returns 200 with the matching relation."""
        response = rest_api.get(f'{ROUTE_URL}/{REL_ID_FOR_GET}')

        assert response.status_code == HTTPStatus.OK
        assert response.get_json()['result']['public_id'] == REL_ID_FOR_GET

    def test_get_single_missing_returns_404(self, rest_api) -> None:
        """A missing relation id returns 404."""
        response = rest_api.get(f'{ROUTE_URL}/{MISSING_REL_ID}')

        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_get_list_returns_results_envelope(self, rest_api) -> None:
        """GET /relations/ returns a results envelope matching X-Total-Count."""
        response = rest_api.get(f'{ROUTE_URL}/')

        assert response.status_code == HTTPStatus.OK
        body = response.get_json()
        assert 'results' in body
        assert len(body['results']) == int(response.headers['X-Total-Count'])

    def test_head_list_answers_without_a_body(self, rest_api) -> None:
        """HEAD /relations/ serves the counting headers but no payload."""
        response = rest_api.head(f'{ROUTE_URL}/')

        assert response.status_code == HTTPStatus.OK
        assert 'X-Total-Count' in response.headers
        assert response.data == b''

    def test_head_single_answers_without_a_body(self, rest_api) -> None:
        """HEAD /relations/<id> answers for an existing relation without a payload."""
        response = rest_api.head(f'{ROUTE_URL}/{REL_ID_FOR_GET}')

        assert response.status_code == HTTPStatus.OK
        assert response.data == b''


class TestUpdateRelation:
    """PUT /relations/<id> updates a CmdbRelation."""

    def test_update_persists_new_name(self, rest_api,
                                      database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A PUT updates the relation and the change is retrievable."""
        _insert_relation_doc(database_manager, database_name, REL_ID_FOR_UPDATE)
        try:
            payload = _relation_payload(REL_ID_FOR_UPDATE)
            payload['relation_name'] = 'renamed'

            response = rest_api.put(f'{ROUTE_URL}/{REL_ID_FOR_UPDATE}', json=payload)

            assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
            follow_up = rest_api.get(f'{ROUTE_URL}/{REL_ID_FOR_UPDATE}')
            assert follow_up.get_json()['result']['relation_name'] == 'renamed'
        finally:
            database_manager.get_collection(CmdbRelation.COLLECTION, database_name)\
                .delete_one({'public_id': REL_ID_FOR_UPDATE})

    def test_update_missing_returns_404(self, rest_api) -> None:
        """A PUT against a missing relation returns 404."""
        response = rest_api.put(f'{ROUTE_URL}/{MISSING_REL_ID}', json=_relation_payload(MISSING_REL_ID))

        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_update_with_unknown_type_returns_400(self, rest_api,
                                                 database_manager: MongoDatabaseManager,
                                                 database_name: str) -> None:
        """An update may not move a relation onto a CmdbType that does not exist."""
        _insert_relation_doc(database_manager, database_name, REL_ID_FOR_UPDATE)
        try:
            payload = _relation_payload(REL_ID_FOR_UPDATE, child_ids=[UNKNOWN_TYPE_ID])

            response = rest_api.put(f'{ROUTE_URL}/{REL_ID_FOR_UPDATE}', json=payload)

            assert response.status_code == HTTPStatus.BAD_REQUEST
            # The stored relation is untouched
            stored = rest_api.get(f'{ROUTE_URL}/{REL_ID_FOR_UPDATE}').get_json()['result']
            assert stored['child_type_ids'] == [CHILD_TYPE_ID]
        finally:
            database_manager.get_collection(CmdbRelation.COLLECTION, database_name)\
                .delete_one({'public_id': REL_ID_FOR_UPDATE})

    def test_update_deletes_object_relations_of_a_removed_type(self, rest_api,
                                                              database_manager: MongoDatabaseManager,
                                                              database_name: str) -> None:
        """Dropping a child type from the definition deletes the instances that used it."""
        relations = database_manager.get_collection(CmdbRelation.COLLECTION, database_name)
        object_relations = database_manager.get_collection(CmdbObjectRelation.COLLECTION, database_name)

        relations.insert_one(
            _relation_payload(REL_ID_FOR_UPDATE, child_ids=[CHILD_TYPE_ID, REMOVED_CHILD_TYPE_ID])
        )
        object_relations.insert_one({
            'public_id': OBJECT_RELATION_ID,
            'relation_id': REL_ID_FOR_UPDATE,
            'relation_child_type_id': REMOVED_CHILD_TYPE_ID,
        })
        try:
            payload = _relation_payload(REL_ID_FOR_UPDATE, child_ids=[CHILD_TYPE_ID])

            response = rest_api.put(f'{ROUTE_URL}/{REL_ID_FOR_UPDATE}', json=payload)

            assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
            assert object_relations.find_one({'public_id': OBJECT_RELATION_ID}) is None
        finally:
            relations.delete_one({'public_id': REL_ID_FOR_UPDATE})
            object_relations.delete_one({'public_id': OBJECT_RELATION_ID})

    def test_update_pins_public_id_to_the_url(self, rest_api,
                                             database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A forged body public_id must not rewrite the document identity (regression)."""
        _insert_relation_doc(database_manager, database_name, REL_ID_FOR_PIN)
        try:
            payload = _relation_payload(FORGED_PUBLIC_ID)  # body carries a different public_id

            response = rest_api.put(f'{ROUTE_URL}/{REL_ID_FOR_PIN}', json=payload)

            assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
            # The URL id still exists; the forged id was never created
            assert rest_api.get(f'{ROUTE_URL}/{REL_ID_FOR_PIN}').status_code == HTTPStatus.OK
            assert rest_api.get(f'{ROUTE_URL}/{FORGED_PUBLIC_ID}').status_code == HTTPStatus.NOT_FOUND
        finally:
            database_manager.get_collection(CmdbRelation.COLLECTION, database_name)\
                .delete_many({'public_id': {'$in': [REL_ID_FOR_PIN, FORGED_PUBLIC_ID]}})


class TestDeleteRelation:
    """DELETE /relations/<id> removes a CmdbRelation, guarding in-use relations."""

    def test_delete_removes_relation(self, rest_api,
                                    database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A DELETE removes the relation and a subsequent GET returns 404."""
        _insert_relation_doc(database_manager, database_name, REL_ID_FOR_DELETE)
        try:
            response = rest_api.delete(f'{ROUTE_URL}/{REL_ID_FOR_DELETE}')

            assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
            assert rest_api.get(f'{ROUTE_URL}/{REL_ID_FOR_DELETE}').status_code == HTTPStatus.NOT_FOUND
        finally:
            database_manager.get_collection(CmdbRelation.COLLECTION, database_name)\
                .delete_one({'public_id': REL_ID_FOR_DELETE})

    def test_delete_missing_returns_404(self, rest_api) -> None:
        """Deleting a non-existent relation returns 404."""
        assert rest_api.delete(f'{ROUTE_URL}/{MISSING_REL_ID}').status_code == HTTPStatus.NOT_FOUND

    def test_delete_in_use_returns_400(self, rest_api,
                                      database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A relation referenced by a CmdbObjectRelation cannot be deleted (400, a business rule)."""
        _insert_relation_doc(database_manager, database_name, REL_ID_FOR_INUSE)
        database_manager.get_collection(CmdbObjectRelation.COLLECTION, database_name)\
            .insert_one({'public_id': OBJECT_RELATION_ID, 'relation_id': REL_ID_FOR_INUSE})
        try:
            response = rest_api.delete(f'{ROUTE_URL}/{REL_ID_FOR_INUSE}')

            assert response.status_code == HTTPStatus.BAD_REQUEST
            # The relation must still exist
            assert rest_api.get(f'{ROUTE_URL}/{REL_ID_FOR_INUSE}').status_code == HTTPStatus.OK
        finally:
            database_manager.get_collection(CmdbRelation.COLLECTION, database_name)\
                .delete_one({'public_id': REL_ID_FOR_INUSE})
            database_manager.get_collection(CmdbObjectRelation.COLLECTION, database_name)\
                .delete_one({'public_id': OBJECT_RELATION_ID})


def _raise(exc: Exception):
    """Returns a function that ignores its args and raises the given exception."""
    def _fail(*_args, **_kwargs):
        raise exc
    return _fail


def _found_relation(*_args, **_kwargs) -> dict[str, Any]:
    """Stands in for RelationsManager.get_relation, reporting an existing relation."""
    return _relation_payload(MISSING_REL_ID)


def _not_in_use(*_args, **_kwargs) -> int:
    """Stands in for the in-use probe, reporting no dependent CmdbObjectRelation."""
    return 0


class TestErrorMapping:
    """The routes map manager failures to the documented HTTP statuses."""

    def test_insert_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A RelationsManagerInsertError on create surfaces as 400."""
        monkeypatch.setattr(RelationsManager, 'insert_relation', _raise(RelationsManagerInsertError('boom')))

        response = rest_api.post(f'{ROUTE_URL}/', json=_relation_payload())

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_insert_read_back_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A RelationsManagerGetError while reading the created relation back surfaces as 400."""
        monkeypatch.setattr(RelationsManager, 'insert_relation', lambda _self, _data: MISSING_REL_ID)
        monkeypatch.setattr(RelationsManager, 'get_relation', _raise(RelationsManagerGetError('boom')))

        assert rest_api.post(f'{ROUTE_URL}/', json=_relation_payload()).status_code == HTTPStatus.BAD_REQUEST

    def test_insert_missing_after_create_returns_500(self, rest_api, monkeypatch) -> None:
        """A created relation that cannot be read back is a server-side inconsistency, not a 404."""
        monkeypatch.setattr(RelationsManager, 'insert_relation', lambda _self, _data: MISSING_REL_ID)
        monkeypatch.setattr(RelationsManager, 'get_relation', lambda _self, _pid: None)

        response = rest_api.post(f'{ROUTE_URL}/', json=_relation_payload())

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_insert_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unmapped failure on create surfaces as 500."""
        monkeypatch.setattr(RelationsManager, 'insert_relation', _raise(RuntimeError('boom')))

        assert rest_api.post(f'{ROUTE_URL}/', json=_relation_payload()).status_code \
               == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_insert_type_validation_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A failed type-existence lookup on create is reported as 400, and nothing is inserted."""
        monkeypatch.setattr(TypesManager, 'get_existing_type_ids', _raise(TypesManagerGetError('boom')))
        monkeypatch.setattr(RelationsManager, 'insert_relation', _raise(AssertionError('must not insert')))

        response = rest_api.post(f'{ROUTE_URL}/', json=_relation_payload())

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert 'Types' in response.get_json()['message']

    def test_update_type_validation_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A failed type-existence lookup on update is reported as 400, and nothing is written."""
        monkeypatch.setattr(RelationsManager, 'get_relation', _found_relation)
        monkeypatch.setattr(TypesManager, 'get_existing_type_ids', _raise(TypesManagerGetError('boom')))
        monkeypatch.setattr(RelationsManager, 'update_relation', _raise(AssertionError('must not update')))

        response = rest_api.put(f'{ROUTE_URL}/{MISSING_REL_ID}', json=_relation_payload(MISSING_REL_ID))

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_list_iteration_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A RelationsManagerIterationError on list surfaces as 400."""
        monkeypatch.setattr(RelationsManager, 'iterate', _raise(RelationsManagerIterationError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/').status_code == HTTPStatus.BAD_REQUEST

    def test_list_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unmapped failure on list surfaces as 500."""
        monkeypatch.setattr(RelationsManager, 'iterate', _raise(RuntimeError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/').status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_get_single_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A RelationsManagerGetError on get-single surfaces as 400."""
        monkeypatch.setattr(RelationsManager, 'get_relation', _raise(RelationsManagerGetError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/{MISSING_REL_ID}').status_code == HTTPStatus.BAD_REQUEST

    def test_get_single_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unmapped failure on get-single surfaces as 500."""
        monkeypatch.setattr(RelationsManager, 'get_relation', _raise(RuntimeError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/{MISSING_REL_ID}').status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_update_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A RelationsManagerUpdateError (after the relation is found) surfaces as 400."""
        monkeypatch.setattr(RelationsManager, 'get_relation', _found_relation)
        monkeypatch.setattr(RelationsManager, 'update_relation', _raise(RelationsManagerUpdateError('boom')))

        response = rest_api.put(f'{ROUTE_URL}/{MISSING_REL_ID}', json=_relation_payload(MISSING_REL_ID))

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_update_lookup_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A RelationsManagerGetError while loading the relation to update surfaces as 400."""
        monkeypatch.setattr(RelationsManager, 'get_relation', _raise(RelationsManagerGetError('boom')))

        response = rest_api.put(f'{ROUTE_URL}/{MISSING_REL_ID}', json=_relation_payload(MISSING_REL_ID))

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_update_cascade_failure_returns_500(self, rest_api, monkeypatch) -> None:
        """The relation is already written when the cascade fails, so the partial application is a 500."""
        monkeypatch.setattr(RelationsManager, 'get_relation', _found_relation)
        monkeypatch.setattr(RelationsManager, 'update_relation', lambda _self, _pid, _data: None)
        monkeypatch.setattr(
            ObjectRelationsManager, 'update_changed_fields', _raise(BaseManagerUpdateError('boom')),
        )

        response = rest_api.put(f'{ROUTE_URL}/{MISSING_REL_ID}', json=_relation_payload(MISSING_REL_ID))

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert 'ObjectRelations' in response.get_json()['message']

    def test_update_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unmapped failure on update surfaces as 500."""
        monkeypatch.setattr(RelationsManager, 'get_relation', _found_relation)
        monkeypatch.setattr(RelationsManager, 'update_relation', _raise(RuntimeError('boom')))

        response = rest_api.put(f'{ROUTE_URL}/{MISSING_REL_ID}', json=_relation_payload(MISSING_REL_ID))

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_delete_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A RelationsManagerDeleteError (relation found, not in use) surfaces as 400."""
        monkeypatch.setattr(RelationsManager, 'get_relation', _found_relation)
        monkeypatch.setattr(ObjectRelationsManager, 'count_documents', _not_in_use)
        monkeypatch.setattr(RelationsManager, 'delete_relation', _raise(RelationsManagerDeleteError('boom')))

        assert rest_api.delete(f'{ROUTE_URL}/{MISSING_REL_ID}').status_code == HTTPStatus.BAD_REQUEST

    def test_delete_lookup_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A RelationsManagerGetError while loading the relation to delete surfaces as 400."""
        monkeypatch.setattr(RelationsManager, 'get_relation', _raise(RelationsManagerGetError('boom')))

        assert rest_api.delete(f'{ROUTE_URL}/{MISSING_REL_ID}').status_code == HTTPStatus.BAD_REQUEST

    def test_delete_in_use_probe_failure_returns_400(self, rest_api, monkeypatch) -> None:
        """A failed in-use probe leaves it unknown whether the delete is allowed: 400, nothing written."""
        monkeypatch.setattr(RelationsManager, 'get_relation', _found_relation)
        monkeypatch.setattr(ObjectRelationsManager, 'count_documents', _raise(BaseManagerGetError('boom')))
        monkeypatch.setattr(RelationsManager, 'delete_relation', _raise(AssertionError('must not delete')))

        response = rest_api.delete(f'{ROUTE_URL}/{MISSING_REL_ID}')

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert 'in use' in response.get_json()['message']

    def test_delete_profile_cleanup_failure_returns_500(self, rest_api, monkeypatch) -> None:
        """The relation is already deleted when the CiExplorerProfile cleanup fails: partial application."""
        monkeypatch.setattr(RelationsManager, 'get_relation', _found_relation)
        monkeypatch.setattr(ObjectRelationsManager, 'count_documents', _not_in_use)
        monkeypatch.setattr(RelationsManager, 'delete_relation', lambda _self, _pid: True)
        monkeypatch.setattr(
            CiExplorerProfileManager, 'remove_relation_from_profiles',
            _raise(CiExplorerProfileManagerUpdateError('boom')),
        )

        response = rest_api.delete(f'{ROUTE_URL}/{MISSING_REL_ID}')

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert 'CI Explorer' in response.get_json()['message']

    def test_delete_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unmapped failure on delete surfaces as 500."""
        monkeypatch.setattr(RelationsManager, 'get_relation', _found_relation)
        monkeypatch.setattr(ObjectRelationsManager, 'count_documents', _not_in_use)
        monkeypatch.setattr(RelationsManager, 'delete_relation', _raise(RuntimeError('boom')))

        assert rest_api.delete(f'{ROUTE_URL}/{MISSING_REL_ID}').status_code == HTTPStatus.INTERNAL_SERVER_ERROR
