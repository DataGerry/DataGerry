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
(GET + POST happy paths, the query/body parse errors -> 400, and - since 2026-09-09 - a failing
search REPORTED as 400/500 instead of the empty 204 it used to answer, plus the paging contract:
`limit=0` means every match, a negative limit or skip is refused).

TestGetCarriesTheSamePayloadAsPost and TestRequestParametersAreStrict were added 2026-09-14 with the
fixes they describe: a GET search carrying an actual parameter list used to answer 500, and a
non-numeric `?limit=` / an unrecognised `?resolve=` used to be accepted with the default substituted.

TestMatchedFields drives the whole chain against a seeded type + object: a text search must come
back with the matching field reported under `matches`, in the shape the Angular search result
renders (`<cmdb-render-element>` needs a full field entry).
"""
import json
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import ObjectsManager
from cmdb.manager.manager_provider_model import ManagerProvider
from cmdb.framework.search.search_constants import (
    SearchFormType,
    SearchGroupKey,
    SearchResultKey,
    SearchResultMapKey,
)
from cmdb.framework.search.searcher_framework import SearcherFramework
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType
from cmdb.errors.manager.objects_manager import ObjectsManagerIterationError
# -------------------------------------------------------------------------------------------------------------------- #

QUICK_COUNT_URL: str = '/search/quick/count/'
SEARCH_URL: str = '/search/'

#: The payload both methods carry - a JSON array of search parameters
TEXT_PARAM: list[dict[str, str]] = [{'searchText': 'searchable', 'searchForm': SearchFormType.TEXT.value}]

TYPE_ID: int = 47601
TYPE_LABEL: str = 'Search Obj Type'
OBJECT_ID: int = 47611
NAME_FIELD: str = 'dg-search-name'
NAME_LABEL: str = 'Name'
NAME_VALUE: str = 'searchable-host-1'
EMPTY_FIELD: str = 'dg-search-empty'
EMPTY_LABEL: str = 'Empty'
TEXT_FIELD_TYPE: str = 'text'

#: An unset field used to hold the text 'None' when values were stringified before matching, so a
#: search for this term used to return every object carrying an empty field
NONE_SEARCH_TERM: str = 'none'


def _type_doc() -> dict[str, Any]:
    """Builds an active CmdbType with a searchable text field plus one that is left unset."""
    field_names = [NAME_FIELD, EMPTY_FIELD]

    return {
        'public_id': TYPE_ID,
        'name': 'search-obj-type',
        'label': TYPE_LABEL,
        'author_id': 1,
        'creation_time': datetime.now(timezone.utc),
        'active': True,
        'fields': [
            {'type': TEXT_FIELD_TYPE, 'name': NAME_FIELD, 'label': NAME_LABEL},
            {'type': TEXT_FIELD_TYPE, 'name': EMPTY_FIELD, 'label': EMPTY_LABEL},
        ],
        'render_meta': {
            'icon': 'fa-cube',
            'sections': [{'type': 'section', 'name': 'main', 'label': 'Main', 'fields': field_names}],
            'summary': {'fields': [NAME_FIELD]},
        },
        'acl': {'activated': False, 'groups': {'includes': None}},
        'version': '1.0.0',
    }


def _object_doc() -> dict[str, Any]:
    """Builds a CmdbObject of the seeded type: one filled field and one left unset."""
    return {
        'public_id': OBJECT_ID,
        'type_id': TYPE_ID,
        'active': True,
        'author_id': 1,
        'version': '1.0.0',
        'creation_time': datetime.now(timezone.utc),
        'fields': [
            {'type': TEXT_FIELD_TYPE, 'name': NAME_FIELD, 'value': NAME_VALUE},
            {'type': TEXT_FIELD_TYPE, 'name': EMPTY_FIELD, 'value': None},
        ],
    }


def _search_body(search_text: str, search_form: str = TEXT_FIELD_TYPE) -> str:
    """Builds the POST body for one search parameter."""
    return json.dumps([{'searchText': search_text, 'searchForm': search_form}])


def _entry_for_seeded_object(body: dict[str, Any]) -> dict[str, Any] | None:
    """Returns the result entry of the seeded object, or None when it is not in the page."""
    for entry in body[SearchResultKey.RESULTS.value]:
        object_information = entry[SearchResultMapKey.RESULT.value]['object_information']

        if object_information['object_id'] == OBJECT_ID:
            return entry

    return None


def _raiser(exc: Exception):
    """Returns a function that ignores its args and raises the given exception."""
    def _fail(*_args, **_kwargs):
        raise exc
    return _fail


def _query_arg(params: list[dict[str, str]]) -> str:
    """URL-encodes a search parameter list for the ?query= form of the route."""
    return quote(json.dumps(params))


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

    def test_search_failure_is_reported_not_answered_as_empty(self, rest_api, monkeypatch) -> None:
        """
        A failing search is a 500, not an empty 204

        Until 2026-09-09 every error inside the search block answered 204 with an empty body, which a
        client cannot tell apart from "nothing matched" - so a broken pipeline, a Mongo timeout and an
        unusable page size all looked like a successful empty search.
        """
        monkeypatch.setattr(SearcherFramework, 'aggregate', _raiser(RuntimeError('boom')))

        response = rest_api.get(f'{SEARCH_URL}?query={{}}')

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_an_aggregation_failure_is_a_400(self, rest_api, monkeypatch) -> None:
        """The database refusing the pipeline is the caller's problem, and says so"""
        monkeypatch.setattr(
            SearcherFramework, 'aggregate', _raiser(ObjectsManagerIterationError('bad pipeline')),
        )

        response = rest_api.get(f'{SEARCH_URL}?query={{}}')

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_limit_zero_returns_every_match(self, rest_api) -> None:
        """
        0 means unlimited here as in every paginated route

        It used to produce a `$limit: 0`, which MongoDB refuses - and the refusal was swallowed as an
        empty 204, so asking for "all results" answered with none.
        """
        response = rest_api.get(f'{SEARCH_URL}?query={{}}&limit=0')

        assert response.status_code == HTTPStatus.OK
        body = response.get_json()
        assert len(body[SearchResultKey.RESULTS.value]) == body[SearchResultKey.TOTAL_RESULTS.value]

    @pytest.mark.parametrize('query', ['limit=-1', 'skip=-1'], ids=['limit', 'skip'])
    def test_negative_paging_is_refused(self, rest_api, query: str) -> None:
        """A negative page size or offset is an unusable request, not a weaker 'unlimited'"""
        response = rest_api.get(f'{SEARCH_URL}?query={{}}&{query}')

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_unexpected_error_returns_500(self, rest_api, monkeypatch) -> None:
        """An unexpected error before the search runs surfaces as 500."""
        monkeypatch.setattr(ManagerProvider, 'get_manager', _raiser(RuntimeError('boom')))

        assert rest_api.get(f'{SEARCH_URL}?query={{}}').status_code == HTTPStatus.INTERNAL_SERVER_ERROR


