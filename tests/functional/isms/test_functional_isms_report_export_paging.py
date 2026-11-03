# DataGerry - OpenSource Enterprise CMDB
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
Functional tests for how the Risk Treatment Plan and RiskAssessment reports read a page and an export

A ``$facet`` answers its rows inside one document, capped at 16 MB, so only a bounded page is read in one
``$facet`` pass. ``limit=0`` - the frontend's CSV / XLSX / PDF export - and a page above
``REPORT_FACET_MAX_LIMIT`` are read through a cursor. These tests spy on the aggregations the routes run and
show that each path answers the same rows and the same total. Seeding 16 MB of assessments is out of reach for
a test, so the shape of the aggregations is what is pinned.
"""
import json
from http import HTTPStatus
from typing import Any
from urllib.parse import urlencode

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.isms_manager.risk_assessment_manager import RiskAssessmentManager
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.models.isms_model import IsmsRisk, IsmsRiskAssessment
from cmdb.security.license.license_constants import LicenseFeature
from cmdb.interface.rest_api.routes.isms_routes import isms_report_helper
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_URL: str = '/isms/reports'
# The two reports read through read_report_page, each with the key its row carries the risk's name under
AGGREGATION_REPORTS: list[tuple[str, str]] = [
    ('risk_treatment_plan', 'risk_name'),
    ('risk_assessments', 'risk_title'),
]
FACET_OPERATOR: str = '$facet'
COUNT_OPERATOR: str = '$count'

PAGING_RISK_BASE_ID: int = 99650
PAGING_RA_BASE_ID: int = 99660
# Distinct names in sort order; every request filters on them, so the other rows of the test database never count
PAGING_RISK_NAMES: list[str] = ['Paging A', 'Paging B', 'Paging C', 'Paging D', 'Paging E']
# A bound below the seeded count, so a page of PAGE_ABOVE_BOUND rows is "above the bound" in the tests
TEST_FACET_BOUND: int = 1
PAGE_ABOVE_BOUND: int = 2
# With five rows at two per page: page 2 is full, page 3 holds the one last row, page 4 is past the end
FULL_PAGE: int = 2
LAST_PAGE: int = 3
PAST_THE_END_PAGE: int = 4


@pytest.fixture(autouse=True)
def _isms_licensed(monkeypatch: pytest.MonkeyPatch):
    """Licenses the ISMS feature so the gated report routes are reachable."""
    monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, feature: feature == LicenseFeature.ISMS)


@pytest.fixture(name='seeded_ids')
def fixture_seeded_ids(database_manager: MongoDatabaseManager, database_name: str):
    """One Risk per PAGING_RISK_NAMES and one RiskAssessment of each, removed again; yields the assessment ids"""
    risks = database_manager.get_collection(IsmsRisk.COLLECTION, database_name)
    assessments = database_manager.get_collection(IsmsRiskAssessment.COLLECTION, database_name)
    risk_ids: list[int] = list(range(PAGING_RISK_BASE_ID, PAGING_RISK_BASE_ID + len(PAGING_RISK_NAMES)))
    ra_ids: list[int] = list(range(PAGING_RA_BASE_ID, PAGING_RA_BASE_ID + len(PAGING_RISK_NAMES)))

    risks.insert_many([{'public_id': risk_id, 'name': name} for risk_id, name in zip(risk_ids, PAGING_RISK_NAMES)])
    assessments.insert_many([
        {'public_id': ra_id, 'risk_id': risk_id, 'object_id_ref_type': 'OBJECT', 'object_id': 0}
        for ra_id, risk_id in zip(ra_ids, risk_ids)
    ])

    yield ra_ids

    assessments.delete_many({'public_id': {'$in': ra_ids}})
    risks.delete_many({'public_id': {'$in': risk_ids}})


@pytest.fixture(name='pipelines')
def fixture_pipelines(monkeypatch: pytest.MonkeyPatch) -> list[list[dict[str, Any]]]:
    """Every pipeline the report aggregations run, in order - the aggregations still run for real"""
    original = RiskAssessmentManager.aggregate_within_time_limit
    recorded: list[list[dict[str, Any]]] = []

    def _spy(self, pipeline: list[dict[str, Any]], time_limit_ms: int, **kwargs: Any) -> list[dict[str, Any]]:
        recorded.append(list(pipeline))
        return original(self, pipeline, time_limit_ms, **kwargs)

    monkeypatch.setattr(RiskAssessmentManager, 'aggregate_within_time_limit', _spy)

    return recorded


def _operators(pipeline: list[dict[str, Any]]) -> list[str]:
    """The operator of every stage"""
    return [next(iter(stage)) for stage in pipeline]


def _get(rest_api, report: str, name_key: str, **query: Any) -> dict[str, Any]:
    """The report's body over the seeded rows only, sorted by the risk name"""
    arguments: str = urlencode({
        'sort': name_key, 'order': 1, 'filter': json.dumps({name_key: {'$in': PAGING_RISK_NAMES}}), **query,
    })
    response = rest_api.get(f'{ROUTE_URL}/{report}?{arguments}')

    assert response.status_code == HTTPStatus.OK
    return response.get_json()


