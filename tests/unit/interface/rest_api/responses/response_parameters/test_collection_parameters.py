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
Unit tests for CollectionParameters - the pager of every list route

The package had no test module at all before 2026-08-27; it was covered only incidentally through route
tests, which is how the pager validation gaps survived.

Two things these tests exist to pin:

* **Every value arrives as a STRING.** Flask's query parser hands over ``'10'``, and a non-empty string
  is always truthy - which is exactly why the old ``int((page or 1) or page < 1)`` let ``'0'`` through
  as page 0 and produced a negative ``$skip``. Where a test passes a string it is deliberate.
* **A bad pager value must be rejected HERE.** Left to MongoDB it surfaced through the route's
  ``except …IterationError`` arm, so the caller was told the database failed. A ``ValueError`` raised
  from this layer is turned into an HTTP 400 by the ``parse_*_parameters`` decorators instead.
"""
import pytest

from cmdb.interface.rest_api.responses.response_parameters import CollectionParameters
from cmdb.interface.rest_api.responses.response_parameters.response_parameters_constants import (
    BuilderParamKey,
    DEFAULT_LIMIT,
    DEFAULT_SORT,
    FIRST_PAGE,
    ParameterKey,
    SORT_ASCENDING,
    SORT_DESCENDING,
    UNLIMITED_LIMIT,
)
# -------------------------------------------------------------------------------------------------------------------- #

QUERY_STRING: str = 'limit=10&page=1'


class TestPageCoercion:
    """`page` is clamped to the first page, never allowed to produce a negative skip."""

    @pytest.mark.parametrize('page', ['0', '-1', '-42', 0, -1], ids=str)
    def test_a_page_below_one_is_clamped(self, page) -> None:
        """
        Regression: '0' is a truthy string, so the old expression yielded page 0 and skip -limit

        Verified over HTTP before the fix: ?page=0 answered 400 "Failed to retrieve Objects from the
        database!". A caller asking for page 0 is asking for the start of the collection.
        """
        params = CollectionParameters(QUERY_STRING, limit='10', page=page)

        assert params.page == FIRST_PAGE
        assert params.skip == 0

    @pytest.mark.parametrize('page, expected_skip', [('1', 0), ('2', 10), ('5', 40)])
    def test_a_valid_page_sets_the_skip(self, page: str, expected_skip: int) -> None:
        """skip is (page - 1) * limit."""
        params = CollectionParameters(QUERY_STRING, limit='10', page=page)

        assert params.skip == expected_skip

    def test_an_absent_page_is_the_first_page(self) -> None:
        """No page parameter means page 1, not page 0."""
        assert CollectionParameters(QUERY_STRING).page == FIRST_PAGE

    def test_an_empty_page_is_the_first_page(self) -> None:
        """`?page=` sends an empty string, which is not an integer and must not raise."""
        assert CollectionParameters(QUERY_STRING, page='').page == FIRST_PAGE

    def test_a_non_numeric_page_raises(self) -> None:
        """The decorator turns this into a 400; it must not reach the aggregation."""
        with pytest.raises(ValueError):
            CollectionParameters(QUERY_STRING, page='abc')


class TestLimitCoercion:
    """`limit` may be 0 (unlimited) or positive; negative is refused."""

    def test_an_absent_limit_is_the_default(self) -> None:
        """No limit parameter means DEFAULT_LIMIT."""
        assert CollectionParameters(QUERY_STRING).limit == DEFAULT_LIMIT

    def test_an_empty_limit_is_the_default(self) -> None:
        """`?limit=` sends an empty string."""
        assert CollectionParameters(QUERY_STRING, limit='').limit == DEFAULT_LIMIT

    def test_zero_means_unlimited_and_skips_nothing(self) -> None:
        """
        limit=0 is 'no limit', and the frontend sends it in ~49 places

        With no limit there is nothing to page over, so skip stays 0 whatever the page.
        """
        params = CollectionParameters(QUERY_STRING, limit='0', page='7')

        assert params.limit == UNLIMITED_LIMIT
        assert params.skip == 0

    @pytest.mark.parametrize('limit', ['-1', '-5', -5], ids=str)
    def test_a_negative_limit_raises(self, limit) -> None:
        """
        Regression: a negative page size used to be accepted and echoed back to the frontend

        Verified over HTTP before the fix: ?limit=-5 answered 200 with pager.page_size -5.
        """
        with pytest.raises(ValueError):
            CollectionParameters(QUERY_STRING, limit=limit)

    def test_a_non_numeric_limit_raises(self) -> None:
        """Not an integer at all."""
        with pytest.raises(ValueError):
            CollectionParameters(QUERY_STRING, limit='ten')


class TestOrderCoercion:
    """`order` may only be the two values MongoDB's $sort accepts."""

    @pytest.mark.parametrize('order, expected', [('1', SORT_ASCENDING), ('-1', SORT_DESCENDING),
                                                 (1, SORT_ASCENDING), (-1, SORT_DESCENDING)], ids=str)
    def test_ascending_and_descending_are_accepted(self, order, expected: int) -> None:
        """Both directions the frontend sends stay valid."""
        assert CollectionParameters(QUERY_STRING, order=order).order == expected

    def test_an_absent_order_is_ascending(self) -> None:
        """No order parameter means ascending."""
        assert CollectionParameters(QUERY_STRING).order == SORT_ASCENDING

    @pytest.mark.parametrize('order', [None, ''], ids=['none', 'empty'])
    def test_an_empty_order_is_ascending(self, order) -> None:
        """
        `?order=` sends an empty string, and a caller may pass None explicitly

        Neither reaches the constructor's own default (which is already an int), so this is the branch
        that turns "no direction given" into ascending.
        """
        assert CollectionParameters(QUERY_STRING, order=order).order == SORT_ASCENDING

    @pytest.mark.parametrize('order', ['0', '2', '99', '-2'])
    def test_any_other_order_raises(self, order: str) -> None:
        """
        Regression: ?order=99 used to fail inside $sort and be reported as a database error

        Verified over HTTP before the fix: 400 "Failed to retrieve Objects from the database!".
        """
        with pytest.raises(ValueError):
            CollectionParameters(QUERY_STRING, order=order)


