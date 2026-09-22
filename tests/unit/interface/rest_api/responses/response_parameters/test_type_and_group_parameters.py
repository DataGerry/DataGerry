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
from cmdb.security.acl.permission import AccessControlPermission
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

        assert result == {
            **parent,
            ParameterKey.ACTIVE.value: True,
            ParameterKey.CATEGORY.value: None,
            ParameterKey.UNCATEGORIZED.value: False,
            ParameterKey.ACL.value: ['READ'],
        }


class TestTypeIterationParametersCategoryFilters:
    """`category` and `uncategorized` replace the $lookup pipelines the frontend used to post."""

    def test_defaults_to_no_category_restriction(self) -> None:
        """An ordinary listing asks for neither, and neither is set."""
        params = TypeIterationParameters.from_data(QUERY_STRING)

        assert params.category is None
        assert params.uncategorized is False

    def test_converts_the_category_id_to_an_int(self) -> None:
        """Flask delivers it as a string; it is a CmdbCategory public_id."""
        params = TypeIterationParameters.from_data(QUERY_STRING, **{ParameterKey.CATEGORY.value: '12'})

        assert params.category == 12

    def test_an_empty_category_means_no_restriction(self) -> None:
        """An Angular HttpParams entry whose source was cleared arrives as the empty string."""
        params = TypeIterationParameters.from_data(QUERY_STRING, **{ParameterKey.CATEGORY.value: ''})

        assert params.category is None

    def test_a_non_numeric_category_is_rejected(self) -> None:
        """The parse_parameters decorator turns the ValueError into an HTTP 400."""
        with pytest.raises(ValueError):
            TypeIterationParameters.from_data(QUERY_STRING, **{ParameterKey.CATEGORY.value: 'abc'})

    @pytest.mark.parametrize('raw, expected', [('true', True), ('false', False), (True, True)], ids=str)
    def test_converts_the_uncategorized_flag(self, raw, expected: bool) -> None:
        """Same string coercion the `active` flag gets."""
        params = TypeIterationParameters.from_data(QUERY_STRING, **{ParameterKey.UNCATEGORIZED.value: raw})

        assert params.uncategorized is expected

    def test_a_non_boolean_uncategorized_is_rejected(self) -> None:
        """str_to_bool accepts only the two literals, so anything else is a 400."""
        with pytest.raises(ValueError):
            TypeIterationParameters.from_data(QUERY_STRING, **{ParameterKey.UNCATEGORIZED.value: 'yes'})

    def test_the_two_category_filters_cannot_be_combined(self) -> None:
        """A type is either in the given category or in none at all - asking both is a contradiction."""
        with pytest.raises(ValueError):
            TypeIterationParameters.from_data(QUERY_STRING, **{
                ParameterKey.CATEGORY.value: '12',
                ParameterKey.UNCATEGORIZED.value: 'true',
            })

    def test_a_category_with_uncategorized_false_is_allowed(self) -> None:
        """Only a truthy `uncategorized` contradicts a category id."""
        params = TypeIterationParameters.from_data(QUERY_STRING, **{
            ParameterKey.CATEGORY.value: '12',
            ParameterKey.UNCATEGORIZED.value: 'false',
        })

        assert params.category == 12

    def test_the_category_filters_do_not_leak_into_optional(self) -> None:
        """They are named parameters, so they must not also ride along as optional ones."""
        params = TypeIterationParameters.from_data(QUERY_STRING, **{
            ParameterKey.CATEGORY.value: '12',
        })

        assert ParameterKey.CATEGORY.value not in params.optional
        assert ParameterKey.UNCATEGORIZED.value not in params.optional