class TestGetCarriesTheSamePayloadAsPost:
    """
    A GET search carries the SAME parameter array as a POST, in ?query=

    Until 2026-09-14 it did not: the GET branch handed the raw JSON to the pipeline builder without
    building SearchParam objects, so the builder read `.search_form` off plain strings and the route
    answered 500. It went unnoticed because every GET test in this file sent `?query={}` - the one
    payload that happens to work, because an empty parameter list needs no parameters.
    """

    def test_a_real_parameter_list_is_accepted(self, rest_api) -> None:
        """The exact payload POST accepts used to be a 500 on GET."""
        response = rest_api.get(f'{SEARCH_URL}?query={_query_arg(TEXT_PARAM)}')

        assert response.status_code == HTTPStatus.OK

    def test_get_and_post_answer_the_same_body(self, rest_api) -> None:
        """Same parameters, same search - the method is only how the payload travels."""
        from_get = rest_api.get(f'{SEARCH_URL}?query={_query_arg(TEXT_PARAM)}').get_json()
        from_post = rest_api.post(
            SEARCH_URL, data=json.dumps(TEXT_PARAM), content_type='application/json',
        ).get_json()

        assert from_get[SearchResultKey.TOTAL_RESULTS.value] == from_post[SearchResultKey.TOTAL_RESULTS.value]

    def test_an_unusable_parameter_is_refused_on_get_too(self, rest_api) -> None:
        """The validation POST has always had now runs for GET: a bad form is a 400, not a 500."""
        bad = [{'searchText': 'x', 'searchForm': 'not-a-form'}]

        assert rest_api.get(f'{SEARCH_URL}?query={_query_arg(bad)}').status_code == HTTPStatus.BAD_REQUEST

    def test_an_empty_object_query_still_works(self, rest_api) -> None:
        """The historical `?query={}` spelling has to keep answering an unfiltered search."""
        assert rest_api.get(f'{SEARCH_URL}?query={{}}').status_code == HTTPStatus.OK

    def test_no_query_at_all_searches_everything(self, rest_api) -> None:
        """Omitting the parameter is the same as sending an empty list."""
        assert rest_api.get(SEARCH_URL).status_code == HTTPStatus.OK


