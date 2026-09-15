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
create/update routes read their data from the query string (parse_request_parameters), and both
sanitise it: a payload without a usable ``name`` is a 400 and every key outside the write whitelist
is dropped instead of being persisted as a document key. A predefined category is read-only, so it
can neither be renamed nor deleted
"""
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.group_model.cmdb_user_group import CmdbUserGroup
from cmdb.models.user_model import CmdbUser
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

# public_id of the seeded 'user' group, which holds no base.framework.report.* right at all
NO_REPORT_RIGHTS_GROUP_ID: int = 2
NO_REPORT_RIGHTS_USER_ID: int = 9610

# A group holding ONLY the report VIEW right, proving each write route demands its own right rather
# than merely any report right
VIEW_ONLY_GROUP_ID: int = 9611
VIEW_ONLY_USER_ID: int = 9612
REPORT_VIEW_RIGHT: str = 'base.framework.report.view'


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
        response = rest_api.post(f'{ROUTE_URL}/', json={'name': 'Created Category', 'predefined': True})

        assert response.status_code == HTTPStatus.OK
        new_id = response.get_json()
        try:
            stored = _categories(database_manager, database_name).find_one({'public_id': new_id})
            assert stored['name'] == 'Created Category'
            # predefined is forced False regardless of the request
            assert stored['predefined'] is False
        finally:
            _categories(database_manager, database_name).delete_one({'public_id': new_id})

    def test_create_trims_the_name_and_drops_unknown_keys(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """The name is stored trimmed and a parameter outside the write whitelist is not persisted."""
        response = rest_api.post(
            f'{ROUTE_URL}/',
            json={'name': '  Padded Category  ', 'public_id': BOGUS_BODY_ID, 'injected': 'value'},
        )

        assert response.status_code == HTTPStatus.OK
        new_id = response.get_json()
        try:
            # The payload public_id never reaches the insert - the server assigns the next id
            assert new_id != BOGUS_BODY_ID
            stored = _categories(database_manager, database_name).find_one({'public_id': new_id})
            assert stored['name'] == 'Padded Category'
            assert 'injected' not in stored
        finally:
            _categories(database_manager, database_name).delete_one({'public_id': new_id})

    @pytest.mark.parametrize('body', [{}, {'name': ''}, {'name': '   '}], ids=['absent', 'empty', 'blank'])
    def test_create_without_a_usable_name_returns_400(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str, body: dict[str, Any],
    ) -> None:
        """A missing / blank name is a 400 and no nameless category reaches the collection.

        'absent' and 'empty' are now refused by the schema before the handler runs; 'blank' passes the
        schema (a non-empty string) and is caught by the helper's trim-then-require.
        """
        categories = _categories(database_manager, database_name)
        before = categories.count_documents({})

        response = rest_api.post(f'{ROUTE_URL}/', json=body)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert categories.count_documents({}) == before


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
            json={'name': 'Renamed', 'public_id': BOGUS_BODY_ID, 'predefined': True},
        )

        assert response.status_code == HTTPStatus.ACCEPTED
        categories = _categories(database_manager, database_name)
        # Identity pinned to the URL id - the bogus body id created nothing and did not move the doc
        assert categories.find_one({'public_id': BOGUS_BODY_ID}) is None
        stored = categories.find_one({'public_id': CATEGORY_ID_FOR_UPDATE})
        assert stored['name'] == 'Renamed'
        # predefined stays immutable despite predefined=true in the request
        assert stored['predefined'] is False

    def test_update_drops_unknown_keys(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """A parameter outside the write whitelist is not written onto the stored document."""
        _categories(database_manager, database_name).insert_one(_category_doc(CATEGORY_ID_FOR_UPDATE, 'Original'))

        response = rest_api.put(
            f'{ROUTE_URL}/{CATEGORY_ID_FOR_UPDATE}',
            json={'name': '  Renamed  ', 'injected': 'value'},
        )

        assert response.status_code == HTTPStatus.ACCEPTED
        stored = _categories(database_manager, database_name).find_one({'public_id': CATEGORY_ID_FOR_UPDATE})
        assert stored['name'] == 'Renamed'
        assert 'injected' not in stored

    def test_update_without_a_usable_name_returns_400(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """A missing name is a 400 and the stored name is left untouched."""
        _categories(database_manager, database_name).insert_one(_category_doc(CATEGORY_ID_FOR_UPDATE, 'Original'))

        response = rest_api.put(f'{ROUTE_URL}/{CATEGORY_ID_FOR_UPDATE}', json={})

        assert response.status_code == HTTPStatus.BAD_REQUEST
        stored = _categories(database_manager, database_name).find_one({'public_id': CATEGORY_ID_FOR_UPDATE})
        assert stored['name'] == 'Original'

    def test_update_of_a_predefined_category_returns_403(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """A predefined category is read-only: the rename is refused and the stored name stays."""
        _categories(database_manager, database_name).insert_one(
            _category_doc(CATEGORY_ID_PREDEFINED, 'System', predefined=True)
        )

        response = rest_api.put(f'{ROUTE_URL}/{CATEGORY_ID_PREDEFINED}', json={'name': 'Renamed'})

        assert response.status_code == HTTPStatus.FORBIDDEN
        stored = _categories(database_manager, database_name).find_one({'public_id': CATEGORY_ID_PREDEFINED})
        assert stored['name'] == 'System'

    def test_update_missing_returns_404(self, rest_api) -> None:
        """Updating a missing id returns 404."""
        response = rest_api.put(f'{ROUTE_URL}/{MISSING_CATEGORY_ID}', json={'name': 'x'})

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

        response = rest_api.delete(f'{ROUTE_URL}/{CATEGORY_ID_FOR_DELETE}')

        assert response.status_code == HTTPStatus.OK
        assert _categories(database_manager, database_name).find_one({'public_id': CATEGORY_ID_FOR_DELETE}) is None

    def test_delete_missing_returns_404(self, rest_api) -> None:
        """Deleting a missing id returns 404 (not a 500 from the generic handler)."""
        assert rest_api.delete(f'{ROUTE_URL}/{MISSING_CATEGORY_ID}').status_code == HTTPStatus.NOT_FOUND

    def test_delete_predefined_returns_403(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """Deleting a predefined category is rejected with 403 (a business-rule rejection, not 405)."""
        _categories(database_manager, database_name).insert_one(
            _category_doc(CATEGORY_ID_PREDEFINED, 'System', predefined=True)
        )

        assert rest_api.delete(f'{ROUTE_URL}/{CATEGORY_ID_PREDEFINED}').status_code == HTTPStatus.FORBIDDEN

    def test_delete_in_use_returns_403(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """Deleting a category still referenced by a report is rejected with 403."""
        _categories(database_manager, database_name).insert_one(_category_doc(CATEGORY_ID_IN_USE, 'Used'))
        _reports(database_manager, database_name).insert_one(
            {'public_id': REPORT_ID_USING_CATEGORY, 'report_category_id': CATEGORY_ID_IN_USE}
        )

        assert rest_api.delete(f'{ROUTE_URL}/{CATEGORY_ID_IN_USE}').status_code == HTTPStatus.FORBIDDEN


# -------------------------------------------------------------------------------------------------------------------- #
#                                                   ACL RIGHTS                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
def _insert_user(database_manager: MongoDatabaseManager, database_name: str, user_id: int, group_id: int) -> CmdbUser:
    """Inserts a user in the given group and returns the matching CmdbUser for token minting."""
    database_manager.get_collection(CmdbUser.COLLECTION, database_name).insert_one({
        'public_id': user_id,
        'user_name': f'cat-rights-{user_id}',
        'active': True,
        'group_id': group_id,
        'registration_time': datetime.now(timezone.utc),
        'api_level': 2,
        'config_items_limit': 1000,
        'database': database_name,
    })

    return CmdbUser(public_id=user_id, user_name=f'cat-rights-{user_id}', active=True, group_id=group_id)


@pytest.fixture(name='no_rights_user', scope='module')
def fixture_no_rights_user(database_manager: MongoDatabaseManager, database_name: str):
    """An authenticated user in the seeded 'user' group, which carries no report right."""
    user = _insert_user(database_manager, database_name, NO_REPORT_RIGHTS_USER_ID, NO_REPORT_RIGHTS_GROUP_ID)
    yield user
    database_manager.get_collection(CmdbUser.COLLECTION, database_name)\
        .delete_one({'public_id': NO_REPORT_RIGHTS_USER_ID})


@pytest.fixture(name='view_only_user', scope='module')
def fixture_view_only_user(database_manager: MongoDatabaseManager, database_name: str):
    """A user whose group holds base.framework.report.view and nothing else."""
    groups = database_manager.get_collection(CmdbUserGroup.COLLECTION, database_name)
    groups.insert_one({
        'public_id': VIEW_ONLY_GROUP_ID,
        'name': 'cat-report-view-only',
        'label': 'Report view only',
        'rights': [REPORT_VIEW_RIGHT],
    })
    user = _insert_user(database_manager, database_name, VIEW_ONLY_USER_ID, VIEW_ONLY_GROUP_ID)
    yield user
    database_manager.get_collection(CmdbUser.COLLECTION, database_name).delete_one({'public_id': VIEW_ONLY_USER_ID})
    groups.delete_one({'public_id': VIEW_ONLY_GROUP_ID})


class TestReportCategoryRouteRights:
    """Every /report_categories route enforces its ReportRight.

    Report categories have no right family of their own and reuse the report rights - the pairing the
    Angular app already gates its category screens on (report-category-routing.module.ts,
    category-overview.component.html), so wiring the backend needed no frontend change.
    """

    def test_reads_require_the_view_right(self, rest_api, no_rights_user: CmdbUser) -> None:
        """The single read and the list both demand VIEW."""
        for url in (f'{ROUTE_URL}/{CATEGORY_ID_FOR_GET}', f'{ROUTE_URL}/'):
            assert rest_api.get(url, user=no_rights_user).status_code == HTTPStatus.FORBIDDEN, url

    def test_create_requires_the_add_right(self, rest_api, no_rights_user: CmdbUser) -> None:
        """A create without base.framework.report.add is refused before the body is validated."""
        response = rest_api.post(f'{ROUTE_URL}/', json={'name': 'denied'}, user=no_rights_user)

        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_update_requires_the_edit_right(self, rest_api, no_rights_user: CmdbUser) -> None:
        """An update without base.framework.report.edit is refused."""
        response = rest_api.put(
            f'{ROUTE_URL}/{CATEGORY_ID_FOR_UPDATE}', json={'name': 'denied'}, user=no_rights_user,
        )

        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_delete_requires_the_delete_right(self, rest_api, no_rights_user: CmdbUser) -> None:
        """A delete without base.framework.report.delete is refused."""
        response = rest_api.delete(f'{ROUTE_URL}/{CATEGORY_ID_FOR_DELETE}', user=no_rights_user)

        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_the_full_access_user_is_not_blocked(self, rest_api) -> None:
        """Sanity check that the rights were not simply wired to deny everyone."""
        assert rest_api.get(f'{ROUTE_URL}/').status_code == HTTPStatus.OK


class TestReportCategoryRightsAreDistinct:
    """Each write route demands its OWN right - a copy-pasted VIEW would pass the class above."""

    def test_view_right_allows_the_list(self, rest_api, view_only_user: CmdbUser) -> None:
        """VIEW really is sufficient for a read, so the group is not simply denied everything."""
        assert rest_api.get(f'{ROUTE_URL}/', user=view_only_user).status_code == HTTPStatus.OK

    def test_view_right_does_not_allow_create(self, rest_api, view_only_user: CmdbUser) -> None:
        """Create demands ADD."""
        response = rest_api.post(f'{ROUTE_URL}/', json={'name': 'denied'}, user=view_only_user)

        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_view_right_does_not_allow_update(self, rest_api, view_only_user: CmdbUser) -> None:
        """Update demands EDIT."""
        response = rest_api.put(
            f'{ROUTE_URL}/{CATEGORY_ID_FOR_UPDATE}', json={'name': 'denied'}, user=view_only_user,
        )

        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_view_right_does_not_allow_delete(self, rest_api, view_only_user: CmdbUser) -> None:
        """Delete demands DELETE - the privilege-escalation case."""
        response = rest_api.delete(f'{ROUTE_URL}/{CATEGORY_ID_FOR_DELETE}', user=view_only_user)

        assert response.status_code == HTTPStatus.FORBIDDEN


# -------------------------------------------------------------------------------------------------------------------- #
#                                   FRONTEND CONTRACT (schema validation + DELETE URL)                                 #
# -------------------------------------------------------------------------------------------------------------------- #
class TestFrontendRequestShape:
    """The exact request shapes report-category.service.ts sends still work.

    The write routes moved from reading the query string to reading the schema-validated JSON body.
    That is safe only because the Angular service sends its payload BOTH ways - it fills
    ``this.options.params`` from the same object it passes as the body. These tests pin that shape, so
    trimming the redundant query string out of the service would fail here instead of in production.
    """

    def test_create_with_the_frontend_shape(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """createCategory: body {name, predefined} plus the same values stringified in the query."""
        payload = {'name': 'FE Shaped', 'predefined': False}
        response = rest_api.post(
            f'{ROUTE_URL}/', json=payload, query_string={'name': 'FE Shaped', 'predefined': 'false'},
        )

        assert response.status_code == HTTPStatus.OK
        new_id = response.get_json()
        try:
            stored = _categories(database_manager, database_name).find_one({'public_id': new_id})
            assert stored['name'] == 'FE Shaped'
        finally:
            _categories(database_manager, database_name).delete_one({'public_id': new_id})

    def test_update_with_the_frontend_shape(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """updateCategory: body {public_id, name, predefined} plus the stringified query twin."""
        _categories(database_manager, database_name).insert_one(_category_doc(CATEGORY_ID_FOR_UPDATE, 'Original'))
        payload = {'public_id': CATEGORY_ID_FOR_UPDATE, 'name': 'FE Renamed', 'predefined': False}

        response = rest_api.put(
            f'{ROUTE_URL}/{CATEGORY_ID_FOR_UPDATE}',
            json=payload,
            query_string={'public_id': str(CATEGORY_ID_FOR_UPDATE), 'name': 'FE Renamed', 'predefined': 'false'},
        )

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)

    def test_a_write_without_a_body_is_refused(self, rest_api) -> None:
        """The query string alone is no longer enough - the body is the payload now

        Pins the consequence of the move for anyone reading the diff: a client that only sets query
        parameters gets a 400 rather than silently creating a category.
        """
        response = rest_api.post(f'{ROUTE_URL}/', query_string={'name': 'Query Only'})

        assert response.status_code == HTTPStatus.BAD_REQUEST

    @pytest.mark.parametrize('body, reason', [
        ({'name': 123}, 'name-not-a-string'),
        ({'name': 'x', 'predefined': 'true'}, 'predefined-not-a-boolean'),
        ({'name': 'x', 'public_id': 'nine'}, 'public_id-not-an-integer'),
    ], ids=lambda value: value if isinstance(value, str) else '')
    def test_schema_rejects_wrongly_typed_values(self, rest_api, body: dict[str, Any], reason: str) -> None:
        """What the schema buys over the old hand-rolled check: types are enforced, not just presence"""
        assert rest_api.post(f'{ROUTE_URL}/', json=body).status_code == HTTPStatus.BAD_REQUEST, reason

    def test_delete_without_a_trailing_slash_is_not_redirected(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """The URL the frontend calls matches the route directly - no 308 round-trip (backlog #108)"""
        categories = _categories(database_manager, database_name)
        categories.insert_one({'public_id': CATEGORY_ID_FOR_DELETE, 'name': 'To Delete', 'predefined': False})
        try:
            response = rest_api.delete(f'{ROUTE_URL}/{CATEGORY_ID_FOR_DELETE}')

            assert response.status_code != HTTPStatus.PERMANENT_REDIRECT
        finally:
            categories.delete_one({'public_id': CATEGORY_ID_FOR_DELETE})
