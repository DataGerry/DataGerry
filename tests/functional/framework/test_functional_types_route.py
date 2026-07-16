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
Functional smoke for the ``/types`` REST routes

Covers the route-layer concerns that the TypesManager integration suite cannot:
HTTP status codes, schema validation, the uniqueness guard returning 400 on a
duplicate name, the 404 on a missing id, the JSON envelope returned by GET-list,
the PUT round-trip, and the DELETE 200 + follow-up 404. The CRUD behavior itself
is asserted at the manager layer; these tests only verify the route wraps it
correctly
"""
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import TypesManager, ObjectsManager
from cmdb.models.type_model import CmdbType
from cmdb.models.object_model import CmdbObject
from cmdb.interface.rest_api.routes.framework_routes.cmdb_types import types_routes
from cmdb.errors.manager.types_manager import (
    TypesManagerGetError,
    TypesManagerInsertError,
    TypesManagerIterationError,
    TypesManagerUpdateError,
    TypesManagerUpdateMDSError,
    TypesManagerDeleteError,
)
from cmdb.errors.manager.objects_manager import ObjectsManagerGetError, ObjectsManagerUpdateError
from cmdb.errors.manager.locations_manager import LocationsManagerUpdateError
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_URL: str = '/types'

NAME_FIELD: str = 'type-field'
SEED_AUTHOR_ID: int = 1
SEED_VERSION: str = '1.0.0'

TYPE_ID_FOR_CREATE: int = 9701
TYPE_ID_FOR_DUPLICATE: int = 9702
TYPE_ID_FOR_GET: int = 9703
TYPE_ID_FOR_UPDATE: int = 9704
TYPE_ID_FOR_DELETE: int = 9705
TYPE_ID_FOR_SELECTABLE: int = 9706
MISSING_TYPE_ID: int = 9799

# selectable_as_parent guard fixtures
LOCATION_FIELD_NAME: str = 'dg_location'
PLACED_OBJECT_ID: int = 9806
PLACED_PARENT_LOCATION_ID: int = 999

ALL_TYPE_IDS: list[int] = [
    TYPE_ID_FOR_CREATE,
    TYPE_ID_FOR_DUPLICATE,
    TYPE_ID_FOR_GET,
    TYPE_ID_FOR_UPDATE,
    TYPE_ID_FOR_DELETE,
    TYPE_ID_FOR_SELECTABLE,
]

ORIGINAL_LABEL: str = 'Original'
UPDATED_LABEL: str = 'Updated'


def _type_payload(public_id: int, label: str) -> dict[str, Any]:
    """Builds a CmdbType-shaped payload acceptable to POST /types/ and PUT /types/<id>."""
    return {
        'public_id': public_id,
        'name': f'type-{public_id}',
        'label': label,
        'author_id': SEED_AUTHOR_ID,
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


def _type_doc(public_id: int, label: str) -> dict[str, Any]:
    """Builds a complete CmdbType doc for direct DB insertion (bypasses the POST schema validation)."""
    doc = _type_payload(public_id, label)
    doc['creation_time'] = datetime.now(timezone.utc)
    return doc


@pytest.fixture(scope='module', autouse=True)
def _cleanup_types_after_module(database_manager: MongoDatabaseManager, database_name: str):
    """Removes any leftover test types after the module's tests have run."""
    yield
    database_manager.get_collection(CmdbType.COLLECTION, database_name)\
        .delete_many({'public_id': {'$in': ALL_TYPE_IDS}})


def _drop_type(database_manager: MongoDatabaseManager, database_name: str, public_id: int) -> None:
    """Removes a single CmdbType doc directly via the collection, for per-test cleanup."""
    database_manager.get_collection(CmdbType.COLLECTION, database_name).delete_one({'public_id': public_id})


def _insert_type_doc(database_manager: MongoDatabaseManager, database_name: str, public_id: int, label: str) -> None:
    """Inserts a CmdbType doc directly via the collection, bypassing the POST route validation."""
    database_manager.get_collection(CmdbType.COLLECTION, database_name).insert_one(_type_doc(public_id, label))


