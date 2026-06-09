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
Functional smoke for the ``/section_templates`` REST routes

Covers the route-layer concerns the SectionTemplatesManager suite cannot: HTTP status codes, the
query-string parameter parsing on create/update, the predefined-create rejection (400), the 404 on
a missing id, the GET-list envelope, the PUT round-trip and the DELETE + follow-up 404. The CRUD /
propagation behavior itself is asserted at the manager layer; these tests verify the route wraps it
"""
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.section_template_model.cmdb_section_template import CmdbSectionTemplate
from cmdb.models.type_model import SectionType
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_URL: str = '/section_templates'

TEMPLATE_ID_FOR_CREATE: int = 9801
TEMPLATE_ID_FOR_GET: int = 9802
TEMPLATE_ID_FOR_UPDATE: int = 9803
TEMPLATE_ID_FOR_DELETE: int = 9804
MISSING_TEMPLATE_ID: int = 9899

ALL_TEMPLATE_IDS: list[int] = [
    TEMPLATE_ID_FOR_CREATE,
    TEMPLATE_ID_FOR_GET,
    TEMPLATE_ID_FOR_UPDATE,
    TEMPLATE_ID_FOR_DELETE,
]

CREATE_NAME: str = 'func-sectpl-create'
ORIGINAL_LABEL: str = 'Original'
UPDATED_LABEL: str = 'Updated'


def _create_params(name: str, predefined: str = 'false') -> dict[str, str]:
    """Builds the query-string parameters POST /section_templates/ parses (fields is a JSON string)."""
    return {
        'name': name,
        'label': ORIGINAL_LABEL,
        'type': SectionType.SECTION.value,
        'is_global': 'false',
        'predefined': predefined,
        'fields': '[]',
    }


def _template_doc(public_id: int, name: str, label: str = ORIGINAL_LABEL) -> dict[str, Any]:
    """Builds a non-global CmdbSectionTemplate doc for direct DB insertion."""
    return {
        'public_id': public_id,
        'name': name,
        'label': label,
        'type': SectionType.SECTION.value,
        'fields': [],
        'is_global': False,
        'predefined': False,
    }


def _collection(database_manager: MongoDatabaseManager, database_name: str):
    """Returns the section-template collection bound to the test database."""
    return database_manager.get_collection(CmdbSectionTemplate.COLLECTION, database_name)


@pytest.fixture(scope='module', autouse=True)
def _cleanup_after_module(database_manager: MongoDatabaseManager, database_name: str):
    """Removes any leftover test section templates after the module's tests have run."""
    yield
    _collection(database_manager, database_name).delete_many(
        {'$or': [{'public_id': {'$in': ALL_TEMPLATE_IDS}}, {'name': CREATE_NAME}]},
    )


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       CREATE                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class TestPostSectionTemplate:
    """POST /section_templates/ creates a template from query params and rejects predefined ones."""

    def test_creates_new_template(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """A POST with valid params succeeds and the template is then present in the collection."""
        try:
            response = rest_api.post(f'{ROUTE_URL}/', query_string=_create_params(CREATE_NAME))

            assert response.status_code in (HTTPStatus.OK, HTTPStatus.CREATED)
            assert _collection(database_manager, database_name).find_one({'name': CREATE_NAME}) is not None
        finally:
            _collection(database_manager, database_name).delete_many({'name': CREATE_NAME})

    def test_predefined_create_returns_400(self, rest_api) -> None:
        """A POST asking for a predefined template is rejected with 400 (not creatable via API)."""
        response = rest_api.post(f'{ROUTE_URL}/', query_string=_create_params(CREATE_NAME, predefined='true'))

        assert response.status_code == HTTPStatus.BAD_REQUEST


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       READ                                                           #
# -------------------------------------------------------------------------------------------------------------------- #
class TestGetSectionTemplate:
    """GET /section_templates/<id> and GET /section_templates/ return the expected responses."""

    @pytest.fixture(autouse=True)
    def _seed(self, database_manager: MongoDatabaseManager, database_name: str):
        """Inserts one template directly via the DB before each test and removes it after."""
        _collection(database_manager, database_name).insert_one(
            _template_doc(TEMPLATE_ID_FOR_GET, 'func-sectpl-get'),
        )
        yield
        _collection(database_manager, database_name).delete_one({'public_id': TEMPLATE_ID_FOR_GET})

    def test_get_single_returns_template(self, rest_api) -> None:
        """A GET for a seeded template returns 200."""
        response = rest_api.get(f'{ROUTE_URL}/{TEMPLATE_ID_FOR_GET}')

        assert response.status_code == HTTPStatus.OK

    def test_get_single_missing_returns_404(self, rest_api) -> None:
        """A GET for a missing id returns 404."""
        response = rest_api.get(f'{ROUTE_URL}/{MISSING_TEMPLATE_ID}')

        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_get_list_returns_results_envelope(self, rest_api) -> None:
        """A GET list returns a JSON envelope whose results length matches X-Total-Count."""
        response = rest_api.get(f'{ROUTE_URL}/')

        assert response.status_code == HTTPStatus.OK
        body = response.get_json()
        assert 'results' in body
        assert len(body['results']) == int(response.headers['X-Total-Count'])


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       UPDATE                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class TestPutSectionTemplate:
    """PUT /section_templates/ updates a template addressed by its public_id query param."""

    def test_update_persists_new_label(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """After PUT, the stored template carries the updated label."""
        collection = _collection(database_manager, database_name)
        collection.insert_one(_template_doc(TEMPLATE_ID_FOR_UPDATE, 'func-sectpl-update'))
        try:
            params = {
                'public_id': str(TEMPLATE_ID_FOR_UPDATE),
                'name': 'func-sectpl-update',
                'label': UPDATED_LABEL,
                'type': SectionType.SECTION.value,
                'is_global': 'false',
                'predefined': 'false',
                'fields': '[]',
            }

            response = rest_api.put(f'{ROUTE_URL}/', query_string=params)

            assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
            stored = collection.find_one({'public_id': TEMPLATE_ID_FOR_UPDATE})
            assert stored['label'] == UPDATED_LABEL
        finally:
            collection.delete_one({'public_id': TEMPLATE_ID_FOR_UPDATE})


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       DELETE                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class TestDeleteSectionTemplate:
    """DELETE /section_templates/<id>/ removes the template; a follow-up GET reports 404."""

    def test_delete_removes_template(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """A DELETE succeeds and a subsequent GET for the same id returns 404."""
        collection = _collection(database_manager, database_name)
        collection.insert_one(_template_doc(TEMPLATE_ID_FOR_DELETE, 'func-sectpl-delete'))
        try:
            response = rest_api.delete(f'{ROUTE_URL}/{TEMPLATE_ID_FOR_DELETE}/')

            assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
            follow_up = rest_api.get(f'{ROUTE_URL}/{TEMPLATE_ID_FOR_DELETE}')
            assert follow_up.status_code == HTTPStatus.NOT_FOUND
        finally:
            collection.delete_one({'public_id': TEMPLATE_ID_FOR_DELETE})
