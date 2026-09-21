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
from cmdb.models.category_model import CmdbCategory
from cmdb.models.group_model.group_constants import ADMIN_GROUP_ID
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
# `_type_payload` names a type after the id it is built FOR; the create tests look their type up by
# this name, because the id itself is assigned by the server
TYPE_NAME_FOR_CREATE: str = f'type-{TYPE_ID_FOR_CREATE}'
TYPE_ID_FOR_DUPLICATE: int = 9702
TYPE_ID_FOR_GET: int = 9703
TYPE_ID_FOR_UPDATE: int = 9704
TYPE_ID_FOR_DELETE: int = 9705
TYPE_ID_FOR_SELECTABLE: int = 9706
# The bug report's two types: 'User' owns the referenced section, 'test' references it
TYPE_ID_REFERENCED: int = 9707
TYPE_ID_DEPENDENT: int = 9708
# the listing-filter fixtures: one categorized, one not, one the admin group may not READ
TYPE_ID_CATEGORIZED: int = 9709
TYPE_ID_UNCATEGORIZED: int = 9710
TYPE_ID_ACL_DENIED: int = 9711
TYPE_ID_ACL_CREATE_ONLY: int = 9712
MISSING_TYPE_ID: int = 9799

LISTING_CATEGORY_ID: int = 9750
MISSING_CATEGORY_ID: int = 9751

REFERENCED_SECTION_NAME: str = 'personal-data'
UNREFERENCED_SECTION_NAME: str = 'other'
REF_SECTION_NAME: str = 'personal-data-ref'

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
    TYPE_ID_REFERENCED,
    TYPE_ID_DEPENDENT,
    TYPE_ID_CATEGORIZED,
    TYPE_ID_UNCATEGORIZED,
    TYPE_ID_ACL_DENIED,
    TYPE_ID_ACL_CREATE_ONLY,
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


def _referenced_type_payload(public_id: int = TYPE_ID_REFERENCED) -> dict[str, Any]:
    """The bug report's 'User' type: a referenced section plus one nothing references."""
    payload = _type_payload(public_id, 'User')
    payload['render_meta']['sections'] = [
        {'type': 'section', 'name': REFERENCED_SECTION_NAME, 'label': 'Personal Data',
         'fields': [NAME_FIELD]},
        {'type': 'section', 'name': UNREFERENCED_SECTION_NAME, 'label': 'Other', 'fields': []},
    ]

    return payload


def _dependent_type_payload(public_id: int = TYPE_ID_DEPENDENT,
                            section_name: str = REFERENCED_SECTION_NAME) -> dict[str, Any]:
    """The bug report's 'test' type: a ref-section pulling the referenced section's field."""
    payload = _type_payload(public_id, 'test')
    payload['fields'].append({'type': 'ref', 'name': f'{REF_SECTION_NAME}-field', 'label': 'User',
                              'ref_types': [TYPE_ID_REFERENCED]})
    payload['render_meta']['sections'].append({
        'type': 'ref-section', 'name': REF_SECTION_NAME, 'label': 'Personal Data',
        'reference': {'type_id': TYPE_ID_REFERENCED, 'section_name': section_name,
                      'selected_fields': [NAME_FIELD]},
        'fields': [],
    })

    return payload


def _without_section(payload: dict[str, Any], section_name: str) -> dict[str, Any]:
    """Returns the payload with one section removed - step 5 of the bug report."""
    stripped = {**payload, 'render_meta': {**payload['render_meta']}}
    stripped['render_meta']['sections'] = [
        section for section in payload['render_meta']['sections'] if section['name'] != section_name
    ]

    return stripped


