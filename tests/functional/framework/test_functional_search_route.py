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
Functional coverage for the /search routes

Covers the quick-search counter (result envelope, the empty -> zeroed counts, and the
ObjectsManagerIterationError -> 400 / unexpected -> 500 mappings) and the search framework
(GET + POST happy paths, the query/body parse errors -> 400, and the graceful search-failure
degrade to an empty 204).
"""
import json
from http import HTTPStatus

from cmdb.manager import ObjectsManager
from cmdb.manager.manager_provider_model import ManagerProvider
from cmdb.framework.search.searcher_framework import SearcherFramework
from cmdb.errors.manager.objects_manager import ObjectsManagerIterationError
# -------------------------------------------------------------------------------------------------------------------- #

QUICK_COUNT_URL: str = '/search/quick/count/'
SEARCH_URL: str = '/search/'


def _raiser(exc: Exception):
    """Returns a function that ignores its args and raises the given exception."""
    def _fail(*_args, **_kwargs):
        raise exc
    return _fail


class TestQuickSearchCounter:
    """GET /search/quick/count/ aggregates active / inactive / total counts."""

    def test_returns_counts(self, rest_api) -> None:
        """A quick-search count for a non-matching term returns the zeroed counts envelope."""
        response = rest_api.get(f'{QUICK_COUNT_URL}?searchValue=no-such-value-xyz')

        assert response.status_code == HTTPStatus.OK
        body = response.get_json()
        assert set(body) >= {'active', 'inactive', 'total'}

    def test_returns_aggregated_result_when_present(self, rest_api, monkeypatch) -> None:
        """When the aggregation yields a row, it is returned as the response body."""
        counts = {'active': 3, 'inactive': 1, 'total': 4}
        monkeypatch.setattr(ObjectsManager, 'aggregate_objects', lambda *_a, **_k: [counts])

        response = rest_api.get(QUICK_COUNT_URL)

        assert response.status_code == HTTPStatus.OK
        assert response.get_json() == counts

    def test_iteration_error_returns_400(self, rest_api, monkeypatch) -> None:
        """An ObjectsManagerIterationError during aggregation surfaces as 400."""
        monkeypatch.setattr(ObjectsManager, 'aggregate_objects', _raiser(ObjectsManagerIterationError('boom')))

        assert rest_api.get(QUICK_COUNT_URL).status_code == HTTPStatus.BAD_REQUEST

    def test_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error during aggregation surfaces as 500."""
        monkeypatch.setattr(ObjectsManager, 'aggregate_objects', _raiser(RuntimeError('boom')))

        assert rest_api.get(QUICK_COUNT_URL).status_code == HTTPStatus.INTERNAL_SERVER_ERROR


class TestSearchFramework:
    """GET/POST /search/ runs a search and returns the results."""

    def test_get_search_succeeds(self, rest_api) -> None:
        """A GET search with an empty query returns a results payload."""
        response = rest_api.get(f'{SEARCH_URL}?query={{}}')

        assert response.status_code == HTTPStatus.OK

    def test_post_search_succeeds(self, rest_api) -> None:
        """A POST search with a valid param list returns a results payload."""
        body = json.dumps([{'searchText': 'x', 'searchForm': 'text'}])

        response = rest_api.post(SEARCH_URL, data=body, content_type='application/json')

        assert response.status_code == HTTPStatus.OK

    def test_get_invalid_query_returns_400(self, rest_api) -> None:
        """A GET search whose query is not valid JSON is rejected with 400."""
        assert rest_api.get(f'{SEARCH_URL}?query=not-json').status_code == HTTPStatus.BAD_REQUEST

    def test_post_invalid_body_returns_400(self, rest_api) -> None:
        """A POST search whose body is not valid JSON is rejected with 400."""
        response = rest_api.post(SEARCH_URL, data='not-json', content_type='application/json')

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_search_failure_degrades_to_204(self, rest_api, monkeypatch) -> None:
        """A failure during aggregation degrades to an empty 204 rather than erroring."""
        monkeypatch.setattr(SearcherFramework, 'aggregate', _raiser(RuntimeError('boom')))

        response = rest_api.get(f'{SEARCH_URL}?query={{}}')

        assert response.status_code == HTTPStatus.NO_CONTENT

    def test_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error before the search runs surfaces as 500."""
        monkeypatch.setattr(ManagerProvider, 'get_manager', _raiser(RuntimeError('boom')))

        assert rest_api.get(f'{SEARCH_URL}?query={{}}').status_code == HTTPStatus.INTERNAL_SERVER_ERROR