class TestRequestParametersAreStrict:
    """
    A malformed parameter is refused, never silently replaced by its default

    `request.args.get(name, default, int)` catches the ValueError itself and answers the default, so
    `?limit=abc` used to be served as an ordinary search with a substituted page size - while
    `?limit=-1` two lines below was a 400. The route parses the numbers itself now.
    """

    @pytest.mark.parametrize('query', ['limit=abc', 'skip=abc', 'limit=1.5'], ids=str)
    def test_a_non_numeric_pager_is_refused(self, rest_api, query: str) -> None:
        """Answering 200 with a different page size than the client asked for is a wrong answer."""
        assert rest_api.get(f'{SEARCH_URL}?{query}').status_code == HTTPStatus.BAD_REQUEST

    @pytest.mark.parametrize('query', ['limit=', 'skip='], ids=str)
    def test_an_empty_pager_value_falls_back_to_the_default(self, rest_api, query: str) -> None:
        """Sending the key with no value is 'not sent', which is not the same as sending garbage."""
        assert rest_api.get(f'{SEARCH_URL}?{query}').status_code == HTTPStatus.OK

    @pytest.mark.parametrize('raw', ['true', 'True', 'false', 'False'], ids=str)
    def test_the_documented_resolve_values_are_accepted(self, rest_api, raw: str) -> None:
        """Both spellings of both values, as str_to_bool defines them."""
        assert rest_api.get(f'{SEARCH_URL}?resolve={raw}').status_code == HTTPStatus.OK

    @pytest.mark.parametrize('raw', ['yes', '1', 'maybe'], ids=str)
    def test_an_unrecognised_resolve_is_refused(self, rest_api, raw: str) -> None:
        """`?resolve=1` silently meant False before; a client asking for resolution got ids back."""
        assert rest_api.get(f'{SEARCH_URL}?resolve={raw}').status_code == HTTPStatus.BAD_REQUEST

    def test_an_unrouted_method_is_refused_by_the_router(self, rest_api) -> None:
        """Only GET and POST are registered, which is why the view needs no method branch of its own."""
        assert rest_api.put(SEARCH_URL).status_code == HTTPStatus.METHOD_NOT_ALLOWED


