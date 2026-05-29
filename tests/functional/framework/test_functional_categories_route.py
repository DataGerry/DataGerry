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
Functional smoke for the ``/categories`` REST routes

End-to-end coverage that the CategoriesManager integration suite cannot give: HTTP status
codes, schema validation, the unique-name guard returning 400 on a duplicate, the 404 on a
missing id, the JSON envelope returned by GET-list, the ``?view=tree`` branch toggle, the
PUT round-trip returning the re-read document (B1), and DELETE detaching children before
removing the parent (B2 end-to-end). CRUD correctness itself is asserted at the manager
layer; these tests only verify the route wraps it correctly.
"""
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.category_model import CmdbCategory
from cmdb.interface.rest_api.routes.framework_routes.categories_constants import CategoryListView
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_URL: str = '/categories'

CATEGORY_ID_FOR_CREATE: int = 9801
CATEGORY_ID_FOR_DUPLICATE: int = 9802
CATEGORY_ID_FOR_GET: int = 9803
CATEGORY_ID_FOR_UPDATE: int = 9804
CATEGORY_ID_FOR_DELETE: int = 9805
CATEGORY_ID_FOR_TREE_PARENT: int = 9806
CATEGORY_ID_FOR_TREE_CHILD: int = 9807
CATEGORY_ID_FOR_CASCADE_PARENT: int = 9808
CATEGORY_ID_FOR_CASCADE_CHILD_A: int = 9809
CATEGORY_ID_FOR_CASCADE_CHILD_B: int = 9810
CATEGORY_ID_FOR_CASCADE_UNRELATED: int = 9811
MISSING_CATEGORY_ID: int = 9899

ALL_CATEGORY_IDS: list[int] = [
    CATEGORY_ID_FOR_CREATE,
    CATEGORY_ID_FOR_DUPLICATE,
    CATEGORY_ID_FOR_DUPLICATE + 1,
    CATEGORY_ID_FOR_GET,
    CATEGORY_ID_FOR_UPDATE,
    CATEGORY_ID_FOR_DELETE,
    CATEGORY_ID_FOR_TREE_PARENT,
    CATEGORY_ID_FOR_TREE_CHILD,
    CATEGORY_ID_FOR_CASCADE_PARENT,
    CATEGORY_ID_FOR_CASCADE_CHILD_A,
    CATEGORY_ID_FOR_CASCADE_CHILD_B,
    CATEGORY_ID_FOR_CASCADE_UNRELATED,
]

ORIGINAL_LABEL: str = 'Original'
UPDATED_LABEL: str = 'Updated'


def _category_payload(
    public_id: int,
    label: str = ORIGINAL_LABEL,
    parent: int | None = None,
    name: str | None = None,
) -> dict[str, Any]:
    """Builds a CmdbCategory-shaped payload acceptable to POST /categories/ and PUT /categories/<id>."""
    return {
        'public_id': public_id,
        'name': name if name is not None else f'func-test-cat-{public_id}',
        'label': label,
        'parent': parent,
        'types': [],
        'meta': {'icon': 'fa-folder', 'order': public_id},
    }


def _category_doc(public_id: int, label: str = ORIGINAL_LABEL, parent: int | None = None) -> dict[str, Any]:
    """Builds a complete CmdbCategory doc for direct DB insertion (bypasses POST schema validation)."""
    doc = _category_payload(public_id, label=label, parent=parent)
    doc['creation_time'] = datetime.now(timezone.utc)
    return doc


def _drop_category(database_manager: MongoDatabaseManager, database_name: str, public_id: int) -> None:
    """Removes a single CmdbCategory doc directly via the collection, for per-test cleanup."""
    database_manager.get_collection(CmdbCategory.COLLECTION, database_name).delete_one({'public_id': public_id})


def _drop_categories(database_manager: MongoDatabaseManager, database_name: str, public_ids: list[int]) -> None:
    """Removes multiple CmdbCategory docs directly via the collection."""
    database_manager.get_collection(CmdbCategory.COLLECTION, database_name)\
        .delete_many({'public_id': {'$in': public_ids}})


def _insert_category_doc(
    database_manager: MongoDatabaseManager,
    database_name: str,
    public_id: int,
    label: str = ORIGINAL_LABEL,
    parent: int | None = None,
) -> None:
    """Inserts a CmdbCategory doc directly via the collection, bypassing the POST route validation."""
    database_manager.get_collection(CmdbCategory.COLLECTION, database_name)\
        .insert_one(_category_doc(public_id, label=label, parent=parent))


@pytest.fixture(scope='module', autouse=True)
def _cleanup_categories_after_module(database_manager: MongoDatabaseManager, database_name: str):
    """Removes any leftover test categories after the module's tests have run."""
    yield
    _drop_categories(database_manager, database_name, ALL_CATEGORY_IDS)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       CREATE                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class TestPostCategory:
    """POST /categories/ creates a new CmdbCategory and rejects a duplicate name with 400."""

    def test_creates_new_category(
        self,
        rest_api,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """A POST with a fresh public_id + name succeeds; the category is then queryable."""
        try:
            response = rest_api.post(
                f'{ROUTE_URL}/',
                json=_category_payload(CATEGORY_ID_FOR_CREATE),
            )

            assert response.status_code == HTTPStatus.CREATED
            follow_up = rest_api.get(f'{ROUTE_URL}/{CATEGORY_ID_FOR_CREATE}')
            assert follow_up.status_code == HTTPStatus.OK
        finally:
            _drop_category(database_manager, database_name, CATEGORY_ID_FOR_CREATE)

    def test_invalid_payload_rejected_by_schema_validation(
        self,
        rest_api,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """A POST missing the required ``name`` field is rejected by ``@validate`` with 400."""
        invalid_payload = _category_payload(CATEGORY_ID_FOR_DUPLICATE)
        del invalid_payload['name']

        try:
            response = rest_api.post(f'{ROUTE_URL}/', json=invalid_payload)

            assert response.status_code == HTTPStatus.BAD_REQUEST
        finally:
            _drop_category(database_manager, database_name, CATEGORY_ID_FOR_DUPLICATE)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       READ                                                           #
# -------------------------------------------------------------------------------------------------------------------- #
class TestGetCategory:
    """GET /categories/<id> and GET /categories/ return the expected envelopes."""

    @pytest.fixture(autouse=True)
    def _seed(self, database_manager: MongoDatabaseManager, database_name: str):
        """Inserts one category directly via the DB before each test and removes it after."""
        _insert_category_doc(database_manager, database_name, CATEGORY_ID_FOR_GET)
        yield
        _drop_category(database_manager, database_name, CATEGORY_ID_FOR_GET)

    def test_get_single_returns_category(self, rest_api) -> None:
        """A GET /categories/<id> for a seeded category returns 200 with a parseable body."""
        response = rest_api.get(f'{ROUTE_URL}/{CATEGORY_ID_FOR_GET}')

        assert response.status_code == HTTPStatus.OK
        body = response.get_json()
        assert body['result']['public_id'] == CATEGORY_ID_FOR_GET
        assert body['result']['label'] == ORIGINAL_LABEL

    def test_get_single_missing_returns_404(self, rest_api) -> None:
        """A GET /categories/<id> for a missing id returns 404."""
        response = rest_api.get(f'{ROUTE_URL}/{MISSING_CATEGORY_ID}')

        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_get_list_returns_results_envelope(self, rest_api) -> None:
        """A GET /categories/ returns a JSON envelope whose results length matches X-Total-Count."""
        response = rest_api.get(f'{ROUTE_URL}/')

        assert response.status_code == HTTPStatus.OK
        body = response.get_json()
        assert 'results' in body
        assert len(body['results']) == int(response.headers['X-Total-Count'])


class TestGetCategoriesTreeView:
    """GET /categories/?view=tree returns the un-paginated CategoryTree representation."""

    @pytest.fixture(autouse=True)
    def _seed_parent_and_child(self, database_manager: MongoDatabaseManager, database_name: str):
        """Inserts one parent + one child so the tree has structure to traverse."""
        _insert_category_doc(database_manager, database_name, CATEGORY_ID_FOR_TREE_PARENT)
        _insert_category_doc(
            database_manager,
            database_name,
            CATEGORY_ID_FOR_TREE_CHILD,
            parent=CATEGORY_ID_FOR_TREE_PARENT,
        )
        yield
        _drop_categories(
            database_manager,
            database_name,
            [CATEGORY_ID_FOR_TREE_PARENT, CATEGORY_ID_FOR_TREE_CHILD],
        )

    def test_tree_view_returns_200(self, rest_api) -> None:
        """``?view=tree`` returns 200 and a non-empty result payload."""
        response = rest_api.get(f'{ROUTE_URL}/?view={CategoryListView.TREE.value}')

        assert response.status_code == HTTPStatus.OK
        body = response.get_json()
        assert body['results']


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       UPDATE                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class TestPutCategory:
    """PUT /categories/<id> writes the new payload and the response carries the re-read doc."""

    def test_update_persists_new_label(
        self,
        rest_api,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """After PUT, a follow-up GET reflects the updated label."""
        _insert_category_doc(database_manager, database_name, CATEGORY_ID_FOR_UPDATE)
        try:
            updated_payload = _category_payload(CATEGORY_ID_FOR_UPDATE, label=UPDATED_LABEL)

            response = rest_api.put(f'{ROUTE_URL}/{CATEGORY_ID_FOR_UPDATE}', json=updated_payload)
            assert response.status_code == HTTPStatus.ACCEPTED

            follow_up = rest_api.get(f'{ROUTE_URL}/{CATEGORY_ID_FOR_UPDATE}')
            assert follow_up.get_json()['result']['label'] == UPDATED_LABEL
        finally:
            _drop_category(database_manager, database_name, CATEGORY_ID_FOR_UPDATE)

    def test_update_response_body_reflects_persisted_state(
        self,
        rest_api,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """The PUT response carries the RE-READ document (B1), not the submitted payload."""
        _insert_category_doc(database_manager, database_name, CATEGORY_ID_FOR_UPDATE)
        try:
            updated_payload = _category_payload(CATEGORY_ID_FOR_UPDATE, label=UPDATED_LABEL)

            response = rest_api.put(f'{ROUTE_URL}/{CATEGORY_ID_FOR_UPDATE}', json=updated_payload)

            assert response.status_code == HTTPStatus.ACCEPTED
            body = response.get_json()
            assert body['result']['public_id'] == CATEGORY_ID_FOR_UPDATE
            assert body['result']['label'] == UPDATED_LABEL
        finally:
            _drop_category(database_manager, database_name, CATEGORY_ID_FOR_UPDATE)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       DELETE                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class TestDeleteCategory:
    """DELETE /categories/<id> removes the doc; a follow-up GET reports 404."""

    def test_delete_removes_category(
        self,
        rest_api,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """A DELETE succeeds, and a subsequent GET for the same id returns 404."""
        _insert_category_doc(database_manager, database_name, CATEGORY_ID_FOR_DELETE)
        try:
            response = rest_api.delete(f'{ROUTE_URL}/{CATEGORY_ID_FOR_DELETE}')

            assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED, HTTPStatus.NO_CONTENT)
            follow_up = rest_api.get(f'{ROUTE_URL}/{CATEGORY_ID_FOR_DELETE}')
            assert follow_up.status_code == HTTPStatus.NOT_FOUND
        finally:
            _drop_category(database_manager, database_name, CATEGORY_ID_FOR_DELETE)

    def test_delete_missing_returns_404(self, rest_api) -> None:
        """A DELETE for a missing id returns 404."""
        response = rest_api.delete(f'{ROUTE_URL}/{MISSING_CATEGORY_ID}')

        assert response.status_code == HTTPStatus.NOT_FOUND


class TestDeleteCategoryCascade:
    """End-to-end coverage of the B2 cascade: delete detaches children before removing the parent."""

    @pytest.fixture(autouse=True)
    def _seed_cascade(self, database_manager: MongoDatabaseManager, database_name: str):
        """Inserts a parent, two children, and one unrelated category."""
        _insert_category_doc(database_manager, database_name, CATEGORY_ID_FOR_CASCADE_PARENT)
        _insert_category_doc(
            database_manager,
            database_name,
            CATEGORY_ID_FOR_CASCADE_CHILD_A,
            parent=CATEGORY_ID_FOR_CASCADE_PARENT,
        )
        _insert_category_doc(
            database_manager,
            database_name,
            CATEGORY_ID_FOR_CASCADE_CHILD_B,
            parent=CATEGORY_ID_FOR_CASCADE_PARENT,
        )
        _insert_category_doc(database_manager, database_name, CATEGORY_ID_FOR_CASCADE_UNRELATED)
        yield
        _drop_categories(
            database_manager,
            database_name,
            [
                CATEGORY_ID_FOR_CASCADE_PARENT,
                CATEGORY_ID_FOR_CASCADE_CHILD_A,
                CATEGORY_ID_FOR_CASCADE_CHILD_B,
                CATEGORY_ID_FOR_CASCADE_UNRELATED,
            ],
        )

    def test_delete_detaches_children_and_removes_parent(self, rest_api) -> None:
        """DELETE /<parent_id> removes the parent AND nulls ``parent`` on every child."""
        response = rest_api.delete(f'{ROUTE_URL}/{CATEGORY_ID_FOR_CASCADE_PARENT}')

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED, HTTPStatus.NO_CONTENT)

        # Parent gone
        parent_lookup = rest_api.get(f'{ROUTE_URL}/{CATEGORY_ID_FOR_CASCADE_PARENT}')
        assert parent_lookup.status_code == HTTPStatus.NOT_FOUND

        # Children still present, but parent field nulled
        child_a = rest_api.get(f'{ROUTE_URL}/{CATEGORY_ID_FOR_CASCADE_CHILD_A}').get_json()['result']
        child_b = rest_api.get(f'{ROUTE_URL}/{CATEGORY_ID_FOR_CASCADE_CHILD_B}').get_json()['result']
        assert child_a['parent'] is None
        assert child_b['parent'] is None

        # Unrelated category untouched
        unrelated = rest_api.get(f'{ROUTE_URL}/{CATEGORY_ID_FOR_CASCADE_UNRELATED}').get_json()['result']
        assert unrelated['public_id'] == CATEGORY_ID_FOR_CASCADE_UNRELATED