class TestSort:
    """`sort` is passed through; MongoDB sorts by a missing field without error."""

    def test_an_absent_sort_is_the_default(self) -> None:
        """No sort parameter means the public_id default."""
        assert CollectionParameters(QUERY_STRING).sort == DEFAULT_SORT

    def test_an_empty_sort_is_the_default(self) -> None:
        """`?sort=` sends an empty string."""
        assert CollectionParameters(QUERY_STRING, sort='').sort == DEFAULT_SORT

    def test_an_unknown_field_is_accepted(self) -> None:
        """Not validated on purpose: sorting by a field no document has is legal in MongoDB."""
        assert CollectionParameters(QUERY_STRING, sort='no-such-field').sort == 'no-such-field'


class TestFilterIsMappedToCriteria:
    """The wire calls it `filter`; the constructor calls it `criteria`."""

    def test_the_wire_key_reaches_the_filter_attribute(self) -> None:
        """
        `filter=` is accepted as a keyword and lands on self.filter

        The constructor parameter was renamed to `criteria` so it stops shadowing the `filter`
        builtin, and the mapping happens here rather than in a from_data override - which is what lets
        the JSON parsing stay in APIParameters.from_data.
        """
        params = CollectionParameters(QUERY_STRING, **{ParameterKey.FILTER.value: {'a': 1}})

        assert params.filter == {'a': 1}

    def test_the_criteria_keyword_also_works(self) -> None:
        """Callers inside the backend may use the internal name directly."""
        assert CollectionParameters(QUERY_STRING, criteria={'b': 2}).filter == {'b': 2}

    def test_the_wire_key_wins_over_the_internal_one(self) -> None:
        """Only one of them is ever supplied, but the wire value is the caller's real intent."""
        params = CollectionParameters(QUERY_STRING, criteria={'internal': True},
                                      **{ParameterKey.FILTER.value: {'wire': True}})

        assert params.filter == {'wire': True}

    def test_an_absent_filter_is_an_empty_dict(self) -> None:
        """No filter means match everything."""
        assert CollectionParameters(QUERY_STRING).filter == {}

    def test_the_filter_does_not_leak_into_optional(self) -> None:
        """It is consumed by the constructor, so it must not also show up as an optional parameter."""
        params = CollectionParameters(QUERY_STRING, **{ParameterKey.FILTER.value: {'a': 1}})

        assert ParameterKey.FILTER.value not in params.optional


