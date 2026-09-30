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
Unit tests for the parameter helpers of the search routes

`_int_arg` and `_parse_search_parameters` are the two pieces of the routes that are decidable
without a database, and both exist because of a bug:

* `_int_arg` replaces `request.args.get(name, default, int)`, which catches the `ValueError` itself
  and answers the default - so `?limit=abc` would be served as an ordinary search with a
  substituted page size, while `?limit=-1` was refused
* `_parse_search_parameters` is shared by GET and POST, so the GET branch cannot skip the
  `SearchParam` construction entirely and hand raw JSON to the pipeline builder, which answered 500
  for every GET search carrying a term

The request context is driven through a `BaseCmdbApp.test_request_context`, so no app, database or
token is involved. The routes themselves are covered end-to-end in
the functional search-route tests.
"""
# pylint: disable=protected-access
import json

import pytest

from cmdb.framework.search.search_constants import QuickSearchCountKey, SearchFormType, SearchQueryKey
from cmdb.framework.search.search_param import SearchParam
from cmdb.interface.cmdb_app import BaseCmdbApp
from cmdb.interface.rest_api.routes.framework_routes.search_routes import (
    DEFAULT_RESOLVE,
    DEFAULT_SKIP,
    EMPTY_COUNT,
    EMPTY_QUERY,
    _int_arg,
    _parse_search_parameters,
)

from cmdb.errors.framework_search import SearchParamError
# -------------------------------------------------------------------------------------------------------------------- #

DEFAULT_LIMIT: int = 10
SEARCH_TEXT: str = 'searchable'


@pytest.fixture(name='app')
def fixture_app() -> BaseCmdbApp:
    """An app object, used only for its request context."""
    return BaseCmdbApp(__name__)


def _text_param(text: str = SEARCH_TEXT) -> dict[str, str]:
    """One search parameter in the shape the frontend sends."""
    return {'searchText': text, 'searchForm': SearchFormType.TEXT.value}


class TestIntArg:
    """Reading an integer query parameter, strictly."""

    def test_reads_the_value(self, app: BaseCmdbApp) -> None:
        """The ordinary case: a number is returned as an int, not as the string it arrived as."""
        with app.test_request_context('/?limit=25'):
            assert _int_arg(SearchQueryKey.LIMIT.value, DEFAULT_LIMIT) == 25

    def test_an_absent_parameter_is_the_default(self, app: BaseCmdbApp) -> None:
        """Not asking for a page size means the route picks one."""
        with app.test_request_context('/'):
            assert _int_arg(SearchQueryKey.LIMIT.value, DEFAULT_LIMIT) == DEFAULT_LIMIT

    def test_an_empty_parameter_is_the_default(self, app: BaseCmdbApp) -> None:
        """`?limit=` is the key with no value, which is 'not sent' - not garbage."""
        with app.test_request_context('/?limit='):
            assert _int_arg(SearchQueryKey.LIMIT.value, DEFAULT_LIMIT) == DEFAULT_LIMIT

    @pytest.mark.parametrize('raw', ['abc', '1.5', '1e3', ' ', '0x10'], ids=str)
    def test_a_non_numeric_value_raises(self, app: BaseCmdbApp, raw: str) -> None:
        """The route turns this into a 400: answering 200 with a different page size is a wrong answer."""
        with app.test_request_context(f'/?limit={raw}'):
            with pytest.raises(ValueError):
                _int_arg(SearchQueryKey.LIMIT.value, DEFAULT_LIMIT)

    @pytest.mark.parametrize('raw, expected', [('0', 0), ('-1', -1)], ids=['zero', 'negative'])
    def test_it_does_not_judge_the_value(self, app: BaseCmdbApp, raw: str, expected: int) -> None:
        """0 means 'every match' and a negative is refused - both decisions belong to the route."""
        with app.test_request_context(f'/?limit={raw}'):
            assert _int_arg(SearchQueryKey.LIMIT.value, DEFAULT_LIMIT) == expected

    def test_each_parameter_is_read_by_its_own_name(self, app: BaseCmdbApp) -> None:
        """limit and skip must not read each other's value."""
        with app.test_request_context('/?limit=25&skip=5'):
            assert _int_arg(SearchQueryKey.LIMIT.value, DEFAULT_LIMIT) == 25
            assert _int_arg(SearchQueryKey.SKIP.value, DEFAULT_SKIP) == 5


class TestParseSearchParameters:
    """Turning a request's JSON payload into the objects the pipeline builder consumes."""

    def test_builds_search_param_objects(self) -> None:
        """The builder reads `.search_form` off each entry, so plain dicts are not enough."""
        result = _parse_search_parameters(json.dumps([_text_param()]))

        assert all(isinstance(param, SearchParam) for param in result)
        assert result[0].search_text == SEARCH_TEXT

    def test_keeps_the_order_the_client_sent(self) -> None:
        """Parameter order decides stage order, and a search is not commutative across forms."""
        result = _parse_search_parameters(json.dumps([_text_param('a'), _text_param('b')]))

        assert [param.search_text for param in result] == ['a', 'b']

    def test_accepts_bytes(self) -> None:
        """POST hands it `request.data`, which is bytes rather than str."""
        result = _parse_search_parameters(json.dumps([_text_param()]).encode())

        assert len(result) == 1

    @pytest.mark.parametrize('raw', ['[]', '{}', EMPTY_QUERY], ids=['empty-list', 'empty-object', 'default'])
    def test_an_empty_payload_is_no_parameters(self, raw: str) -> None:
        """An unfiltered search is a valid request - `?query={}` is the historical spelling of it."""
        result = _parse_search_parameters(raw)

        assert isinstance(result, list)
        assert not result

    def test_an_unusable_entry_refuses_the_whole_payload(self) -> None:
        """Dropping the bad parameter would answer 200 with more objects than the filter allows."""
        with pytest.raises(SearchParamError):
            _parse_search_parameters(json.dumps([_text_param(), {'searchText': 'x', 'searchForm': 'nope'}]))

    def test_a_missing_key_is_refused(self) -> None:
        """Every entry has to carry both required keys."""
        with pytest.raises(SearchParamError):
            _parse_search_parameters(json.dumps([{'searchText': 'x'}]))

    @pytest.mark.parametrize('raw', ['not-json', '', '[{]'], ids=str)
    def test_invalid_json_raises_a_value_error(self, raw: str) -> None:
        """JSONDecodeError derives from ValueError, which is what the route's 400 arm catches."""
        with pytest.raises(ValueError):
            _parse_search_parameters(raw)


class TestModuleDefaults:
    """The route's named defaults, which the tests above and the frontend both depend on."""

    def test_the_empty_query_parses_to_no_parameters(self) -> None:
        """EMPTY_QUERY stands in for an omitted ?query=, so it has to mean 'no filter'."""
        result = _parse_search_parameters(EMPTY_QUERY)

        assert isinstance(result, list)
        assert not result

    def test_the_default_resolve_is_falsy_and_parseable(self) -> None:
        """It is fed to str_to_bool, which rejects anything but 'true'/'false'."""
        assert DEFAULT_RESOLVE == 'false'

    def test_the_empty_count_matches_the_frontend_model(self) -> None:
        """The Angular NumberSearchResults model declares exactly these three fields."""
        assert EMPTY_COUNT == {
            QuickSearchCountKey.ACTIVE.value: 0,
            QuickSearchCountKey.INACTIVE.value: 0,
            QuickSearchCountKey.TOTAL.value: 0,
        }
