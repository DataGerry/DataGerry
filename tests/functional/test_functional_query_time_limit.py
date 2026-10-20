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
What the REST API answers for a query that runs past its server-side time budget

Two kinds of test. A REAL burn - a ``?filter=`` the client filter guard accepts that costs server CPU per document -
on the object list and the object export, with the budget lowered so the test stays short: the server stops the
aggregation and the route answers 503 naming the budget. And the WIRING of every other surface, with the timeout
raised where the read happens: the search and its quick count, the ISMS reports, list routes with a hand-written
iteration arm and a list route on an error table all answer the same 503, and the reports run under the long budget
"""
import json
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.database.database_constants import LONG_QUERY_TIME_LIMIT_MS, QUERY_TIME_LIMIT_MS
from cmdb.framework.exporter.writer import base_export_writer as base_export_writer_module
from cmdb.framework.search.search_constants import SearchFormType
from cmdb.interface.request_limits_constants import MILLISECONDS_PER_SECOND, QUERY_TIME_LIMIT_RESPONSE_MESSAGE
from cmdb.manager.base_manager import BaseManager
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.manager.objects_manager import ObjectsManager
from cmdb.manager.query_builder import builder_parameters as builder_parameters_module
from cmdb.models.isms_model import IsmsRiskAssessment
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType
from cmdb.security.license.license_constants import LicenseFeature
from cmdb.errors.database import DocumentQueryTimeLimitError
from cmdb.errors.manager import BaseManagerIterationError
from cmdb.errors.manager.objects_manager import ObjectsManagerIterationError
# -------------------------------------------------------------------------------------------------------------------- #

TYPE_ID: int = 92101
FIRST_OBJECT_ID: int = 92110
# Many cheap documents: the server checks the budget between documents
OBJECT_COUNT: int = 1000
# About 3 ms of server CPU per document - 3 s for them all, against a budget of 1 s
BURN_LENGTH: int = 30000
TEST_BUDGET_MS: int = 1000
NAME_FIELD: str = 'dg-name'

OBJECTS_URL: str = '/objects/'
EXPORT_URL: str = '/exporter/'
SEARCH_URL: str = '/search/'
QUICK_COUNT_URL: str = '/search/quick/count/'
REPORTS_URL: str = '/isms/reports'
LONG_BUDGET_REPORTS: list[str] = ['risk_treatment_plan', 'risk_assessments']

# List routes reading through the pager: four with a hand-written iteration arm, one on an error table
LIST_URLS: list[str] = ['/users/', '/types/', '/groups/', '/categories/', '/isms/risk_classes/']


def _message(time_limit_ms: int) -> str:
    """The 503's text for a budget."""
    return QUERY_TIME_LIMIT_RESPONSE_MESSAGE.format(seconds=time_limit_ms // MILLISECONDS_PER_SECOND)


def _burning_filter(object_ids: list[int]) -> str:
    """A list-shaped ?filter= the guard lets through: the seeded objects, each costing server CPU"""
    return json.dumps([
        {'$match': {'public_id': {'$in': object_ids}}},
        {'$addFields': {'burn': {'$reduce': {
            'input': {'$range': [0, {'$add': [BURN_LENGTH, '$public_id']}]},
            'initialValue': 0,
            'in': {'$add': ['$$value', '$$this']},
        }}}},
    ])


def _timed_out(time_limit_ms: int) -> BaseManagerIterationError:
    """What BaseManager.aggregate_within_time_limit raises for an aggregation the server stopped."""
    timeout = DocumentQueryTimeLimitError('operation exceeded time limit', time_limit_ms)
    error = BaseManagerIterationError(timeout)
    error.__cause__ = timeout

    return error


def _type_doc() -> dict[str, Any]:
    """An active type with one text field."""
    return {
        'public_id': TYPE_ID, 'name': 'query-time-limit-type', 'label': 'Query Time Limit', 'author_id': 1,
        'creation_time': datetime.now(timezone.utc), 'active': True, 'version': '1.0.0',
        'fields': [{'type': 'text', 'name': NAME_FIELD, 'label': 'Name'}],
        'render_meta': {
            'icon': 'fa-cube', 'summary': {'fields': [NAME_FIELD]},
            'sections': [{'type': 'section', 'name': 'main', 'label': 'Main', 'fields': [NAME_FIELD]}],
        },
        'acl': {'activated': False, 'groups': {'includes': None}},
    }


def _object_doc(public_id: int) -> dict[str, Any]:
    """An object of the seeded type."""
    return {
        'public_id': public_id, 'type_id': TYPE_ID, 'active': True, 'author_id': 1, 'version': '1.0.0',
        'creation_time': datetime.now(timezone.utc),
        'fields': [{'type': 'text', 'name': NAME_FIELD, 'value': f'host-{public_id}'}],
    }


@pytest.fixture(name='object_ids')
def fixture_object_ids(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds the type and OBJECT_COUNT objects, removed afterwards."""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    ids: list[int] = list(range(FIRST_OBJECT_ID, FIRST_OBJECT_ID + OBJECT_COUNT))

    def _purge() -> None:
        types.delete_many({'public_id': TYPE_ID})
        objects.delete_many({'public_id': {'$in': ids}})

    _purge()
    types.insert_one(_type_doc())
    objects.insert_many([_object_doc(public_id) for public_id in ids])
    yield ids
    _purge()


@pytest.fixture(name='isms_licensed')
def fixture_isms_licensed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Licenses the ISMS feature so the gated routes are reachable."""
    monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, feature: feature == LicenseFeature.ISMS)


class TestARealBurn:
    """The server stops a burning ?filter= and the route says so."""

    def test_the_object_list_answers_503_naming_the_budget(
            self, rest_api, object_ids: list[int], monkeypatch: pytest.MonkeyPatch) -> None:
        """Not the 500 / 400 of a failed query - a 503 that says it ran out of time"""
        monkeypatch.setattr(builder_parameters_module, 'QUERY_TIME_LIMIT_MS', TEST_BUDGET_MS)

        response = rest_api.get(OBJECTS_URL, query_string={'filter': _burning_filter(object_ids)})

        assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE
        assert response.get_json()['message'] == _message(TEST_BUDGET_MS)

    def test_a_filter_within_the_budget_still_answers(
            self, rest_api, object_ids: list[int], monkeypatch: pytest.MonkeyPatch) -> None:
        """The same budget, a plain filter: 200 with the rows"""
        monkeypatch.setattr(builder_parameters_module, 'QUERY_TIME_LIMIT_MS', TEST_BUDGET_MS)

        response = rest_api.get(OBJECTS_URL, query_string={
            'filter': json.dumps({'public_id': {'$in': object_ids}}), 'limit': 5,
        })

        assert response.status_code == HTTPStatus.OK
        assert response.get_json()['total'] == OBJECT_COUNT

    def test_the_export_runs_under_the_long_budget_and_answers_503(
            self, rest_api, object_ids: list[int], monkeypatch: pytest.MonkeyPatch) -> None:
        """The export's own budget is the one that stops it - the list budget is left alone"""
        monkeypatch.setattr(base_export_writer_module, 'LONG_QUERY_TIME_LIMIT_MS', TEST_BUDGET_MS)

        response = rest_api.get(EXPORT_URL, query_string={'filter': _burning_filter(object_ids)})

        assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE
        assert response.get_json()['message'] == _message(TEST_BUDGET_MS)


class TestTheSearch:
    """The search and the quick count run under the client-shaped budget."""

    @pytest.fixture(autouse=True)
    def _budgets(self, monkeypatch: pytest.MonkeyPatch) -> list[int]:
        """Records each budget the objects are aggregated under, and times every aggregation out"""
        budgets: list[int] = []

        def _time_out(_manager: ObjectsManager, _pipeline: list[dict[str, Any]], time_limit_ms: int) -> None:
            budgets.append(time_limit_ms)
            base = _timed_out(time_limit_ms)
            raise ObjectsManagerIterationError(base) from base

        monkeypatch.setattr(ObjectsManager, 'aggregate_objects_within_time_limit', _time_out)

        return budgets

    def test_the_search_answers_503(self, rest_api, _budgets: list[int]) -> None:
        """POST /search/ - not the route's 400 'Failed to aggregate'"""
        body: str = json.dumps([{'searchText': 'host', 'searchForm': SearchFormType.TEXT.value}])

        response = rest_api.post(SEARCH_URL, data=body, content_type='application/json')

        assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE
        assert response.get_json()['message'] == _message(QUERY_TIME_LIMIT_MS)
        assert _budgets == [QUERY_TIME_LIMIT_MS]

    def test_the_quick_count_answers_503(self, rest_api, _budgets: list[int]) -> None:
        """GET /search/quick/count/ - the search bar's counter"""
        response = rest_api.get(QUICK_COUNT_URL, query_string={'searchValue': 'host'})

        assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE
        assert _budgets == [QUERY_TIME_LIMIT_MS]


@pytest.mark.usefixtures('isms_licensed')
class TestTheIsmsReports:
    """The two aggregation reports run under the long budget."""

    @pytest.mark.parametrize('report', LONG_BUDGET_REPORTS)
    def test_the_report_runs_under_the_long_budget(
            self, rest_api, report: str, monkeypatch: pytest.MonkeyPatch) -> None:
        """Their own allowDiskUse aggregation is held to LONG_QUERY_TIME_LIMIT_MS"""
        budgets: list[int] = []
        original = BaseManager.aggregate_within_time_limit

        def _spy(manager: BaseManager, pipeline: list[dict[str, Any]], time_limit_ms: int, **kwargs: Any) -> Any:
            if manager.collection == IsmsRiskAssessment.COLLECTION and kwargs.get('allowDiskUse'):
                budgets.append(time_limit_ms)

            return original(manager, pipeline, time_limit_ms, **kwargs)

        monkeypatch.setattr(BaseManager, 'aggregate_within_time_limit', _spy)

        assert rest_api.get(f'{REPORTS_URL}/{report}').status_code == HTTPStatus.OK
        assert budgets == [LONG_QUERY_TIME_LIMIT_MS]

    @pytest.mark.parametrize('report', LONG_BUDGET_REPORTS)
    def test_a_timed_out_report_answers_503_naming_the_long_budget(
            self, rest_api, report: str, monkeypatch: pytest.MonkeyPatch) -> None:
        """28 seconds, not 10"""
        original = BaseManager.aggregate_within_time_limit

        def _time_out(manager: BaseManager, pipeline: list[dict[str, Any]], time_limit_ms: int, **kwargs: Any) -> Any:
            if manager.collection == IsmsRiskAssessment.COLLECTION and kwargs.get('allowDiskUse'):
                raise _timed_out(time_limit_ms)

            return original(manager, pipeline, time_limit_ms, **kwargs)

        monkeypatch.setattr(BaseManager, 'aggregate_within_time_limit', _time_out)

        response = rest_api.get(f'{REPORTS_URL}/{report}')

        assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE
        assert response.get_json()['message'] == _message(LONG_QUERY_TIME_LIMIT_MS)


@pytest.mark.usefixtures('isms_licensed')
class TestTheListRoutes:
    """Every list route reads through the pager, so every one answers the same 503."""

    @pytest.mark.parametrize('url', LIST_URLS)
    def test_a_timed_out_list_answers_503(self, rest_api, url: str, monkeypatch: pytest.MonkeyPatch) -> None:
        """A hand-written iteration arm and an error table alike"""
        def _time_out(_manager: BaseManager, _pipeline: list[dict[str, Any]], time_limit_ms: int, **_: Any) -> None:
            raise _timed_out(time_limit_ms)

        monkeypatch.setattr(BaseManager, 'aggregate_within_time_limit', _time_out)

        response = rest_api.get(url)

        assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE, response.get_json()
        assert response.get_json()['message'] == _message(QUERY_TIME_LIMIT_MS)
