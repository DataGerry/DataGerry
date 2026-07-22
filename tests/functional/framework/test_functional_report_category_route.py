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
Functional tests for the ``/report_categories`` REST routes

Pins the route-layer behaviour: create forces a server id + predefined=False, the missing-id 404s,
the GET-list envelope, the update path (identity pinned to the URL id, predefined immutable), and
the delete guards - missing -> 404, predefined -> 403, in-use-by-report -> 403, otherwise 200. The
create/update routes read their data from the query string (parse_request_parameters)
"""
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.reports_model.cmdb_report_category import CmdbReportCategory
from cmdb.models.reports_model.cmdb_report import CmdbReport
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_URL: str = '/report_categories'

CATEGORY_ID_FOR_GET: int = 9601
CATEGORY_ID_FOR_UPDATE: int = 9602
CATEGORY_ID_FOR_DELETE: int = 9603
CATEGORY_ID_PREDEFINED: int = 9604
CATEGORY_ID_IN_USE: int = 9605
MISSING_CATEGORY_ID: int = 9699

REPORT_ID_USING_CATEGORY: int = 9651

ALL_CATEGORY_IDS: list[int] = [
    CATEGORY_ID_FOR_GET, CATEGORY_ID_FOR_UPDATE, CATEGORY_ID_FOR_DELETE,
    CATEGORY_ID_PREDEFINED, CATEGORY_ID_IN_USE,
]
BOGUS_BODY_ID: int = 88888


def _category_doc(public_id: int, name: str = 'cat', predefined: bool = False) -> dict[str, Any]:
    """Builds a minimal CmdbReportCategory doc for direct DB insertion."""
    return {'public_id': public_id, 'name': name, 'predefined': predefined}


def _categories(database_manager: MongoDatabaseManager, database_name: str):
    """Returns the report-categories collection handle."""
    return database_manager.get_collection(CmdbReportCategory.COLLECTION, database_name)


def _reports(database_manager: MongoDatabaseManager, database_name: str):
    """Returns the reports collection handle."""
    return database_manager.get_collection(CmdbReport.COLLECTION, database_name)


@pytest.fixture(autouse=True)
def _cleanup(database_manager: MongoDatabaseManager, database_name: str):
    """Removes all seeded categories, the in-use report, and any bogus-id doc after each test."""
    yield
    _categories(database_manager, database_name).delete_many(
        {'public_id': {'$in': ALL_CATEGORY_IDS + [BOGUS_BODY_ID]}}
    )
    _reports(database_manager, database_name).delete_one({'public_id': REPORT_ID_USING_CATEGORY})


# -------------------------------------------------------------------------------------------------------------------- #
#                                                      CREATE                                                          #
# -------------------------------------------------------------------------------------------------------------------- #
class TestCreateReportCategory:
    """POST /report_categories/ creates a category with a server id and predefined forced to False."""

    def test_create_returns_id_and_forces_predefined_false(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """A create returns the new public_id and persists the category with predefined=False."""
        response = rest_api.post(f'{ROUTE_URL}/', query_string={'name': 'Created Category', 'predefined': 'true'})

        assert response.status_code == HTTPStatus.OK
        new_id = response.get_json()
        try:
            stored = _categories(database_manager, database_name).find_one({'public_id': new_id})
            assert stored['name'] == 'Created Category'
            # predefined is forced False regardless of the request
            assert stored['predefined'] is False
        finally:
            _categories(database_manager, database_name).delete_one({'public_id': new_id})


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       READ                                                           #
# -------------------------------------------------------------------------------------------------------------------- #
class TestReadReportCategory:
    """GET single + list return the expected envelopes; a missing id is 404."""

    def test_get_single_returns_category(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """A GET for a seeded category returns 200 and its data."""
        _categories(database_manager, database_name).insert_one(_category_doc(CATEGORY_ID_FOR_GET, 'Readable'))

        response = rest_api.get(f'{ROUTE_URL}/{CATEGORY_ID_FOR_GET}')

        assert response.status_code == HTTPStatus.OK
        assert response.get_json()['name'] == 'Readable'

    def test_get_single_missing_returns_404(self, rest_api) -> None:
        """A GET for a missing id returns 404."""
        assert rest_api.get(f'{ROUTE_URL}/{MISSING_CATEGORY_ID}').status_code == HTTPStatus.NOT_FOUND

    def test_get_list_returns_envelope(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """A GET list returns a results envelope including the seeded category."""
        _categories(database_manager, database_name).insert_one(_category_doc(CATEGORY_ID_FOR_GET, 'Listed'))

        response = rest_api.get(f'{ROUTE_URL}/')

        assert response.status_code == HTTPStatus.OK
        assert 'results' in response.get_json()

    def test_list_authenticates_before_parsing_params(self, rest_api) -> None:
        """Auth runs before collection-param parsing (decorator order).

        An unauthorized request whose collection params would fail to parse (``filter`` is not JSON)
        is rejected with 401 by ``@insert_request_user`` - not the 400 the parse decorator raised
        when it sat outside the auth decorators.
        """
        response = rest_api.get(f'{ROUTE_URL}/?filter=notjson', unauthorized=True)

        assert response.status_code == HTTPStatus.UNAUTHORIZED


# -------------------------------------------------------------------------------------------------------------------- #
#                                                      UPDATE                                                          #
# -------------------------------------------------------------------------------------------------------------------- #
class TestUpdateReportCategory:
    """PUT pins identity to the URL id and keeps predefined immutable; missing -> 404."""

    def test_update_persists_name_and_pins_identity_and_predefined(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """A body public_id/predefined are ignored: the name updates, identity + predefined stay."""
        _categories(database_manager, database_name).insert_one(
            _category_doc(CATEGORY_ID_FOR_UPDATE, 'Original', predefined=False)
        )

        response = rest_api.put(
            f'{ROUTE_URL}/{CATEGORY_ID_FOR_UPDATE}',
            query_string={'name': 'Renamed', 'public_id': BOGUS_BODY_ID, 'predefined': 'true'},
        )

        assert response.status_code == HTTPStatus.ACCEPTED
        categories = _categories(database_manager, database_name)
        # Identity pinned to the URL id - the bogus body id created nothing and did not move the doc
        assert categories.find_one({'public_id': BOGUS_BODY_ID}) is None
        stored = categories.find_one({'public_id': CATEGORY_ID_FOR_UPDATE})
        assert stored['name'] == 'Renamed'
        # predefined stays immutable despite predefined=true in the request
        assert stored['predefined'] is False

    def test_update_missing_returns_404(self, rest_api) -> None:
        """Updating a missing id returns 404."""
        response = rest_api.put(f'{ROUTE_URL}/{MISSING_CATEGORY_ID}', query_string={'name': 'x'})

        assert response.status_code == HTTPStatus.NOT_FOUND


# -------------------------------------------------------------------------------------------------------------------- #
#                                                      DELETE                                                          #
# -------------------------------------------------------------------------------------------------------------------- #
class TestDeleteReportCategory:
    """DELETE guards: success 200, missing 404, predefined 403, in-use 403 (none leak as 500)."""

    def test_delete_removes_category(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """A delete of a free category succeeds and removes the doc."""
        _categories(database_manager, database_name).insert_one(_category_doc(CATEGORY_ID_FOR_DELETE, 'Deletable'))

        response = rest_api.delete(f'{ROUTE_URL}/{CATEGORY_ID_FOR_DELETE}/')

        assert response.status_code == HTTPStatus.OK
        assert _categories(database_manager, database_name).find_one({'public_id': CATEGORY_ID_FOR_DELETE}) is None

    def test_delete_missing_returns_404(self, rest_api) -> None:
        """Deleting a missing id returns 404 (not a 500 from the generic handler)."""
        assert rest_api.delete(f'{ROUTE_URL}/{MISSING_CATEGORY_ID}/').status_code == HTTPStatus.NOT_FOUND

    def test_delete_predefined_returns_403(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """Deleting a predefined category is rejected with 403 (a business-rule rejection, not 405)."""
        _categories(database_manager, database_name).insert_one(
            _category_doc(CATEGORY_ID_PREDEFINED, 'System', predefined=True)
        )

        assert rest_api.delete(f'{ROUTE_URL}/{CATEGORY_ID_PREDEFINED}/').status_code == HTTPStatus.FORBIDDEN

    def test_delete_in_use_returns_403(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """Deleting a category still referenced by a report is rejected with 403."""
        _categories(database_manager, database_name).insert_one(_category_doc(CATEGORY_ID_IN_USE, 'Used'))
        _reports(database_manager, database_name).insert_one(
            {'public_id': REPORT_ID_USING_CATEGORY, 'report_category_id': CATEGORY_ID_IN_USE}
        )

        assert rest_api.delete(f'{ROUTE_URL}/{CATEGORY_ID_IN_USE}/').status_code == HTTPStatus.FORBIDDEN