@pytest.mark.usefixtures('seeded_ids')
@pytest.mark.parametrize('report, name_key', AGGREGATION_REPORTS)
class TestReportExportAndPaging:
    """The export and every page size answer the same rows and total."""

    def test_an_export_reads_every_row_without_a_facet(self, rest_api, pipelines, report: str,
                                                       name_key: str) -> None:
        """limit=0 runs one aggregation with no $facet and no $count, and answers every row."""
        body = _get(rest_api, report, name_key, limit=0)

        assert len(pipelines) == 1
        assert FACET_OPERATOR not in _operators(pipelines[0])
        assert COUNT_OPERATOR not in _operators(pipelines[0])
        assert [row[name_key] for row in body['results']] == PAGING_RISK_NAMES
        assert body['total'] == len(PAGING_RISK_NAMES)

    def test_an_export_answers_what_the_facet_counts(self, rest_api, pipelines, report: str, name_key: str) -> None:
        """The export's total is the total a paged read counts in its $facet."""
        export = _get(rest_api, report, name_key, limit=0)
        page = _get(rest_api, report, name_key, limit=PAGE_ABOVE_BOUND)

        assert FACET_OPERATOR in _operators(pipelines[-1])
        assert page['total'] == export['total']
        assert page['results'] == export['results'][:PAGE_ABOVE_BOUND]

    def test_a_full_page_above_the_bound_counts_in_a_second_read(self, rest_api, pipelines, monkeypatch,
                                                                 report: str, name_key: str) -> None:
        """Above the bound and full: rows through a cursor, then a $count - with the facet's rows and total."""
        expected = _get(rest_api, report, name_key, limit=PAGE_ABOVE_BOUND, page=FULL_PAGE)
        pipelines.clear()
        monkeypatch.setattr(isms_report_helper, 'REPORT_FACET_MAX_LIMIT', TEST_FACET_BOUND)

        body = _get(rest_api, report, name_key, limit=PAGE_ABOVE_BOUND, page=FULL_PAGE)

        assert [FACET_OPERATOR in _operators(pipeline) for pipeline in pipelines] == [False, False]
        assert _operators(pipelines[1])[-1] == COUNT_OPERATOR
        assert body['results'] == expected['results']
        assert body['total'] == expected['total']

    def test_the_last_page_above_the_bound_needs_no_count(self, rest_api, pipelines, monkeypatch,
                                                          report: str, name_key: str) -> None:
        """A short page decides the total itself - one read, and the same total as the facet."""
        expected = _get(rest_api, report, name_key, limit=PAGE_ABOVE_BOUND, page=LAST_PAGE)
        pipelines.clear()
        monkeypatch.setattr(isms_report_helper, 'REPORT_FACET_MAX_LIMIT', TEST_FACET_BOUND)

        body = _get(rest_api, report, name_key, limit=PAGE_ABOVE_BOUND, page=LAST_PAGE)

        assert len(pipelines) == 1
        assert [row[name_key] for row in body['results']] == PAGING_RISK_NAMES[-1:]
        assert body['results'] == expected['results']
        assert body['total'] == expected['total'] == len(PAGING_RISK_NAMES)

    def test_a_page_past_the_end_above_the_bound_counts(self, rest_api, pipelines, monkeypatch,
                                                        report: str, name_key: str) -> None:
        """No rows past the end, so the total is read by a count - and still names every row."""
        monkeypatch.setattr(isms_report_helper, 'REPORT_FACET_MAX_LIMIT', TEST_FACET_BOUND)

        body = _get(rest_api, report, name_key, limit=PAGE_ABOVE_BOUND, page=PAST_THE_END_PAGE)

        assert len(pipelines) == 2
        assert body['results'] == []
        assert body['total'] == len(PAGING_RISK_NAMES)
