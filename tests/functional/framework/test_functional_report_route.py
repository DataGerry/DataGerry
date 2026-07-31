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
Functional smoke for the ``/reports`` REST routes

Covers the route-layer concerns the ReportsManager suite cannot: HTTP status codes, the
query-string parameter parsing on create / update (selected_fields and conditions arrive
JSON-encoded), the 400 when the report's Type cannot be resolved, the Ref-Section-Field guard
returning 400, the 404 on a missing id, the GET-list envelope, the run / count endpoints and the
DELETE + follow-up 404. The CRUD behaviour itself is asserted at the manager layer; these tests
verify the routes wrap it correctly
"""
import json
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.type_model import CmdbType
from cmdb.models.reports_model.cmdb_report import CmdbReport
from cmdb.models.reports_model.cmdb_report_category import CmdbReportCategory
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_URL: str = '/reports'

PLAIN_TYPE_ID: int = 8810
REF_SECTION_TYPE_ID: int = 8811
MISSING_TYPE_ID: int = 88199

REPORT_CATEGORY_ID: int = 8815
MISSING_CATEGORY_ID: int = 88159

REPORT_ID_FOR_GET: int = 8820
REPORT_ID_FOR_UPDATE: int = 8821
REPORT_ID_FOR_DELETE: int = 8822
REPORT_ID_FOR_RUN: int = 8823
REPORT_ID_FOR_COUNT: int = 8824
MISSING_REPORT_ID: int = 88299

ALL_REPORT_IDS: list[int] = [
    REPORT_ID_FOR_GET, REPORT_ID_FOR_UPDATE, REPORT_ID_FOR_DELETE, REPORT_ID_FOR_RUN, REPORT_ID_FOR_COUNT,
]
ALL_TYPE_IDS: list[int] = [PLAIN_TYPE_ID, REF_SECTION_TYPE_ID]
BOGUS_PAYLOAD_ID: int = 88888

PLAIN_FIELD: str = 'field-a'
REF_SECTION_FIELD: str = 'rsf'

ORIGINAL_NAME: str = 'Functional Report'
UPDATED_NAME: str = 'Functional Report (updated)'

EMPTY_CONDITIONS: dict[str, Any] = {'condition': 'and', 'rules': []}


def _type_doc(public_id: int, fields: list[dict[str, Any]]) -> dict[str, Any]:
    """Builds a CmdbType doc for direct DB insertion (so create / run can resolve the report type)."""
    field_names = [field['name'] for field in fields]
    return {
        'public_id': public_id,
        'name': f'report-type-{public_id}',
        'label': 'Report Type',
        'author_id': 1,
        'active': True,
        'fields': fields,
        'render_meta': {
            'icon': 'fa-cube',
            'sections': [{'type': 'section', 'name': 'main', 'label': 'Main', 'fields': field_names}],
            'summary': {'fields': field_names},
        },
        'acl': {'activated': False, 'groups': {'includes': None}},
        'version': '1.0.0',
        'creation_time': datetime.now(timezone.utc),
    }


def _report_doc(public_id: int, name: str = ORIGINAL_NAME, type_id: int = PLAIN_TYPE_ID) -> dict[str, Any]:
    """Builds a complete CmdbReport doc for direct DB insertion."""
    return {
        'public_id': public_id,
        'report_category_id': REPORT_CATEGORY_ID,
        'name': name,
        'type_id': type_id,
        'selected_fields': [PLAIN_FIELD],
        'conditions': EMPTY_CONDITIONS,
        'report_query': {'data': '{}'},
        'predefined': False,
        'mds_mode': 'ROWS',
    }


def _report_params(
    name: str = ORIGINAL_NAME,
    type_id: int = PLAIN_TYPE_ID,
    selected_fields: list[str] | None = None,
    report_category_id: int = REPORT_CATEGORY_ID,
) -> dict[str, str]:
    """Builds the query-string params a report Create / Update parses (JSON-encoded list / dict)."""
    return {
        'report_category_id': str(report_category_id),
        'name': name,
        'type_id': str(type_id),
        'selected_fields': json.dumps(selected_fields if selected_fields is not None else [PLAIN_FIELD]),
        'conditions': json.dumps(EMPTY_CONDITIONS),
        'mds_mode': 'ROWS',
    }


def _reports(database_manager: MongoDatabaseManager, database_name: str):
    """Returns the report collection bound to the test database."""
    return database_manager.get_collection(CmdbReport.COLLECTION, database_name)


@pytest.fixture(scope='module', autouse=True)
def _seed_types_and_cleanup(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds the report Types + the report Category once and removes all test data afterwards.

    The category has to exist: a report write verifies both of its foreign keys, so a report pointing
    at a non-existent CmdbReportCategory is rejected with 400.
    """
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    types.insert_many([
        _type_doc(PLAIN_TYPE_ID, [{'type': 'text', 'name': PLAIN_FIELD, 'label': 'A'}]),
        _type_doc(REF_SECTION_TYPE_ID, [{'type': 'ref-section-field', 'name': REF_SECTION_FIELD, 'label': 'RSF'}]),
    ])
    categories = database_manager.get_collection(CmdbReportCategory.COLLECTION, database_name)
    categories.insert_one({'public_id': REPORT_CATEGORY_ID, 'name': 'Functional', 'predefined': False})
    yield
    types.delete_many({'public_id': {'$in': ALL_TYPE_IDS}})
    categories.delete_one({'public_id': REPORT_CATEGORY_ID})
    _reports(database_manager, database_name).delete_many({'public_id': {'$in': ALL_REPORT_IDS}})


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       CREATE                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class TestPostReport:
    """POST /reports/ creates a report and rejects bad type / Ref-Section-Field selections."""

    def test_creates_new_report(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """A POST with valid params succeeds and the created report is then queryable."""
        response = rest_api.post(f'{ROUTE_URL}/', query_string=_report_params(name='created-report'))

        assert response.status_code == HTTPStatus.OK
        new_id = response.get_json()
        try:
            follow_up = rest_api.get(f'{ROUTE_URL}/{new_id}')
            assert follow_up.status_code == HTTPStatus.OK
        finally:
            _reports(database_manager, database_name).delete_one({'public_id': new_id})

    def test_unknown_type_returns_400(self, rest_api) -> None:
        """A POST whose type_id does not resolve to a CmdbType is rejected with 400."""
        response = rest_api.post(f'{ROUTE_URL}/', query_string=_report_params(type_id=MISSING_TYPE_ID))

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_ref_section_field_selection_returns_400(self, rest_api) -> None:
        """A POST selecting a Ref-Section-Field of the type is rejected with 400."""
        params = _report_params(type_id=REF_SECTION_TYPE_ID, selected_fields=[REF_SECTION_FIELD])

        response = rest_api.post(f'{ROUTE_URL}/', query_string=params)

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_unknown_report_category_returns_400(self, rest_api) -> None:
        """A POST whose report_category_id does not resolve to a CmdbReportCategory is rejected."""
        response = rest_api.post(
            f'{ROUTE_URL}/', query_string=_report_params(report_category_id=MISSING_CATEGORY_ID),
        )

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_create_forces_predefined_false_and_drops_unknown_keys(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """predefined is server-owned, and a parameter outside the write whitelist is not persisted."""
        params = _report_params(name='sanitised-report')
        params.update({'predefined': 'true', 'public_id': str(BOGUS_PAYLOAD_ID), 'injected': 'value'})

        response = rest_api.post(f'{ROUTE_URL}/', query_string=params)

        assert response.status_code == HTTPStatus.OK
        new_id = response.get_json()
        try:
            # The payload public_id never reaches the insert - the server assigns the next id
            assert new_id != BOGUS_PAYLOAD_ID
            stored = _reports(database_manager, database_name).find_one({'public_id': new_id})
            assert stored['predefined'] is False
            assert 'injected' not in stored
            # report_query is always rebuilt from the conditions, never taken from the request
            assert 'data' in stored['report_query']
        finally:
            _reports(database_manager, database_name).delete_one({'public_id': new_id})

    def test_missing_required_parameter_returns_400(self, rest_api) -> None:
        """A POST without a required parameter is rejected with 400."""
        params = _report_params()
        del params['name']

        assert rest_api.post(f'{ROUTE_URL}/', query_string=params).status_code == HTTPStatus.BAD_REQUEST


# -------------------------------------------------------------------------------------------------------------------- #
#                                                        READ                                                          #
# -------------------------------------------------------------------------------------------------------------------- #
class TestGetReport:
    """GET /reports/<id> and GET /reports/ return the expected responses."""

    @pytest.fixture(autouse=True)
    def _seed(self, database_manager: MongoDatabaseManager, database_name: str):
        """Inserts one report directly via the DB before each test and removes it after."""
        _reports(database_manager, database_name).insert_one(_report_doc(REPORT_ID_FOR_GET))
        yield
        _reports(database_manager, database_name).delete_one({'public_id': REPORT_ID_FOR_GET})

    def test_get_single_returns_report(self, rest_api) -> None:
        """A GET for a seeded report returns 200."""
        response = rest_api.get(f'{ROUTE_URL}/{REPORT_ID_FOR_GET}')

        assert response.status_code == HTTPStatus.OK

    def test_get_single_missing_returns_404(self, rest_api) -> None:
        """A GET for a missing id returns 404."""
        response = rest_api.get(f'{ROUTE_URL}/{MISSING_REPORT_ID}')

        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_get_list_returns_results_envelope(self, rest_api) -> None:
        """A GET list returns a JSON envelope whose results length matches X-Total-Count."""
        response = rest_api.get(f'{ROUTE_URL}/')

        assert response.status_code == HTTPStatus.OK
        body = response.get_json()
        assert 'results' in body
        assert len(body['results']) == int(response.headers['X-Total-Count'])

    def test_list_authenticates_before_parsing_params(self, rest_api) -> None:
        """Auth runs before collection-param parsing (decorator order).

        An unauthorized request whose collection params would fail to parse (``filter`` is not JSON)
        is rejected with 401 by ``@insert_request_user`` - not the 400 the parse decorator raised
        when it sat outside the auth decorators.
        """
        response = rest_api.get(f'{ROUTE_URL}/?filter=notjson', unauthorized=True)

        assert response.status_code == HTTPStatus.UNAUTHORIZED


# -------------------------------------------------------------------------------------------------------------------- #
#                                                    RUN / COUNT                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
class TestRunAndCountReport:
    """GET /reports/run/<id> executes a report; /<type_id>/count_reports_of_type counts by type."""

    def test_run_existing_report_returns_200(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """Running a stored report evaluates its query and answers 200."""
        _reports(database_manager, database_name).insert_one(_report_doc(REPORT_ID_FOR_RUN))
        try:
            response = rest_api.get(f'{ROUTE_URL}/run/{REPORT_ID_FOR_RUN}')

            assert response.status_code == HTTPStatus.OK
        finally:
            _reports(database_manager, database_name).delete_one({'public_id': REPORT_ID_FOR_RUN})

    def test_run_missing_report_returns_404(self, rest_api) -> None:
        """Running a missing report returns 404."""
        response = rest_api.get(f'{ROUTE_URL}/run/{MISSING_REPORT_ID}')

        assert response.status_code == HTTPStatus.NOT_FOUND

    @pytest.mark.parametrize('preview_value', ['1', 'yes', 'maybe'])
    def test_run_with_a_malformed_preview_flag_returns_400(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str, preview_value: str,
    ) -> None:
        """An unrecognised ?preview= value is a bad request, not an internal 500."""
        _reports(database_manager, database_name).insert_one(_report_doc(REPORT_ID_FOR_RUN))
        try:
            response = rest_api.get(f'{ROUTE_URL}/run/{REPORT_ID_FOR_RUN}?preview={preview_value}')

            assert response.status_code == HTTPStatus.BAD_REQUEST
        finally:
            _reports(database_manager, database_name).delete_one({'public_id': REPORT_ID_FOR_RUN})

    def test_run_report_without_a_stored_query_returns_200(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """A document that carries no report_query answers an empty result instead of a 500."""
        legacy_report = _report_doc(REPORT_ID_FOR_RUN)
        del legacy_report['report_query']
        _reports(database_manager, database_name).insert_one(legacy_report)
        try:
            response = rest_api.get(f'{ROUTE_URL}/run/{REPORT_ID_FOR_RUN}')

            assert response.status_code == HTTPStatus.OK
            assert response.get_json() == {}
        finally:
            _reports(database_manager, database_name).delete_one({'public_id': REPORT_ID_FOR_RUN})

    def test_count_reports_of_type_counts_the_seeded_report(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """The count endpoint reports at least the one seeded report of the type."""
        _reports(database_manager, database_name).insert_one(_report_doc(REPORT_ID_FOR_COUNT, type_id=PLAIN_TYPE_ID))
        try:
            response = rest_api.get(f'{ROUTE_URL}/{PLAIN_TYPE_ID}/count_reports_of_type')

            assert response.status_code == HTTPStatus.OK
            assert response.get_json() >= 1
        finally:
            _reports(database_manager, database_name).delete_one({'public_id': REPORT_ID_FOR_COUNT})


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       UPDATE                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class TestPutReport:
    """PUT /reports/<id> writes the new payload over the existing report."""

    def test_update_persists_new_name(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """After PUT, the stored report carries the updated name."""
        collection = _reports(database_manager, database_name)
        collection.insert_one(_report_doc(REPORT_ID_FOR_UPDATE))
        try:
            response = rest_api.put(
                f'{ROUTE_URL}/{REPORT_ID_FOR_UPDATE}', query_string=_report_params(name=UPDATED_NAME),
            )

            assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
            assert collection.find_one({'public_id': REPORT_ID_FOR_UPDATE})['name'] == UPDATED_NAME
        finally:
            collection.delete_one({'public_id': REPORT_ID_FOR_UPDATE})

    def test_update_pins_identity_and_predefined_and_drops_unknown_keys(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """A payload public_id / predefined / extra key cannot reach the stored document."""
        collection = _reports(database_manager, database_name)
        stored_doc = _report_doc(REPORT_ID_FOR_UPDATE)
        stored_doc['predefined'] = True
        collection.insert_one(stored_doc)
        try:
            params = _report_params(name=UPDATED_NAME)
            params.update({'predefined': 'false', 'public_id': str(BOGUS_PAYLOAD_ID), 'injected': 'value'})

            response = rest_api.put(f'{ROUTE_URL}/{REPORT_ID_FOR_UPDATE}', query_string=params)

            assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
            # Identity pinned to the URL id - the bogus payload id created / moved nothing
            assert collection.find_one({'public_id': BOGUS_PAYLOAD_ID}) is None
            stored = collection.find_one({'public_id': REPORT_ID_FOR_UPDATE})
            assert stored['name'] == UPDATED_NAME
            # predefined is carried over from the stored report, not taken from the payload
            assert stored['predefined'] is True
            assert 'injected' not in stored
        finally:
            collection.delete_one({'public_id': REPORT_ID_FOR_UPDATE})

    def test_update_unknown_report_category_returns_400(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """A PUT whose report_category_id does not resolve is rejected with 400."""
        collection = _reports(database_manager, database_name)
        collection.insert_one(_report_doc(REPORT_ID_FOR_UPDATE))
        try:
            response = rest_api.put(
                f'{ROUTE_URL}/{REPORT_ID_FOR_UPDATE}',
                query_string=_report_params(report_category_id=MISSING_CATEGORY_ID),
            )

            assert response.status_code == HTTPStatus.BAD_REQUEST
        finally:
            collection.delete_one({'public_id': REPORT_ID_FOR_UPDATE})

    def test_update_response_matches_the_stored_document(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """The echoed document equals a re-read of the stored one (the update is a $set of the payload)."""
        collection = _reports(database_manager, database_name)
        collection.insert_one(_report_doc(REPORT_ID_FOR_UPDATE))
        try:
            response = rest_api.put(
                f'{ROUTE_URL}/{REPORT_ID_FOR_UPDATE}', query_string=_report_params(name=UPDATED_NAME),
            )
            echoed: dict[str, Any] = response.get_json()['result']
            re_read = rest_api.get(f'{ROUTE_URL}/{REPORT_ID_FOR_UPDATE}').get_json()

            assert echoed == re_read
        finally:
            collection.delete_one({'public_id': REPORT_ID_FOR_UPDATE})

    def test_update_unknown_type_returns_400(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """A PUT whose type_id does not resolve to a CmdbType is rejected with 400."""
        collection = _reports(database_manager, database_name)
        collection.insert_one(_report_doc(REPORT_ID_FOR_UPDATE))
        try:
            response = rest_api.put(
                f'{ROUTE_URL}/{REPORT_ID_FOR_UPDATE}', query_string=_report_params(type_id=MISSING_TYPE_ID),
            )

            assert response.status_code == HTTPStatus.BAD_REQUEST
        finally:
            collection.delete_one({'public_id': REPORT_ID_FOR_UPDATE})

    def test_update_ref_section_field_selection_returns_400(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """A PUT selecting a Ref-Section-Field of the type is rejected with 400."""
        collection = _reports(database_manager, database_name)
        collection.insert_one(_report_doc(REPORT_ID_FOR_UPDATE))
        try:
            params = _report_params(type_id=REF_SECTION_TYPE_ID, selected_fields=[REF_SECTION_FIELD])
            response = rest_api.put(f'{ROUTE_URL}/{REPORT_ID_FOR_UPDATE}', query_string=params)

            assert response.status_code == HTTPStatus.BAD_REQUEST
        finally:
            collection.delete_one({'public_id': REPORT_ID_FOR_UPDATE})


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       DELETE                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class TestDeleteReport:
    """DELETE /reports/<id>/ removes the report; a follow-up GET reports 404."""

    def test_delete_removes_report(
        self, rest_api, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """A DELETE succeeds and a subsequent GET for the same id returns 404."""
        _reports(database_manager, database_name).insert_one(_report_doc(REPORT_ID_FOR_DELETE))
        try:
            response = rest_api.delete(f'{ROUTE_URL}/{REPORT_ID_FOR_DELETE}/')

            assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
            follow_up = rest_api.get(f'{ROUTE_URL}/{REPORT_ID_FOR_DELETE}')
            assert follow_up.status_code == HTTPStatus.NOT_FOUND
        finally:
            _reports(database_manager, database_name).delete_one({'public_id': REPORT_ID_FOR_DELETE})