class TestMatchedFields:
    """POST /search/ reports which fields of each hit matched, against a seeded type + object."""

    @pytest.fixture(autouse=True)
    def _seed(self, database_manager: MongoDatabaseManager, database_name: str):
        """Seeds the searchable type + object, cleaning both up after each test."""
        types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
        objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)

        def _purge() -> None:
            types.delete_many({'public_id': TYPE_ID})
            objects.delete_many({'public_id': OBJECT_ID})

        _purge()
        types.insert_one(_type_doc())
        objects.insert_one(_object_doc())
        yield
        _purge()

    def test_search_finds_the_seeded_object(self, rest_api) -> None:
        """A text search for the object's field value returns that object."""
        response = rest_api.post(SEARCH_URL, data=_search_body(NAME_VALUE), content_type='application/json')

        assert response.status_code == HTTPStatus.OK
        assert _entry_for_seeded_object(response.get_json()) is not None

    def test_response_carries_the_documented_envelope(self, rest_api) -> None:
        """The body exposes exactly the keys the Angular SearchResultList model mirrors."""
        response = rest_api.post(SEARCH_URL, data=_search_body(NAME_VALUE), content_type='application/json')

        assert set(response.get_json()) == {key.value for key in SearchResultKey}

    def test_matching_field_is_reported(self, rest_api) -> None:
        """The field whose value matched is listed under `matches`."""
        response = rest_api.post(SEARCH_URL, data=_search_body(NAME_VALUE), content_type='application/json')
        entry = _entry_for_seeded_object(response.get_json())

        matched_names = [match['name'] for match in entry[SearchResultMapKey.MATCHES.value]]

        assert matched_names == [NAME_FIELD]

    def test_matched_entry_is_a_full_field_dict(self, rest_api) -> None:
        """Each match keeps the label/type/value the frontend renders it with."""
        response = rest_api.post(SEARCH_URL, data=_search_body(NAME_VALUE), content_type='application/json')
        entry = _entry_for_seeded_object(response.get_json())

        match = entry[SearchResultMapKey.MATCHES.value][0]

        assert (match['label'], match['type'], match['value']) == (NAME_LABEL, TEXT_FIELD_TYPE, NAME_VALUE)

    def test_partial_term_matches(self, rest_api) -> None:
        """A substring of the value is enough - the term becomes a regex, not an equality test."""
        response = rest_api.post(SEARCH_URL, data=_search_body('searchable'), content_type='application/json')

        assert _entry_for_seeded_object(response.get_json()) is not None

    def test_result_carries_the_rendered_object(self, rest_api) -> None:
        """The wrapped result is the serialized RenderResult the frontend reads its labels from."""
        response = rest_api.post(SEARCH_URL, data=_search_body(NAME_VALUE), content_type='application/json')
        entry = _entry_for_seeded_object(response.get_json())

        result = entry[SearchResultMapKey.RESULT.value]

        assert result['type_information']['type_id'] == TYPE_ID
        assert 'summary_line' in result

    def test_the_per_type_group_is_a_ready_made_type_parameter(self, rest_api) -> None:
        """
        The `groups` entries are what the Angular result bar re-submits as a TYPE tag

        It reads `searchLabel` and `total` off each entry, so these keys are a frontend contract - and
        the group branch of the search facet builds them by hand, where nothing else would notice a
        rename.
        """
        body = rest_api.post(
            SEARCH_URL, data=_search_body(NAME_VALUE), content_type='application/json',
        ).get_json()

        group = next(
            entry for entry in body[SearchResultKey.GROUPS.value]
            if entry[SearchGroupKey.SETTINGS.value][SearchGroupKey.TYPES.value] == [TYPE_ID]
        )

        assert group[SearchGroupKey.SEARCH_FORM.value] == SearchFormType.TYPE.value
        assert group[SearchGroupKey.SEARCH_LABEL.value] == TYPE_LABEL
        assert group[SearchGroupKey.SEARCH_TEXT.value] == TYPE_LABEL
        assert group[SearchGroupKey.TOTAL.value] >= 1

    def test_unmatched_term_returns_no_hit(self, rest_api) -> None:
        """A term absent from every field does not return the seeded object."""
        response = rest_api.post(SEARCH_URL, data=_search_body('no-such-value-xyz'), content_type='application/json')

        assert _entry_for_seeded_object(response.get_json()) is None

    def test_empty_field_is_not_reported_as_matching_none(self, rest_api) -> None:
        """Regression: an unset field used to be stringified to 'None' and match a search for it."""
        response = rest_api.post(SEARCH_URL, data=_search_body(NONE_SEARCH_TERM),
                                 content_type='application/json')
        entry = _entry_for_seeded_object(response.get_json())

        matched_names = [] if entry is None else [match['name'] for match in entry[SearchResultMapKey.MATCHES.value]]

        assert EMPTY_FIELD not in matched_names