def _type_payload_with_location(public_id: int, label: str, selectable_as_parent: bool = True) -> dict[str, Any]:
    """Builds a CmdbType payload that carries a location field and a selectable_as_parent flag."""
    payload = _type_payload(public_id, label)
    payload['selectable_as_parent'] = selectable_as_parent
    payload['fields'].append({'type': 'location', 'name': LOCATION_FIELD_NAME, 'label': 'Location'})
    payload['render_meta']['sections'][0]['fields'].append(LOCATION_FIELD_NAME)
    return payload


def _insert_type_doc_with_location(database_manager: MongoDatabaseManager, database_name: str,
                                   public_id: int) -> None:
    """Inserts a CmdbType doc that has a location field and is selectable_as_parent (default True)."""
    doc = _type_payload_with_location(public_id, ORIGINAL_LABEL)
    doc['creation_time'] = datetime.now(timezone.utc)
    database_manager.get_collection(CmdbType.COLLECTION, database_name).insert_one(doc)


def _insert_placed_object(database_manager: MongoDatabaseManager, database_name: str,
                          object_id: int, type_id: int) -> None:
    """Inserts a CmdbObject of the type holding a location value > 0 (i.e. placed in the tree)."""
    database_manager.get_collection(CmdbObject.COLLECTION, database_name).insert_one({
        'public_id': object_id,
        'type_id': type_id,
        'active': True,
        'author_id': SEED_AUTHOR_ID,
        'version': SEED_VERSION,
        'fields': [{'type': 'location', 'name': LOCATION_FIELD_NAME, 'value': PLACED_PARENT_LOCATION_ID}],
        'creation_time': datetime.now(timezone.utc),
    })


