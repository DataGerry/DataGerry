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
Unit tests for `as_executable_pattern`

The rule is narrow on purpose: a term that compiles goes to the database as written, a term that does
not goes as an escaped literal. These pin both halves, and - because it is the interesting boundary -
which side of it the three terms recorded in tier 2 T187 fall on.
"""
import re

import pytest

from cmdb.framework.search.search_pattern import as_executable_pattern
# -------------------------------------------------------------------------------------------------------------------- #


@pytest.mark.parametrize('term', ['plain text', 'a.*b', 'C++', 'Data (EU)', '^anchored$', ''], ids=repr)
def test_a_usable_pattern_is_returned_unchanged(term: str) -> None:
    """A caller who meant a regular expression still gets one."""
    assert as_executable_pattern(term) == term


@pytest.mark.parametrize('term', ['*', '[unclosed', 'a**', '+', '?', '(unclosed'], ids=repr)
def test_an_unusable_pattern_is_escaped(term: str) -> None:
    """Otherwise the database refuses the query and the route answers 400."""
    assert as_executable_pattern(term) == re.escape(term)


@pytest.mark.parametrize('term', ['*', '[unclosed', 'a**', 'C++', 'Data (EU)', 'plain'], ids=repr)
def test_the_result_always_compiles(term: str) -> None:
    """The point of the rule: whatever was typed, the pattern that leaves here is executable."""
    re.compile(as_executable_pattern(term))


def test_an_escaped_term_is_left_alone() -> None:
    """
    What the Angular search bar sends must pass through untouched

    It escapes the term before sending, so every UI search already compiles - the fallback can only
    fire for a term the UI never produces, which is why this needed no frontend change.
    """
    assert as_executable_pattern(r'C\+\+') == r'C\+\+'


def test_a_still_wrong_pattern_is_not_rescued() -> None:
    """
    The rest of T187, stated as a test so the boundary is not mistaken for a full fix

    `C++` and `Data (EU)` are valid patterns, so nothing here can tell they were meant literally.
    Closing that needs the frontend to stop escaping at the same time.
    """
    assert as_executable_pattern('C++') == 'C++'
    assert as_executable_pattern('Data (EU)') == 'Data (EU)'