class TestFromData:
    """from_data is inherited: the JSON parsing lives in APIParameters alone."""

    def test_parses_the_filter_and_projection_json(self) -> None:
        """Both arrive as JSON strings in the query and come out as structures."""
        params = CollectionParameters.from_data(
            QUERY_STRING,
            **{ParameterKey.FILTER.value: '{"type_id": 1}',
               ParameterKey.PROJECTION.value: '{"public_id": 1}'},
        )

        assert params.filter == {'type_id': 1}
        assert params.projection == {'public_id': 1}

    def test_parses_a_pipeline_shaped_filter(self) -> None:
        """
        A filter may be a LIST of aggregation stages, not only a criteria dict

        Several routes and the frontend's log tables send that shape; discussion-backlog #175 is the
        decision about restricting which stages are allowed, and it would be implemented behind this
        parsing.
        """
        params = CollectionParameters.from_data(
            QUERY_STRING, **{ParameterKey.FILTER.value: '[{"$match": {"a": 1}}]'},
        )

        assert params.filter == [{'$match': {'a': 1}}]

    def test_returns_the_calling_class(self) -> None:
        """The inherited classmethod builds an instance of the subclass, not of APIParameters."""
        assert isinstance(CollectionParameters.from_data(QUERY_STRING), CollectionParameters)

    def test_a_malformed_filter_raises(self) -> None:
        """
        Deliberately unguarded: the decorator converts this into a 400

        Verified over HTTP: ?projection=not-json answers 400.
        """
        with pytest.raises(ValueError):
            CollectionParameters.from_data(QUERY_STRING, **{ParameterKey.FILTER.value: 'not json'})

    def test_a_bad_pager_value_raises_through_from_data(self) -> None:
        """The validation applies on the from_data path too, not only on direct construction."""
        with pytest.raises(ValueError):
            CollectionParameters.from_data(QUERY_STRING, **{ParameterKey.ORDER.value: '99'})

    def test_unknown_parameters_are_kept_as_optional(self) -> None:
        """Route-specific query args ride along in `optional`."""
        params = CollectionParameters.from_data(QUERY_STRING, view='native')

        assert params.optional == {'view': 'native'}


class TestToDict:
    """to_dict produces the `parameters` block a GetMultiResponse echoes back."""

    def test_emits_the_frontend_contract_keys(self) -> None:
        """The criteria is echoed under its WIRE name, not the internal one."""
        params = CollectionParameters(QUERY_STRING, limit='5', sort='name', order='-1', page='2',
                                      criteria={'a': 1})

        assert CollectionParameters.to_dict(params) == {
            ParameterKey.LIMIT.value: 5,
            ParameterKey.SORT.value: 'name',
            ParameterKey.ORDER.value: SORT_DESCENDING,
            ParameterKey.PAGE.value: 2,
            ParameterKey.FILTER.value: {'a': 1},
            ParameterKey.OPTIONAL.value: {},
        }

    def test_omits_the_projection_when_there_is_none(self) -> None:
        """An absent projection is left out of the envelope rather than sent as {}."""
        assert ParameterKey.PROJECTION.value not in CollectionParameters.to_dict(
            CollectionParameters(QUERY_STRING),
        )

    def test_includes_the_projection_when_given(self) -> None:
        """A supplied projection is echoed back."""
        params = CollectionParameters(QUERY_STRING, projection={'public_id': 1})

        assert CollectionParameters.to_dict(params)[ParameterKey.PROJECTION.value] == {'public_id': 1}

    def test_echoes_the_clamped_page_not_the_requested_one(self) -> None:
        """The caller is told which page it actually got."""
        params = CollectionParameters(QUERY_STRING, page='0')

        assert CollectionParameters.to_dict(params)[ParameterKey.PAGE.value] == FIRST_PAGE


class TestRepr:
    """The repr is what shows up in a log line, so it has to carry the pager's state."""

    def test_names_the_query_filter_projection_and_optional(self) -> None:
        """All four values a reader would need to diagnose a bad list request."""
        params = CollectionParameters(QUERY_STRING, criteria={'a': 1}, projection={'public_id': 1},
                                      view='native')

        text = repr(params)

        assert QUERY_STRING in text
        assert "'a': 1" in text
        assert "'public_id': 1" in text
        assert 'native' in text


class TestGetBuilderParams:
    """get_builder_params is the internal hand-off to BuilderParameters."""

    def test_maps_the_filter_onto_criteria(self) -> None:
        """This is where the wire name becomes the internal one, and it is NOT frontend contract."""
        params = CollectionParameters(QUERY_STRING, limit='5', sort='name', order='-1', page='3',
                                      criteria={'a': 1})

        assert CollectionParameters.get_builder_params(params) == {
            BuilderParamKey.CRITERIA.value: {'a': 1},
            BuilderParamKey.LIMIT.value: 5,
            BuilderParamKey.SORT.value: 'name',
            BuilderParamKey.ORDER.value: SORT_DESCENDING,
            BuilderParamKey.SKIP.value: 10,
        }

    def test_carries_the_zero_skip_of_an_unlimited_read(self) -> None:
        """limit=0 pins skip at 0, so an unlimited read never skips."""
        params = CollectionParameters(QUERY_STRING, limit='0', page='4')

        assert CollectionParameters.get_builder_params(params)[BuilderParamKey.SKIP.value] == 0