class TestTypeIterationParametersAclFilter:
    """`acl` names the permissions a listed type must grant, replacing the READ default."""

    def test_defaults_to_read(self) -> None:
        """An ordinary listing asks the question it always asked."""
        params = TypeIterationParameters.from_data(QUERY_STRING)

        assert params.acl == [AccessControlPermission.READ]

    def test_converts_a_single_permission(self) -> None:
        """?acl=CREATE replaces READ rather than adding to it."""
        params = TypeIterationParameters.from_data(QUERY_STRING, **{ParameterKey.ACL.value: 'CREATE'})

        assert params.acl == [AccessControlPermission.CREATE]

    def test_converts_a_comma_separated_list(self) -> None:
        """One value, not a repeated key - a repeated key would silently lose all but the first."""
        params = TypeIterationParameters.from_data(
            QUERY_STRING, **{ParameterKey.ACL.value: 'READ,CREATE,UPDATE'},
        )

        assert params.acl == [
            AccessControlPermission.READ,
            AccessControlPermission.CREATE,
            AccessControlPermission.UPDATE,
        ]

    def test_tolerates_whitespace_around_the_separator(self) -> None:
        """`?acl=READ, CREATE` is the same request."""
        params = TypeIterationParameters.from_data(
            QUERY_STRING, **{ParameterKey.ACL.value: 'READ, CREATE'},
        )

        assert params.acl == [AccessControlPermission.READ, AccessControlPermission.CREATE]

    @pytest.mark.parametrize('raw', ['', ' ', 'READ,', ',READ'], ids=repr)
    def test_an_empty_entry_is_rejected(self, raw: str) -> None:
        """An empty $all matches nothing, so an empty value would hide every ACL-carrying type."""
        with pytest.raises(ValueError):
            TypeIterationParameters.from_data(QUERY_STRING, **{ParameterKey.ACL.value: raw})

    @pytest.mark.parametrize('raw', ['read', 'Read', 'NOPE', 'READ,nope'], ids=repr)
    def test_an_unknown_permission_is_rejected(self, raw: str) -> None:
        """Matching is case-sensitive: a stored ACL holds the upper-case value, so 'read' matches nothing."""
        with pytest.raises(ValueError):
            TypeIterationParameters.from_data(QUERY_STRING, **{ParameterKey.ACL.value: raw})

    def test_the_rejection_names_the_valid_permissions(self) -> None:
        """The 400 has to say what to send instead."""
        with pytest.raises(ValueError, match='CREATE'):
            TypeIterationParameters.from_data(QUERY_STRING, **{ParameterKey.ACL.value: 'nope'})

    def test_an_already_parsed_list_is_taken_as_given(self) -> None:
        """An internal caller may hand the permissions over parsed rather than as a query string."""
        params = TypeIterationParameters.from_data(
            QUERY_STRING, **{ParameterKey.ACL.value: [AccessControlPermission.CREATE]},
        )

        assert params.acl == [AccessControlPermission.CREATE]

    def test_an_empty_parsed_list_is_rejected_like_an_empty_string(self) -> None:
        """Empty means the same thing whichever way it arrives: nothing would match."""
        with pytest.raises(ValueError):
            TypeIterationParameters.from_data(QUERY_STRING, **{ParameterKey.ACL.value: []})

    def test_the_acl_filter_does_not_leak_into_optional(self) -> None:
        """It is a named parameter, so it must not also ride along as an optional one."""
        params = TypeIterationParameters.from_data(QUERY_STRING, **{ParameterKey.ACL.value: 'CREATE'})

        assert ParameterKey.ACL.value not in params.optional


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

    @pytest.mark.parametrize('raw', ['MOVE', GroupDeleteMode.MOVE], ids=['string', 'member'])
    def test_coerces_the_action_to_the_enum(self, raw) -> None:
        """Flask delivers it as a string; the annotation and the manager both expect the member."""
        params = GroupDeletionParameters(QUERY_STRING, action=raw, group_id='7')

        assert params.action is GroupDeleteMode.MOVE

    def test_a_missing_action_stays_none(self) -> None:
        """Omitting it is how a caller deletes the group without touching its members."""
        assert GroupDeletionParameters(QUERY_STRING).action is None

    @pytest.mark.parametrize('raw', ['BOGUS', 'null', '', 'move'], ids=str)
    def test_an_unknown_action_raises(self, raw: str) -> None:
        """Letting it through would delete the group while redistributing none of its members,
        stranding every one of them on a group_id that no longer resolves."""
        with pytest.raises(ValueError):
            GroupDeletionParameters(QUERY_STRING, action=raw)

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
