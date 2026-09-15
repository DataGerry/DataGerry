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
Unit tests for cmdb.framework.search.search_param

Pure tests: no Mongo, no Flask. `SearchParam` is the wire contract of the object search - one parsed
tag of the Angular search bar - and no test module had ever named it: the pipeline-builder tests
construct it directly, so `from_request`, the form validation and the two defaults were never
exercised.

What is pinned here:

  - **a malformed parameter refuses the request.** It used to be logged and skipped, so the search ran
    with fewer criteria than the user asked for - and a lost FILTER parameter returns MORE objects,
    with a 200 and nothing to notice
  - **one default for `disjunction`.** The constructor said False and `from_request` said True, so the
    same absent key meant OR or AND depending on which built the parameter
  - **the accepted form names are the frontend's own strings**, including the two that drive no
    pipeline stage, because rejecting either would reject a payload the UI sends
"""
from typing import Any

import pytest

from cmdb.framework.search.search_constants import SearchFormType, SearchParamKey
from cmdb.framework.search.search_param import SearchParam
from cmdb.errors.framework_search import SearchParamError
# -------------------------------------------------------------------------------------------------------------------- #


def _param(**overrides: Any) -> dict[str, Any]:
    """Builds one raw search parameter as the frontend sends it"""
    param: dict[str, Any] = {
        SearchParamKey.SEARCH_TEXT.value: 'srv-01',
        SearchParamKey.SEARCH_FORM.value: SearchFormType.TEXT.value,
    }
    param.update(overrides)

    return param


class TestAMalformedParameterRefusesTheRequest:
    """The behaviour change of 2026-09-08, and the reason for it."""

    @pytest.mark.parametrize('missing', [
        SearchParamKey.SEARCH_TEXT.value,
        SearchParamKey.SEARCH_FORM.value,
    ])
    def test_a_missing_required_key_is_refused(self, missing: str) -> None:
        """
        Both keys are required, and the message names the position

        A caller sending five tags needs to know which one the server could not read.
        """
        param: dict[str, Any] = _param()
        param.pop(missing)

        with pytest.raises(SearchParamError) as caught:
            SearchParam.from_request([param])

        assert missing in str(caught.value)
        assert 'position 0' in str(caught.value)

    def test_the_position_of_the_bad_parameter_is_reported(self) -> None:
        """With several tags, the index is the only thing that identifies the broken one."""
        params: list[dict[str, Any]] = [_param(), _param(), {SearchParamKey.SEARCH_TEXT.value: 'x'}]

        with pytest.raises(SearchParamError) as caught:
            SearchParam.from_request(params)

        assert 'position 2' in str(caught.value)

    def test_an_unknown_form_is_refused(self) -> None:
        """A typo'd form used to be dropped, and the search silently ran without that criterion."""
        with pytest.raises(SearchParamError) as caught:
            SearchParam.from_request([_param(searchForm='nope')])

        assert 'nope' in str(caught.value)

    def test_nothing_is_returned_when_one_parameter_is_bad(self) -> None:
        """
        The whole request fails rather than part of it succeeding

        A partial list is what made the old behaviour dangerous: a dropped filter widens the result
        set, so the caller gets MORE than they asked for and reads it as the answer.
        """
        params: list[dict[str, Any]] = [_param(), {SearchParamKey.SEARCH_FORM.value: 'text'}]

        with pytest.raises(SearchParamError):
            SearchParam.from_request(params)

    def test_a_well_formed_request_is_parsed_in_order(self) -> None:
        """The happy path, which is every request the frontend sends."""
        params: list[dict[str, Any]] = [
            _param(searchText='a'),
            _param(searchText='b', searchForm=SearchFormType.REGEX.value),
        ]

        parsed: list[SearchParam] = SearchParam.from_request(params)

        assert [(item.search_text, item.search_form) for item in parsed] == [
            ('a', SearchFormType.TEXT.value), ('b', SearchFormType.REGEX.value),
        ]

    def test_an_empty_request_parses_to_nothing(self) -> None:
        """A search with no tags is a valid search, not an error."""
        assert SearchParam.from_request([]) == []