class TestAnUnusableSearchParameterIsRefused:
    """
    A search that cannot read one of its parameters answers 400 instead of searching without it

    Until 2026-09-08 the parameter was logged and skipped, so the request ran with fewer criteria than
    the caller sent - and a dropped FILTER returns more objects than the filter allows, with a 200.
    """

    def test_a_parameter_without_a_form_is_a_400(self, rest_api) -> None:
        """The message names the position, which is the only way to identify one tag of several."""
        body = json.dumps([{'searchText': 'srv'}])

        response = rest_api.post(SEARCH_URL, data=body, content_type='application/json')

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert 'position 0' in response.get_json()['message']

    def test_an_unknown_form_is_a_400(self, rest_api) -> None:
        """A typo'd form used to widen the search silently."""
        body = json.dumps([{'searchText': 'srv', 'searchForm': 'not-a-form'}])

        response = rest_api.post(SEARCH_URL, data=body, content_type='application/json')

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert 'not-a-form' in response.get_json()['message']

    def test_one_bad_parameter_refuses_the_whole_request(self, rest_api) -> None:
        """
        The valid tags are not searched on their own

        Answering with the results of a partial filter set is exactly the failure this replaced.
        """
        body = json.dumps([
            {'searchText': 'srv', 'searchForm': 'text'},
            {'searchText': 'x', 'searchForm': 'not-a-form'},
        ])

        assert rest_api.post(SEARCH_URL, data=body, content_type='application/json').status_code \
            == HTTPStatus.BAD_REQUEST

    def test_a_non_numeric_public_id_search_is_a_400_naming_the_form(self, rest_api) -> None:
        """
        It used to fail two layers away, in the pipeline builder's bare int()

        The route could only answer a generic 400 there; the form is known here, so the message says
        what was wrong with which parameter.
        """
        body = json.dumps([{'searchText': 'abc', 'searchForm': 'publicID'}])

        response = rest_api.post(SEARCH_URL, data=body, content_type='application/json')

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert 'publicID' in response.get_json()['message']

    def test_the_payload_the_frontend_sends_is_still_accepted(self, rest_api) -> None:
        """
        The search bar's OR mode appends a 'disjunction' marker parameter that nothing reads

        It is accepted on purpose: rejecting it would 400 every OR type search the UI performs.
        """
        body = json.dumps([
            {'searchText': 'srv', 'searchForm': 'text'},
            {'searchText': 'or', 'searchForm': 'disjunction', 'searchLabel': 'or', 'disjunction': True},
        ])

        assert rest_api.post(SEARCH_URL, data=body, content_type='application/json').status_code \
            == HTTPStatus.OK


class TestAnUnusableTextTermIsAnswered:
    """
    A search box must not answer 400 because somebody typed a regex metacharacter

    A TEXT term reaches MongoDB as a regular expression, so before 2026-09-17 `*` was not a search
    that found nothing - it was a query the database refused. Tier 2 **T187**; this is the half that
    needed no frontend change, because the Angular search bar escapes every term it sends and an
    escaped term always compiles.
    """

    @pytest.mark.parametrize('term', ['*', '[unclosed', 'a**', '+'], ids=repr)
    def test_an_unusable_text_term_returns_results_not_400(self, rest_api, term: str) -> None:
        """It is matched as the literal text it evidently was."""
        body = json.dumps([{'searchText': term, 'searchForm': 'text'}])

        response = rest_api.post(SEARCH_URL, data=body, content_type='application/json')

        assert response.status_code == HTTPStatus.OK

    @pytest.mark.parametrize('term', ['C++', 'Data (EU)'], ids=repr)
    def test_a_usable_text_term_still_answers(self, rest_api, term: str) -> None:
        """The terms T187's remaining half is about are valid patterns and were never the 400."""
        body = json.dumps([{'searchText': term, 'searchForm': 'text'}])

        response = rest_api.post(SEARCH_URL, data=body, content_type='application/json')

        assert response.status_code == HTTPStatus.OK

    def test_an_unusable_regex_term_is_still_refused(self, rest_api) -> None:
        """
        The REGEX form is not second-guessed

        A caller who asks for a pattern and gives an invalid one is told, rather than quietly served
        a literal match they did not ask for.
        """
        body = json.dumps([{'searchText': '*', 'searchForm': 'regex'}])

        response = rest_api.post(SEARCH_URL, data=body, content_type='application/json')

        assert response.status_code == HTTPStatus.BAD_REQUEST