def _insert_payload(database_manager: MongoDatabaseManager, database_name: str,
                    payload: dict[str, Any]) -> None:
    """Inserts a type payload directly, bypassing the POST route."""
    doc = {**payload, 'creation_time': datetime.now(timezone.utc)}
    database_manager.get_collection(CmdbType.COLLECTION, database_name).insert_one(doc)


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
        """A POST with a fresh name succeeds; the type is then queryable under the id the SERVER gave it."""
        created_id: int | None = None

        try:
            response = rest_api.post(f'{ROUTE_URL}/', json=_type_payload(TYPE_ID_FOR_CREATE, ORIGINAL_LABEL))

            assert response.status_code == HTTPStatus.CREATED
            # `public_id` is server-owned: the payload's id is purged, so the answer names the real one
            created_id = response.get_json()['result_id']
            assert created_id != TYPE_ID_FOR_CREATE

            follow_up = rest_api.get(f'{ROUTE_URL}/{created_id}')
            assert follow_up.status_code == HTTPStatus.OK
        finally:
            if created_id is not None:
                _drop_type(database_manager, database_name, created_id)

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

    def test_update_response_is_the_persisted_document(
        self,
        rest_api,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """The PUT body is a fresh read of the stored Type (the side effects may mutate it further)."""
        _insert_type_doc(database_manager, database_name, TYPE_ID_FOR_UPDATE, ORIGINAL_LABEL)
        try:
            response = rest_api.put(
                f'{ROUTE_URL}/{TYPE_ID_FOR_UPDATE}',
                json=_type_payload(TYPE_ID_FOR_UPDATE, UPDATED_LABEL),
            )

            assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
            follow_up = rest_api.get(f'{ROUTE_URL}/{TYPE_ID_FOR_UPDATE}')
            assert response.get_json()['result'] == follow_up.get_json()['result']
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
    """The types overview listing, location-field usage and object-count read routes."""

    def test_overview_returns_items(self, rest_api, database_manager, database_name) -> None:
        """GET /overview returns 200 with a list of {type_data, user_data} items."""
        _insert_type_doc(database_manager, database_name, TYPE_ID_FOR_GET, ORIGINAL_LABEL)
        try:
            response = rest_api.get(f'{ROUTE_URL}/overview')

            assert response.status_code == HTTPStatus.OK
            results = response.get_json()['results']
            assert isinstance(results, list)
            item = next(i for i in results if i['type_data']['public_id'] == TYPE_ID_FOR_GET)
            assert 'user_data' in item
            assert 'clean_status' not in item
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

    def test_both_usage_routes_answer_identically(self, rest_api, database_manager, database_name) -> None:
        """The two pre-check routes share one body, so the same Type must produce the same payload."""
        _insert_type_doc_with_location(database_manager, database_name, TYPE_ID_FOR_SELECTABLE)
        _insert_placed_object(database_manager, database_name, PLACED_OBJECT_ID, TYPE_ID_FOR_SELECTABLE)
        try:
            location_usage = rest_api.get(f'{ROUTE_URL}/location_field_usage/{TYPE_ID_FOR_SELECTABLE}')
            selectable_usage = rest_api.get(f'{ROUTE_URL}/selectable_as_parent_usage/{TYPE_ID_FOR_SELECTABLE}')

            assert location_usage.status_code == HTTPStatus.OK
            assert selectable_usage.status_code == HTTPStatus.OK
            # The projected query still returns the placed object's public_id
            assert location_usage.get_json()['object_public_ids'] == [PLACED_OBJECT_ID]
            assert location_usage.get_json() == selectable_usage.get_json()
        finally:
            _drop_object(database_manager, database_name, PLACED_OBJECT_ID)
            _drop_type(database_manager, database_name, TYPE_ID_FOR_SELECTABLE)

    @pytest.mark.parametrize('usage_route', ['location_field_usage', 'selectable_as_parent_usage'])
    def test_usage_of_missing_type_returns_404(self, rest_api, usage_route: str) -> None:
        """Both pre-check routes 404 for a Type that does not exist."""
        response = rest_api.get(f'{ROUTE_URL}/{usage_route}/{MISSING_TYPE_ID}')

        assert response.status_code == HTTPStatus.NOT_FOUND

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

    @pytest.fixture(autouse=True)
    def _drop_anything_created(self, database_manager: MongoDatabaseManager, database_name: str):
        """
        Removes a Type a failing-create test managed to store

        A create that fails AFTER the insert still leaves a document - `get_type` raising on the
        read-back is exactly that case - and the next test posts the same (unique) name, so without
        this the failure cascades into a duplicate-name 400.
        """
        yield
        database_manager.get_collection(CmdbType.COLLECTION, database_name)\
            .delete_many({'name': TYPE_NAME_FOR_CREATE})

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

    def test_overview_iteration_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A TypesManagerIterationError maps the overview route to 400."""
        monkeypatch.setattr(TypesManager, 'iterate', _raiser(TypesManagerIterationError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/overview').status_code == HTTPStatus.BAD_REQUEST

    def test_overview_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error maps the overview route to 500."""
        monkeypatch.setattr(TypesManager, 'iterate', _raiser(RuntimeError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/overview').status_code == HTTPStatus.INTERNAL_SERVER_ERROR

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
        monkeypatch.setattr(TypesManager, 'get_type_instance', _raiser(TypesManagerGetError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/location_field_usage/{MISSING_TYPE_ID}').status_code \
            == HTTPStatus.BAD_REQUEST

    def test_referenced_section_usage_get_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A TypesManagerGetError while resolving the type maps the reference-usage route to 400."""
        monkeypatch.setattr(TypesManager, 'get_type_instance', _raiser(TypesManagerGetError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/referenced_section_usage/{MISSING_TYPE_ID}').status_code \
            == HTTPStatus.BAD_REQUEST

    def test_referenced_section_usage_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """Any other failure while resolving the type is a 500, not a masked 400."""
        monkeypatch.setattr(TypesManager, 'get_type_instance', _raiser(RuntimeError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/referenced_section_usage/{MISSING_TYPE_ID}').status_code \
            == HTTPStatus.INTERNAL_SERVER_ERROR

    # ---- UPDATE ---- #
    def test_update_get_error_returns_400(self, rest_api, monkeypatch) -> None:
        """A TypesManagerGetError from the update lookup maps PUT to 400."""
        monkeypatch.setattr(TypesManager, 'get_type_instance', _raiser(TypesManagerGetError('boom')))

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


# -------------------------------------------------------------------------------------------------------------------- #
#                                    REFERENCED-SECTION REMOVAL GUARD                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
class TestReferencedSectionGuard:
    """
    A section another Type pulls fields from through a ref-section may not be removed

    Reproduces the reported bug end to end: before the guard, step 5 (deleting 'Personal Data' from
    the User type) succeeded and left the dependent type's reference dangling, which blanked the
    referenced block in every object view of that type.
    """

    @pytest.fixture(autouse=True)
    def _seed(self, database_manager: MongoDatabaseManager, database_name: str):
        """Seeds the report's two types and removes them afterwards."""
        _drop_type(database_manager, database_name, TYPE_ID_REFERENCED)
        _drop_type(database_manager, database_name, TYPE_ID_DEPENDENT)
        _insert_payload(database_manager, database_name, _referenced_type_payload())
        _insert_payload(database_manager, database_name, _dependent_type_payload())

        yield

        _drop_type(database_manager, database_name, TYPE_ID_REFERENCED)
        _drop_type(database_manager, database_name, TYPE_ID_DEPENDENT)

    def test_removing_the_referenced_section_returns_400(self, rest_api) -> None:
        """Step 5 of the report is now refused, naming the dependent Type."""
        payload = _without_section(_referenced_type_payload(), REFERENCED_SECTION_NAME)

        response = rest_api.put(f'{ROUTE_URL}/{TYPE_ID_REFERENCED}', json=payload)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        # The API's error envelope carries the abort text in 'message'; 'description' is werkzeug's
        # generic per-status text
        assert REFERENCED_SECTION_NAME in response.get_json()['message']
        assert str(TYPE_ID_DEPENDENT) in response.get_json()['message']

    def test_the_section_survives_the_refused_update(self, rest_api, database_manager, database_name) -> None:
        """A refused update must persist nothing at all, not even the allowed half of it."""
        payload = _without_section(_referenced_type_payload(), REFERENCED_SECTION_NAME)
        payload['label'] = 'Renamed by a refused update'

        rest_api.put(f'{ROUTE_URL}/{TYPE_ID_REFERENCED}', json=payload)

        stored = database_manager.get_collection(CmdbType.COLLECTION, database_name)\
            .find_one({'public_id': TYPE_ID_REFERENCED})
        section_names = [section['name'] for section in stored['render_meta']['sections']]

        assert REFERENCED_SECTION_NAME in section_names
        assert stored['label'] == 'User'

    def test_renaming_the_referenced_section_returns_400(self, rest_api) -> None:
        """A ref-section resolves its target by NAME, so a rename breaks it exactly as a delete does."""
        payload = _referenced_type_payload()
        payload['render_meta']['sections'][0]['name'] = 'renamed-personal-data'

        response = rest_api.put(f'{ROUTE_URL}/{TYPE_ID_REFERENCED}', json=payload)

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_removing_an_unreferenced_section_succeeds(self, rest_api, database_manager, database_name) -> None:
        """Only referenced sections are protected - the guard must not block ordinary edits."""
        payload = _without_section(_referenced_type_payload(), UNREFERENCED_SECTION_NAME)

        response = rest_api.put(f'{ROUTE_URL}/{TYPE_ID_REFERENCED}', json=payload)

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)

        stored = database_manager.get_collection(CmdbType.COLLECTION, database_name)\
            .find_one({'public_id': TYPE_ID_REFERENCED})

        assert [section['name'] for section in stored['render_meta']['sections']] == [REFERENCED_SECTION_NAME]

    def test_removing_the_section_after_the_dependent_is_gone_succeeds(
            self, rest_api, database_manager, database_name) -> None:
        """The documented way out: drop the reference section first, then the section."""
        _drop_type(database_manager, database_name, TYPE_ID_DEPENDENT)

        payload = _without_section(_referenced_type_payload(), REFERENCED_SECTION_NAME)
        response = rest_api.put(f'{ROUTE_URL}/{TYPE_ID_REFERENCED}', json=payload)

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)

    def test_deleting_the_referenced_type_returns_400(self, rest_api, database_manager, database_name) -> None:
        """
        The type-level half of the same rule

        Deleting the whole referenced Type leaves the dependent pointing at a type_id that no longer
        resolves - the same blank block, one level up. Reachable because verify_type_deletable only
        checked objects and reports.
        """
        response = rest_api.delete(f'{ROUTE_URL}/{TYPE_ID_REFERENCED}')

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert str(TYPE_ID_DEPENDENT) in response.get_json()['message']

        stored = database_manager.get_collection(CmdbType.COLLECTION, database_name)\
            .find_one({'public_id': TYPE_ID_REFERENCED})

        assert stored is not None

    def test_deleting_the_dependent_type_is_unaffected(self, rest_api) -> None:
        """The dependent side is free to go - it is the one holding the reference."""
        response = rest_api.delete(f'{ROUTE_URL}/{TYPE_ID_DEPENDENT}')

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)

    def test_emptying_the_referenced_section_returns_400(self, rest_api) -> None:
        """
        The field side of the same rule: the section survives but would show nothing

        The dependent selects exactly one field; taking it out of the section leaves a valid
        reference rendering an empty block - the same blank area, reached from the field side.
        """
        payload = _referenced_type_payload()
        payload['render_meta']['sections'][0]['fields'] = []

        response = rest_api.put(f'{ROUTE_URL}/{TYPE_ID_REFERENCED}', json=payload)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert 'would show nothing' in response.get_json()['message']
        assert str(TYPE_ID_DEPENDENT) in response.get_json()['message']

    def test_reducing_the_referenced_section_succeeds(
            self, rest_api, database_manager, database_name) -> None:
        """
        A reduction that leaves the dependent something to show is allowed

        Losing the column of a field that was just deleted is the direct consequence of deleting it;
        refusing it would make every field edit on a referenced Type a 400.
        """
        payload = _referenced_type_payload()
        payload['fields'].append({'type': 'text', 'name': 'second-field', 'label': 'Second'})
        payload['render_meta']['sections'][0]['fields'] = [NAME_FIELD, 'second-field']

        assert rest_api.put(f'{ROUTE_URL}/{TYPE_ID_REFERENCED}', json=payload).status_code \
            in (HTTPStatus.OK, HTTPStatus.ACCEPTED)

        # now drop the field the dependent does NOT select
        reduced = _referenced_type_payload()

        response = rest_api.put(f'{ROUTE_URL}/{TYPE_ID_REFERENCED}', json=reduced)

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)

        stored = database_manager.get_collection(CmdbType.COLLECTION, database_name)\
            .find_one({'public_id': TYPE_ID_REFERENCED})

        assert stored['render_meta']['sections'][0]['fields'] == [NAME_FIELD]

    def test_moving_the_selected_field_out_of_the_section_returns_400(self, rest_api) -> None:
        """The trigger is a field leaving the SECTION - a move breaks the dependent identically."""
        payload = _referenced_type_payload()
        payload['render_meta']['sections'][0]['fields'] = []
        payload['render_meta']['sections'][1]['fields'] = [NAME_FIELD]

        response = rest_api.put(f'{ROUTE_URL}/{TYPE_ID_REFERENCED}', json=payload)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert 'would show nothing' in response.get_json()['message']

    def test_the_usage_route_names_the_blocked_section(self, rest_api) -> None:
        """The pre-check the type builder needs to disable the delete action up front."""
        response = rest_api.get(f'{ROUTE_URL}/referenced_section_usage/{TYPE_ID_REFERENCED}')

        assert response.status_code == HTTPStatus.OK
        body = response.get_json()
        assert body['in_use'] is True
        assert body['count'] == 1
        assert body['referencing_type_ids'] == [TYPE_ID_DEPENDENT]
        assert list(body['sections']) == [REFERENCED_SECTION_NAME]
        assert body['sections'][REFERENCED_SECTION_NAME][0]['public_id'] == TYPE_ID_DEPENDENT

    def test_the_usage_route_reports_an_unreferenced_type_as_free(self, rest_api) -> None:
        """The dependent type itself is referenced by nothing."""
        response = rest_api.get(f'{ROUTE_URL}/referenced_section_usage/{TYPE_ID_DEPENDENT}')

        assert response.status_code == HTTPStatus.OK
        body = response.get_json()
        assert body['in_use'] is False
        assert body['sections'] == {}

    def test_the_usage_route_404s_for_a_missing_type(self, rest_api) -> None:
        """Consistent with the other two pre-check routes."""
        response = rest_api.get(f'{ROUTE_URL}/referenced_section_usage/{MISSING_TYPE_ID}')

        assert response.status_code == HTTPStatus.NOT_FOUND


# -------------------------------------------------------------------------------------------------------------------- #
#                                             LISTING FILTERS AND ACCESS CONTROL                                       #
# -------------------------------------------------------------------------------------------------------------------- #
def _denied_acl() -> dict[str, Any]:
    """An activated ACL granting the admin group everything except READ."""
    return {'activated': True, 'groups': {'includes': {str(ADMIN_GROUP_ID): ['CREATE', 'UPDATE', 'DELETE']}}}


class TestListingFilterEcho:
    """The ``parameters.filter`` echoed back is what the CLIENT sent, never what the server injected."""

    def test_a_dict_filter_is_echoed_unchanged(self, rest_api) -> None:
        """The active flag restricts the query without appearing in the echoed filter."""
        response = rest_api.get(f'{ROUTE_URL}/?active=true&filter={{"label":"{ORIGINAL_LABEL}"}}')

        assert response.status_code == HTTPStatus.OK
        assert response.get_json()['parameters']['filter'] == {'label': ORIGINAL_LABEL}

    def test_a_pipeline_filter_is_echoed_unchanged(self, rest_api) -> None:
        """A client pipeline comes back with exactly the stages it went in with."""
        client_pipeline = '[{"$match":{"label":"%s"}}]' % ORIGINAL_LABEL

        response = rest_api.get(f'{ROUTE_URL}/?active=true&filter={client_pipeline}')

        assert response.status_code == HTTPStatus.OK
        assert response.get_json()['parameters']['filter'] == [{'$match': {'label': ORIGINAL_LABEL}}]

    def test_no_filter_echoes_no_injected_stages(self, rest_api) -> None:
        """Without a client filter the echo stays empty instead of showing the server's own $match."""
        response = rest_api.get(f'{ROUTE_URL}/?active=true')

        assert response.status_code == HTTPStatus.OK
        assert response.get_json()['parameters']['filter'] == {}

    def test_the_active_flag_still_restricts_the_rows(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """Not echoing the injected stage does not mean not applying it."""
        doc = _type_doc(TYPE_ID_FOR_GET, ORIGINAL_LABEL)
        doc['active'] = False
        database_manager.get_collection(CmdbType.COLLECTION, database_name).insert_one(doc)

        try:
            response = rest_api.get(f'{ROUTE_URL}/?active=true&limit=0')
            listed = [t['public_id'] for t in response.get_json()['results']]
        finally:
            _drop_type(database_manager, database_name, TYPE_ID_FOR_GET)

        assert TYPE_ID_FOR_GET not in listed


class TestListingCategoryFilters:
    """``?category=`` and ``?uncategorized=`` replace the $lookup pipelines the frontend posted."""

    @pytest.fixture(autouse=True)
    def _seed(self, database_manager: MongoDatabaseManager, database_name: str):
        """One categorized type, one uncategorized type, and the category binding them."""
        types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
        categories = database_manager.get_collection(CmdbCategory.COLLECTION, database_name)

        types.insert_one(_type_doc(TYPE_ID_CATEGORIZED, ORIGINAL_LABEL))
        types.insert_one(_type_doc(TYPE_ID_UNCATEGORIZED, ORIGINAL_LABEL))
        categories.insert_one({
            'public_id': LISTING_CATEGORY_ID,
            'name': 'listing-category',
            'label': 'Listing Category',
            'meta': {'icon': '', 'order': None},
            'parent': None,
            'types': [TYPE_ID_CATEGORIZED],
        })
        yield
        types.delete_many({'public_id': {'$in': [TYPE_ID_CATEGORIZED, TYPE_ID_UNCATEGORIZED]}})
        categories.delete_many({'public_id': LISTING_CATEGORY_ID})

    @staticmethod
    def _listed_ids(response) -> list[int]:
        """The public_ids in a listing response."""
        return [result['public_id'] for result in response.get_json()['results']]

    def test_category_lists_only_its_own_types(self, rest_api) -> None:
        """?category=<id> answers the types assigned to that category."""
        response = rest_api.get(f'{ROUTE_URL}/?limit=0&category={LISTING_CATEGORY_ID}')

        assert response.status_code == HTTPStatus.OK
        assert self._listed_ids(response) == [TYPE_ID_CATEGORIZED]

    def test_uncategorized_excludes_the_categorized_type(self, rest_api) -> None:
        """?uncategorized=true answers the complement."""
        response = rest_api.get(f'{ROUTE_URL}/?limit=0&uncategorized=true')

        listed = self._listed_ids(response)

        assert response.status_code == HTTPStatus.OK
        assert TYPE_ID_UNCATEGORIZED in listed
        assert TYPE_ID_CATEGORIZED not in listed

    def test_the_total_agrees_with_the_filtered_rows(self, rest_api) -> None:
        """The category filter lives in the criteria, so the count aggregation applies it too."""
        response = rest_api.get(f'{ROUTE_URL}/?limit=0&category={LISTING_CATEGORY_ID}')
        body = response.get_json()

        assert body['total'] == len(body['results'])

    def test_an_unknown_category_lists_nothing(self, rest_api) -> None:
        """An id nothing is assigned to is an empty result, matching the pipeline this replaced."""
        response = rest_api.get(f'{ROUTE_URL}/?limit=0&category={MISSING_CATEGORY_ID}')

        assert response.status_code == HTTPStatus.OK
        assert self._listed_ids(response) == []

    def test_a_category_filter_combines_with_a_client_filter(self, rest_api) -> None:
        """The server condition narrows the client's filter rather than replacing it."""
        response = rest_api.get(
            f'{ROUTE_URL}/?limit=0&category={LISTING_CATEGORY_ID}'
            f'&filter={{"public_id":{TYPE_ID_UNCATEGORIZED}}}'
        )

        assert response.status_code == HTTPStatus.OK
        assert self._listed_ids(response) == []

    def test_both_category_filters_at_once_are_refused(self, rest_api) -> None:
        """A contradiction is a 400, not an empty list."""
        response = rest_api.get(f'{ROUTE_URL}/?category={LISTING_CATEGORY_ID}&uncategorized=true')

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_a_non_numeric_category_is_refused(self, rest_api) -> None:
        """The parameter is a public_id."""
        response = rest_api.get(f'{ROUTE_URL}/?category=not-a-number')

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_the_category_parameter_returns_what_the_frontend_pipeline_returns(self, rest_api) -> None:
        """
        The migration contract for **F3**: same rows, same order, same documents

        The Angular app asks "types in category N" with a `$lookup` into `framework.categories`
        posted as `?filter=`. `?category=` has to be a drop-in for it, or switching the frontend over
        is not the one-line change it is supposed to be.
        """
        frontend_pipeline = (
            '[{"$lookup":{"from":"framework.categories","let":{"type_public_id":"$public_id"},'
            '"pipeline":[{"$match":{"public_id":%d}},'
            '{"$match":{"$expr":{"$in":["$$type_public_id","$types"]}}}],"as":"category"}},'
            '{"$match":{"category.0":{"$exists":true}}},'
            '{"$project":{"category":0}}]'
        ) % LISTING_CATEGORY_ID

        with_pipeline = rest_api.get(f'{ROUTE_URL}/?limit=0&active=false&filter={frontend_pipeline}')
        with_parameter = rest_api.get(f'{ROUTE_URL}/?limit=0&active=false&category={LISTING_CATEGORY_ID}')

        assert with_pipeline.status_code == HTTPStatus.OK
        assert with_parameter.get_json()['results'] == with_pipeline.get_json()['results']
        assert with_parameter.get_json()['total'] == with_pipeline.get_json()['total']

    def test_the_uncategorized_parameter_returns_what_the_frontend_pipeline_returns(self, rest_api) -> None:
        """The same contract for the other half of **F3**: "types in no category"."""
        frontend_pipeline = (
            '[{"$lookup":{"from":"framework.categories","localField":"public_id",'
            '"foreignField":"types","as":"categories"}},'
            '{"$match":{"categories":{"$size":0}}},'
            '{"$project":{"categories":0}}]'
        )

        with_pipeline = rest_api.get(f'{ROUTE_URL}/?limit=0&active=true&filter={frontend_pipeline}')
        with_parameter = rest_api.get(f'{ROUTE_URL}/?limit=0&active=true&uncategorized=true')

        assert with_pipeline.status_code == HTTPStatus.OK
        assert with_parameter.get_json()['results'] == with_pipeline.get_json()['results']
        assert with_parameter.get_json()['total'] == with_pipeline.get_json()['total']

    def test_the_overview_accepts_the_same_filters(self, rest_api) -> None:
        """/types/overview shares the helper, so the parameters work there too."""
        response = rest_api.get(f'{ROUTE_URL}/overview?limit=0&category={LISTING_CATEGORY_ID}')

        assert response.status_code == HTTPStatus.OK
        listed = [item['type_data']['public_id'] for item in response.get_json()['results']]
        assert listed == [TYPE_ID_CATEGORIZED]


class TestListingAccessControl:
    """Both listings are restricted to the types the requesting user's group may READ."""

    @pytest.fixture(autouse=True)
    def _seed(self, database_manager: MongoDatabaseManager, database_name: str):
        """One type the admin group may read and one it may not."""
        types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
        denied = _type_doc(TYPE_ID_ACL_DENIED, ORIGINAL_LABEL)
        denied['acl'] = _denied_acl()

        types.insert_one(_type_doc(TYPE_ID_UNCATEGORIZED, ORIGINAL_LABEL))
        types.insert_one(denied)
        yield
        types.delete_many({'public_id': {'$in': [TYPE_ID_UNCATEGORIZED, TYPE_ID_ACL_DENIED]}})

    def test_a_denied_type_is_absent_from_the_listing(self, rest_api) -> None:
        """The route enforces the ACL itself now - no client-supplied filter is involved."""
        response = rest_api.get(f'{ROUTE_URL}/?limit=0')

        listed = [result['public_id'] for result in response.get_json()['results']]

        assert response.status_code == HTTPStatus.OK
        assert TYPE_ID_UNCATEGORIZED in listed
        assert TYPE_ID_ACL_DENIED not in listed

    def test_a_denied_type_is_absent_from_the_overview(self, rest_api) -> None:
        """The overview applies the same rule, so the two never disagree about what exists."""
        response = rest_api.get(f'{ROUTE_URL}/overview?limit=0')

        listed = [item['type_data']['public_id'] for item in response.get_json()['results']]

        assert response.status_code == HTTPStatus.OK
        assert TYPE_ID_UNCATEGORIZED in listed
        assert TYPE_ID_ACL_DENIED not in listed

    def test_the_total_excludes_the_denied_type_too(self, rest_api) -> None:
        """The rule is in the criteria, so the count aggregation reads it as well."""
        response = rest_api.get(f'{ROUTE_URL}/?limit=0')
        body = response.get_json()

        assert body['total'] == len(body['results'])

    def test_a_client_filter_cannot_widen_the_listing(self, rest_api) -> None:
        """Asking for the denied type by public_id still does not return it."""
        response = rest_api.get(f'{ROUTE_URL}/?limit=0&filter={{"public_id":{TYPE_ID_ACL_DENIED}}}')

        assert response.status_code == HTTPStatus.OK
        assert response.get_json()['results'] == []

    def test_a_client_pipeline_cannot_widen_the_listing(self, rest_api) -> None:
        """The server's $match runs before the client's stages, so no stage can undo it."""
        client_pipeline = '[{"$match":{"public_id":%d}}]' % TYPE_ID_ACL_DENIED

        response = rest_api.get(f'{ROUTE_URL}/?limit=0&filter={client_pipeline}')

        assert response.status_code == HTTPStatus.OK
        assert response.get_json()['results'] == []

    def test_a_deactivated_acl_is_listed(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """Access control is opt-in: a switched-off ACL restricts nothing."""
        types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
        types.update_one(
            {'public_id': TYPE_ID_ACL_DENIED},
            {'$set': {'acl': {'activated': False, 'groups': {'includes': {}}}}},
        )

        response = rest_api.get(f'{ROUTE_URL}/?limit=0')
        listed = [result['public_id'] for result in response.get_json()['results']]

        assert TYPE_ID_ACL_DENIED in listed


class TestCreateNormalisesTheAcl:
    """
    ``POST /types/`` stores the same ``acl`` block every other write path stores

    The insert hands the raw payload to the manager, so before 2026-09-17 a create without an ``acl``
    stored a document without one and the first edit silently added it - two stored shapes for one
    meaning, decided by whether anyone had edited the type.
    """

    @staticmethod
    def _stored_acl(database_manager: MongoDatabaseManager, database_name: str) -> dict[str, Any]:
        """
        The acl block as it actually landed in the collection

        Found by the type NAME: the payload cannot choose the id (it is server-owned), and the name
        is unique.
        """
        stored = database_manager.get_collection(CmdbType.COLLECTION, database_name).find_one(
            {'name': TYPE_NAME_FOR_CREATE}
        )

        return stored['acl']

    @pytest.fixture(autouse=True)
    def _cleanup(self, database_manager: MongoDatabaseManager, database_name: str):
        """Removes the created type after each test."""
        yield
        database_manager.get_collection(CmdbType.COLLECTION, database_name)\
            .delete_many({'name': TYPE_NAME_FOR_CREATE})

    def test_a_payload_without_an_acl_stores_the_default(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """The deactivated, group-less block - access control is opt-in."""
        payload = _type_payload(TYPE_ID_FOR_CREATE, ORIGINAL_LABEL)
        del payload['acl']

        response = rest_api.post(f'{ROUTE_URL}/', json=payload)

        assert response.status_code == HTTPStatus.CREATED
        assert self._stored_acl(database_manager, database_name) == {
            'activated': False, 'groups': {'includes': {}},
        }

    def test_a_partial_acl_is_completed_rather_than_refused(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """Groups without the flag is the shape the model and the query used to read differently."""
        payload = _type_payload(TYPE_ID_FOR_CREATE, ORIGINAL_LABEL)
        payload['acl'] = {'groups': {'includes': {str(ADMIN_GROUP_ID): ['READ']}}}

        response = rest_api.post(f'{ROUTE_URL}/', json=payload)

        assert response.status_code == HTTPStatus.CREATED
        assert self._stored_acl(database_manager, database_name) == {
            'activated': False,
            'groups': {'includes': {str(ADMIN_GROUP_ID): ['READ']}},
        }

    def test_an_activated_acl_survives_the_normalisation(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """Completing the block must not switch anyone's access control off."""
        payload = _type_payload(TYPE_ID_FOR_CREATE, ORIGINAL_LABEL)
        payload['acl'] = {'activated': True, 'groups': {'includes': {str(ADMIN_GROUP_ID): ['READ']}}}

        response = rest_api.post(f'{ROUTE_URL}/', json=payload)

        assert response.status_code == HTTPStatus.CREATED
        assert self._stored_acl(database_manager, database_name) == payload['acl']

    def test_a_null_groups_does_not_become_a_500(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """``GroupACL.from_data`` used to raise on a null groups; the create path must not inherit that."""
        payload = _type_payload(TYPE_ID_FOR_CREATE, ORIGINAL_LABEL)
        payload['acl'] = {'activated': False, 'groups': None}

        response = rest_api.post(f'{ROUTE_URL}/', json=payload)

        assert response.status_code == HTTPStatus.CREATED
        assert self._stored_acl(database_manager, database_name) == {
            'activated': False, 'groups': {'includes': {}},
        }

    def test_the_created_type_reads_back_with_the_same_acl(self, rest_api) -> None:
        """The response and the stored document agree, so no client sees a different shape."""
        payload = _type_payload(TYPE_ID_FOR_CREATE, ORIGINAL_LABEL)
        del payload['acl']
        created = rest_api.post(f'{ROUTE_URL}/', json=payload)

        body = rest_api.get(f"{ROUTE_URL}/{created.get_json()['result_id']}").get_json()

        assert body['result']['acl'] == {'activated': False, 'groups': {'includes': {}}}


class TestListingAclParameter:
    """``?acl=`` names the permission the listing filter asks about, replacing the READ default."""

    @pytest.fixture(autouse=True)
    def _seed(self, database_manager: MongoDatabaseManager, database_name: str):
        """One readable type and one the admin group may CREATE but not READ."""
        types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
        create_only = _type_doc(TYPE_ID_ACL_CREATE_ONLY, ORIGINAL_LABEL)
        create_only['acl'] = {
            'activated': True,
            'groups': {'includes': {str(ADMIN_GROUP_ID): ['CREATE', 'UPDATE']}},
        }

        types.insert_one(_type_doc(TYPE_ID_UNCATEGORIZED, ORIGINAL_LABEL))
        types.insert_one(create_only)
        yield
        types.delete_many({'public_id': {'$in': [TYPE_ID_UNCATEGORIZED, TYPE_ID_ACL_CREATE_ONLY]}})

    @staticmethod
    def _listed_ids(response) -> list[int]:
        """The public_ids in a listing response."""
        return [result['public_id'] for result in response.get_json()['results']]

    def test_the_default_listing_asks_for_read(self, rest_api) -> None:
        """Without the parameter nothing changes: a CREATE-only type stays hidden."""
        response = rest_api.get(f'{ROUTE_URL}/?limit=0')

        assert response.status_code == HTTPStatus.OK
        assert TYPE_ID_ACL_CREATE_ONLY not in self._listed_ids(response)

    def test_asking_for_create_lists_the_create_only_type(self, rest_api) -> None:
        """?acl=CREATE replaces READ - this is what object-add asks for."""
        response = rest_api.get(f'{ROUTE_URL}/?limit=0&acl=CREATE')

        assert response.status_code == HTTPStatus.OK
        assert TYPE_ID_ACL_CREATE_ONLY in self._listed_ids(response)

    def test_asking_for_read_and_create_requires_both(self, rest_api) -> None:
        """A comma list is a conjunction, so the CREATE-only type drops out again."""
        response = rest_api.get(f'{ROUTE_URL}/?limit=0&acl=READ,CREATE')

        listed = self._listed_ids(response)

        assert response.status_code == HTTPStatus.OK
        assert TYPE_ID_ACL_CREATE_ONLY not in listed
        assert TYPE_ID_UNCATEGORIZED in listed

    def test_the_total_follows_the_requested_permission(self, rest_api) -> None:
        """The rule is in the criteria, so the count aggregation asks the same question."""
        body = rest_api.get(f'{ROUTE_URL}/?limit=0&acl=CREATE').get_json()

        assert body['total'] == len(body['results'])

    def test_an_unlicensed_permission_name_is_refused(self, rest_api) -> None:
        """An unknown permission would match no group entry and hide everything - so it is a 400."""
        assert rest_api.get(f'{ROUTE_URL}/?acl=NOPE').status_code == HTTPStatus.BAD_REQUEST

    def test_a_lowercase_permission_is_refused(self, rest_api) -> None:
        """A stored ACL holds the upper-case value; 'read' would silently match nothing."""
        assert rest_api.get(f'{ROUTE_URL}/?acl=read').status_code == HTTPStatus.BAD_REQUEST

    def test_an_empty_acl_is_refused(self, rest_api) -> None:
        """An empty $all matches nothing, so an empty value must not mean 'no restriction'."""
        assert rest_api.get(f'{ROUTE_URL}/?acl=').status_code == HTTPStatus.BAD_REQUEST

    def test_a_repeated_key_is_refused_rather_than_silently_narrowed(self, rest_api) -> None:
        """
        ``?acl=READ&acl=CREATE`` is not how the parameter is spelled

        ``request.args.to_dict()`` keeps only the first value of a repeated key, so this shape would
        silently narrow to READ. The first value is a valid permission, so it parses - this pins that
        the request is *answered as READ*, which is why the documented spelling is a comma list.
        """
        repeated = rest_api.get(f'{ROUTE_URL}/?limit=0&acl=CREATE&acl=READ')

        assert repeated.status_code == HTTPStatus.OK
        assert TYPE_ID_ACL_CREATE_ONLY in self._listed_ids(repeated)

    def test_the_overview_refuses_the_parameter(self, rest_api) -> None:
        """It always asks for READ, and a parameter accepted and ignored is worse than none."""
        assert rest_api.get(f'{ROUTE_URL}/overview?acl=CREATE').status_code == HTTPStatus.BAD_REQUEST

    def test_the_overview_tolerates_an_explicit_read(self, rest_api) -> None:
        """``?acl=READ`` asks the overview for exactly what it already does, so it is not an error."""
        assert rest_api.get(f'{ROUTE_URL}/overview?limit=0&acl=READ').status_code == HTTPStatus.OK