class TestTheDisjunctionDefault:
    """One concept, one default - it used to have two."""

    def test_both_constructors_default_to_or(self) -> None:
        """
        The constructor said False while from_request said True

        Whichever built the parameter decided whether two type filters were OR'd or AND'd, and the
        builder branches on exactly this flag.
        """
        assert SearchParam('x', SearchFormType.TYPE.value).disjunction is True
        assert SearchParam.from_request([_param(searchForm=SearchFormType.TYPE.value)])[0].disjunction is True

    def test_an_explicit_false_is_kept(self) -> None:
        """
        The AND branch of the pipeline builder is reachable only this way

        No frontend path sends it today, which is why it is pinned here rather than in a route test.
        """
        param: dict[str, Any] = _param(searchForm=SearchFormType.TYPE.value, disjunction=False)

        assert SearchParam.from_request([param])[0].disjunction is False


class TestTheAcceptedForms:
    """The frontend spells these itself, so the list is a contract rather than an implementation."""

    def test_the_accepted_forms_come_from_the_enum(self) -> None:
        """A form added to the enum cannot be left out of the accepted list."""
        assert SearchParam.POSSIBLE_FORM_TYPES == [form_type.value for form_type in SearchFormType]

    @pytest.mark.parametrize('form_type', list(SearchFormType), ids=lambda form: form.value)
    def test_every_form_the_enum_names_is_accepted(self, form_type: SearchFormType) -> None:
        """
        Including the two that drive no pipeline stage

        DISJUNCTION is a marker the result bar appends when type filtering switches to OR, and
        PUBLIC_ID is for API clients - the search bar expresses an id search as a TEXT tag. Rejecting
        either would reject a payload the UI still sends.
        """
        search_text: Any = 5 if form_type is SearchFormType.PUBLIC_ID else 'x'

        assert SearchParam(search_text, form_type.value).search_form == form_type.value

    def test_the_form_names_match_what_the_frontend_sends(self) -> None:
        """
        Pinned literally: these four are hardcoded in the Angular search bar's addTag calls

        A rename here is a frontend change, not a backend one.
        """
        assert {'text', 'regex', 'type', 'category'} <= set(SearchParam.POSSIBLE_FORM_TYPES)


class TestThePublicIdForm:
    """The one form whose text has to be a number, checked where the form is known."""

    @pytest.mark.parametrize('search_text', [5, '5', ' 42 ', '-3'], ids=['int', 'digits', 'padded', 'negative'])
    def test_a_whole_number_is_accepted(self, search_text: Any) -> None:
        """The pipeline builder coerces with int(), so anything int() reads is fine here."""
        assert SearchParam(search_text, SearchFormType.PUBLIC_ID.value).search_text == search_text

    @pytest.mark.parametrize('search_text', ['abc', '', '1.5', None, True],
                             ids=['letters', 'empty', 'decimal', 'none', 'bool'])
    def test_anything_else_is_refused_here_rather_than_two_layers_away(self, search_text: Any) -> None:
        """
        The builder's bare int() raised inside pipeline construction, where the route could only
        answer a generic 400 that named no parameter

        A bool is refused on purpose: int(True) is 1, so it would silently search for object 1.
        """
        with pytest.raises(SearchParamError):
            SearchParam(search_text, SearchFormType.PUBLIC_ID.value)

    def test_the_other_forms_take_any_text(self) -> None:
        """Only PUBLIC_ID constrains its text; a text search may be anything the user typed."""
        assert SearchParam('', SearchFormType.TEXT.value).search_text == ''


class TestTheParsedShape:
    """What a parameter carries once built."""

    def test_absent_settings_become_an_empty_dict(self) -> None:
        """The builder reads `param.settings.get(...)`, so None would raise there."""
        assert SearchParam.from_request([_param()])[0].settings == {}

    def test_settings_are_passed_through(self) -> None:
        """A TYPE parameter's type ids live here, and the builder reads them by key."""
        param: dict[str, Any] = _param(searchForm=SearchFormType.TYPE.value, settings={'types': [1, 2]})

        assert SearchParam.from_request([param])[0].settings == {'types': [1, 2]}

    def test_the_representation_names_the_text_and_the_form(self) -> None:
        """What a log line shows when a search is traced."""
        assert repr(SearchParam('srv', SearchFormType.TEXT.value)) == '[SearchParam] srv - text'
