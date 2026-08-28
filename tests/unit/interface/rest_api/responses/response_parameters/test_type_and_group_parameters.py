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
Unit tests for TypeIterationParameters and GroupDeletionParameters

The two remaining parameter classes. ``TypeIterationParameters`` adds the type listing's ``active``
flag on top of the collection pager and no longer repeats the pager's JSON parsing - these tests pin
that it still converts ``active`` and that everything else is genuinely inherited.

``GroupDeletionParameters`` is not a pager at all: it carries the group-delete arguments and inherits
APIParameters only for the query-string plumbing.

``no-member`` is disabled for the file: ``from_data`` is an inherited classmethod that builds ``cls(...)``
and is annotated ``Self``, but pylint's inference does not follow that, so it types every result as the
base ``APIParameters`` and reports the subclass attributes as missing. The attributes are real - the
tests below are what prove it.
"""
# pylint: disable=no-member
import pytest

from cmdb.models.group_model import GroupDeleteMode
from cmdb.interface.rest_api.responses.response_parameters import (
    CollectionParameters,
    GroupDeletionParameters,
    TypeIterationParameters,
)
from cmdb.interface.rest_api.responses.response_parameters.response_parameters_constants import (
    FIRST_PAGE,
    ParameterKey,
    SORT_DESCENDING,
)
# -------------------------------------------------------------------------------------------------------------------- #

QUERY_STRING: str = 'active=true'


class TestTypeIterationParametersActive:
    """`active` arrives as a string and is converted to a bool."""

    @pytest.mark.parametrize('raw, expected', [('true', True), ('True', True), ('false', False),
                                               ('False', False), (True, True), (False, False)], ids=str)
    def test_converts_the_active_flag(self, raw, expected: bool) -> None:
        """Flask delivers 'true'/'false' as strings; str_to_bool does the conversion."""
        params = TypeIterationParameters.from_data(QUERY_STRING, **{ParameterKey.ACTIVE.value: raw})

        assert params.active is expected

    def test_defaults_to_active_when_absent(self) -> None:
        """A type listing shows active types unless told otherwise."""
        params = TypeIterationParameters.from_data(QUERY_STRING)

        assert params.active is True

    def test_the_active_flag_does_not_leak_into_optional(self) -> None:
        """It is a named parameter, so it must not also ride along as an optional one."""
        params = TypeIterationParameters.from_data(QUERY_STRING, **{ParameterKey.ACTIVE.value: 'false'})

        assert ParameterKey.ACTIVE.value not in params.optional


class TestTypeIterationParametersInheritsThePager:
    """Everything except `active` is inherited - the class repeats no parsing of its own."""

    def test_parses_the_filter_and_projection_json(self) -> None:
        """The JSON parsing now happens once, in APIParameters.from_data."""
        params = TypeIterationParameters.from_data(
            QUERY_STRING,
            **{ParameterKey.FILTER.value: '{"a": 1}', ParameterKey.PROJECTION.value: '{"b": 1}'},
        )

        assert params.filter == {'a': 1}
        assert params.projection == {'b': 1}

    def test_applies_the_pager_validation(self) -> None:
        """A bad order is refused here too, not only on the base collection route."""
        with pytest.raises(ValueError):
            TypeIterationParameters.from_data(QUERY_STRING, **{ParameterKey.ORDER.value: '99'})

    def test_clamps_the_page(self) -> None:
        """The page clamp is inherited."""
        params = TypeIterationParameters.from_data(QUERY_STRING, **{ParameterKey.PAGE.value: '0'})

        assert params.page == FIRST_PAGE

    def test_from_data_returns_the_subclass(self) -> None:
        """The inherited classmethod builds the right type."""
        assert isinstance(TypeIterationParameters.from_data(QUERY_STRING), TypeIterationParameters)


class TestTypeIterationParametersToDict:
    """to_dict adds `active` to the collection pager."""

    def test_carries_the_pager_plus_active(self) -> None:
        """
        Note this method has no caller: GetMultiResponse calls CollectionParameters.to_dict directly,
        so `active` never reaches the response envelope. Nothing in the frontend reads it, so the
        envelope is left alone - but the serializer is still the correct one for this class.
        """
        params = TypeIterationParameters.from_data(
            QUERY_STRING, **{ParameterKey.ACTIVE.value: 'false', ParameterKey.ORDER.value: '-1'},
        )

        result = TypeIterationParameters.to_dict(params)

        assert result[ParameterKey.ACTIVE.value] is False
        assert result[ParameterKey.ORDER.value] == SORT_DESCENDING
        assert result[ParameterKey.LIMIT.value] == params.limit

    def test_matches_the_collection_pager_apart_from_active(self) -> None:
        """The only difference from the parent's output is the added flag."""
        params = TypeIterationParameters.from_data(QUERY_STRING)

        result = TypeIterationParameters.to_dict(params)
        parent = CollectionParameters.to_dict(params)

        assert result == {**parent, ParameterKey.ACTIVE.value: True}


class TestGroupDeletionParameters:
    """The group-delete arguments: what to do with the users, and where to move them."""

    def test_coerces_the_group_id_to_an_int(self) -> None:
        """Flask delivers it as a string; the manager needs an int public_id."""
        params = GroupDeletionParameters(QUERY_STRING, action=GroupDeleteMode.MOVE, group_id='7')

        assert params.group_id == 7

    def test_a_missing_group_id_stays_none(self) -> None:
        """The DELETE mode removes the users outright, so it needs no target group."""
        assert GroupDeletionParameters(QUERY_STRING, action=GroupDeleteMode.DELETE).group_id is None

    def test_a_non_numeric_group_id_raises(self) -> None:
        """The parse_parameters decorator turns this into an HTTP 400."""
        with pytest.raises(ValueError):
            GroupDeletionParameters(QUERY_STRING, group_id='not-a-number')

    def test_from_data_is_inherited(self) -> None:
        """It has no JSON parameters of its own, so the base implementation is enough."""
        params = GroupDeletionParameters.from_data(QUERY_STRING, group_id='3')

        assert isinstance(params, GroupDeletionParameters)
        assert params.group_id == 3

    def test_to_dict_emits_the_action_group_id_and_optional(self) -> None:
        """This method had no test; it is the serializer of the delete parameters."""
        params = GroupDeletionParameters(
            QUERY_STRING, action=GroupDeleteMode.MOVE, group_id='7', view='native',
        )

        assert GroupDeletionParameters.to_dict(params) == {
            ParameterKey.ACTION.value: GroupDeleteMode.MOVE,
            ParameterKey.GROUP_ID.value: 7,
            ParameterKey.OPTIONAL.value: {'view': 'native'},
        }