def _drop_object(database_manager: MongoDatabaseManager, database_name: str, object_id: int) -> None:
    """Removes a single CmdbObject doc directly via the collection, for per-test cleanup."""
    database_manager.get_collection(CmdbObject.COLLECTION, database_name).delete_one({'public_id': object_id})


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       CREATE                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class TestPostType:
    """POST /types/ creates a new CmdbType and rejects a duplicate name with 400."""

    def test_creates_new_type(
        self,
        rest_api,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """A POST with a fresh public_id + name succeeds; the type is then queryable."""
        try:
            response = rest_api.post(f'{ROUTE_URL}/', json=_type_payload(TYPE_ID_FOR_CREATE, ORIGINAL_LABEL))

            assert response.status_code == HTTPStatus.CREATED
            follow_up = rest_api.get(f'{ROUTE_URL}/{TYPE_ID_FOR_CREATE}')
            assert follow_up.status_code == HTTPStatus.OK
        finally:
            _drop_type(database_manager, database_name, TYPE_ID_FOR_CREATE)

    def test_duplicate_name_returns_400(
        self,
        rest_api,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """A POST whose ``name`` already exists is rejected with 400 by the uniqueness guard."""
        _insert_type_doc(database_manager, database_name, TYPE_ID_FOR_DUPLICATE, ORIGINAL_LABEL)
        try:
            # Same name as the seeded doc, different public_id — uniqueness check is on name.
            duplicate_payload = _type_payload(TYPE_ID_FOR_DUPLICATE + 1, ORIGINAL_LABEL)
            duplicate_payload['name'] = f'type-{TYPE_ID_FOR_DUPLICATE}'

            response = rest_api.post(f'{ROUTE_URL}/', json=duplicate_payload)

            assert response.status_code == HTTPStatus.BAD_REQUEST
        finally:
            _drop_type(database_manager, database_name, TYPE_ID_FOR_DUPLICATE)
            _drop_type(database_manager, database_name, TYPE_ID_FOR_DUPLICATE + 1)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       READ                                                           #
# -------------------------------------------------------------------------------------------------------------------- #
class TestGetType:
    """GET /types/<id> and GET /types/ return the expected envelopes."""

    @pytest.fixture(autouse=True)
    def _seed(self, database_manager: MongoDatabaseManager, database_name: str):
        """Inserts one type directly via the DB before each test and removes it after."""
        _insert_type_doc(database_manager, database_name, TYPE_ID_FOR_GET, ORIGINAL_LABEL)
        yield
        _drop_type(database_manager, database_name, TYPE_ID_FOR_GET)

    def test_get_single_returns_type(self, rest_api) -> None:
        """A GET /types/<id> for a seeded type returns 200 and a parseable payload."""
        response = rest_api.get(f'{ROUTE_URL}/{TYPE_ID_FOR_GET}')

        assert response.status_code == HTTPStatus.OK
        body = response.get_json()
        parsed = CmdbType.from_data(body['result'])
        assert parsed.public_id == TYPE_ID_FOR_GET

    def test_get_single_missing_returns_404(self, rest_api) -> None:
        """A GET /types/<id> for a missing id returns 404."""
        response = rest_api.get(f'{ROUTE_URL}/{MISSING_TYPE_ID}')

        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_get_list_returns_results_envelope(self, rest_api) -> None:
        """A GET /types/ returns a JSON envelope whose results length matches X-Total-Count."""
        response = rest_api.get(f'{ROUTE_URL}/')

        assert response.status_code == HTTPStatus.OK
        body = response.get_json()
        assert 'results' in body
        assert len(body['results']) == int(response.headers['X-Total-Count'])


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       UPDATE                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class TestPutType:
    """PUT /types/<id> writes the new payload over the existing CmdbType."""

    def test_update_persists_new_label(
        self,
        rest_api,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """After PUT, GET reflects the updated label."""
        _insert_type_doc(database_manager, database_name, TYPE_ID_FOR_UPDATE, ORIGINAL_LABEL)
        try:
            updated_payload = _type_payload(TYPE_ID_FOR_UPDATE, UPDATED_LABEL)

            response = rest_api.put(f'{ROUTE_URL}/{TYPE_ID_FOR_UPDATE}', json=updated_payload)
            assert response.status_code == HTTPStatus.ACCEPTED

            follow_up = rest_api.get(f'{ROUTE_URL}/{TYPE_ID_FOR_UPDATE}')
            assert follow_up.get_json()['result']['label'] == UPDATED_LABEL
        finally:
            _drop_type(database_manager, database_name, TYPE_ID_FOR_UPDATE)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       DELETE                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class TestDeleteType:
    """DELETE /types/<id> removes the doc; a follow-up GET reports 404."""

    def test_delete_removes_type(
        self,
        rest_api,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """A DELETE succeeds, and a subsequent GET for the same id returns 404."""
        _insert_type_doc(database_manager, database_name, TYPE_ID_FOR_DELETE, ORIGINAL_LABEL)
        try:
            response = rest_api.delete(f'{ROUTE_URL}/{TYPE_ID_FOR_DELETE}')

            assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
            follow_up = rest_api.get(f'{ROUTE_URL}/{TYPE_ID_FOR_DELETE}')
            assert follow_up.status_code == HTTPStatus.NOT_FOUND
        finally:
            _drop_type(database_manager, database_name, TYPE_ID_FOR_DELETE)


# -------------------------------------------------------------------------------------------------------------------- #
#                                            READ EXTRAS (happy paths)                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class TestTypeReadExtras:
    """The clean-status listing, location-field usage and object-count read routes."""

    def test_with_clean_status_returns_items(self, rest_api, database_manager, database_name) -> None:
        """GET /with_clean_status returns 200 with a list of clean-status items."""
        _insert_type_doc(database_manager, database_name, TYPE_ID_FOR_GET, ORIGINAL_LABEL)
        try:
            response = rest_api.get(f'{ROUTE_URL}/with_clean_status')

            assert response.status_code == HTTPStatus.OK
            assert isinstance(response.get_json()['results'], list)
        finally:
            _drop_type(database_manager, database_name, TYPE_ID_FOR_GET)

    def test_location_field_usage_not_in_use(self, rest_api, database_manager, database_name) -> None:
        """A type with no location field reports in_use False and count 0."""
        _insert_type_doc(database_manager, database_name, TYPE_ID_FOR_GET, ORIGINAL_LABEL)
        try:
            response = rest_api.get(f'{ROUTE_URL}/location_field_usage/{TYPE_ID_FOR_GET}')

            assert response.status_code == HTTPStatus.OK
            body = response.get_json()
            assert body['in_use'] is False
            assert body['count'] == 0
        finally:
            _drop_type(database_manager, database_name, TYPE_ID_FOR_GET)

    def test_count_objects_zero_for_fresh_type(self, rest_api, database_manager, database_name) -> None:
        """A type with no objects reports a count of 0."""
        _insert_type_doc(database_manager, database_name, TYPE_ID_FOR_GET, ORIGINAL_LABEL)
        try:
            response = rest_api.get(f'{ROUTE_URL}/count_objects/{TYPE_ID_FOR_GET}')

            assert response.status_code == HTTPStatus.OK
            assert response.get_json() == 0
        finally:
            _drop_type(database_manager, database_name, TYPE_ID_FOR_GET)


# -------------------------------------------------------------------------------------------------------------------- #
#                                       SELECTABLE-AS-PARENT GUARD                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
class TestSelectableAsParentGuard:
    """selectable_as_parent may not be turned off while objects of the Type are placed in the tree."""

    def test_usage_in_use_true_when_object_placed(self, rest_api, database_manager, database_name) -> None:
        """The pre-check route reports in_use True when an object of the type holds a location value."""
        _insert_type_doc_with_location(database_manager, database_name, TYPE_ID_FOR_SELECTABLE)
        _insert_placed_object(database_manager, database_name, PLACED_OBJECT_ID, TYPE_ID_FOR_SELECTABLE)
        try:
            response = rest_api.get(f'{ROUTE_URL}/selectable_as_parent_usage/{TYPE_ID_FOR_SELECTABLE}')

            assert response.status_code == HTTPStatus.OK
            body = response.get_json()
            assert body['in_use'] is True
            assert body['count'] == 1
            assert body['object_public_ids'] == [PLACED_OBJECT_ID]
        finally:
            _drop_object(database_manager, database_name, PLACED_OBJECT_ID)
            _drop_type(database_manager, database_name, TYPE_ID_FOR_SELECTABLE)

    def test_usage_false_when_no_object_placed(self, rest_api, database_manager, database_name) -> None:
        """The pre-check route reports in_use False when no object of the type is placed."""
        _insert_type_doc_with_location(database_manager, database_name, TYPE_ID_FOR_SELECTABLE)
        try:
            response = rest_api.get(f'{ROUTE_URL}/selectable_as_parent_usage/{TYPE_ID_FOR_SELECTABLE}')

            assert response.status_code == HTTPStatus.OK
            body = response.get_json()
            assert body['in_use'] is False
            assert body['count'] == 0
        finally:
            _drop_type(database_manager, database_name, TYPE_ID_FOR_SELECTABLE)

    def test_update_blocked_when_disabling_with_placed_object(self, rest_api, database_manager, database_name) -> None:
        """Turning selectable_as_parent off is rejected 400 while an object of the type is placed."""
        _insert_type_doc_with_location(database_manager, database_name, TYPE_ID_FOR_SELECTABLE)
        _insert_placed_object(database_manager, database_name, PLACED_OBJECT_ID, TYPE_ID_FOR_SELECTABLE)
        try:
            payload = _type_payload_with_location(TYPE_ID_FOR_SELECTABLE, ORIGINAL_LABEL, selectable_as_parent=False)

            response = rest_api.put(f'{ROUTE_URL}/{TYPE_ID_FOR_SELECTABLE}', json=payload)

            assert response.status_code == HTTPStatus.BAD_REQUEST
            # the flag is preserved (still selectable) since the update was rejected
            assert rest_api.get(f'{ROUTE_URL}/{TYPE_ID_FOR_SELECTABLE}')\
                .get_json()['result']['selectable_as_parent'] is True
        finally:
            _drop_object(database_manager, database_name, PLACED_OBJECT_ID)
            _drop_type(database_manager, database_name, TYPE_ID_FOR_SELECTABLE)

    def test_update_allowed_when_disabling_without_placed_object(
        self, rest_api, database_manager, database_name,
    ) -> None:
        """Turning selectable_as_parent off succeeds when no object of the type is placed."""
        _insert_type_doc_with_location(database_manager, database_name, TYPE_ID_FOR_SELECTABLE)
        try:
            payload = _type_payload_with_location(TYPE_ID_FOR_SELECTABLE, ORIGINAL_LABEL, selectable_as_parent=False)

            response = rest_api.put(f'{ROUTE_URL}/{TYPE_ID_FOR_SELECTABLE}', json=payload)

            assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
            assert rest_api.get(f'{ROUTE_URL}/{TYPE_ID_FOR_SELECTABLE}')\
                .get_json()['result']['selectable_as_parent'] is False
        finally:
            _drop_type(database_manager, database_name, TYPE_ID_FOR_SELECTABLE)


# -------------------------------------------------------------------------------------------------------------------- #
#                                              ERROR MAPPING MATRIX                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
def _raiser(exc: Exception):
    """Returns a function that ignores its args and raises the given exception."""
    def _fail(*_args, **_kwargs):
        raise exc
    return _fail


class TestTypeErrorMapping:
    """Each route maps its manager exceptions to the documented HTTP status codes."""

    # ---- CREATE ---- #
    def test_insert_insert_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A TypesManagerInsertError from insert_type maps POST to 400."""
        monkeypatch.setattr(TypesManager, 'insert_type', _raiser(TypesManagerInsertError('boom')))

        response = rest_api.post(f'{ROUTE_URL}/', json=_type_payload(TYPE_ID_FOR_CREATE, ORIGINAL_LABEL))

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_insert_get_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A TypesManagerGetError raised during the uniqueness check maps POST to 400."""
        monkeypatch.setattr(TypesManager, 'get_type', _raiser(TypesManagerGetError('boom')))

        response = rest_api.post(f'{ROUTE_URL}/', json=_type_payload(TYPE_ID_FOR_CREATE, ORIGINAL_LABEL))

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_insert_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error from insert_type maps POST to 500."""
        monkeypatch.setattr(TypesManager, 'insert_type', _raiser(RuntimeError('boom')))

        response = rest_api.post(f'{ROUTE_URL}/', json=_type_payload(TYPE_ID_FOR_CREATE, ORIGINAL_LABEL))

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    # ---- READ ---- #
    def test_list_iteration_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A TypesManagerIterationError from iterate maps the list route to 400."""
        monkeypatch.setattr(TypesManager, 'iterate', _raiser(TypesManagerIterationError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/').status_code == HTTPStatus.BAD_REQUEST

    def test_with_clean_status_iteration_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A TypesManagerIterationError maps the clean-status route to 400."""
        monkeypatch.setattr(TypesManager, 'iterate', _raiser(TypesManagerIterationError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/with_clean_status').status_code == HTTPStatus.BAD_REQUEST

    def test_with_clean_status_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error maps the clean-status route to 500."""
        monkeypatch.setattr(TypesManager, 'iterate', _raiser(RuntimeError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/with_clean_status').status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_get_single_get_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A TypesManagerGetError from get_type maps the single-get route to 400."""
        monkeypatch.setattr(TypesManager, 'get_type', _raiser(TypesManagerGetError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/{MISSING_TYPE_ID}').status_code == HTTPStatus.BAD_REQUEST

    def test_get_single_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error from get_type maps the single-get route to 500."""
        monkeypatch.setattr(TypesManager, 'get_type', _raiser(RuntimeError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/{MISSING_TYPE_ID}').status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_count_objects_get_error_returns_400(self, rest_api, monkeypatch) -> None:
        """An ObjectsManagerGetError from count_documents maps the count route to 400."""
        monkeypatch.setattr(ObjectsManager, 'count_documents', _raiser(ObjectsManagerGetError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/count_objects/{MISSING_TYPE_ID}').status_code == HTTPStatus.BAD_REQUEST

    def test_count_objects_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error from count_documents maps the count route to 500."""
        monkeypatch.setattr(ObjectsManager, 'count_documents', _raiser(RuntimeError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/count_objects/{MISSING_TYPE_ID}').status_code \
            == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_location_field_usage_get_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A TypesManagerGetError while resolving the type maps the usage route to 400."""
        monkeypatch.setattr(TypesManager, 'get_type', _raiser(TypesManagerGetError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/location_field_usage/{MISSING_TYPE_ID}').status_code \
            == HTTPStatus.BAD_REQUEST

    # ---- UPDATE ---- #
    def test_update_get_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A TypesManagerGetError from the update lookup maps PUT to 400."""
        monkeypatch.setattr(TypesManager, 'get_type', _raiser(TypesManagerGetError('boom')))

        response = rest_api.put(f'{ROUTE_URL}/{MISSING_TYPE_ID}', json=_type_payload(MISSING_TYPE_ID, UPDATED_LABEL))

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_update_update_error_returns_400(self, rest_api, monkeypatch, database_manager, database_name) -> None:
        """A TypesManagerUpdateError while persisting maps PUT to 400."""
        _insert_type_doc(database_manager, database_name, TYPE_ID_FOR_UPDATE, ORIGINAL_LABEL)
        monkeypatch.setattr(TypesManager, 'update_type', _raiser(TypesManagerUpdateError('boom')))

        try:
            response = rest_api.put(
                f'{ROUTE_URL}/{TYPE_ID_FOR_UPDATE}', json=_type_payload(TYPE_ID_FOR_UPDATE, UPDATED_LABEL)
            )
            assert response.status_code == HTTPStatus.BAD_REQUEST
        finally:
            _drop_type(database_manager, database_name, TYPE_ID_FOR_UPDATE)

    def test_update_unexpected_error_returns_500(self, rest_api, monkeypatch, database_manager, database_name) -> None:
        """An unexpected error while persisting maps PUT to 500."""
        _insert_type_doc(database_manager, database_name, TYPE_ID_FOR_UPDATE, ORIGINAL_LABEL)
        monkeypatch.setattr(TypesManager, 'update_type', _raiser(RuntimeError('boom')))

        try:
            response = rest_api.put(
                f'{ROUTE_URL}/{TYPE_ID_FOR_UPDATE}', json=_type_payload(TYPE_ID_FOR_UPDATE, UPDATED_LABEL)
            )
            assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        finally:
            _drop_type(database_manager, database_name, TYPE_ID_FOR_UPDATE)

    @pytest.mark.parametrize('exc', [
        LocationsManagerUpdateError('boom'),
        ObjectsManagerUpdateError('boom'),
        ObjectsManagerGetError('boom'),
        TypesManagerUpdateMDSError('boom'),
    ])
    def test_update_side_effect_errors_return_400(
        self, rest_api, monkeypatch, database_manager, database_name, exc,
    ) -> None:
        """Each post-update side-effect error family maps PUT to 400 (the Type itself was updated)."""
        _insert_type_doc(database_manager, database_name, TYPE_ID_FOR_UPDATE, ORIGINAL_LABEL)
        monkeypatch.setattr(types_routes, 'apply_type_update_side_effects', _raiser(exc))

        try:
            response = rest_api.put(
                f'{ROUTE_URL}/{TYPE_ID_FOR_UPDATE}', json=_type_payload(TYPE_ID_FOR_UPDATE, UPDATED_LABEL)
            )
            assert response.status_code == HTTPStatus.BAD_REQUEST
        finally:
            _drop_type(database_manager, database_name, TYPE_ID_FOR_UPDATE)

    # ---- DELETE ---- #
    def test_delete_get_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A TypesManagerGetError from the delete lookup maps DELETE to 400."""
        monkeypatch.setattr(TypesManager, 'get_type', _raiser(TypesManagerGetError('boom')))

        assert rest_api.delete(f'{ROUTE_URL}/{MISSING_TYPE_ID}').status_code == HTTPStatus.BAD_REQUEST

    def test_delete_delete_error_returns_400(self, rest_api, monkeypatch, database_manager, database_name) -> None:
        """A TypesManagerDeleteError maps DELETE to 400."""
        _insert_type_doc(database_manager, database_name, TYPE_ID_FOR_DELETE, ORIGINAL_LABEL)
        monkeypatch.setattr(TypesManager, 'delete_type', _raiser(TypesManagerDeleteError('boom')))

        try:
            assert rest_api.delete(f'{ROUTE_URL}/{TYPE_ID_FOR_DELETE}').status_code == HTTPStatus.BAD_REQUEST
        finally:
            _drop_type(database_manager, database_name, TYPE_ID_FOR_DELETE)

    def test_delete_object_count_error_returns_400(
        self, rest_api, monkeypatch, database_manager, database_name,
    ) -> None:
        """An ObjectsManagerGetError while checking deletability maps DELETE to 400."""
        _insert_type_doc(database_manager, database_name, TYPE_ID_FOR_DELETE, ORIGINAL_LABEL)
        monkeypatch.setattr(ObjectsManager, 'count_documents', _raiser(ObjectsManagerGetError('boom')))

        try:
            assert rest_api.delete(f'{ROUTE_URL}/{TYPE_ID_FOR_DELETE}').status_code == HTTPStatus.BAD_REQUEST
        finally:
            _drop_type(database_manager, database_name, TYPE_ID_FOR_DELETE)

    def test_delete_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error from the delete lookup maps DELETE to 500."""
        monkeypatch.setattr(TypesManager, 'get_type', _raiser(RuntimeError('boom')))

        assert rest_api.delete(f'{ROUTE_URL}/{MISSING_TYPE_ID}').status_code == HTTPStatus.INTERNAL_SERVER_ERROR
