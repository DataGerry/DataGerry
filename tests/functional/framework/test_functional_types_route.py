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
from cmdb.models.type_model import CmdbType
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
MISSING_TYPE_ID: int = 9799

ALL_TYPE_IDS: list[int] = [
    TYPE_ID_FOR_CREATE,
    TYPE_ID_FOR_DUPLICATE,
    TYPE_ID_FOR_GET,
    TYPE_ID_FOR_UPDATE,
    TYPE_ID_FOR_DELETE,
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
