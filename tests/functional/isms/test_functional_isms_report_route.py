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
Functional smoke for the ``/isms/reports`` routes

Each report GET drives a full aggregation pipeline (or the RiskMatrix report builder) plus the
object-summary post-processing. These smoke tests assert the routes wire up and respond 200 with a
parseable body; the report contents are exercised against whatever ISMS data is present. The SOA
test additionally checks that the extendable-option ids are resolved to their labels. The routes
are ISMS-license gated, so the check is stubbed.
"""
from http import HTTPStatus
from urllib.parse import urlencode

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.isms_manager.risk_assessment_manager import RiskAssessmentManager
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.models.isms_model import IsmsControlMeasure, IsmsRisk, IsmsRiskAssessment
from cmdb.models.extendable_option_model import CmdbExtendableOption, OptionType
from cmdb.security.license.license_constants import LicenseFeature
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_URL: str = '/isms/reports'
# Reports wrapped in a paginated GetMultiResponse envelope
PAGINATED_REPORTS: list[str] = ['risk_treatment_plan', 'risk_assessments', 'soa']

# Risk Treatment Plan pagination fixtures: a handful of bare RiskAssessments to page over
RTP_RA_BASE_ID: int = 99420
RTP_SEEDED_COUNT: int = 5

# Risk Assessments pagination fixtures: RiskAssessments plus the Risk they reference (the report's
# hard $unwind on the risk lookup drops assessments whose risk does not resolve)
RA_RISK_ID: int = 99430
RA_RA_BASE_ID: int = 99431
RA_SEEDED_COUNT: int = 5

# SOA-specific fixtures: a control measure whose source / implementation_state ids get resolved to labels
SOA_CM_ID: int = 99401
SOA_SOURCE_OPTION_ID: int = 99402
SOA_STATE_OPTION_ID: int = 99403
SOA_SOURCE_VALUE: str = 'ImportTest ISO Source'
SOA_STATE_VALUE: str = 'ImportTest Implemented State'

# SOA pagination fixtures: a handful of ControlMeasures to page over
SOA_CM_BASE_ID: int = 99440
SOA_SEEDED_COUNT: int = 5

# Sort/offset fixtures: Risks with known names + one RiskAssessment each, to assert ordering and paging
# across the two aggregation reports. Names are deliberately not in insertion order.
SORT_RISK_BASE_ID: int = 99450
SORT_RA_BASE_ID: int = 99455
SORT_RISK_NAMES: list[str] = ['ZzzSortName', 'AaaSortName', 'MmmSortName']

# SOA natural-sort fixtures: identifiers inserted out of order; sort_key must yield A.1, A.2, A.10
# (a plain lexicographic sort would wrongly give A.1, A.10, A.2)
SOA_NATURAL_SORT_IDENTIFIERS: dict[str, int] = {'A.10': 99460, 'A.1': 99461, 'A.2': 99462}

# Risk-assessment report search fixtures: two Risks whose names differ by a distinctive token, each
# with one RiskAssessment, so the server-side ?search= can be shown to keep the match and drop the miss.
SEARCH_TERM: str = 'Zxqvv'
SEARCH_RISK_MATCH_ID: int = 99470
SEARCH_RISK_MISS_ID: int = 99471
SEARCH_RA_MATCH_ID: int = 99472
SEARCH_RA_MISS_ID: int = 99473
SEARCH_MATCH_RISK_NAME: str = f'{SEARCH_TERM}Alpha Risk'
SEARCH_MISS_RISK_NAME: str = 'Ordinary Beta Risk'


def _seed_search_assessments(
        database_manager: MongoDatabaseManager,
        database_name: str) -> tuple[list[int], list[int]]:
    """
    Seeds a "match" and a "miss" Risk (distinguished by SEARCH_TERM in the name) plus one
    RiskAssessment referencing each, so the report's risk-name search can be exercised.

    Returns:
        tuple[list[int], list[int]]: The seeded (risk public_ids, risk assessment public_ids), for cleanup
    """
    risks = database_manager.get_collection(IsmsRisk.COLLECTION, database_name)
    assessments = database_manager.get_collection(IsmsRiskAssessment.COLLECTION, database_name)

    risks.insert_many([
        {'public_id': SEARCH_RISK_MATCH_ID, 'name': SEARCH_MATCH_RISK_NAME},
        {'public_id': SEARCH_RISK_MISS_ID, 'name': SEARCH_MISS_RISK_NAME},
    ])
    assessments.insert_many([
        {'public_id': SEARCH_RA_MATCH_ID, 'risk_id': SEARCH_RISK_MATCH_ID,
         'object_id_ref_type': 'OBJECT', 'object_id': 0},
        {'public_id': SEARCH_RA_MISS_ID, 'risk_id': SEARCH_RISK_MISS_ID,
         'object_id_ref_type': 'OBJECT', 'object_id': 0},
    ])

    return [SEARCH_RISK_MATCH_ID, SEARCH_RISK_MISS_ID], [SEARCH_RA_MATCH_ID, SEARCH_RA_MISS_ID]


def _seed_named_assessments(
        database_manager: MongoDatabaseManager,
        database_name: str) -> tuple[list[int], list[int]]:
    """
    Seeds one Risk per SORT_RISK_NAMES plus a RiskAssessment referencing each.

    The assessments carry a resolvable risk so both aggregation reports (the treatment plan and the
    risk assessments report, the latter dropping assessments whose risk is missing) surface them.

    Returns:
        tuple[list[int], list[int]]: The seeded (risk public_ids, risk assessment public_ids), for cleanup
    """
    risks = database_manager.get_collection(IsmsRisk.COLLECTION, database_name)
    assessments = database_manager.get_collection(IsmsRiskAssessment.COLLECTION, database_name)

    risk_ids = list(range(SORT_RISK_BASE_ID, SORT_RISK_BASE_ID + len(SORT_RISK_NAMES)))
    ra_ids = list(range(SORT_RA_BASE_ID, SORT_RA_BASE_ID + len(SORT_RISK_NAMES)))

    risks.insert_many([
        {'public_id': risk_id, 'name': name} for risk_id, name in zip(risk_ids, SORT_RISK_NAMES)
    ])
    assessments.insert_many([
        {'public_id': ra_id, 'risk_id': risk_id, 'object_id_ref_type': 'OBJECT', 'object_id': 0}
        for ra_id, risk_id in zip(ra_ids, risk_ids)
    ])

    return risk_ids, ra_ids


@pytest.fixture(autouse=True)
def _isms_licensed(monkeypatch: pytest.MonkeyPatch):
    """Licenses the ISMS feature so the gated report routes are reachable."""
    monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, feature: feature == LicenseFeature.ISMS)


class TestIsmsReports:
    """Every ISMS report route responds 200 with a parseable body."""

    def test_risk_matrix_report_responds(self, rest_api) -> None:
        """The RiskMatrix report returns 200 with a dict body (builder guards missing data)."""
        response = rest_api.get(f'{ROUTE_URL}/risk_matrix')

        assert response.status_code == HTTPStatus.OK
        assert isinstance(response.get_json(), dict)

    @pytest.mark.parametrize('report', PAGINATED_REPORTS)
    def test_paginated_report_responds(self, rest_api, report: str) -> None:
        """The paginated reports return 200 with a GetMultiResponse envelope (results / total / pager)."""
        response = rest_api.get(f'{ROUTE_URL}/{report}')

        assert response.status_code == HTTPStatus.OK
        payload = response.get_json()
        assert isinstance(payload, dict)
        assert isinstance(payload['results'], list)
        assert 'total' in payload
        assert 'pager' in payload

    def test_risk_treatment_plan_respects_limit(self, rest_api,
                                                database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A limit query param caps the returned rows while total reflects the full set."""
        assessments = database_manager.get_collection(IsmsRiskAssessment.COLLECTION, database_name)
        seeded_ids = list(range(RTP_RA_BASE_ID, RTP_RA_BASE_ID + RTP_SEEDED_COUNT))
        assessments.insert_many([
            {'public_id': ra_id, 'object_id_ref_type': 'OBJECT', 'object_id': 0}
            for ra_id in seeded_ids
        ])
        try:
            response = rest_api.get(f'{ROUTE_URL}/risk_treatment_plan?limit=2')

            assert response.status_code == HTTPStatus.OK
            payload = response.get_json()
            assert len(payload['results']) <= 2
            assert payload['total'] >= RTP_SEEDED_COUNT
        finally:
            assessments.delete_many({'public_id': {'$in': seeded_ids}})

    def test_risk_assessments_respects_limit(self, rest_api,
                                             database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A limit query param caps the returned rows while total reflects the full set."""
        risks = database_manager.get_collection(IsmsRisk.COLLECTION, database_name)
        assessments = database_manager.get_collection(IsmsRiskAssessment.COLLECTION, database_name)
        seeded_ids = list(range(RA_RA_BASE_ID, RA_RA_BASE_ID + RA_SEEDED_COUNT))
        # The risk must exist so the report's hard $unwind on the risk lookup keeps the assessments
        risks.insert_one({'public_id': RA_RISK_ID, 'name': 'RA report test risk'})
        assessments.insert_many([
            {'public_id': ra_id, 'risk_id': RA_RISK_ID, 'object_id_ref_type': 'OBJECT', 'object_id': 0}
            for ra_id in seeded_ids
        ])
        try:
            response = rest_api.get(f'{ROUTE_URL}/risk_assessments?limit=2')

            assert response.status_code == HTTPStatus.OK
            payload = response.get_json()
            assert len(payload['results']) <= 2
            assert payload['total'] >= RA_SEEDED_COUNT
        finally:
            assessments.delete_many({'public_id': {'$in': seeded_ids}})
            risks.delete_one({'public_id': RA_RISK_ID})

    def test_soa_respects_limit(self, rest_api,
                                database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A limit query param caps the returned rows while total reflects the full set."""
        measures = database_manager.get_collection(IsmsControlMeasure.COLLECTION, database_name)
        seeded_ids = list(range(SOA_CM_BASE_ID, SOA_CM_BASE_ID + SOA_SEEDED_COUNT))
        measures.insert_many([
            {'public_id': cm_id, 'title': f'SOA paging CM {cm_id}', 'control_measure_type': 'CONTROL'}
            for cm_id in seeded_ids
        ])
        try:
            response = rest_api.get(f'{ROUTE_URL}/soa?limit=2')

            assert response.status_code == HTTPStatus.OK
            payload = response.get_json()
            assert len(payload['results']) <= 2
            assert payload['total'] >= SOA_SEEDED_COUNT
        finally:
            measures.delete_many({'public_id': {'$in': seeded_ids}})

    def test_soa_resolves_option_ids_to_values(self, rest_api,
                                               database_manager: MongoDatabaseManager, database_name: str) -> None:
        """SOA replaces the control measure's source / implementation_state ids with their option labels."""
        options = database_manager.get_collection(CmdbExtendableOption.COLLECTION, database_name)
        measures = database_manager.get_collection(IsmsControlMeasure.COLLECTION, database_name)
        options.insert_one({'public_id': SOA_SOURCE_OPTION_ID, 'value': SOA_SOURCE_VALUE,
                            'option_type': OptionType.CONTROL_MEASURE, 'predefined': False})
        options.insert_one({'public_id': SOA_STATE_OPTION_ID, 'value': SOA_STATE_VALUE,
                            'option_type': OptionType.IMPLEMENTATION_STATE, 'predefined': False})
        measures.insert_one({'public_id': SOA_CM_ID, 'title': 'SOA CM', 'control_measure_type': 'CONTROL',
                             'source': SOA_SOURCE_OPTION_ID, 'implementation_state': SOA_STATE_OPTION_ID})
        try:
            # limit=0 returns every row, so the seeded measure is present regardless of the SOA order
            response = rest_api.get(f'{ROUTE_URL}/soa?limit=0')

            assert response.status_code == HTTPStatus.OK
            entry = next(cm for cm in response.get_json()['results'] if cm['public_id'] == SOA_CM_ID)
            assert entry['source'] == SOA_SOURCE_VALUE
            assert entry['implementation_state'] == SOA_STATE_VALUE
        finally:
            options.delete_many({'public_id': {'$in': [SOA_SOURCE_OPTION_ID, SOA_STATE_OPTION_ID]}})
            measures.delete_one({'public_id': SOA_CM_ID})

    @pytest.mark.parametrize('report, title_field', [
        ('risk_treatment_plan', 'risk_name'),
        ('risk_assessments', 'risk_title'),
    ])
    def test_report_sort_and_paging(self, rest_api, database_manager: MongoDatabaseManager,
                                    database_name: str, report: str, title_field: str) -> None:
        """The aggregation reports sort by the requested field and slice consistent, offset pages."""
        risk_ids, ra_ids = _seed_named_assessments(database_manager, database_name)
        try:
            full_asc = rest_api.get(
                f'{ROUTE_URL}/{report}?limit=0&sort={title_field}&order=1'
            ).get_json()
            full_desc = rest_api.get(
                f'{ROUTE_URL}/{report}?limit=0&sort={title_field}&order=-1'
            ).get_json()

            # The seeded names appear in ascending / descending order among all report rows
            asc_seeded = [row[title_field] for row in full_asc['results'] if row[title_field] in SORT_RISK_NAMES]
            desc_seeded = [row[title_field] for row in full_desc['results'] if row[title_field] in SORT_RISK_NAMES]
            assert asc_seeded == sorted(SORT_RISK_NAMES)
            assert desc_seeded == sorted(SORT_RISK_NAMES, reverse=True)

            # Each page equals the matching window of the full ordered list (offset correctness)
            page_one = rest_api.get(f'{ROUTE_URL}/{report}?limit=2&page=1&sort={title_field}&order=1').get_json()
            page_two = rest_api.get(f'{ROUTE_URL}/{report}?limit=2&page=2&sort={title_field}&order=1').get_json()
            assert page_one['results'] == full_asc['results'][0:2]
            assert page_two['results'] == full_asc['results'][2:4]
            assert page_one['total'] == full_asc['total']
        finally:
            database_manager.get_collection(IsmsRiskAssessment.COLLECTION, database_name)\
                .delete_many({'public_id': {'$in': ra_ids}})
            database_manager.get_collection(IsmsRisk.COLLECTION, database_name)\
                .delete_many({'public_id': {'$in': risk_ids}})

    def test_soa_preserves_sort_key_order(self, rest_api, database_manager: MongoDatabaseManager,
                                          database_name: str) -> None:
        """SOA's natural identifier ordering (sort_key) survives pagination (A.1, A.2, A.10 - not lexicographic)."""
        measures = database_manager.get_collection(IsmsControlMeasure.COLLECTION, database_name)
        measures.insert_many([
            {'public_id': cm_id, 'title': f'Natural sort {identifier}', 'identifier': identifier,
             'control_measure_type': 'CONTROL'}
            for identifier, cm_id in SOA_NATURAL_SORT_IDENTIFIERS.items()
        ])
        try:
            results = rest_api.get(f'{ROUTE_URL}/soa?limit=0').get_json()['results']

            seeded_ids = set(SOA_NATURAL_SORT_IDENTIFIERS.values())
            ordered = [cm['identifier'] for cm in results if cm['public_id'] in seeded_ids]
            assert ordered == ['A.1', 'A.2', 'A.10']
        finally:
            measures.delete_many({'public_id': {'$in': list(SOA_NATURAL_SORT_IDENTIFIERS.values())}})

    def test_soa_does_not_echo_ignored_sort_and_filter(self, rest_api) -> None:
        """SOA ignores sort/order/filter and does not echo the client's ignored values back."""
        query = urlencode({'sort': 'title', 'order': -1, 'filter': '{"public_id": 1}'})
        response = rest_api.get(f'{ROUTE_URL}/soa?{query}')

        assert response.status_code == HTTPStatus.OK
        parameters = response.get_json()['parameters']
        assert parameters['sort'] == 'public_id'
        assert parameters['order'] == 1
        assert parameters['filter'] == {}

    def test_risk_assessments_search_filters_by_risk_name(self, rest_api,
                                                          database_manager: MongoDatabaseManager,
                                                          database_name: str) -> None:
        """?search= keeps only assessments whose resolved display fields match, and totals the filtered set."""
        risk_ids, ra_ids = _seed_search_assessments(database_manager, database_name)
        try:
            payload = rest_api.get(f'{ROUTE_URL}/risk_assessments?limit=0&search={SEARCH_TERM}').get_json()

            titles = [row['risk_title'] for row in payload['results']]
            # the matching risk is kept, the non-matching one is dropped
            assert SEARCH_MATCH_RISK_NAME in titles
            assert SEARCH_MISS_RISK_NAME not in titles
            # every returned row actually matches the term (the search filters, not just reorders)
            assert all(SEARCH_TERM.lower() in (title or '').lower() for title in titles)
            # with limit=0 the whole filtered set is returned, so total equals the row count
            assert payload['total'] == len(payload['results'])
        finally:
            database_manager.get_collection(IsmsRiskAssessment.COLLECTION, database_name)\
                .delete_many({'public_id': {'$in': ra_ids}})
            database_manager.get_collection(IsmsRisk.COLLECTION, database_name)\
                .delete_many({'public_id': {'$in': risk_ids}})

    def test_risk_assessments_search_is_case_insensitive(self, rest_api,
                                                         database_manager: MongoDatabaseManager,
                                                         database_name: str) -> None:
        """A lowercase search term matches a mixed-case risk name."""
        risk_ids, ra_ids = _seed_search_assessments(database_manager, database_name)
        try:
            payload = rest_api.get(
                f'{ROUTE_URL}/risk_assessments?limit=0&search={SEARCH_TERM.lower()}'
            ).get_json()

            assert SEARCH_MATCH_RISK_NAME in [row['risk_title'] for row in payload['results']]
        finally:
            database_manager.get_collection(IsmsRiskAssessment.COLLECTION, database_name)\
                .delete_many({'public_id': {'$in': ra_ids}})
            database_manager.get_collection(IsmsRisk.COLLECTION, database_name)\
                .delete_many({'public_id': {'$in': risk_ids}})

    def test_risk_assessments_without_search_returns_both(self, rest_api,
                                                          database_manager: MongoDatabaseManager,
                                                          database_name: str) -> None:
        """Without a search term both seeded assessments are returned (no filtering regression)."""
        risk_ids, ra_ids = _seed_search_assessments(database_manager, database_name)
        try:
            titles = [row['risk_title'] for row in
                      rest_api.get(f'{ROUTE_URL}/risk_assessments?limit=0').get_json()['results']]

            assert SEARCH_MATCH_RISK_NAME in titles
            assert SEARCH_MISS_RISK_NAME in titles
        finally:
            database_manager.get_collection(IsmsRiskAssessment.COLLECTION, database_name)\
                .delete_many({'public_id': {'$in': ra_ids}})
            database_manager.get_collection(IsmsRisk.COLLECTION, database_name)\
                .delete_many({'public_id': {'$in': risk_ids}})

    @pytest.mark.parametrize('report', ['risk_treatment_plan', 'risk_assessments'])
    def test_aggregation_report_allows_disk_use(self, rest_api, monkeypatch: pytest.MonkeyPatch,
                                                report: str) -> None:
        """The aggregation reports pass allowDiskUse so a large $sort/$group spills to disk, not fails."""
        original_aggregate = RiskAssessmentManager.aggregate
        captured_kwargs: list[dict] = []

        def _spy(self, pipeline, *args, **kwargs):
            captured_kwargs.append(kwargs)
            return original_aggregate(self, pipeline, *args, **kwargs)

        monkeypatch.setattr(RiskAssessmentManager, 'aggregate', _spy)

        response = rest_api.get(f'{ROUTE_URL}/{report}')

        assert response.status_code == HTTPStatus.OK
        assert captured_kwargs, 'the report did not run an aggregation'
        assert all(kwargs.get('allowDiskUse') is True for kwargs in captured_kwargs)
