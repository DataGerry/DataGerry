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
Unit tests for the object-list search stages

The shape of the pipeline is the contract here: what it joins, what it collects, what it matches and -
the part a reviewer is most likely to get wrong later - that it puts the document back the way it
found it. The behaviour against real data is covered functionally.
"""
import re

import pytest

from cmdb.framework.search.list_search import SEARCHABLE_VALUES_FIELD
from cmdb.framework.search.object_list_search import (
    REFERENCED_OBJECTS_FIELD,
    build_object_search_stages,
    build_searchable_values_expression,
)
from cmdb.framework.search.search_pattern import escape_search_term
# -------------------------------------------------------------------------------------------------------------------- #

TERM: str = 'needle'


def _stage(stages: list[dict], operator: str) -> dict:
    """The single stage using the given aggregation operator."""
    return next(stage[operator] for stage in stages if operator in stage)


# An empty list is the contract for "no search", so this asserts the exact value rather than
# falsiness - a None slipping through would break the caller that splices the result
# pylint: disable=use-implicit-booleaness-not-comparison
@pytest.mark.parametrize('term', [None, '', '   ', '\t'], ids=repr)
def test_no_term_adds_no_stages(term) -> None:
    """An unsearched listing must not pay for a join it does not need."""
    assert build_object_search_stages(term) == []


def test_a_term_adds_exactly_four_stages() -> None:
    """Join, collect, match, clean up."""
    assert len(build_object_search_stages(TERM)) == 4


def test_the_join_reads_referenced_objects_by_public_id() -> None:
    """A reference field stores the target's public_id, which is what the join resolves."""
    lookup = _stage(build_object_search_stages(TERM), '$lookup')

    assert lookup['from'] == 'framework.objects'
    assert lookup['localField'] == 'fields.value'
    assert lookup['foreignField'] == 'public_id'
    assert lookup['as'] == REFERENCED_OBJECTS_FIELD


def test_the_match_is_a_regex_over_the_collected_values() -> None:
    """One `$match`, against the working field the stage before it built."""
    match = _stage(build_object_search_stages(TERM), '$match')

    assert match[SEARCHABLE_VALUES_FIELD]['$regex'] == TERM


def test_the_term_is_escaped_into_the_match() -> None:
    """``?search=`` is literal text, so the metacharacters must not act as operators."""
    match = _stage(build_object_search_stages('C++ (EU)'), '$match')

    assert match[SEARCHABLE_VALUES_FIELD]['$regex'] == re.escape('C++ (EU)')


def test_the_term_is_trimmed() -> None:
    """Surrounding whitespace is not part of what the user meant to search for."""
    match = _stage(build_object_search_stages('  needle  '), '$match')

    assert match[SEARCHABLE_VALUES_FIELD]['$regex'] == TERM


def test_both_working_fields_are_removed_again() -> None:
    """
    The document goes back the way it came

    The browser's pipeline rebuilt each document with an inclusive `$project` and silently dropped
    everything it did not list. This one excludes only what it added.
    """
    project = _stage(build_object_search_stages(TERM), '$project')

    assert project == {SEARCHABLE_VALUES_FIELD: 0, REFERENCED_OBJECTS_FIELD: 0}


def test_the_cleanup_is_the_last_stage() -> None:
    """Removing the working fields before the match would leave nothing to match against."""
    stages = build_object_search_stages(TERM)

    assert '$project' in stages[-1]
    assert '$match' in stages[-2]


def test_the_collected_values_cover_the_decided_searchable_set() -> None:
    """public_id, both timestamps, own field values and referenced field values - and nothing else."""
    collected = str(build_searchable_values_expression())

    for path in ['$public_id', '$creation_time', '$last_edit_time', '$fields', REFERENCED_OBJECTS_FIELD]:
        assert path in collected


def test_the_summary_line_is_not_searched() -> None:
    """
    It is composed during rendering and never stored

    The browser's pipeline matched it anyway, which is a clause that could never fire. Dropping it was
    a decision, so it is pinned.
    """
    assert 'summary_line' not in str(build_object_search_stages(TERM))


def test_every_collected_value_is_converted_to_a_string() -> None:
    """A field value can be a number, a date or a bool, and `$regex` matches none of those."""
    collected = str(build_searchable_values_expression())

    assert collected.count('$convert') == 4


def test_escape_search_term_is_re_escape() -> None:
    """The same escaping the rest of the backend uses, not a second spelling of it."""
    assert escape_search_term('a.b*c') == re.escape('a.b*c')
