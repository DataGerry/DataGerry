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
Unit tests for the generic list `?search=`

One helper now answers the search box of every table, so what it does with the values - and what it
does to the document on the way past - is worth pinning precisely. The per-route field sets are the
routes' own business; these cover the machinery they all share.
"""
import re

import pytest

from cmdb.framework.search.list_search import (
    matches_search_term,
    SEARCHABLE_VALUES_FIELD,
    as_text,
    build_list_search_stages,
    build_search_match_stages,
    build_searchable_fields_expression,
)
# -------------------------------------------------------------------------------------------------------------------- #

FIELDS: tuple[str, ...] = ('public_id', 'name')
TERM: str = 'needle'


def _stage(stages: list[dict], operator: str) -> dict:
    """The single stage using the given aggregation operator."""
    return next(stage[operator] for stage in stages if operator in stage)


# An empty list is the contract for "no search", so these assert the exact value rather than falsiness
# pylint: disable=use-implicit-booleaness-not-comparison
@pytest.mark.parametrize('term', [None, '', '   '], ids=repr)
def test_no_term_adds_no_stages(term) -> None:
    """An unsearched listing must not pay for stages it does not need."""
    assert build_list_search_stages(term, FIELDS) == []


def test_no_searchable_fields_adds_no_stages() -> None:
    """A route that declares nothing searchable cannot be searched - not 'matches everything'."""
    assert build_list_search_stages(TERM, ()) == []


def test_a_term_adds_exactly_three_stages() -> None:
    """Collect, match, clean up."""
    assert len(build_list_search_stages(TERM, FIELDS)) == 3


def test_every_declared_field_is_collected() -> None:
    """The route's declaration is the whole searchable set."""
    collected = str(build_searchable_fields_expression(FIELDS))

    assert '$public_id' in collected
    assert '$name' in collected


def test_every_value_is_converted_to_a_string() -> None:
    """A column can hold a number, a date or a null, and `$regex` matches none of those."""
    collected = str(build_searchable_fields_expression(FIELDS))

    assert collected.count('$convert') == len(FIELDS)


def test_a_conversion_never_fails_and_never_answers_null() -> None:
    """One bad column must not fail the whole aggregation."""
    conversion = as_text('$anything')['$convert']

    assert conversion['onError'] == ''
    assert conversion['onNull'] == ''


def test_the_term_is_escaped() -> None:
    """``?search=`` is literal text, so its metacharacters must not act as operators."""
    match = _stage(build_list_search_stages('C++ (EU)', FIELDS), '$match')

    assert match[SEARCHABLE_VALUES_FIELD]['$regex'] == re.escape('C++ (EU)')


def test_the_term_is_trimmed() -> None:
    """Surrounding whitespace is not part of what the user meant to search for."""
    match = _stage(build_list_search_stages('  needle  ', FIELDS), '$match')

    assert match[SEARCHABLE_VALUES_FIELD]['$regex'] == TERM


def test_the_working_field_is_removed_again() -> None:
    """
    The document goes back the way it came

    The browser's versions rebuilt each row with an inclusive `$project` and silently dropped every
    column they did not name.
    """
    assert _stage(build_list_search_stages(TERM, FIELDS), '$project') == {SEARCHABLE_VALUES_FIELD: 0}


def test_extra_cleanup_fields_are_removed_too() -> None:
    """The object search adds a join field and hands it over to be cleaned up here."""
    stages = build_search_match_stages({'$literal': []}, TERM, extra_cleanup_fields=('__dg_joined',))

    assert _stage(stages, '$project') == {SEARCHABLE_VALUES_FIELD: 0, '__dg_joined': 0}


def test_the_cleanup_is_the_last_stage() -> None:
    """Removing the working field before the match would leave nothing to match against."""
    stages = build_list_search_stages(TERM, FIELDS)

    assert '$project' in stages[-1]
    assert '$match' in stages[-2]


# -------------------------------------------------------------------------------------------------------------------- #
#                                             matches_search_term                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
class TestMatchesSearchTerm:
    """The in-memory counterpart of the stages, for a collection that is not in MongoDB.

    Both sides have to mean the same thing by "matches", which is the whole reason it lives beside
    the stage builder rather than in the one manager that needs it.
    """

    @pytest.mark.parametrize('term', [None, '', '   '])
    def test_a_blank_term_matches_everything(self, term) -> None:
        """An unsearched listing returns everything, so an unsearched record matches"""
        assert matches_search_term(['anything'], term) is True

    def test_a_substring_matches(self) -> None:
        """Not an exact match and not a prefix - the same as the `$regex` stage"""
        assert matches_search_term(['base.framework.type.view'], 'framework') is True

    def test_it_is_case_insensitive(self) -> None:
        """SEARCH_REGEX_RE_FLAGS carries IGNORECASE, like the stage's 'i'"""
        assert matches_search_term(['View Type'], 'view type') is True

    def test_the_term_is_literal_text(self) -> None:
        """`escape_search_term` is what makes a dot a dot rather than 'any character'"""
        assert matches_search_term(['baseXframework'], 'base.framework') is False
        assert matches_search_term(['base.framework'], 'base.framework') is True

    def test_non_string_values_are_read_as_strings(self) -> None:
        """Every searchable value goes through a string conversion on both sides"""
        assert matches_search_term([10], '10') is True

    def test_none_values_are_skipped(self) -> None:
        """A field a record does not carry matches nothing rather than raising"""
        assert matches_search_term([None], 'none') is False

    def test_any_value_matching_is_enough(self) -> None:
        """The stage matches the ARRAY of a record's searchable values, not each field in turn"""
        assert matches_search_term(['no', 'nope', 'the-term'], 'term') is True

    def test_nothing_matching_is_false(self) -> None:
        """The record is not part of a searched listing"""
        assert matches_search_term(['a', 'b'], 'zzz') is False
